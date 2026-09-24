/**
 * Qué ventana de escaneos hay que pedirle al backend, y a qué página volver
 * tras un borrado.
 *
 * Vive fuera de `themisStore` porque son cuentas que se pueden probar solas:
 * el store arrastra Pinia, Vue y media docena de composables.
 *
 * La ventana se mide en páginas reveladas (`loadedPages`) y se pide siempre
 * desde `page` con un `per_page` del tamaño acumulado, en una sola petición:
 * así un refresco —manual, o el sondeo que se rearma mientras hay un escaneo
 * corriendo— devuelve exactamente lo que había en pantalla, y un escaneo nuevo
 * entra por arriba sin duplicar filas. Todas las listas de Themis se recorren
 * hoy con paginador (`goToPage`), que deja `loadedPages` en 1: la petición es
 * entonces la página tal cual.
 */

/**
 * Tope de `per_page` del endpoint. Lo impone el backend
 * (`ResultsQuerySchema`: `validate.Range(min=1, max=100)`), así que pedir más
 * no sería una ventana más grande sino un 422.
 */
export const MAX_PER_PAGE = 100

/**
 * Traduce el estado de una lista a los parámetros de la petición.
 *
 * @param {{page?: number, perPage?: number, loadedPages?: number}} state
 *        El estado por tipo de escaneo (`scans.lybra`, `scans.nmap`, …).
 * @returns {{page: number, perPage: number}} Lo que va en la query.
 */
export function scanWindow(state) {
  // Un valor ausente y uno absurdo (0, negativo, NaN) se tratan igual: se cae
  // al defecto en vez de propagar una query que el backend rechazaría.
  const page = state?.page > 0 ? state.page : 1
  const perPage = state?.perPage > 0 ? state.perPage : 10
  const loadedPages = state?.loadedPages > 0 ? state.loadedPages : 1
  return { page, perPage: Math.min(perPage * loadedPages, MAX_PER_PAGE) }
}

/**
 * Página a la que volver tras quitar escaneos de la lista.
 *
 * Borrar las últimas filas de la última página la deja vacía: recargarla
 * tal cual pintaría una lista sin escaneos con el paginador diciendo que hay
 * más. Se retrocede hasta la última página que sigue existiendo con el total
 * ya descontado; si no queda ninguno, la primera.
 *
 * @param {{page?: number, perPage?: number, totalCount?: number}} state
 *        El estado de la lista antes del borrado (`scans.lybra`, `scans.nmap`, …).
 * @param {number} removed Escaneos borrados.
 * @returns {number} La página a pedir, siempre `>= 1`.
 */
export function pageAfterRemoval(state, removed) {
  const { page, perPage } = scanWindow(state)
  const remaining = Math.max(0, (state?.totalCount ?? 0) - removed)
  const lastPage = Math.max(1, Math.ceil(remaining / perPage))
  return Math.min(page, lastPage)
}
