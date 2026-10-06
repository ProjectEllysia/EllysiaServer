<template>
  <router-view />
  <AppToast />
  <PreviewBanner />
</template>

<script setup>
// La sesión se restaura en main.js, antes de instalar el router: aquí era
// demasiado tarde, porque la primera navegación (y su guard) ya se había
// resuelto cuando App se montaba.
import { watch } from 'vue'
import AppToast from '@/components/shared/AppToast.vue'
import PreviewBanner from '@/components/shared/PreviewBanner.vue'
import { useSeo } from '@/composables/useSeo'
import { useAuthStore } from '@/stores/authStore'
import { useMfaStore } from '@/stores/mfaStore'
import { useToastStore } from '@/stores/toastStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const auth = useAuthStore()
const mfa = useMfaStore()
const toast = useToastStore()

let mfaCheckPromise = null
let mfaCheckToken = null

/** Comprueba MFA una vez por entrada de sesión, no en cada cambio de ruta. */
async function notifyIfMfaIsDisabled() {
  const token = auth.accessToken
  if (!token) return
  if (mfaCheckPromise && mfaCheckToken === token) return mfaCheckPromise

  mfaCheckToken = token
  mfaCheckPromise = (async () => {
    try {
      const status = await mfa.loadStatus()
      // El token puede haber sido revocado mientras terminaba la petición. No
      // muestres un aviso de una sesión anterior al usuario siguiente.
      if (auth.accessToken !== token || !status || status.enabled) return
      toast.show(
        t('session.mfaDisabled'),
        'warn',
        10000,
        { label: t('session.enableMfa'), to: '/profile#mfa' },
      )
    } catch (error) {
      // Un fallo al consultar el estado de seguridad no debe bloquear el SPA.
      console.error('[Ellysia] No se pudo comprobar el estado MFA:', error)
    }
  })().finally(() => {
    if (mfaCheckToken === token) {
      mfaCheckPromise = null
      mfaCheckToken = null
    }
  })

  return mfaCheckPromise
}

// Título, descripción, canonical y `robots` de cada página: ver `useSeo`.
useSeo()

watch(() => auth.isAuthenticated, (isAuthenticated) => {
  if (isAuthenticated) void notifyIfMfaIsDisabled()
  else toast.dismiss()
}, { immediate: true })
</script>
