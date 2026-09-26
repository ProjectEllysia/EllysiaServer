import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { i18n } from '@/i18n'

/**
 * Store de escaneos programados de Themis (A2: extraído de themisStore).
 *
 * Sin acoplamiento con el resto de Themis — ni una sola función del store
 * principal leía o escribía este estado, así que fue el primer corte del
 * god-store a extraer.
 */
export const useThemisScheduledStore = defineStore('themisScheduled', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()

  const scheduled = reactive({ scans: [], loading: false, error: null })
  const scheduling = reactive({ showForm: false, submitting: false })

  /** Carga los escaneos programados del usuario. */
  async function loadScheduledScans() {
    scheduled.loading = true
    try {
      const res = await apiFetch('/themis/scheduled-scans')
      if (!res?.ok) { scheduled.scans = []; scheduled.error = i18n.global.t('themisStore.scheduled.loadFailed'); return }
      const data = await res.json()
      scheduled.scans = data.scheduledScans ?? []
      scheduled.error = null
    } catch { scheduled.scans = []; scheduled.error = i18n.global.t('themisStore.scheduled.connectionError') }
    finally { scheduled.loading = false }
  }

  /** Crea un nuevo escaneo programado. */
  async function createScheduledScan(payload) {
    scheduling.submitting = true
    try {
      const res = await apiFetch('/themis/scheduled-scans', { method: 'POST', body: JSON.stringify(payload) })
      if (!res?.ok) {
        toast.show(await apiError(res, i18n.global.t('themisStore.scheduled.createFailed')), 'error')
        return false
      }
      const data = await res.json()
      toast.show(i18n.global.t('themisStore.scheduled.created', { id: data.programedScanId }), 'success')
      await loadScheduledScans()
      scheduling.showForm = false
      return true
    } catch {
      toast.show(i18n.global.t('themisStore.scheduled.unreachable'), 'error')
      return false
    } finally { scheduling.submitting = false }
  }

  /** Revoca (desactiva) un escaneo programado. */
  async function deactivateScheduledScan(id) {
    const res = await apiFetch(`/themis/scheduled-scans/${id}`, { method: 'DELETE' })
    if (!res?.ok) { toast.show(i18n.global.t('themisStore.scheduled.revokeFailed'), 'error'); return false }
    toast.show(i18n.global.t('themisStore.scheduled.revoked'), 'success')
    await loadScheduledScans()
    return true
  }

  /** Elimina permanentemente un escaneo programado. */
  async function deleteScheduledScan(id) {
    const res = await apiFetch(`/themis/scheduled-scans/${id}/permanent`, { method: 'DELETE' })
    if (!res?.ok) { toast.show(i18n.global.t('themisStore.scheduled.deleteFailed'), 'error'); return false }
    toast.show(i18n.global.t('themisStore.scheduled.deleted'), 'success')
    await loadScheduledScans()
    return true
  }

  /** Muestra/oculta el formulario de creacion. */
  function toggleScheduledForm() {
    scheduling.showForm = !scheduling.showForm
  }

  /** Limpia el estado (Q6: logout SPA sin recarga dura). */
  function $reset() {
    Object.assign(scheduled, { scans: [], loading: false, error: null })
    Object.assign(scheduling, { showForm: false, submitting: false })
  }

  return {
    scheduled, scheduling,
    loadScheduledScans, createScheduledScan, deactivateScheduledScan, deleteScheduledScan, toggleScheduledForm,
    $reset,
  }
})
