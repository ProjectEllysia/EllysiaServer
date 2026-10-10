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
   * Pide qué pasaría con la evaluación al pasar un marco a la versión vigente.
   *
   * @param {string} key - Clave del marco.
   * @returns {Promise<object|null>} El plan, o `null` si la API lo rechazó (el error queda en
   *   `state.error`).
   */
  async function previewUpgrade(key) {
    try {
      const res = await apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/upgrade-preview`)
      if (!res?.ok) { state.error = await apiError(res, i18n.global.t('eunomia.frameworks.previewFailed')); return null }
      return await res.json()
    } catch { state.error = i18n.global.t('eunomia.frameworks.offline'); return null }
  }

  const upgrade = (key) => run(key, () => apiFetch(`/eunomia/adoptions/${encodeURIComponent(key)}/upgrade`, {
    method: 'POST',
  }), i18n.global.t('eunomia.frameworks.upgradeFailed'))

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
   * Carga las plantillas de documentos disponibles.
   *
   * @returns {Promise<{ok: boolean, templates: Array, message: string|null}>}
   */
  async function loadTemplates() {
    try {
      const res = await apiFetch('/eunomia/templates')
      if (!res?.ok) return { ok: false, templates: [], message: await apiError(res, i18n.global.t('eunomia.templates.loadFailed')) }
      return { ok: true, templates: (await res.json()).templates ?? [], message: null }
    } catch { return { ok: false, templates: [], message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Carga el formulario de una plantilla con lo guardado y lo precargado.
   *
   * @param {string} key - Clave de la plantilla.
   * @param {number|string|null} [recordId] - Ficha de un registro de la que toma datos.
   * @returns {Promise<{ok: boolean, data: object|null, message: string|null}>}
   */
  async function loadTemplateDraft(key, recordId = null) {
    try {
      const query = recordId ? `?recordId=${encodeURIComponent(recordId)}` : ''
      const res = await apiFetch(`/eunomia/templates/${encodeURIComponent(key)}/draft${query}`)
      if (!res?.ok) return { ok: false, data: null, message: await apiError(res, i18n.global.t('eunomia.templates.loadFailed')) }
      return { ok: true, data: await res.json(), message: null }
    } catch { return { ok: false, data: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Guarda lo escrito en el formulario de una plantilla.
   *
   * @param {string} key - Clave de la plantilla.
   * @param {Record<string, string>} values - Valores a guardar (ver `valuesToSave`).
   * @returns {Promise<{ok: boolean, data: object|null, message: string|null}>}
   */
  async function saveTemplateDraft(key, values) {
    try {
      const res = await apiFetch(`/eunomia/templates/${encodeURIComponent(key)}/draft`, {
        method: 'PUT', body: JSON.stringify({ values }),
      })
      if (!res?.ok) return { ok: false, data: null, message: await apiError(res, i18n.global.t('eunomia.templates.saveFailed')) }
      return { ok: true, data: await res.json(), message: null }
    } catch { return { ok: false, data: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Pide el documento de una plantilla, que se genera en segundo plano.
   *
   * @param {string} key - Clave de la plantilla.
   * @param {'pdf'|'docx'} format - Formato de salida.
   * @param {number|string|null} [recordId] - Ficha de un registro de la que toma datos.
   * @returns {Promise<{ok: boolean, data: object|null, message: string|null}>}
   */
  async function requestDocument(key, format, recordId = null) {
    try {
      const res = await apiFetch(`/eunomia/templates/${encodeURIComponent(key)}/documents`, {
        method: 'POST', body: JSON.stringify({ format, recordId: recordId ? Number(recordId) : null }),
      })
      if (!res?.ok) return { ok: false, data: null, message: await apiError(res, i18n.global.t('eunomia.documents.requestFailed')) }
      return { ok: true, data: await res.json(), message: null }
    } catch { return { ok: false, data: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Carga una página de los documentos generados.
   *
   * @param {number} [page=1]
   * @returns {Promise<{ok: boolean, documents: Array, total: number, message: string|null}>}
   */
  async function loadDocuments(page = 1) {
    try {
      const res = await apiFetch(`/eunomia/documents?page=${page}&perPage=20`)
      if (!res?.ok) return { ok: false, documents: [], total: 0, message: await apiError(res, i18n.global.t('eunomia.documents.loadFailed')) }
      const body = await res.json()
      return { ok: true, documents: body.documents ?? [], total: body.total ?? 0, message: null }
    } catch { return { ok: false, documents: [], total: 0, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Descarga el fichero de un documento listo; va por `apiFetch` porque la ruta exige el JWT.
   *
   * @param {{id: number, downloadName: string|null}} item
   * @returns {Promise<boolean>} Si se descargó.
   */
  async function downloadDocument(item) {
    try {
      const res = await apiFetch(`/eunomia/documents/${item.id}/download`)
      if (!res?.ok) return false
      const url = URL.createObjectURL(await res.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = item.downloadName || 'documento'
      link.click()
      URL.revokeObjectURL(url)
      return true
    } catch { return false }
  }

  /**
   * Borra un documento y su fichero.
   *
   * @param {number} id
   * @returns {Promise<boolean>} Si se borró.
   */
  async function deleteDocument(id) {
    try {
      const res = await apiFetch(`/eunomia/documents/${id}`, { method: 'DELETE' })
      return !!res?.ok
    } catch { return false }
  }

  /**
   * Carga los tipos de registro con su número de fichas.
   *
   * @returns {Promise<{ok: boolean, registers: Array, message: string|null}>}
   */
  async function loadRegisters() {
    try {
      const res = await apiFetch('/eunomia/registers')
      if (!res?.ok) return { ok: false, registers: [], message: await apiError(res, i18n.global.t('eunomia.registers.loadFailed')) }
      return { ok: true, registers: (await res.json()).registers ?? [], message: null }
    } catch { return { ok: false, registers: [], message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Carga un registro: su definición y sus fichas.
   *
   * @param {string} key - Tipo de registro.
   * @param {boolean} [includeArchived=false]
   * @returns {Promise<{ok: boolean, data: object|null, message: string|null}>}
   */
  async function loadRegister(key, includeArchived = false) {
    try {
      const res = await apiFetch(`/eunomia/registers/${encodeURIComponent(key)}?includeArchived=${includeArchived}`)
      if (!res?.ok) return { ok: false, data: null, message: await apiError(res, i18n.global.t('eunomia.registers.loadFailed')) }
      return { ok: true, data: await res.json(), message: null }
    } catch { return { ok: false, data: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Hace una operación de escritura sobre un registro y devuelve su resultado.
   *
   * @param {string} path - Ruta bajo `/eunomia/registers/`.
   * @param {string} method - Método HTTP.
   * @param {object|null} body - Cuerpo JSON, o `null`.
   * @returns {Promise<{ok: boolean, data: object|null, conflict: object|null, message: string|null}>}
   */
  async function writeRegister(path, method, body = null) {
    try {
      const res = await apiFetch(`/eunomia/registers/${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) })
      if (res?.status === 409) {
        const error = await res.json().catch(() => ({}))
        return { ok: false, data: null, conflict: error?.details?.current ?? {}, message: null }
      }
      if (!res?.ok) return { ok: false, data: null, conflict: null, message: await apiError(res, i18n.global.t('eunomia.registers.saveFailed')) }
      return { ok: true, data: await res.json(), conflict: null, message: null }
    } catch { return { ok: false, data: null, conflict: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Descarga un registro en CSV o PDF.
   *
   * @param {string} key - Tipo de registro.
   * @param {'csv'|'pdf'} format
   * @returns {Promise<boolean>} Si se descargó.
   */
  async function exportRegister(key, format) {
    try {
      const res = await apiFetch(`/eunomia/registers/${encodeURIComponent(key)}/export?format=${format}`)
      if (!res?.ok) return false
      const url = URL.createObjectURL(await res.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `${key}.${format}`
      link.click()
      URL.revokeObjectURL(url)
      return true
    } catch { return false }
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
   * Carga las evidencias que otros módulos aportan solas a un control.
   *
   * @param {string} key - Clave del marco.
   * @param {string} identifier - Identificador del control.
   * @returns {Promise<Array|null>} Las evidencias, o `null` si no se pudieron cargar.
   */
  async function loadAutomaticEvidence(key, identifier) {
    try {
      const res = await apiFetch(
        `/eunomia/adoptions/${encodeURIComponent(key)}/automatic-evidence/${encodeURIComponent(identifier)}`)
      return res?.ok ? ((await res.json()).evidence ?? []) : null
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

  /**
   * Carga las evidencias del dueño efectivo, con los controles que demuestran.
   *
   * @returns {Promise<{evidence: Array, usage: object|null}>} Las fichas y el uso de
   *   almacenamiento (`usedBytes`, `limitBytes`); vacío y sin uso si falla.
   */
  async function loadEvidence() {
    try {
      const res = await apiFetch('/eunomia/evidence')
      if (!res?.ok) return { evidence: [], usage: null }
      const data = await res.json()
      return { evidence: data.evidence ?? [], usage: data.usage ?? null }
    } catch { return { evidence: [], usage: null } }
  }

  /**
   * Sube un fichero como evidencia.
   *
   * @param {File} file - El fichero elegido.
   * @param {{title?: string, description?: string, validUntil?: string}} [fields]
   * @returns {Promise<{ok: boolean, evidence: object|null, message: string|null}>}
   */
  async function uploadEvidence(file, { title = '', description = '', validUntil = '' } = {}) {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    form.append('description', description)
    if (validUntil) form.append('validUntil', validUntil)
    try {
      const res = await apiFetch('/eunomia/evidence', { method: 'POST', body: form })
      if (!res?.ok) return { ok: false, evidence: null, message: await apiError(res, i18n.global.t('eunomia.evidence.uploadFailed')) }
      return { ok: true, evidence: await res.json(), message: null }
    } catch { return { ok: false, evidence: null, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Enlaza o desenlaza una evidencia con un control.
   *
   * @param {number} evidenceId - Id de la evidencia.
   * @param {string} framework - Clave del marco.
   * @param {string} identifier - Identificador del control.
   * @param {boolean} linked - `true` para enlazar, `false` para quitar el enlace.
   * @returns {Promise<{ok: boolean, message: string|null}>}
   */
  async function setEvidenceLink(evidenceId, framework, identifier, linked) {
    try {
      const res = linked
        ? await apiFetch(`/eunomia/evidence/${evidenceId}/links`, {
          method: 'POST', body: JSON.stringify({ frameworkKey: framework, controlIdentifier: identifier }) })
        : await apiFetch(`/eunomia/evidence/${evidenceId}/links/${encodeURIComponent(framework)}/${encodeURIComponent(identifier)}`,
          { method: 'DELETE' })
      if (!res?.ok) return { ok: false, message: await apiError(res, i18n.global.t('eunomia.evidence.linkFailed')) }
      return { ok: true, message: null }
    } catch { return { ok: false, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Borra una evidencia.
   *
   * @param {number} evidenceId - Id de la evidencia.
   * @returns {Promise<{ok: boolean, message: string|null}>}
   */
  async function deleteEvidence(evidenceId) {
    try {
      const res = await apiFetch(`/eunomia/evidence/${evidenceId}`, { method: 'DELETE' })
      if (!res?.ok) return { ok: false, message: await apiError(res, i18n.global.t('eunomia.evidence.deleteFailed')) }
      return { ok: true, message: null }
    } catch { return { ok: false, message: i18n.global.t('eunomia.frameworks.offline') } }
  }

  /**
   * Descarga una evidencia como fichero.
   *
   * @param {{id: number, filename: string}} evidence - La evidencia.
   * @returns {Promise<boolean>} `true` si se descargó.
   */
  async function downloadEvidence(evidence) {
    const res = await apiFetch(`/eunomia/evidence/${evidence.id}/download`)
    if (!res?.ok) return false
    const url = URL.createObjectURL(await res.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = evidence.filename
    link.click()
    URL.revokeObjectURL(url)
    return true
  }

  /** El catálogo repartido entre disponibles, adoptados y archivados. */
  function grouped() {
    return splitFrameworks(state.catalog, state.adoptions)
  }

  return { state, load, adopt, archive, restore, previewRemoval, previewUpgrade, upgrade, loadTemplates, loadTemplateDraft, saveTemplateDraft, loadRegisters, loadRegister, writeRegister, exportRegister, requestDocument, loadDocuments, downloadDocument, deleteDocument, loadTree, loadSummary, loadHistory, loadAutomaticEvidence, saveAssessment,
    loadEvidence, uploadEvidence, setEvidenceLink, deleteEvidence, downloadEvidence, grouped }
})
