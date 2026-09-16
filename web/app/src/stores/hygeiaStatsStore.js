import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import {
  MAX_COMPARISON_METRICS, STATS_METRICS, bucketForPeriod, metricOf,
} from '@/components/hygeia/statsMath'

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

    // Gráfica comparativa: las métricas superpuestas y sus series ya
    // alineadas por cubo. `bucket` se guarda porque la respuesta lo ecoa y es
    // lo que explica la resolución de la gráfica.
    comparisonMetrics: ['cpuPct', 'memPct'],
    series: [], bucket: null, seriesLoading: false, seriesError: null,
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

  /**
   * Carga las series de las métricas superpuestas, una petición por métrica.
   *
   * Todas se piden con el **mismo cubo explícito**, que es lo que las deja
   * alineadas: los cubos del servidor son múltiplos del reloj, así que dos
   * peticiones con el mismo tamaño caen en los mismos instantes y el cliente
   * no tiene que reconciliar ni interpolar nada. Dejar que cada métrica
   * eligiera su cubo desfasaría las líneas entre sí.
   *
   * Las peticiones van en paralelo: son independientes entre sí, y en serie
   * la gráfica tardaría el triple en aparecer. Una métrica que falle deja su
   * hueco sin tumbar las demás.
   *
   * @param {Array<number>} fleetAssetIds - Ids de los activos del usuario, que
   *   hacen falta solo en el alcance de parque (la serie multi-activo se pide
   *   por lista explícita de activos, hasta 50).
   */
  async function fetchComparison(fleetAssetIds = []) {
    const requests = buildSeriesRequests(fleetAssetIds)
    if (!requests) { state.series = []; state.seriesError = null; return }

    state.seriesLoading = true
    try {
      const responses = await Promise.all(requests.map(async (request) => {
        const res = await apiFetch(request.path)
        if (!res?.ok) return null
        const body = await res.json()
        // La respuesta trae una serie por activo salvo que se combine; en los
        // tres alcances de esta vista siempre es una sola.
        const [series] = body.series ?? []
        return {
          key: request.key,
          name: metricOf(request.key)?.name ?? request.key,
          points: series?.points ?? [],
          bucket: body.bucket ?? null,
        }
      }))
      const loaded = responses.filter(Boolean)
      state.series = loaded
      state.bucket = loaded[0]?.bucket ?? null
      state.seriesError = loaded.length
        ? null
        : 'No se pudieron cargar las series de las métricas elegidas.'
    } catch { state.seriesError = 'No se pudo conectar con la API.' }
    finally { state.seriesLoading = false }
  }

  /**
   * Una petición de serie por métrica seleccionada, o `null` si no procede.
   *
   * @param {Array<number>} fleetAssetIds - Activos del usuario, para el parque.
   * @returns {Array<{key: string, path: string}>|null}
   */
  function buildSeriesRequests(fleetAssetIds = []) {
    const metrics = state.comparisonMetrics.slice(0, MAX_COMPARISON_METRICS)
    if (!metrics.length) return null

    const bucket = bucketForPeriod(state.period)
    const period = encodeURIComponent(state.period)
    let scopeQuery = null

    if (state.scope === 'asset') {
      if (!state.assetId) return null
      scopeQuery = `assetIds=${state.assetId}`
    } else if (state.scope === 'tag') {
      if (!state.tagId) return null
      scopeQuery = `tagId=${state.tagId}&agg=${seriesAggregation()}`
    } else {
      // El parque se pide por lista explícita; el servidor admite hasta 50, y
      // por encima de eso la gráfica no se pide en vez de mandar una petición
      // que volvería como un error de validación.
      if (!fleetAssetIds.length || fleetAssetIds.length > 50) return null
      scopeQuery = `assetIds=${fleetAssetIds.join(',')}&agg=${seriesAggregation()}`
    }

    return metrics.map((key) => ({
      key,
      path: `/hygeia/stats/series?metric=${key}&${scopeQuery}`
        + `&bucketAgg=avg&bucket=${bucket}&period=${period}`,
    }))
  }

  /**
   * La agregación con la que se combinan los activos en la serie.
   *
   * `sum` solo lo admiten las métricas aditivas, y la gráfica superpone varias
   * a la vez: si una no fuera aditiva, esa petición volvería como un 400 y la
   * línea faltaría sin explicación. Por eso la serie combina con la media
   * cuando la selección incluye alguna métrica que no se puede sumar.
   *
   * @returns {string} `sum`, `avg` o `max`.
   */
  function seriesAggregation() {
    if (state.aggregation !== 'sum') return state.aggregation
    const allAdditive = state.comparisonMetrics.every((key) => metricOf(key)?.additive)
    return allAdditive ? 'sum' : 'avg'
  }

  /**
   * Añade o quita una métrica de la comparación.
   *
   * No deja quedarse sin ninguna —una gráfica vacía no dice nada— ni pasar del
   * tope: cada métrica superpuesta tiene su propia escala vertical, y a partir
   * de la cuarta la gráfica deja de comparar y empieza a estorbar.
   *
   * @param {string} key - Clave pública de la métrica.
   */
  function toggleComparisonMetric(key) {
    const selected = state.comparisonMetrics
    if (selected.includes(key)) {
      if (selected.length > 1) state.comparisonMetrics = selected.filter((m) => m !== key)
      return
    }
    if (selected.length < MAX_COMPARISON_METRICS) state.comparisonMetrics = [...selected, key]
  }

  /** Cambia el alcance, limpiando lo que ya no aplica. */
  function selectScope(scope) {
    state.scope = scope
    if (scope !== 'asset') state.summary = null
    if (scope !== 'tag') state.tagStats = null
    if (scope !== 'fleet') state.ranking = null
  }

  return {
    state, fetchOverview, fetchScope, buildScopeRequest, selectScope,
    fetchComparison, buildSeriesRequests, toggleComparisonMetric,
  }
})
