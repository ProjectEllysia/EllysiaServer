import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { i18n } from '@/i18n'
import { splitFrameworks } from '@/components/eunomia/frameworks'

/**
 * Store de la configuración de Eunomia: qué marcos hay, cuáles tiene adoptados el dueño
 * efectivo de los datos y las tres operaciones (adoptar, quitar, restaurar).
 *
 * Un miembro de una organización ve lo del dueño y no puede operar: `ownership.isOwnData`
 * lo dice y la API lo impone con un 403.
 */
export const useEunomiaStore = defineStore('eunomia', () => {
  const { apiFetch, apiError } = useApi()

  const state = reactive({
    catalog: [], adoptions: [], ownership: { isOwnData: true },
    loading: false, error: null, busyKey: null,
  })

  /** Carga el catálogo y las adopciones. */
  async function load() {
    state.loading = true
    try {
      const [catalogRes, adoptionsRes] = await Promise.all([
        apiFetch('/eunomia/frameworks'), apiFetch('/eunomia/adoptions'),
      ])
      if (!catalogRes?.ok) { state.error = await apiError(catalogRes, i18n.global.t('eunomia.frameworks.loadFailed')); return }
      if (!adoptionsRes?.ok) { state.error = await apiError(adoptionsRes, i18n.global.t('eunomia.frameworks.loadFailed')); return }
      state.catalog = (await catalogRes.json()).frameworks ?? []
      const adoptions = await adoptionsRes.json()
      state.adoptions = adoptions.adoptions ?? []
      state.ownership = adoptions.ownership ?? { isOwnData: true }
      state.error = null
    } catch { state.error = i18n.global.t('eunomia.frameworks.offline') }
    finally { state.loading = false }
  }

  /**
   * Ejecuta una operación sobre un marco y recarga si salió bien.
   *
   * @param {string} key - Clave del marco.
   * @param {() => Promise<Response>} request - La petición.
   * @param {string} failedMessage - Texto si la API no da uno propio.
   * @returns {Promise<{ok: boolean, message: string|null}>} `message` es el error ya traducido.
   */
  async function run(key, request, failedMessage) {
    state.busyKey = key
    try {
      const res = await request()
      if (!res?.ok) return { ok: false, message: await apiError(res, failedMessage) }
      await load()
      return { ok: true, message: null }
    } catch { return { ok: false, message: i18n.global.t('eunomia.frameworks.offline') } }
    finally { state.busyKey = null }
  }

  const adopt = (key) => run(key, () => apiFetch('/eunomia/adoptions', {
    method: 'POST', body: JSON.stringify({ frameworkKey: key }),
  }), i18n.global.t('eunomia.frameworks.adoptFailed'))

  const archive = (key) => run(key, () => apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  }), i18n.global.t('eunomia.frameworks.removeFailed'))

  const restore = (key) => run(key, () => apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/restore`, {
    method: 'POST',
  }), i18n.global.t('eunomia.frameworks.restoreFailed'))

  /**
   * Pide qué se perdería al quitar un marco.
   *
   * @param {string} key - Clave del marco.
   * @returns {Promise<object|null>} La vista previa, o `null` si la API la rechazó.
   */
  async function previewRemoval(key) {
    try {
      const res = await apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/removal-preview`)
      if (!res?.ok) { state.error = await apiError(res, i18n.global.t('eunomia.frameworks.previewFailed')); return null }
      return await res.json()
    } catch { state.error = i18n.global.t('eunomia.frameworks.offline'); return null }
  }

  /**
   * Carga el árbol personal de un marco adoptado: catálogo más las evaluaciones del dueño.
   *
   * @param {string} key - Clave del marco.
   * @returns {Promise<{ok: boolean, data: object|null, notAdopted: boolean, message: string|null}>}
   */
  async function loadTree(key) {
    try {
      const res = await apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/tree`)
      if (res?.status === 404) return { ok: false, data: null, notAdopted: true, message: null }
      if (!res?.ok) return { ok: false, data: null, notAdopted: false, message: await apiError(res, i18n.global.t('eunomia.tree.loadFailed')) }
      return { ok: true, data: await res.json(), notAdopted: false, message: null }
    } catch {
      return { ok: false, data: null, notAdopted: false, message: i18n.global.t('eunomia.frameworks.offline') }
    }
  }

  /**
   * Carga el resumen de cumplimiento de un marco adoptado.
   *
   * @param {string} key - Clave del marco.
   * @returns {Promise<object|null>} El resumen, o `null` si no se pudo cargar.
   */
  async function loadSummary(key) {
    try {
      const res = await apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/summary`)
      return res?.ok ? await res.json() : null
    } catch { return null }
  }

  /**
   * Carga el historial de cambios de un control.
   *
   * @param {string} key - Clave del marco.
   * @param {string} identifier - Identificador del control.
   * @returns {Promise<Array>} Los eventos, del más reciente al más antiguo; vacío si falla.
   */
  async function loadHistory(key, identifier) {
    try {
      const res = await apiFetch(
        `/eunomia/adoptions/${encodeURIComponent(key)}/history/${encodeURIComponent(identifier)}`)
      if (!res?.ok) return []
      return (await res.json()).events ?? []
    } catch { return [] }
  }

  /**
   * Guarda la evaluación de un control.
   *
   * @param {string} key - Clave del marco.
   * @param {string} identifier - Identificador del control.
   * @param {object} body - `status`, `justification`, `notes`, `responsibleUserId`, `dueDate` y
   *   `updatedAt` (el testigo que vio el cliente).
   * @returns {Promise<{ok: boolean, assessment: object|null, conflict: object|null, message: string|null}>}
   *   `conflict` es la evaluación actual cuando alguien la cambió mientras se editaba (409).
   */
  async function saveAssessment(key, identifier, body) {
    try {
      const res = await apiFetch(
        `/eunomia/adoptions/${encodeURIComponent(key)}/controls/${encodeURIComponent(identifier)}`,
        { method: 'PUT', body: JSON.stringify(body) },
      )
      if (res?.ok) return { ok: true, assessment: await res.json(), conflict: null, message: null }
      if (res?.status === 409) {
        const error = await res.json().catch(() => ({}))
        return { ok: false, assessment: null, conflict: error?.details?.current ?? null,
          message: i18n.global.t('eunomia.tree.conflict') }
      }
      return { ok: false, assessment: null, conflict: null,
        message: await apiError(res, i18n.global.t('eunomia.tree.saveFailed')) }
    } catch {
      return { ok: false, assessment: null, conflict: null, message: i18n.global.t('eunomia.frameworks.offline') }
    }
  }

  /** El catálogo repartido entre disponibles, adoptados y archivados. */
  function grouped() {
    return splitFrameworks(state.catalog, state.adoptions)
  }

  return { state, load, adopt, archive, restore, previewRemoval, loadTree, loadSummary, loadHistory, saveAssessment, grouped }
})
