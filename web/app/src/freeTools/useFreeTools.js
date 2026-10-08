import { computed, toValue } from 'vue'
import { useLaunch } from '@/composables/useLaunch'
import { selectFreeTools } from './catalog'

/**
 * Herramientas gratuitas que se pueden enseñar ahora, de un módulo o de todos.
 *
 * Es lo único que consulta la interfaz: ningún hub declara las suyas. Un módulo
 * sin herramientas devuelve una lista vacía y quien la pinta se calla.
 *
 * @param {string|import('vue').Ref<string>|null} [moduleId] - Módulo
 *   (`'themis'`, `'acheron'`…), también reactivo; `null` pide las de todos.
 * @returns {{tools: import('vue').ComputedRef<Array<object>>}} Entradas del
 *   catálogo con su `path`, filtradas por módulo y por las superficies del
 *   lanzamiento que el servidor tiene abiertas (ver `selectFreeTools`).
 */
export function useFreeTools(moduleId = null) {
  const { isSurfaceEnabled } = useLaunch()
  const tools = computed(() => selectFreeTools({ moduleId: toValue(moduleId), isSurfaceEnabled }))
  return { tools }
}
