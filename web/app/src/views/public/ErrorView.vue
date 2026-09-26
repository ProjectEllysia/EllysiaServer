<template>
  <InfoPage :eyebrow="t('errorPage.eyebrow', { code: error.code })" :title="t(`errorPage.${error.entry.key}.title`, { code: error.code })">
    <p v-for="index in error.entry.paragraphs" :key="index">{{ t(`errorPage.${error.entry.key}.p${index}`) }}</p>

    <p v-if="error.entry.reload" class="note">
      <button type="button" class="retry" @click="reload">{{ t('errorPage.retry') }}</button>
    </p>

    <p v-if="links.length" class="note">
      {{ t('errorPage.fromHere') }}
      <template v-for="(link, index) in links" :key="link.to">
        <template v-if="index > 0">{{ index === links.length - 1 ? t('errorPage.lastSeparator') : t('errorPage.separator') }}</template>
        <router-link :to="link.to">{{ t(`errorPage.links.${link.label}`) }}</router-link>
      </template>.
    </p>
  </InfoPage>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLaunch } from '@/composables/useLaunch'
import InfoPage from '@/components/shared/InfoPage.vue'
import { resolveError } from '@/views/public/errorCatalog'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()

/**
 * Vista genérica de errores: UNA vista para todos los códigos. Resuelve la
 * entrada del catálogo (`views/public/errorCatalog.js`) y pinta su copia, sus
 * enlaces y, si la entrada lo pide, el botón de reintento. Añadir un error
 * nuevo es añadir una entrada al catálogo, no crear otra vista.
 *
 * Código de error: el de la ruta `/error/:code` si la hay (la usan los guards,
 * el `onError` del router y el `handle_errors` del Caddyfile), o 404 cuando
 * la URL simplemente no existe y ha caído en el comodín del router.
 */
const error = computed(() => resolveError(route.params.code ?? route.meta.errorCode ?? 404))

const router = useRouter()
const { isSurfaceEnabled } = useLaunch()

/**
 * Enlaces de salida de la entrada, sin los que llevan a una ruta cerrada al
 * público (`meta.surface`): mandar a alguien a otra página de «no disponible»
 * no es una salida.
 */
const links = computed(() => error.value.entry.links.filter((link) => {
  const surface = router.resolve(link.to).meta.surface
  return !surface || isSurfaceEnabled(surface)
}))

/** Botón de "volver a intentar" de las entradas que lo declaran. */
function reload() {
  window.location.reload()
}
</script>

<style scoped>
.retry {
  font-family: var(--font-body); font-size-adjust: var(--fsa-body);
  font-size: var(--fs-md); font-weight: 600;
  color: var(--text);
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  padding: 0.55rem 1.2rem;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.retry:hover { background: var(--accent); color: var(--bg); }
</style>
