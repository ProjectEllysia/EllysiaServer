import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

export const useIrisMailboxStore = defineStore('irisMailbox', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()

  const providers = ref([])
  const connections = ref([])
  const loading = ref(false)
  const listError = ref(null)
  const connecting = ref(false)
  // IDs de conexión con un sondeo manual en curso — alimenta el estado de
  // "ocupado" por fila (antes no existía ninguno) mientras se espera a que
  // el worker de iris.ingest, que corre aparte, termine de verdad.
  const syncingIds = reactive(new Set())

  async function fetchProviders() {
    const res = await apiFetch('/iris/mailbox/providers')
    if (!res?.ok) return
    const data = await res.json()
    providers.value = data.providers ?? []
  }

  async function fetchConnections() {
    loading.value = true
    try {
      const res = await apiFetch('/iris/mailbox/connections')
      if (!res?.ok) { connections.value = []; listError.value = i18n.global.t('irisStore.mailbox.loadFailed'); return }
      const data = await res.json()
      connections.value = data.connections ?? []
      listError.value = null
    } catch {
      connections.value = []
      listError.value = i18n.global.t('irisStore.mailbox.loadConnection')
    } finally {
      loading.value = false
    }
  }

  /**
   * Inicia el flujo OAuth: pide la URL de autorización y navega la página
   * completa a Google/Microsoft. Redirect de página completa (no popup)
   * porque el backend ya cierra el flujo con un redirect de servidor tras
   * el callback (`GET /iris/mailbox/callback` -> vuelve aquí) -- no hace
   * falta postMessage ni gestión de ventanas.
   *
   * @param {string} provider - `gmail` o `microsoft`.
   * @param {{remediationEnabled?: boolean}} [options] - `remediationEnabled` pide al
   *   proveedor permiso de escritura para que Iris pueda actuar sobre el buzón.
   */
  async function connect(provider, { remediationEnabled = false } = {}) {
    connecting.value = true
    try {
      const res = await apiFetch('/iris/mailbox/connect', {
        method: 'POST',
        body: JSON.stringify({ provider, remediationEnabled }),
      })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.connectFailed')), 'error')
        return
      }
      const data = await res.json()
      window.location.href = data.authorizeUrl
    } finally {
      connecting.value = false
    }
  }

  async function updateConnection(id, { folder, status } = {}) {
    const body = {}
    if (folder !== undefined) body.folder = folder
    if (status !== undefined) body.status = status
    const res = await apiFetch(`/iris/mailbox/connections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.updateFailed')), 'error')
      return false
    }
    toast.show(i18n.global.t('irisStore.mailbox.updated'), 'success')
    await fetchConnections()
    return true
  }

  async function deleteConnection(id) {
    const res = await apiFetch(`/iris/mailbox/connections/${id}`, { method: 'DELETE' })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.deleteFailed')), 'error')
      return false
    }
    toast.show(i18n.global.t('irisStore.mailbox.deleted'), 'success')
    connections.value = connections.value.filter((c) => c.connectionId !== id)
    return true
  }

  /**
   * Antes esta función no refetcheaba nunca — "Sondear ahora" parecía no
   * hacer nada porque `lastSyncAt` en la lista se quedaba congelado hasta
   * la próxima recarga manual de la página. El sondeo real corre en un
   * worker de `iris.ingest` aparte (encolado, no síncrono con este POST),
   * así que una única foto inmediata normalmente todavía no lo refleja:
   * se refetchea una vez al encolar y una segunda vez tras un margen para
   * capturar el resultado real, y `syncingIds` da al usuario una señal
   * visual de que algo está en marcha durante ese margen.
   */
  async function syncConnection(id) {
    syncingIds.add(id)
    try {
      const res = await apiFetch(`/iris/mailbox/connections/${id}/sync`, { method: 'POST' })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.syncFailed')), 'error')
        return false
      }
      toast.show(i18n.global.t('irisStore.mailbox.syncQueued'), 'success')
      await fetchConnections()
      setTimeout(() => { fetchConnections() }, 3000)
      return true
    } finally {
      setTimeout(() => { syncingIds.delete(id) }, 3000)
    }
  }

  /**
   * Conecta un buzón personal por IMAP; el servidor prueba las credenciales antes de guardarlas.
   *
   * @param {{host: string, port: number, username: string, password: string, folder?: string|null,
   *   fullMessageMode?: boolean}} data - Servidor IMAP con TLS y contraseña de aplicación.
   * @returns {Promise<boolean>} `true` si quedó conectado.
   */
  async function connectImap(data) {
    connecting.value = true
    try {
      const res = await apiFetch('/iris/mailbox/imap', { method: 'POST', body: JSON.stringify(data) })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.connectFailed')), 'error')
        return false
      }
      toast.show(i18n.global.t('iris.connections.connected'), 'success')
      await fetchConnections()
      return true
    } finally {
      connecting.value = false
    }
  }

  /**
   * Cambia la contraseña de aplicación de una conexión IMAP (se prueba antes de guardarla).
   *
   * @param {number} id - Conexión.
   * @param {string} password - Contraseña nueva.
   * @returns {Promise<boolean>} `true` si se guardó.
   */
  async function rotateCredentials(id, password) {
    const res = await apiFetch(`/iris/mailbox/connections/${id}/credentials`, {
      method: 'PUT', body: JSON.stringify({ password }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.updateFailed')), 'error')
      return false
    }
    toast.show(i18n.global.t('irisStore.mailbox.updated'), 'success')
    await fetchConnections()
    return true
  }

  /**
   * Carpetas reales de la cuenta de una conexión.
   *
   * @param {number} id - Conexión.
   * @returns {Promise<Array<{providerId: string, displayName: string, folderType: string}>|null>}
   *   Las carpetas, o `null` si no se pudieron leer.
   */
  async function fetchFolders(id) {
    const res = await apiFetch(`/iris/mailbox/connections/${id}/folders`)
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.loadFailed')), 'error')
      return null
    }
    return (await res.json()).folders ?? []
  }

  /**
   * Cambia las carpetas que se vigilan además de la principal.
   *
   * @param {number} id - Conexión.
   * @param {string[]} folders - Ids de carpeta.
   * @returns {Promise<boolean>} `true` si se guardó.
   */
  async function setFolders(id, folders) {
    const res = await apiFetch(`/iris/mailbox/connections/${id}/folders`, {
      method: 'PUT', body: JSON.stringify({ folders }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('irisStore.mailbox.updateFailed')), 'error')
      return false
    }
    toast.show(i18n.global.t('irisStore.mailbox.updated'), 'success')
    await fetchConnections()
    return true
  }

  function $reset() {
    providers.value = []
    connections.value = []
    loading.value = false
    listError.value = null
    connecting.value = false
    syncingIds.clear()
  }

  return {
    providers, connections, loading, listError, connecting, syncingIds,
    fetchProviders, fetchConnections, connect, updateConnection, deleteConnection, syncConnection,
    connectImap, rotateCredentials, fetchFolders, setFolders,
    $reset,
  }
})
