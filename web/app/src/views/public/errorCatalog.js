/**
 * Catálogo de errores HTTP de la SPA.
 *
 * Es el único sitio que hay que tocar para añadir (o afinar) una página de
 * error: `ErrorView.vue` resuelve el código contra este catálogo y monta la
 * entrada correspondiente. Un código sin entrada cae en una página genérica
 * (o en la de 500 si es un error de servidor), así que ninguna URL puede
 * terminar en una pantalla en blanco.
 *
 * Los textos viven en el diccionario, bajo `errorPage.<clave>`:
 * `title` (con el hueco `{code}`) y `p1`, `p2`… Cada entrada:
 * - `key`: la rama del diccionario (`'404'`, `'generic'`…).
 * - `paragraphs`: cuántos párrafos tiene esa rama.
 * - `links`: enlaces de salida; `label` es la clave de `errorPage.links`, cuyo
 *   texto lleva el verbo y el artículo incorporados para que la frase «Desde
 *   aquí puedes …» suene bien sin concordar nada.
 * - `reload`: opcional; si es true, la vista muestra un botón de recarga.
 */
export const ERROR_CATALOG = {
  404: {
    key: '404',
    paragraphs: 1,
    links: [
      { to: '/', label: 'home' },
      { to: '/themis', label: 'tools' },
      { to: '/planes', label: 'plans' },
    ],
  },
  403: {
    key: '403',
    paragraphs: 2,
    links: [
      { to: '/', label: 'home' },
      { to: '/themis', label: 'tools' },
      { to: '/planes', label: 'plans' },
    ],
  },
  409: {
    key: '409',
    paragraphs: 2,
    reload: true,
    links: [
      { to: '/', label: 'home' },
      { to: '/themis', label: 'tools' },
    ],
  },
  500: {
    key: '500',
    paragraphs: 2,
    reload: true,
    links: [
      { to: '/', label: 'home' },
    ],
  },
}

/** Entrada para los códigos 4xx sin entrada propia; su título lleva el código. */
const GENERIC_ENTRY = {
  key: 'generic',
  paragraphs: 1,
  links: [
    { to: '/', label: 'home' },
    { to: '/planes', label: 'plans' },
  ],
}

/**
 * Resuelve un código HTTP contra el catálogo.
 *
 * - Entrada exacta → esa.
 * - 5xx sin entrada → la de 500 (cualquier error de servidor se explica
 *   igual de bien con su copia).
 * - 4xx sin entrada → entrada genérica con el código.
 * - Código inválido o ausente → 404.
 *
 * @param {string|number|undefined} code - Código HTTP (ruta, meta o query).
 * @returns {{ code: number, entry: object }} Código normalizado y su entrada.
 */
export function resolveError(code) {
  const numeric = Number(code)
  if (!Number.isInteger(numeric) || numeric < 100 || numeric > 599) {
    return { code: 404, entry: ERROR_CATALOG[404] }
  }
  const entry = ERROR_CATALOG[numeric] ?? (numeric >= 500 ? ERROR_CATALOG[500] : GENERIC_ENTRY)
  return { code: numeric, entry }
}
