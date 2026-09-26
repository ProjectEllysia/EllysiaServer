import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { i18n } from '@/i18n'

/**
 * Store de estadísticas históricas de Themis (A2: extraído de themisStore).
 *
 * Único punto de acoplamiento con el núcleo: `setViewMode('history')`
 * comprueba `history.hosts.length` y llama a `loadHistoryHosts()` si hace
 * falta — el núcleo importa este store para ese único caso.
 */
export const useThemisHistoryStore = defineStore('themisHistory', () => {
  const { apiFetch, apiError } = useApi()

  const history = reactive({
    hosts: [], loading: false, error: null,
    selected: null,          // { target, scanType }
    chart: null, chartLoading: false, chartError: null,
    cache: {},                // `${type}|${target}` -> payload, evita refetch al re-seleccionar
  })

  /** Carga la lista de hosts escaneados por el usuario (para el selector). */
  async function loadHistoryHosts({ force = false } = {}) {
    history.loading = true
    try {
      const res = await apiFetch('/themis/history/hosts')
      if (!res?.ok) { history.hosts = []; history.error = i18n.global.t('themisStore.history.hostsFailed'); return }
      const data = await res.json()
      history.hosts = data.hosts ?? []
      if (force) history.cache = {}
      history.error = null
    } catch { history.hosts = []; history.error = i18n.global.t('themisStore.history.connectionError') }
    finally { history.loading = false }
  }

  /** Carga las estadísticas históricas de un host + herramienta. Usa cache salvo `force`. */
  async function loadHistoryStats(target, type, { force = false } = {}) {
    history.selected = { target, scanType: type }
    const key = `${type}|${target}`

    if (!force && history.cache[key]) {
      history.chart = history.cache[key]
      return
    }

    history.chartLoading = true
    history.chart = null
    try {
      const params = new URLSearchParams({ target, type })
      const res = await apiFetch(`/themis/history/stats?${params}`)
      if (!res?.ok) {
        history.chartError = await apiError(res, i18n.global.t('themisStore.history.statsFailed'))
        return
      }
      const data = await res.json()
      history.chart = data
      history.cache[key] = data
      history.chartError = null
    } catch {
      history.chartError = i18n.global.t('themisStore.history.unreachable')
    } finally { history.chartLoading = false }
  }

  /** Limpia el estado (Q6: logout SPA sin recarga dura). */
  function $reset() {
    Object.assign(history, {
      hosts: [], loading: false, error: null,
      selected: null,
      chart: null, chartLoading: false, chartError: null,
      cache: {},
    })
  }

  return { history, loadHistoryHosts, loadHistoryStats, $reset }
})
