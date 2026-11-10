# GEOECOSOF ♻️

Plataforma web académica para conectar ciudadanos y recicladores en Colombia.

## Funcionalidades incluidas
- Registro de ciudadanos e inicio/cierre de sesión.
- Roles: administrador, reciclador y ciudadano.
- Publicación, consulta, edición y eliminación de solicitudes de reciclaje.
- Avisos internos a recicladores cuando se publica material.
- Asignación de solicitudes a recicladores.
- Confirmación e historial de recolecciones.
- Paneles diferenciados por rol.
- Mapa de solicitudes con coordenadas usando OpenStreetMap/Leaflet.
- Contraseñas con hash, consultas SQL parametrizadas y token CSRF en formularios.

## Requisitos
Python 3.10 o superior.

## Instalación en Windows (PowerShell)
```powershell
cd GEOECOSOF
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

En macOS/Linux:
```bash
cd GEOECOSOF
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abrir http://127.0.0.1:5000

## Acceso inicial de administrador
- Correo: admin@geoecosof.co
- Contraseña local inicial: Geoecosof2026*

**Cambiar esta contraseña antes de publicar el sitio.** Se puede configurar con las variables `ADMIN_EMAIL` y `ADMIN_PASSWORD`.

## Tipos de cuenta
- **Publicador:** registro público inmediato para publicar materiales disponibles.
- **Recolector:** registro público con verificación obligatoria de administración antes de consultar y aceptar recolecciones.
- **Administrador:** cuenta de acceso restringido, creada mediante variables de entorno o por otro administrador; nunca se ofrece como rol en el registro público.

El administrador revisa usuarios, verifica recolectores, activa/desactiva cuentas y consulta las publicaciones y recolecciones.

## Datos e indicadores calculados
Los contadores de usuarios, publicaciones, solicitudes, recolecciones y kilogramos se calculan con consultas a la base de datos en cada carga del panel. El peso total suma únicamente registros cuya unidad sea `kg`; no mezcla bolsas ni unidades con kilogramos. A medida que los clientes publican y los recolectores confirman cantidades, los indicadores se actualizan automáticamente.

## Publicación en Render
1. Sube el contenido de esta carpeta a un repositorio de GitHub.
2. En Render crea un Web Service conectado al repositorio.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. Configura `SECRET_KEY` con un valor secreto y `ADMIN_PASSWORD` con una contraseña fuerte.

**Importante:** esta primera versión usa SQLite local. En Render, el disco del servicio puede ser efímero; para conservar los datos de forma confiable entre despliegues, configura un disco persistente o migra la base de datos a PostgreSQL. La base de datos SQLite de desarrollo se crea automáticamente al iniciar. Las solicitudes ahora guardan departamento y municipio para permitir el uso nacional.

## Mapa
Para que una solicitud aparezca en el mapa, el ciudadano debe proporcionar latitud y longitud. En esta versión son opcionales; si no se ingresan, la solicitud sigue apareciendo en los listados.

## Alcance académico
Las notificaciones de esta versión son internas dentro de la plataforma (no SMS ni WhatsApp). La ruta se organiza visualizando los puntos con coordenadas; la optimización automática de recorridos y las notificaciones externas se pueden implementar como una siguiente mejora.


## Actualización visual premium
La interfaz incorpora una portada editorial, fotografía ambiental, secciones de propósito e impacto, proceso en tres etapas y formularios de acceso con diseño dividido. Las fotografías se cargan desde Unsplash y requieren conexión a internet en el navegador.


## Alcance geográfico nacional
Cada solicitud solicita departamento, municipio/ciudad, barrio o sector y dirección. Esto permite registrar oportunidades de recolección en cualquier zona de Colombia. La asignación geográfica avanzada y los filtros por distancia quedan previstos para la siguiente iteración.


## Indicadores dinámicos
Los indicadores del panel y la portada se calculan desde SQLite con los registros reales: usuarios, publicaciones, estados y kilogramos confirmados en recolecciones. No son cifras de demostración. Las cuentas de recolector requieren verificación administrativa.

## Cuenta administradora inicial
Configura `ADMIN_EMAIL`, `ADMIN_PASSWORD` y `SECRET_KEY` como variables de entorno en Render. Cambia la contraseña inicial antes de compartir el sitio. El rol administrador no se puede seleccionar en el registro público.


En Render define también `DATABASE_PATH=/var/data/geoecosof.db` solo si has conectado un disco persistente montado en `/var/data`. Sin almacenamiento persistente, SQLite puede perder datos al reiniciar o desplegar el servicio.
