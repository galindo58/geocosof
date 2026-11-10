import os
import sqlite3
import secrets
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "geoecosof.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esta-clave-antes-de-publicar-geoecosof")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"

MATERIALES = ["Plástico", "Cartón", "Papel", "Vidrio", "Metales", "Electrónicos", "Otros"]

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        correo TEXT NOT NULL UNIQUE,
        telefono TEXT,
        password_hash TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'ciudadano',
        activo INTEGER NOT NULL DEFAULT 1,
        verificado INTEGER NOT NULL DEFAULT 1,
        creado_en TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS materiales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        descripcion TEXT
    );
    CREATE TABLE IF NOT EXISTS solicitudes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ciudadano_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        cantidad REAL NOT NULL,
        unidad TEXT NOT NULL DEFAULT 'kg',
        direccion TEXT NOT NULL,
        barrio TEXT NOT NULL,
        departamento TEXT NOT NULL DEFAULT 'Córdoba',
        municipio TEXT NOT NULL DEFAULT 'Montería',
        referencia TEXT,
        latitud REAL,
        longitud REAL,
        fecha_disponible TEXT,
        notas TEXT,
        estado TEXT NOT NULL DEFAULT 'Disponible',
        creado_en TEXT NOT NULL,
        FOREIGN KEY(ciudadano_id) REFERENCES usuarios(id),
        FOREIGN KEY(material_id) REFERENCES materiales(id)
    );
    CREATE TABLE IF NOT EXISTS asignaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        solicitud_id INTEGER NOT NULL UNIQUE,
        reciclador_id INTEGER NOT NULL,
        asignado_en TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'Asignada',
        FOREIGN KEY(solicitud_id) REFERENCES solicitudes(id),
        FOREIGN KEY(reciclador_id) REFERENCES usuarios(id)
    );
    CREATE TABLE IF NOT EXISTS recolecciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        solicitud_id INTEGER NOT NULL UNIQUE,
        reciclador_id INTEGER NOT NULL,
        cantidad_recogida REAL NOT NULL,
        observaciones TEXT,
        fecha_recoleccion TEXT NOT NULL,
        FOREIGN KEY(solicitud_id) REFERENCES solicitudes(id),
        FOREIGN KEY(reciclador_id) REFERENCES usuarios(id)
    );
    CREATE TABLE IF NOT EXISTS notificaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        mensaje TEXT NOT NULL,
        solicitud_id INTEGER,
        leida INTEGER NOT NULL DEFAULT 0,
        creado_en TEXT NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(solicitud_id) REFERENCES solicitudes(id)
    );
    """)
    # Migración compatible con bases SQLite creadas en versiones anteriores.
    columnas = {row[1] for row in db.execute("PRAGMA table_info(solicitudes)").fetchall()}
    if "departamento" not in columnas:
        db.execute("ALTER TABLE solicitudes ADD COLUMN departamento TEXT NOT NULL DEFAULT 'Córdoba'")
    if "municipio" not in columnas:
        db.execute("ALTER TABLE solicitudes ADD COLUMN municipio TEXT NOT NULL DEFAULT 'Montería'")
    columnas_usuarios = {row[1] for row in db.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "verificado" not in columnas_usuarios:
        db.execute("ALTER TABLE usuarios ADD COLUMN verificado INTEGER NOT NULL DEFAULT 1")

    for material in MATERIALES:
        db.execute("INSERT OR IGNORE INTO materiales(nombre, descripcion) VALUES (?, ?)",
                   (material, "Material reciclable registrado en GEOECOSOF"))
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@geoecosof.co")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Geoecosof2026*")
    exists = db.execute("SELECT id FROM usuarios WHERE correo = ?", (admin_email,)).fetchone()
    if not exists:
        db.execute("""INSERT INTO usuarios(nombre, correo, telefono, password_hash, rol, creado_en)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   ("Administrador GEOECOSOF", admin_email, "", generate_password_hash(admin_password),
                    "admin", datetime.now().isoformat(timespec="seconds")))
    db.commit()
    db.close()

