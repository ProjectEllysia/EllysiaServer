/**
 * Documentos de Hygeia (estadísticas en CSV o PDF, e inventario en PDF).
 *
 * Los documentos se generan en segundo plano: pedir uno devuelve al instante
 * un documento «en cola», y el servidor lo genera después. Este store guarda
 * la página de documentos del usuario, pide documentos nuevos y, mientras
 * alguno siga en cola o generándose, vuelve a preguntar por la lista. Cuando
 * uno termina avisa con un toast, esté el usuario en la pantalla que esté:
 * el sondeo vive en el store, no en una vista.
 */

import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { usePolling } from '@/composables/usePolling'
import { useUtils } from '@/composables/useUtils'
import { describeDocument, documentStatusOf, hasActiveDocuments } from '@/components/hygeia/documents'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

// Cada cuánto se pregunta por los documentos que siguen generándose. Un CSV
// tarda segundos y un inventario grande algo más; con el backoff, un documento
// lento no gasta cupo a ritmo fijo.
const POLL_INTERVAL_MS = 3000
const POLL_MAX_INTERVAL_MS = 15000

export const useHygeiaDocumentsStore = defineStore('hygeiaDocuments', () => {
  const { apiFetch, apiError } = useApi()
  const { triggerDownload, filenameFromResponse } = useUtils()
  const toast = useToastStore()

  const state = reactive({
    documents: [],
    total: 0,
    page: 1,
    perPage: 20,
    loading: false,
    error: null,
    requesting: false,
  })

  // Estado anterior de cada documento vigilado, para avisar solo de los que
  // acaban de terminar y no de los que ya estaban listos al abrir la lista.
  const lastStatusById = new Map()

  // Se crea la primera vez que hace falta y no al montar el store: si el store
  // se usa por primera vez desde un componente, `usePolling` se engancharía a
  // su desmontaje y el sondeo moriría al salir de esa pantalla.
  let poller = null

  /** Arranca el sondeo de documentos activos, si no estaba ya en marcha. */
  function startPolling() {
    poller ??= usePolling(pollActiveDocuments, {
      intervalMs: POLL_INTERVAL_MS,
      backoffFactor: 1.5,
      maxIntervalMs: POLL_MAX_INTERVAL_MS,
      immediate: false,
    })
    poller.start()
  }

  /**
   * Avisa de los documentos que han pasado de activos a listos o fallidos.
   *
   * @param {Array<object>} documents - Documentos recién leídos del servidor.
   */
  function announceFinished(documents) {
    for (const document of documents) {
      const previous = lastStatusById.get(document.id)
      lastStatusById.set(document.id, document.status)
      if (!previous || !documentStatusOf(previous).isActive) continue
      const { title } = describeDocument(document, i18n.global.t)
      if (document.status === 'done') {
        toast.show(i18n.global.t('hygeiaStore.documents.ready', { title }), 'success', undefined,
          { label: i18n.global.t('hygeiaStore.documents.viewDocuments'), to: '/hygeia/documentos' })
      } else if (document.status === 'error') {
        toast.show(i18n.global.t('hygeiaStore.documents.failed', { title }), 'error')
      }
    }
  }

  /**
   * Carga una página de documentos.
   *
   * @param {object} [options]
   * @param {number} [options.page] - Página a cargar; por defecto la actual.
   * @param {boolean} [options.silent=false] - No marca la lista como cargando;
   *   es lo que usa el sondeo para no parpadear.
   * @returns {Promise<boolean>} Si la página se cargó.
   */
  async function fetchDocuments({ page = state.page, silent = false } = {}) {
    if (!silent) state.loading = true
    try {
      const res = await apiFetch(`/hygeia/documents?page=${page}&perPage=${state.perPage}`)
      if (!res?.ok) {
        state.error = await apiError(res, i18n.global.t('hygeiaStore.documents.loadFailed'))
        return false
      }
      const body = await res.json()
      state.documents = body.documents ?? []
      state.total = body.total ?? 0
      state.page = body.page ?? page
      state.error = null
      announceFinished(state.documents)
      if (hasActiveDocuments(state.documents)) startPolling()
      return true
    } catch {
      state.error = i18n.global.t('hygeiaStore.documents.offline')
      return false
    } finally {
      if (!silent) state.loading = false
    }
  }

  /**
   * Vuelta del sondeo: relee la página y para cuando ya no queda nada activo.
   *
   * @returns {Promise<false|null>} `false` para detener el sondeo; `null` para
   *   seguir espaciando las vueltas (el backoff de `usePolling`).
   */
  async function pollActiveDocuments() {
    await fetchDocuments({ silent: true })
    return hasActiveDocuments(state.documents) ? null : false
  }

  /**
   * Pide un documento nuevo y empieza a vigilarlo.
   *
   * @param {object} request - Cuerpo de `POST /hygeia/documents`: `kind`
   *   (`stats-csv`, `stats-pdf` o `inventory-pdf`) y los campos de su consulta.
   * @returns {Promise<object|null>} El documento creado, o `null` si el
   *   servidor lo rechazó (el motivo se muestra en un toast).
   */
  async function requestDocument(request) {
    state.requesting = true
    try {
      const res = await apiFetch('/hygeia/documents', {
        method: 'POST',
        body: JSON.stringify(request),
      })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('hygeiaStore.documents.requestFailed')), 'error')
        return null
      }
      const document = await res.json()
      lastStatusById.set(document.id, document.status)
      state.documents = [document, ...state.documents.filter((item) => item.id !== document.id)]
      state.total += 1
      toast.show(i18n.global.t('hygeiaStore.documents.preparing', { title: describeDocument(document, i18n.global.t).title }),
        'info', undefined, { label: i18n.global.t('hygeiaStore.documents.viewDocuments'), to: '/hygeia/documentos' })
      startPolling()
      return document
    } catch {
      toast.show(i18n.global.t('hygeiaStore.documents.offline'), 'error')
      return null
    } finally {
      state.requesting = false
    }
  }

  /**
   * Descarga el fichero de un documento listo.
   *
   * Va por `apiFetch` y no por un enlace porque la ruta exige el JWT, y una
   * descarga nativa del navegador no lleva la cabecera.
   *
   * @param {object} document - Documento en estado `done`.
   * @returns {Promise<boolean>} Si se descargó.
   */
  async function downloadDocument(document) {
    try {
      const res = await apiFetch(`/hygeia/documents/${document.id}/download`)
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('hygeiaStore.documents.downloadFailed')), 'error')
        return false
      }
      triggerDownload(await res.blob(), filenameFromResponse(res, document.downloadName || 'documento'))
      return true
    } catch {
      toast.show(i18n.global.t('hygeiaStore.documents.offline'), 'error')
      return false
    }
  }

  /**
   * Borra un documento y su fichero.
   *
   * @param {number} documentId - Id del documento.
   * @returns {Promise<boolean>} Si se borró.
   */
  async function deleteDocument(documentId) {
    try {
      const res = await apiFetch(`/hygeia/documents/${documentId}`, { method: 'DELETE' })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('hygeiaStore.documents.deleteFailed')), 'error')
        return false
      }
      lastStatusById.delete(documentId)
      state.documents = state.documents.filter((document) => document.id !== documentId)
      state.total = Math.max(0, state.total - 1)
      return true
    } catch {
      toast.show(i18n.global.t('hygeiaStore.documents.offline'), 'error')
      return false
    }
  }

  return { state, fetchDocuments, requestDocument, downloadDocument, deleteDocument }
})
