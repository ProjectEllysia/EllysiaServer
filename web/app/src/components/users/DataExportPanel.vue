<template>
  <section class="profile-section">
    <h2>{{ t('dataExport.title') }}</h2>
    <p class="section-desc">{{ t('dataExport.description') }}</p>

    <!-- Preparándose: se sondea hasta que está lista o falla. -->
    <p v-if="isBeingPrepared" class="export-state" role="status">
      <span class="spinner" aria-hidden="true"></span>{{ t('dataExport.preparing') }}
    </p>

    <!-- Lista: se descarga una sola vez. -->
    <div v-else-if="current?.status === 'done'" class="export-ready">
      <p class="export-state">
        {{ t('dataExport.ready', { size: formattedSize, date: formattedExpiry }) }}
      </p>
      <p class="hint">{{ t('dataExport.oneTime') }}</p>
      <div class="form-actions">
        <button type="button" class="btn btn--primary" :disabled="downloading" @click="download">
          {{ downloading ? t('dataExport.downloading') : t('dataExport.download') }}
        </button>
      </div>
    </div>

    <!-- Sin exportación viva: formulario para pedir otra. -->
    <form v-else class="profile-form" @submit.prevent="request">
      <p v-if="statusMessage" class="hint">{{ statusMessage }}</p>
      <div class="form-group">
        <label for="export-pwd">{{ t('dataExport.confirmPassword') }}</label>
        <input id="export-pwd" v-model="password" type="password" class="inp" required placeholder="••••••••" />
        <span class="hint">{{ t('dataExport.passwordWhy') }}</span>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn--primary" :disabled="requesting">
          {{ requesting ? t('dataExport.requesting') : t('dataExport.request') }}
        </button>
      </div>
    </form>

    <details class="export-contents">
      <summary>{{ t('dataExport.contentsTitle') }}</summary>
      <p>{{ t('dataExport.contents') }}</p>
      <p>{{ t('dataExport.notIncluded') }}</p>
    </details>
  </section>
</template>

<script setup>
/**
 * Descarga de todos los datos propios (RGPD, artículos 15 y 20).
 *
 * Pedirla exige la contraseña; el archivo se prepara en segundo plano y se
 * descarga **una sola vez** (el servidor lo borra al enviarlo y a las 24 horas).
 * Mientras se prepara se sondea con `usePolling`; si el usuario recarga la
 * página, el estado se recupera de `GET /users/me/export`.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApi } from '@/composables/useApi'
import { usePolling } from '@/composables/usePolling'
import { useToastStore } from '@/stores/toastStore'
import { useUtils } from '@/composables/useUtils'
import { formatDate } from '@/i18n/format'

const { t } = useI18n()
const { apiFetch, apiError } = useApi()
const toast = useToastStore()
const { triggerDownload, filenameFromResponse } = useUtils()

/** La última exportación, tal como la devuelve el servidor, o `null`. */
const current = ref(null)
const password = ref('')
const requesting = ref(false)
const downloading = ref(false)

const isBeingPrepared = computed(() => current.value && ['pending', 'running'].includes(current.value.status))

/** Aviso cuando la última exportación ya no se puede descargar o falló. */
const statusMessage = computed(() => {
  const status = current.value?.status
  return status ? t(`dataExport.status.${status}`) : ''
})

const formattedSize = computed(() => {
  const bytes = current.value?.sizeBytes ?? 0
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
})
const formattedExpiry = computed(() => formatDate(current.value?.expiresAt, {
  day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
}))

/** Lee el estado de la última exportación. Devuelve `false` cuando ya no hay que seguir sondeando. */
async function refresh() {
  const res = await apiFetch('/users/me/export')
  if (!res?.ok) return false
  current.value = (await res.json()).export
  return isBeingPrepared.value
}

// Cada 3 s: preparar un ZIP son segundos, y un sondeo más rápido solo gasta cupo.
const polling = usePolling(refresh, { intervalMs: 3000, immediate: false })

async function request() {
  requesting.value = true
  try {
    const res = await apiFetch('/users/me/export', { method: 'POST', body: JSON.stringify({ password: password.value }) })
    if (!res?.ok) {
      toast.show(await apiError(res, t('dataExport.requestFailed')), 'error')
      return
    }
    current.value = await res.json()
    toast.show(t('dataExport.requested'), 'success')
    polling.start()
  } finally {
    requesting.value = false
    password.value = ''
  }
}

async function download() {
  downloading.value = true
  try {
    const res = await apiFetch(`/users/me/export/${current.value.id}/download`)
    if (!res?.ok) {
      toast.show(await apiError(res, t('dataExport.downloadFailed')), 'error')
      await refresh()
      return
    }
    triggerDownload(await res.blob(), filenameFromResponse(res, 'ellysia-datos.zip'))
    // El servidor ya borró el archivo: lo que queda es el aviso de que se descargó.
    await refresh()
  } finally {
    downloading.value = false
  }
}

onMounted(async () => {
  if (await refresh()) polling.start()
})
</script>

<style scoped>
.profile-section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; margin-bottom: 1.1rem; }
.profile-section h2 { font-size: var(--fs-xl); font-weight: 600; margin: 0 0 0.85rem; color: var(--text); font-family: var(--font-display); font-size-adjust: var(--fsa-display); }
.section-desc { font-size: var(--fs-md); color: var(--text-dim); margin: 0 0 0.85rem; }
.profile-form { display: flex; flex-direction: column; gap: 0.85rem; }
.form-group { display: flex; flex-direction: column; gap: 0.3rem; }
.form-group label { font-size: var(--fs-md); font-weight: 600; color: var(--text-dim); }
.inp { background: var(--bg); border: 1px solid var(--border-solid); border-radius: 6px; padding: 0.5rem 0.65rem; color: var(--text); font-size: var(--fs-input); outline: none; transition: border-color 0.2s; }
.inp:focus { border-color: var(--accent); }
.form-actions { display: flex; gap: 0.6rem; justify-content: flex-end; padding-top: 0.35rem; }
.hint { color: var(--text-muted); font-size: var(--fs-md); margin: 0; }
.export-state { display: flex; align-items: center; gap: 0.6rem; color: var(--text); font-size: var(--fs-lg); margin: 0 0 0.5rem; }
.spinner { width: 14px; height: 14px; border: 2px solid var(--border-solid); border-top-color: var(--accent); border-radius: 50%; animation: export-spin 0.8s linear infinite; }
@keyframes export-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
.export-contents { margin-top: 1rem; color: var(--text-muted); font-size: var(--fs-md); }
.export-contents summary { cursor: pointer; color: var(--text-dim); }
.export-contents p { margin: 0.5rem 0 0; line-height: 1.55; }
</style>