@app.before_request
def csrf_setup():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)

@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf_token", ""), "current_user": current_user()}

@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or token != session.get("csrf_token"):
            abort(400, description="Token de seguridad inválido. Recarga la página e inténtalo nuevamente.")

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (user_id,)).fetchone()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Inicia sesión para continuar.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user["rol"] not in roles:
                abort(403)
            if user["rol"] == "reciclador" and not user["verificado"]:
                flash("Tu cuenta de recolector está pendiente de verificación por administración.", "warning")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

def notify_role(role, message, solicitud_id=None):
    db = get_db()
    users = db.execute("SELECT id FROM usuarios WHERE rol = ? AND activo = 1", (role,)).fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    for user in users:
        db.execute("""INSERT INTO notificaciones(usuario_id, mensaje, solicitud_id, creado_en)
                      VALUES (?, ?, ?, ?)""", (user["id"], message, solicitud_id, now))

@app.route("/")
def index():
    db = get_db()
    stats = {
        "solicitudes": db.execute("SELECT COUNT(*) FROM solicitudes WHERE estado = 'Disponible'").fetchone()[0],
        "recicladores": db.execute("SELECT COUNT(*) FROM usuarios WHERE rol = 'reciclador' AND activo = 1 AND verificado = 1").fetchone()[0],
        "recolecciones": db.execute("SELECT COUNT(*) FROM recolecciones").fetchone()[0],
        "kg_recogidos": round(db.execute("SELECT COALESCE(SUM(r.cantidad_recogida),0) FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id WHERE lower(s.unidad)='kg'").fetchone()[0], 2),
    }
    return render_template("index.html", stats=stats)

