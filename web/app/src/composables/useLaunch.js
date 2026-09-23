import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { CLOSED_LAUNCH_STATE, fetchLaunchState, isSurfaceOpen } from './launchState'

/**
 * Qué funciones están abiertas al público, pedido una sola vez por carga de página.
 *
 * Mismo patrón que `useAppVersion`: estado de módulo compartido por todos los
 * que lo llamen, `fetch` crudo porque la portada lo necesita sin sesión, y una
 * sola petición en vuelo. Lo usan el guard del router (`meta.surface`) y los
 * componentes que esconden llamadas a la acción.
 *
 * Hasta que llega la respuesta todo cuenta como cerrado (`launchState.js`).
 */

const launchState = ref(CLOSED_LAUNCH_STATE)
const isLoaded = ref(false)
let inFlight = null

/**
 * Carga el estado si no está cargado ya.
 *
 * @returns {Promise<void>} Se resuelve cuando hay estado; nunca se rechaza.
 */
export function ensureLaunchStateLoaded() {
  if (isLoaded.value) return Promise.resolve()
  if (!inFlight) {
    inFlight = fetchLaunchState().then((state) => {
      launchState.value = state
      isLoaded.value = true
    })
  }
  return inFlight
}

/**
 * Acceso reactivo al estado de lanzamiento.
 *
 * @returns {{
 *   launchState: import('vue').Ref<{mode: string, surfaces: Record<string, boolean>}>,
 *   isPreview: import('vue').ComputedRef<boolean>,
 *   isLoaded: import('vue').Ref<boolean>,
 *   isSurfaceEnabled: (surface: string) => boolean,
 * }}
 */
export function useLaunch() {
  ensureLaunchStateLoaded()
  const auth = useAuthStore()

  /**
   * @param {string} surface - Nombre de la superficie.
   * @returns {boolean} Si quien mira puede usarla; aplica la exención del
   *   administrador principal donde la API también la aplica.
   */
  function isSurfaceEnabled(surface) {
    return isSurfaceOpen(launchState.value, surface, auth.isRoot)
  }

  const isPreview = computed(() => launchState.value.mode !== 'public')

  return { launchState, isPreview, isLoaded, isSurfaceEnabled }
}
