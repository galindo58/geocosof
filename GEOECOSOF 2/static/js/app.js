// Interacciones generales de GEOECOSOF.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form[onsubmit]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!confirm('¿Estás seguro de realizar esta acción?')) event.preventDefault();
    });
  });
});