@app.route("/registro", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        correo = request.form.get("correo", "").strip().lower()
        telefono = request.form.get("telefono", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        rol = request.form.get("rol", "ciudadano")
        if rol not in ("ciudadano", "reciclador"):
            rol = "ciudadano"
        if not nombre or not correo or len(password) < 8:
            flash("Completa los campos. La contraseña debe tener al menos 8 caracteres.", "danger")
        elif password != confirm:
            flash("Las contraseñas no coinciden.", "danger")
        else:
            try:
                verificado = 0 if rol == "reciclador" else 1
                get_db().execute("""INSERT INTO usuarios(nombre, correo, telefono, password_hash, rol, verificado, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (nombre, correo, telefono, generate_password_hash(password), rol, verificado, datetime.now().isoformat(timespec="seconds")))
                get_db().commit()
                if rol == "reciclador":
                    flash("Solicitud de cuenta creada. Administración debe verificar tu perfil antes de habilitar las recolecciones.", "success")
                else:
                    flash("Cuenta de publicador creada. Ya puedes iniciar sesión.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Ese correo ya está registrado.", "danger")
    return render_template("auth.html", mode="registro")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM usuarios WHERE correo = ? AND activo = 1", (correo,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_hex(24)
            flash("Bienvenido a GEOECOSOF.", "success")
            return redirect(url_for("dashboard"))
        flash("Correo o contraseña incorrectos.", "danger")
    return render_template("auth.html", mode="login")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("index"))

@app.route("/panel")
@login_required
def dashboard():
    db = get_db()
    user = current_user()
    unread = db.execute("SELECT COUNT(*) FROM notificaciones WHERE usuario_id = ? AND leida = 0", (user["id"],)).fetchone()[0]
    if user["rol"] == "admin":
        solicitudes = db.execute("""SELECT s.*, m.nombre material, u.nombre ciudadano
            FROM solicitudes s JOIN materiales m ON m.id=s.material_id
            JOIN usuarios u ON u.id=s.ciudadano_id ORDER BY s.id DESC LIMIT 8""").fetchall()
        stats = {
            "usuarios": db.execute("SELECT COUNT(*) FROM usuarios WHERE rol != 'admin'").fetchone()[0],
            "cuentas_por_verificar": db.execute("SELECT COUNT(*) FROM usuarios WHERE rol='reciclador' AND verificado=0 AND activo=1").fetchone()[0],
            "publicaciones_disponibles": db.execute("SELECT COUNT(*) FROM solicitudes WHERE estado='Disponible'").fetchone()[0],
            "kg_recogidos": round(db.execute("SELECT COALESCE(SUM(r.cantidad_recogida),0) FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id WHERE lower(s.unidad)='kg'").fetchone()[0], 2),
            "recolecciones_realizadas": db.execute("SELECT COUNT(*) FROM recolecciones").fetchone()[0]
        }
    elif user["rol"] == "reciclador" and not user["verificado"]:
        solicitudes = []
        stats = {"estado_cuenta": "Pendiente de verificación", "materiales_disponibles": db.execute("SELECT COUNT(*) FROM solicitudes WHERE estado='Disponible'").fetchone()[0]}
    elif user["rol"] == "reciclador":
        solicitudes = db.execute("""SELECT s.*, m.nombre material, u.nombre ciudadano
            FROM solicitudes s JOIN materiales m ON m.id=s.material_id
            JOIN usuarios u ON u.id=s.ciudadano_id
            WHERE s.estado='Disponible' OR s.id IN
            (SELECT solicitud_id FROM asignaciones WHERE reciclador_id=? AND estado='Asignada')
            ORDER BY s.id DESC""", (user["id"],)).fetchall()
        stats = {
            "materiales_disponibles": db.execute("SELECT COUNT(*) FROM solicitudes WHERE estado='Disponible'").fetchone()[0],
            "mis_recolecciones_pendientes": db.execute("SELECT COUNT(*) FROM asignaciones WHERE reciclador_id=? AND estado='Asignada'", (user["id"],)).fetchone()[0],
            "kg_que_he_recogido": round(db.execute("SELECT COALESCE(SUM(r.cantidad_recogida),0) FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id WHERE r.reciclador_id=? AND lower(s.unidad)='kg'", (user["id"],)).fetchone()[0], 2),
            "recolecciones_realizadas": db.execute("SELECT COUNT(*) FROM recolecciones WHERE reciclador_id=?", (user["id"],)).fetchone()[0]
        }
    else:
        solicitudes = db.execute("""SELECT s.*, m.nombre material FROM solicitudes s
            JOIN materiales m ON m.id=s.material_id WHERE ciudadano_id=? ORDER BY s.id DESC""",
            (user["id"],)).fetchall()
        stats = {
            "mis_publicaciones": len(solicitudes),
            "materiales_disponibles": sum(1 for s in solicitudes if s["estado"] == "Disponible"),
            "recolecciones_completadas": sum(1 for s in solicitudes if s["estado"] == "Completada"),
            "kg_ya_recogidos": round(db.execute("SELECT COALESCE(SUM(r.cantidad_recogida),0) FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id WHERE s.ciudadano_id=? AND lower(s.unidad)='kg'", (user["id"],)).fetchone()[0], 2)
        }
    return render_template("dashboard.html", solicitudes=solicitudes, stats=stats, unread=unread)

@app.route("/solicitudes")
@role_required("ciudadano", "reciclador", "admin")
def requests_list():
    db = get_db()
    user = current_user()
    query = """SELECT s.*, m.nombre material, u.nombre ciudadano
               FROM solicitudes s JOIN materiales m ON m.id=s.material_id
               JOIN usuarios u ON u.id=s.ciudadano_id"""
    params = []
    if user["rol"] == "ciudadano":
        query += " WHERE s.ciudadano_id=?"
        params.append(user["id"])
    elif user["rol"] == "reciclador":
        query += " WHERE s.estado='Disponible' OR s.id IN (SELECT solicitud_id FROM asignaciones WHERE reciclador_id=?)"
        params.append(user["id"])
    query += " ORDER BY s.id DESC"
    solicitudes = db.execute(query, params).fetchall()
    return render_template("requests.html", solicitudes=solicitudes)

@app.route("/solicitudes/nueva", methods=["GET", "POST"])
@role_required("ciudadano", "admin")
def new_request():
    db = get_db()
    materiales = db.execute("SELECT * FROM materiales ORDER BY nombre").fetchall()
    if request.method == "POST":
        try:
            cantidad = float(request.form.get("cantidad", "0"))
            material_id = int(request.form.get("material_id", "0"))
            if cantidad <= 0:
                raise ValueError()
        except ValueError:
            flash("Ingresa una cantidad válida mayor que cero.", "danger")
            return render_template("request_form.html", materiales=materiales, item=None)
        direccion = request.form.get("direccion", "").strip()
        barrio = request.form.get("barrio", "").strip()
        departamento = request.form.get("departamento", "").strip()
        municipio = request.form.get("municipio", "").strip()
        if not direccion or not barrio or not departamento or not municipio:
            flash("La dirección, el barrio, el departamento y el municipio son obligatorios.", "danger")
            return render_template("request_form.html", materiales=materiales, item=None)
        lat = request.form.get("latitud") or None
        lon = request.form.get("longitud") or None
        now = datetime.now().isoformat(timespec="seconds")
        cur = db.execute("""INSERT INTO solicitudes(ciudadano_id, material_id, cantidad, unidad, direccion,
            barrio, departamento, municipio, referencia, latitud, longitud, fecha_disponible, notas, estado, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Disponible', ?)""",
            (current_user()["id"], material_id, cantidad, request.form.get("unidad", "kg"),
             direccion, barrio, departamento, municipio, request.form.get("referencia", "").strip(), lat, lon,
             request.form.get("fecha_disponible") or None, request.form.get("notas", "").strip(), now))
        sid = cur.lastrowid
        notify_role("reciclador", f"Nuevo material disponible: {barrio}, {request.form.get('unidad','kg')}.", sid)
        db.commit()
        flash("Solicitud publicada. Los recicladores ya pueden consultarla.", "success")
        return redirect(url_for("requests_list"))
    return render_template("request_form.html", materiales=materiales, item=None)

@app.route("/solicitudes/<int:sid>/editar", methods=["GET", "POST"])
@login_required
def edit_request(sid):
    db = get_db()
    item = db.execute("SELECT * FROM solicitudes WHERE id=?", (sid,)).fetchone()
    if not item:
        abort(404)
    user = current_user()
    if user["rol"] not in ("admin", "ciudadano") or (user["rol"] == "ciudadano" and item["ciudadano_id"] != user["id"]):
        abort(403)
    if item["estado"] != "Disponible":
        flash("Solo se pueden editar solicitudes que siguen disponibles.", "warning")
        return redirect(url_for("requests_list"))
    materiales = db.execute("SELECT * FROM materiales ORDER BY nombre").fetchall()
    if request.method == "POST":
        try:
            cantidad = float(request.form.get("cantidad", "0"))
            material_id = int(request.form.get("material_id", "0"))
            if cantidad <= 0: raise ValueError()
        except ValueError:
            flash("Revisa la cantidad y el material.", "danger")
            return render_template("request_form.html", materiales=materiales, item=item)
        db.execute("""UPDATE solicitudes SET material_id=?, cantidad=?, unidad=?, direccion=?, barrio=?,
            departamento=?, municipio=?, referencia=?, latitud=?, longitud=?, fecha_disponible=?, notas=? WHERE id=?""",
            (material_id, cantidad, request.form.get("unidad","kg"), request.form.get("direccion","").strip(),
             request.form.get("barrio","").strip(), request.form.get("departamento","").strip(),
             request.form.get("municipio","").strip(), request.form.get("referencia","").strip(),
             request.form.get("latitud") or None, request.form.get("longitud") or None,
             request.form.get("fecha_disponible") or None, request.form.get("notas","").strip(), sid))
        db.commit()
        flash("Solicitud actualizada.", "success")
        return redirect(url_for("requests_list"))
    return render_template("request_form.html", materiales=materiales, item=item)

@app.route("/solicitudes/<int:sid>/eliminar", methods=["POST"])
@login_required
def delete_request(sid):
    db = get_db()
    item = db.execute("SELECT * FROM solicitudes WHERE id=?", (sid,)).fetchone()
    if not item: abort(404)
    user = current_user()
    if user["rol"] != "admin" and not (user["rol"] == "ciudadano" and item["ciudadano_id"] == user["id"]):
        abort(403)
    if item["estado"] != "Disponible":
        flash("No se puede eliminar una solicitud que ya está asignada o completada.", "warning")
    else:
        db.execute("DELETE FROM solicitudes WHERE id=?", (sid,))
        db.commit()
        flash("Solicitud eliminada.", "success")
    return redirect(url_for("requests_list"))

@app.route("/solicitudes/<int:sid>/tomar", methods=["POST"])
@role_required("reciclador")
def take_request(sid):
    db = get_db()
    item = db.execute("SELECT * FROM solicitudes WHERE id=? AND estado='Disponible'", (sid,)).fetchone()
    if not item:
        flash("Esta solicitud ya no está disponible.", "warning")
        return redirect(url_for("requests_list"))
    try:
        db.execute("INSERT INTO asignaciones(solicitud_id, reciclador_id, asignado_en) VALUES (?, ?, ?)",
                   (sid, current_user()["id"], datetime.now().isoformat(timespec="seconds")))
        db.execute("UPDATE solicitudes SET estado='Asignada' WHERE id=?", (sid,))
        db.execute("INSERT INTO notificaciones(usuario_id, mensaje, solicitud_id, creado_en) VALUES (?, ?, ?, ?)",
                   (item["ciudadano_id"], "Un reciclador aceptó tu solicitud de recolección.", sid,
                    datetime.now().isoformat(timespec="seconds")))
        db.commit()
        flash("Solicitud asignada a tu cuenta. Ya puedes coordinar la recolección.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Otro reciclador acaba de tomar esta solicitud. Actualiza la página.", "warning")
    return redirect(url_for("requests_list"))

@app.route("/solicitudes/<int:sid>/completar", methods=["POST"])
@role_required("reciclador", "admin")
def complete_request(sid):
    db = get_db()
    assignment = db.execute("SELECT * FROM asignaciones WHERE solicitud_id=? AND estado='Asignada'", (sid,)).fetchone()
    if not assignment or (current_user()["rol"] == "reciclador" and assignment["reciclador_id"] != current_user()["id"]):
        abort(403)
    try:
        cantidad = float(request.form.get("cantidad_recogida", "0"))
        if cantidad <= 0: raise ValueError()
    except ValueError:
        flash("Ingresa la cantidad recogida.", "danger")
        return redirect(url_for("requests_list"))
    obs = request.form.get("observaciones", "").strip()
    db.execute("INSERT INTO recolecciones(solicitud_id, reciclador_id, cantidad_recogida, observaciones, fecha_recoleccion) VALUES (?, ?, ?, ?, ?)",
               (sid, assignment["reciclador_id"], cantidad, obs, datetime.now().isoformat(timespec="seconds")))
    db.execute("UPDATE solicitudes SET estado='Completada' WHERE id=?", (sid,))
    db.execute("UPDATE asignaciones SET estado='Completada' WHERE solicitud_id=?", (sid,))
    owner = db.execute("SELECT ciudadano_id FROM solicitudes WHERE id=?", (sid,)).fetchone()
    db.execute("INSERT INTO notificaciones(usuario_id, mensaje, solicitud_id, creado_en) VALUES (?, ?, ?, ?)",
               (owner["ciudadano_id"], "Tu material fue recogido. ¡Gracias por reciclar!", sid,
                datetime.now().isoformat(timespec="seconds")))
    db.commit()
    flash("Recolección confirmada y registrada en el historial.", "success")
    return redirect(url_for("requests_list"))

@app.route("/notificaciones")
@login_required
def notifications():
    db = get_db()
    rows = db.execute("SELECT * FROM notificaciones WHERE usuario_id=? ORDER BY id DESC", (current_user()["id"],)).fetchall()
    db.execute("UPDATE notificaciones SET leida=1 WHERE usuario_id=?", (current_user()["id"],))
    db.commit()
    return render_template("notifications.html", notifications=rows)

@app.route("/admin/usuarios")
@role_required("admin")
def users_admin():
    users = get_db().execute("SELECT * FROM usuarios ORDER BY id DESC").fetchall()
    return render_template("users.html", users=users)

@app.route("/admin/usuarios/nuevo", methods=["POST"])
@role_required("admin")
def create_user_admin():
    nombre=request.form.get("nombre","").strip()
    correo=request.form.get("correo","").strip().lower()
    rol=request.form.get("rol","ciudadano")
    password=request.form.get("password","")
    if rol not in ("ciudadano","reciclador","admin") or not nombre or not correo or len(password)<8:
        flash("Datos inválidos. La contraseña debe tener al menos 8 caracteres.", "danger")
    else:
        try:
            get_db().execute("""INSERT INTO usuarios(nombre,correo,telefono,password_hash,rol,creado_en)
                VALUES(?,?,?,?,?,?)""",(nombre,correo,request.form.get("telefono","").strip(),
                generate_password_hash(password),rol,datetime.now().isoformat(timespec="seconds")))
            get_db().commit()
            flash("Usuario creado.", "success")
        except sqlite3.IntegrityError:
            flash("El correo ya existe.", "danger")
    return redirect(url_for("users_admin"))


@app.route("/admin/usuarios/<int:uid>/verificar", methods=["POST"])
@role_required("admin")
def verify_user(uid):
    db = get_db()
    target = db.execute("SELECT * FROM usuarios WHERE id=? AND rol='reciclador'", (uid,)).fetchone()
    if not target:
        abort(404)
    db.execute("UPDATE usuarios SET verificado=CASE verificado WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (uid,))
    db.commit()
    flash("Estado de verificación actualizado.", "success")
    return redirect(url_for("users_admin"))

@app.route("/admin/usuarios/<int:uid>/estado", methods=["POST"])
@role_required("admin")
def toggle_user(uid):
    if uid == current_user()["id"]:
        flash("No puedes desactivar tu propia cuenta.", "warning")
    else:
        db=get_db()
        db.execute("UPDATE usuarios SET activo=CASE activo WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(uid,))
        db.commit()
        flash("Estado del usuario actualizado.", "success")
    return redirect(url_for("users_admin"))

@app.route("/mapa")
@role_required("reciclador", "admin")
def map_view():
    rows=get_db().execute("""SELECT s.id,s.cantidad,s.unidad,s.direccion,s.barrio,s.latitud,s.longitud,
        m.nombre material,u.nombre ciudadano FROM solicitudes s JOIN materiales m ON m.id=s.material_id
        JOIN usuarios u ON u.id=s.ciudadano_id WHERE s.estado='Disponible' ORDER BY s.id DESC""").fetchall()
    points=[dict(r) for r in rows if r["latitud"] is not None and r["longitud"] is not None]
    return render_template("map.html", points=points, total=len(rows))

@app.route("/historial")
@role_required("reciclador", "admin")
def history():
    db=get_db()
    if current_user()["rol"] == "admin":
        rows=db.execute("""SELECT r.*,s.barrio,s.direccion,m.nombre material,u.nombre reciclador
            FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id
            JOIN materiales m ON m.id=s.material_id JOIN usuarios u ON u.id=r.reciclador_id
            ORDER BY r.id DESC""").fetchall()
    else:
        rows=db.execute("""SELECT r.*,s.barrio,s.direccion,m.nombre material,u.nombre reciclador
            FROM recolecciones r JOIN solicitudes s ON s.id=r.solicitud_id
            JOIN materiales m ON m.id=s.material_id JOIN usuarios u ON u.id=r.reciclador_id
            WHERE r.reciclador_id=? ORDER BY r.id DESC""",(current_user()["id"],)).fetchall()
    return render_template("history.html", rows=rows)

@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="No tienes permiso para acceder a esta sección."), 403

@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="La página que buscas no existe."), 404

@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Solicitud inválida.")), 400

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
