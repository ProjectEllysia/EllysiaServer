import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { usePolling } from '@/composables/usePolling'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

/**
 * Store de los escaneos de exposición cloud de Themis.
 *
 * Un escaneo cloud no es un escaneo como los demás: mira un dominio y los
 * recursos en la nube que el usuario declara suyos, no un equipo. En la API
 * vive con los escaneos de dominio (`/themis/osint`), así que tampoco cabe en
 * las listas por tipo de `themisStore`: tiene su propia lista, su detalle y
 * sus informes.
 *
 * Los escaneos en marcha y los informes que se están generando se sondean con
 * `usePolling`, con la misma espera creciente que la lista de Lybra: rápido
 * mientras algo cambia, cada vez más espaciado mientras no.
 */
export const useThemisCloudStore = defineStore('themisCloud', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()

  /** Lista de escaneos cloud del usuario, del más nuevo al más viejo. */
  const scans = reactive({ items: [], loading: false, error: null })
  /** Escaneo abierto y su detalle (hallazgos, recursos, subdominios). */
  const selectedId = ref(null)
  const detail = reactive({ scan: null, loading: false, error: null })
  /** Informes PDF del escaneo abierto. */
  const docs = reactive({ items: [], loading: false })
  const launching = ref(false)
  const generating = ref(false)

  /** Cuántos escaneos se piden: los que caben en la lista sin paginar. */
  const LIST_LIMIT = 50
  const POLL_INTERVAL_MS = 4000
  const POLL_MAX_INTERVAL_MS = 30000
  const POLL_BACKOFF = 1.5

  const isActive = status => status === 'pending' || status === 'running'

  let scanPoller = null
  let docsPoller = null

  /** Carga la lista de escaneos cloud; si hay alguno en marcha, sigue sondeando. */
  async function loadScans() {
    scans.loading = true
    try {
      const res = await apiFetch(`/themis/osint?mode=cloud&limit=${LIST_LIMIT}`)
      if (!res?.ok) {
        scans.items = []
        scans.error = await apiError(res, i18n.global.t('themisStore.cloud.loadFailed'))
        return
      }
      const data = await res.json()
      scans.items = data.results ?? []
      scans.error = null
    } catch {
      scans.items = []
      scans.error = i18n.global.t('themisStore.cloud.connectionError')
    } finally {
      scans.loading = false
      _ensureScanPolling()
    }
  }

  /**
   * Arranca el sondeo si hay escaneos en marcha y no hay uno ya corriendo.
   *
   * Cada vuelta relee la lista y, si el escaneo abierto está entre los que
   * cambian, también su detalle: así el resultado aparece solo al terminar.
   */
  function _ensureScanPolling() {
    if (scanPoller?.isRunning() || !scans.items.some(scan => isActive(scan.status))) return
    let fingerprint = ''
    scanPoller = usePolling(async () => {
      const res = await apiFetch(`/themis/osint?mode=cloud&limit=${LIST_LIMIT}`)
      if (!res?.ok) return true
      const data = await res.json()
      const items = data.results ?? []
      const selected = items.find(scan => scan.osintScanId === selectedId.value)
      const wasActive = scans.items.find(scan => scan.osintScanId === selectedId.value)
      scans.items = items
      if (selected && wasActive && isActive(wasActive.status) && !isActive(selected.status)) {
        loadDetail(selected.osintScanId)
      }
      const next = items.map(scan => `${scan.osintScanId}:${scan.status}`).join(',')
      const changed = next !== fingerprint
      fingerprint = next
      if (!items.some(scan => isActive(scan.status))) return false
      // `true` es novedad y vuelve al ritmo rápido; `undefined` estira la espera.
      return changed ? true : undefined
    }, { intervalMs: POLL_INTERVAL_MS, backoffFactor: POLL_BACKOFF, maxIntervalMs: POLL_MAX_INTERVAL_MS, immediate: false })
    scanPoller.start()
  }

  /**
   * Lanza un escaneo cloud y lo deja abierto.
   *
   * @param {{domain: string, cloudResources: string[], checkSubdomains: boolean}} payload
   * @returns {Promise<boolean>} `true` si la API lo aceptó.
   */
  async function launchCloudScan(payload) {
    launching.value = true
    try {
      const res = await apiFetch('/themis/cloud', { method: 'POST', body: JSON.stringify(payload) })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('themisStore.cloud.launchFailed')), 'error')
        return false
      }
      const data = await res.json()
      toast.show(i18n.global.t('themisStore.cloud.started', { domain: data.domain }), 'success')
      await loadScans()
      await selectScan(data.osintScanId)
      return true
    } catch {
      toast.show(i18n.global.t('themisStore.cloud.unreachable'), 'error')
      return false
    } finally { launching.value = false }
  }

  /**
   * Abre un escaneo: carga su detalle y sus informes.
   *
   * @param {number|null} id - El escaneo, o `null` para cerrar el que haya.
   */
  async function selectScan(id) {
    selectedId.value = id
    docsPoller?.stop()
    detail.scan = null
    docs.items = []
    if (!id) return
    await Promise.all([loadDetail(id), loadDocs(id)])
  }

  /** Carga el detalle de un escaneo cloud. */
  async function loadDetail(id) {
    detail.loading = true
    try {
      const res = await apiFetch(`/themis/osint/${id}`)
      if (selectedId.value !== id) return
      if (!res?.ok) {
        detail.scan = null
        detail.error = await apiError(res, i18n.global.t('themisStore.cloud.detailFailed'))
        return
      }
      detail.scan = await res.json()
      detail.error = null
    } catch {
      detail.error = i18n.global.t('themisStore.cloud.connectionError')
    } finally { detail.loading = false }
  }

  /** Carga los informes PDF de un escaneo cloud. */
  async function loadDocs(id) {
    docs.loading = true
    try {
      const res = await apiFetch(`/themis/osint/${id}/documents`)
      if (selectedId.value !== id) return
      docs.items = res?.ok ? ((await res.json()).documents ?? []) : []
    } catch { docs.items = [] }
    finally { docs.loading = false }
  }

  /**
   * Pide el informe PDF del escaneo abierto y sigue su generación.
   *
   * El informe se genera en segundo plano: aparece al momento en la lista como
   * «generando» y se sondea hasta que queda listo o falla.
   *
   * @param {number} id - El escaneo.
   * @returns {Promise<boolean>} `true` si la API aceptó la petición.
   */
  async function generateReport(id) {
    generating.value = true
    try {
      const res = await apiFetch(`/themis/osint/${id}/report`, { method: 'POST' })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('themisStore.cloud.reportFailed')), 'error')
        return false
      }
      toast.show(i18n.global.t('themisStore.scans.documentGenerating'), 'success')
      await loadDocs(id)
      docsPoller?.stop()
      docsPoller = usePolling(async () => {
        if (selectedId.value !== id) return false
        await loadDocs(id)
        return docs.items.some(doc => doc.status === 'running' || doc.status === 'pending')
      }, { intervalMs: 1500, maxAttempts: 40, immediate: false })
      docsPoller.start()
      return true
    } catch {
      toast.show(i18n.global.t('themisStore.cloud.unreachable'), 'error')
      return false
    } finally { generating.value = false }
  }

  /** Detiene los sondeos y limpia el estado (logout sin recarga). */
  function $reset() {
    scanPoller?.stop()
    docsPoller?.stop()
    scanPoller = null
    docsPoller = null
    Object.assign(scans, { items: [], loading: false, error: null })
    selectedId.value = null
    Object.assign(detail, { scan: null, loading: false, error: null })
    Object.assign(docs, { items: [], loading: false })
    launching.value = false
    generating.value = false
  }

  return {
    scans, selectedId, detail, docs, launching, generating,
    loadScans, launchCloudScan, selectScan, loadDetail, loadDocs, generateReport,
    $reset,
  }
})
