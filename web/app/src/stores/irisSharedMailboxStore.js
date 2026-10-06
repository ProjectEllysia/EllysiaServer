import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

/**
 * Buzones compartidos de la organización: los que la persona puede ver, sus
 * análisis y, para quien los administra, quién más tiene acceso.
 */
export const useIrisSharedMailboxStore = defineStore('irisSharedMailbox', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()

  const mailboxes = ref([])
  const loading = ref(false)
  const saving = ref(false)

  /**
   * Hace una petición y, si falla, enseña el error del servidor.
   *
   * @param {string} path - Ruta de la API.
   * @param {RequestInit} [options] - Opciones de `fetch`.
   * @returns {Promise<Response|null>} La respuesta si fue bien; `null` si no.
   */
  async function request(path, options) {
    const res = await apiFetch(path, options)
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('iris.shared.requestFailed')), 'error')
      return null
    }
    return res
  }

  async function fetchMailboxes() {
    loading.value = true
    try {
      const res = await request('/iris/mailbox/shared')
      mailboxes.value = res ? ((await res.json()).mailboxes ?? []) : []
    } finally {
      loading.value = false
    }
  }

  /**
   * Conecta un buzón compartido (solo el dueño de la organización).
   *
   * @param {object} data - `provider`, `address` o `imap`, `folder` y `fullMessageMode`.
   * @returns {Promise<boolean>} `true` si quedó conectado.
   */
  async function createMailbox(data) {
    saving.value = true
    try {
      const res = await request('/iris/mailbox/shared', { method: 'POST', body: JSON.stringify(data) })
      if (!res) return false
      toast.show(i18n.global.t('iris.shared.created'), 'success')
      await fetchMailboxes()
      return true
    } finally {
      saving.value = false
    }
  }

  /**
   * @param {number} id - Buzón.
   * @returns {Promise<Array|null>} Personas con acceso, o `null` si no se pudo.
   */
  async function fetchMembers(id) {
    const res = await request(`/iris/mailbox/shared/${id}/members`)
    return res ? ((await res.json()).members ?? []) : null
  }

  /**
   * @param {number} id - Buzón.
   * @param {number} userId - Persona de la organización.
   * @param {'viewer'|'manager'} access - Acceso que se le da.
   * @returns {Promise<boolean>} `true` si se guardó.
   */
  async function setMember(id, userId, access) {
    return Boolean(await request(`/iris/mailbox/shared/${id}/members/${userId}`, {
      method: 'PUT', body: JSON.stringify({ access }),
    }))
  }

  /**
   * @param {number} id - Buzón.
   * @param {number} userId - Persona.
   * @returns {Promise<boolean>} `true` si se quitó.
   */
  async function removeMember(id, userId) {
    return Boolean(await request(`/iris/mailbox/shared/${id}/members/${userId}`, { method: 'DELETE' }))
  }

  /**
   * @param {number} id - Buzón.
   * @param {number} [page] - Página, desde 1.
   * @returns {Promise<{analyses: Array, total: number}|null>} La página, o `null` si no se pudo.
   */
  async function fetchAnalyses(id, page = 1) {
    const res = await request(`/iris/mailbox/shared/${id}/analyses?page=${page}&perPage=20`)
    return res ? res.json() : null
  }

  /**
   * @param {number} id - Buzón.
   * @param {number} analysisId - Análisis.
   * @returns {Promise<object|null>} El informe completo, o `null` si no se pudo.
   */
  async function fetchAnalysis(id, analysisId) {
    const res = await request(`/iris/mailbox/shared/${id}/analyses/${analysisId}`)
    return res ? res.json() : null
  }

  return {
    mailboxes, loading, saving,
    fetchMailboxes, createMailbox, fetchMembers, setMember, removeMember, fetchAnalyses, fetchAnalysis,
  }
})
