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
import { useLaunch } from '@/composables/useLaunch'
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

/**
 * Pide a los buscadores que no indexen Ellysia mientras esté en vista previa:
 * sus textos legales todavía no son definitivos. Hasta tener la respuesta
 * del servidor cuenta como vista previa, así que la etiqueta está desde el
 * primer momento y solo se quita cuando el modo es «abierto al público».
 * Caddy no conoce el modo, por eso lo decide la aplicación.
 */
const { isPreview } = useLaunch()
watch(isPreview, (isInPreview) => {
  let robotsTag = document.querySelector('meta[name="robots"]')
  if (isInPreview) {
    if (!robotsTag) {
      robotsTag = document.createElement('meta')
      robotsTag.setAttribute('name', 'robots')
      document.head.appendChild(robotsTag)
    }
    robotsTag.setAttribute('content', 'noindex')
  } else if (robotsTag) {
    robotsTag.remove()
  }
}, { immediate: true })

watch(() => auth.isAuthenticated, (isAuthenticated) => {
  if (isAuthenticated) void notifyIfMfaIsDisabled()
  else toast.dismiss()
}, { immediate: true })
</script>
