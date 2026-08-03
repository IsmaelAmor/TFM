/**
 * Configuracion dependiente del entorno.
 *
 * La URL de la API vive aqui y no en los servicios: cambiar de maquina o
 * de puerto no debe obligar a tocar codigo de aplicacion.
 *
 * Para el build de produccion se anadiria un environment.prod.ts y su
 * fileReplacements en angular.json. No se hace ahora porque el TFM se
 * despliega y se defiende en local, y anadir la variante sin usarla seria
 * configuracion muerta.
 */
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api',
  /** Cada cuanto se refresca la cartera, en milisegundos. */
  refrescoMs: 5_000,
};
