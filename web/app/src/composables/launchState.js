/**
 * Qué funciones de Ellysia están abiertas al público, según `GET /system/launch`.
 *
 * Es la mitad pura de `useLaunch`: sin Vue, sin Pinia y sin el alias `@`,
 * para poder probarla con Node (`test/launchState.test.mjs`).
 *
 * La regla de fondo es la del servidor: ante la duda, cerrado. Mientras la
 * respuesta no llega, si la petición falla o si trae algo inesperado, todas las
 * superficies cuentan como cerradas. Esconder un botón de más un instante es
 * un mal menor; enseñar el alta en una instalación en vista previa, no.
 */

/** Estado que se usa hasta tener respuesta, o cuando la respuesta no sirve. */
export const CLOSED_LAUNCH_STATE = Object.freeze({ mode: 'preview', surfaces: Object.freeze({}) })

/**
 * Superficies en las que el servidor exime al administrador principal.
 *
 * Tiene que coincidir con la API: el alta y los precios son consultas
 * anónimas, y la IA externa no sabe para quién trabaja, así que en esas tres
 * no hay exención. Si la SPA eximiera donde la API no lo hace, el
 * administrador vería botones que acaban en un error.
 */
export const ROOT_EXEMPT_SURFACES = Object.freeze(['thirdPartyScanners', 'campaigns', 'mailboxConnectors'])

/**
 * Normaliza la respuesta de `GET /system/launch`.
 *
 * @param {unknown} body - Cuerpo JSON recibido.
 * @returns {{mode: string, surfaces: Record<string, boolean>}} El estado, o
 *   `CLOSED_LAUNCH_STATE` si el cuerpo no tiene la forma esperada. Solo se
 *   conservan los interruptores que son booleanos de verdad.
 */
export function parseLaunchState(body) {
  if (!body || typeof body !== 'object' || typeof body.surfaces !== 'object' || body.surfaces === null) {
    return CLOSED_LAUNCH_STATE
  }
  const surfaces = {}
  for (const [surface, isOpen] of Object.entries(body.surfaces)) {
    if (typeof isOpen === 'boolean') surfaces[surface] = isOpen
  }
  return { mode: body.mode === 'public' ? 'public' : 'preview', surfaces }
}

/**
 * Indica si una superficie está abierta para quien mira la página.
 *
 * @param {{mode: string, surfaces: Record<string, boolean>}} launchState - Estado ya normalizado.
 * @param {string} surface - Nombre de la superficie (`'registration'`, `'pricing'`…).
 * @param {boolean} [isRoot=false] - Si la sesión es del administrador principal.
 * @returns {boolean} `true` si el servidor la tiene abierta, o si la sesión es
 *   del administrador principal y la superficie admite su exención.
 */
export function isSurfaceOpen(launchState, surface, isRoot = false) {
  if (isRoot && ROOT_EXEMPT_SURFACES.includes(surface)) return true
  return launchState?.surfaces?.[surface] === true
}

/**
 * Pide el estado al servidor. Nunca lanza: un fallo es «todo cerrado».
 *
 * @param {typeof fetch} [fetchImpl=fetch] - Función `fetch` (se sustituye en los tests).
 * @returns {Promise<{mode: string, surfaces: Record<string, boolean>}>}
 */
export async function fetchLaunchState(fetchImpl = fetch) {
  try {
    const response = await fetchImpl('/system/launch', { cache: 'no-store' })
    if (!response.ok) return CLOSED_LAUNCH_STATE
    return parseLaunchState(await response.json())
  } catch {
    return CLOSED_LAUNCH_STATE
  }
}
