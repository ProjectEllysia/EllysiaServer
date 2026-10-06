import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

/**
 * Store de la red de Themis: los grupos de equipos y su riesgo de movimiento
 * lateral.
 *
 * Un grupo es una red definida por su rango: los equipos que el usuario ya ha
 * escaneado y cuya dirección cae dentro. El riesgo lateral no se guarda en
 * ningún sitio: la API lo calcula al pedirlo, sobre el último escaneo de cada
 * equipo, así que aquí se guarda solo la última respuesta de cada grupo y de
 * cada escaneo de red, para no recalcular al plegar y desplegar.
 */
export const useThemisNetworkStore = defineStore('themisNetwork', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()

  const groups = reactive({ items: [], loading: false, error: null, creating: false })

  /**
   * Riesgo lateral por ámbito, indexado por `group:<id>` o `scan:<id>`.
   * Cada entrada: `{ loading, error, hostCount, risks }`.
   */
  const riskByScope = reactive({})

  /** Carga los grupos de equipos del usuario. */
  async function loadGroups() {
    groups.loading = true
    try {
      const res = await apiFetch('/themis/asset-groups')
      if (!res?.ok) {
        groups.items = []
        groups.error = await apiError(res, i18n.global.t('themisStore.network.loadFailed'))
        return
      }
      const data = await res.json()
      groups.items = data.results ?? []
      groups.error = null
    } catch {
      groups.items = []
      groups.error = i18n.global.t('themisStore.network.connectionError')
    } finally { groups.loading = false }
  }

  /**
   * Crea un grupo de equipos.
   *
   * @param {string} name - Nombre legible, único entre los del usuario.
   * @param {string} cidr - El rango de la red (`10.0.0.0/24`).
   * @returns {Promise<object|null>} El grupo creado, o `null` si la API lo rechazó.
   */
  async function createGroup(name, cidr) {
    groups.creating = true
    try {
      const res = await apiFetch('/themis/asset-groups', {
        method: 'POST', body: JSON.stringify({ name, cidr }),
      })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('themisStore.network.createFailed')), 'error')
        return null
      }
      const data = await res.json()
      const group = { groupId: data.groupId, name: data.name, cidr: data.cidr, createdAt: new Date().toISOString() }
      groups.items.push(group)
      toast.show(i18n.global.t('themisStore.network.created', { name: data.name }), 'success')
      return group
    } catch {
      toast.show(i18n.global.t('themisStore.network.unreachable'), 'error')
      return null
    } finally { groups.creating = false }
  }

  /**
   * Borra un grupo. Los equipos y sus escaneos no se tocan.
   *
   * @param {number} groupId - El grupo.
   * @returns {Promise<boolean>} `true` si se borró.
   */
  async function deleteGroup(groupId) {
    const res = await apiFetch(`/themis/asset-groups/${groupId}`, { method: 'DELETE' })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('themisStore.network.deleteFailed')), 'error')
      return false
    }
    const index = groups.items.findIndex(group => group.groupId === groupId)
    if (index !== -1) groups.items.splice(index, 1)
    delete riskByScope[`group:${groupId}`]
    toast.show(i18n.global.t('themisStore.network.deleted'), 'success')
    return true
  }

  /**
   * Pide el riesgo lateral de un grupo o de un escaneo de red.
   *
   * @param {'group'|'scan'} kind - Qué se analiza.
   * @param {number} id - El grupo o el escaneo (el padre de un escaneo de red).
   */
  async function loadRisk(kind, id) {
    const key = `${kind}:${id}`
    if (!riskByScope[key]) riskByScope[key] = reactive({ loading: false, error: null, hostCount: 0, risks: [] })
    const entry = riskByScope[key]
    entry.loading = true
    try {
      const param = kind === 'group' ? 'groupId' : 'scanId'
      const res = await apiFetch(`/themis/network-risk?${param}=${id}`)
      if (!res?.ok) {
        entry.error = await apiError(res, i18n.global.t('themisStore.network.riskFailed'))
        return
      }
      const data = await res.json()
      entry.hostCount = data.hostCount ?? 0
      entry.risks = data.risks ?? []
      entry.error = null
    } catch {
      entry.error = i18n.global.t('themisStore.network.connectionError')
    } finally { entry.loading = false }
  }

  /** Limpia el estado (logout sin recarga). */
  function $reset() {
    Object.assign(groups, { items: [], loading: false, error: null, creating: false })
    for (const key of Object.keys(riskByScope)) delete riskByScope[key]
  }

  return { groups, riskByScope, loadGroups, createGroup, deleteGroup, loadRisk, $reset }
})
