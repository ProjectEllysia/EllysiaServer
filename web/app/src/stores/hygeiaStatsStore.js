import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { STATS_METRICS } from '@/components/hygeia/statsMath'

/**
 * Store de la vista de estadísticas de Hygeia.
 *
 * Guarda los tres ejes del selector —alcance, métrica y periodo— y las
 * respuestas de los endpoints de estadísticas que la vista pinta. No calcula
 * nada: el principio del roadmap es que el servidor agrega y el cliente
 * formatea, así que aquí solo se guarda lo que llega y se traduce la selección
 * a parámetros de consulta.
 *
 * Cada bloque de datos tiene su propio error en vez de uno compartido: el
 * panorama del parque y el resumen de un activo son dos peticiones
 * independientes, y que falle una no debe borrar de la pantalla lo que la otra
 * ya había traído.
 */
export const useHygeiaStatsStore = defineStore('hygeiaStats', () => {
  const { apiFetch, apiError } = useApi()

  const state = reactive({
    // Selección del usuario. `scope` manda sobre cuál de los ids hace falta.
    scope: 'fleet',
    assetId: null,
    tagId: null,
    metric: 'cpuPct',
    period: '24h',
    aggregation: 'avg',

    // Panorama del parque: una foto del ahora, sin periodo.
    overview: null, overviewLoading: false, overviewError: null,

    // El bloque que corresponde al alcance elegido.
    summary: null, tagStats: null, ranking: null,
    scopeLoading: false, scopeError: null,
  })

  /** Todas las métricas del catálogo, en una lista para el parámetro `metrics`. */
  const allMetricKeys = STATS_METRICS.map((metric) => metric.key).join(',')

  /** Panorama del parque: activos por estado, anomalías abiertas y última actividad. */
  async function fetchOverview() {
    state.overviewLoading = true
    try {
      const res = await apiFetch('/hygeia/stats/overview')
      if (!res?.ok) {
        state.overviewError = await apiError(res, 'No se pudo cargar el panorama del parque.')
        return
      }
      state.overview = await res.json()
      state.overviewError = null
    } catch { state.overviewError = 'No se pudo conectar con la API.' }
    finally { state.overviewLoading = false }
  }

  /**
   * Carga el bloque del alcance seleccionado.
   *
   * Un alcance al que le falta su id (etiqueta elegida sin etiqueta, activo
   * sin activo) no lanza la petición: el servidor la rechazaría, y el estado
   * intermedio mientras el usuario todavía está eligiendo no es un error que
   * merezca pintarse.
   */
  async function fetchScope() {
    const request = buildScopeRequest()
    if (!request) { state.scopeError = null; return }

    state.scopeLoading = true
    try {
      const res = await apiFetch(request.path)
      if (!res?.ok) {
        state.scopeError = await apiError(res, 'No se pudieron cargar las estadísticas.')
        return
      }
      const body = await res.json()
      state.summary = request.kind === 'asset' ? body : null
      state.tagStats = request.kind === 'tag' ? body : null
      state.ranking = request.kind === 'fleet' ? body : null
      state.scopeError = null
    } catch { state.scopeError = 'No se pudo conectar con la API.' }
    finally { state.scopeLoading = false }
  }

  /**
   * La ruta que toca pedir para la selección actual, o `null` si está incompleta.
   *
   * @returns {{kind: string, path: string}|null}
   */
  function buildScopeRequest() {
    const period = encodeURIComponent(state.period)
    if (state.scope === 'asset') {
      if (!state.assetId) return null
      return {
        kind: 'asset',
        path: `/hygeia/assets/${state.assetId}/stats/summary`
          + `?metrics=${allMetricKeys}&period=${period}`,
      }
    }
    if (state.scope === 'tag') {
      if (!state.tagId) return null
      return {
        kind: 'tag',
        path: `/hygeia/stats/by-tag/${state.tagId}`
          + `?metrics=${allMetricKeys}&agg=${state.aggregation}&period=${period}`,
      }
    }
    // El parque no tiene un resumen propio: la pregunta que se contesta ahí es
    // "¿qué activo está peor?", que es el ranking por la métrica elegida.
    return {
      kind: 'fleet',
      path: `/hygeia/stats/ranking?metric=${state.metric}`
        + `&agg=${state.aggregation === 'sum' ? 'avg' : state.aggregation}`
        + `&order=desc&limit=10&period=${period}`,
    }
  }

  /** Cambia el alcance, limpiando lo que ya no aplica. */
  function selectScope(scope) {
    state.scope = scope
    if (scope !== 'asset') state.summary = null
    if (scope !== 'tag') state.tagStats = null
    if (scope !== 'fleet') state.ranking = null
  }

  return { state, fetchOverview, fetchScope, buildScopeRequest, selectScope }
})
