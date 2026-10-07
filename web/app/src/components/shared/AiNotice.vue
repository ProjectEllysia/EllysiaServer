<template>
  <p class="ai-notice">
    <span class="ai-notice-text">{{ reviewed ? t('aiNotice.reviewed') : t('aiNotice.generated') }}</span>
    <router-link class="ai-notice-link" :to="{ path: '/gobierno-ia', hash: `#${tool}` }">{{ t('aiNotice.link') }}</router-link>
  </p>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

/**
 * Aviso de que un texto lo ha generado una inteligencia artificial, con un
 * enlace al apartado de su herramienta en la página «Gobierno de la IA».
 *
 * Se pone junto al texto generado, no en un pie de página: quien lo lee tiene
 * que saberlo en el momento de leerlo.
 */
defineProps({
  /** Herramienta que generó el texto; es el ancla del apartado (`aegis`, `themis`, `iris`). */
  tool: { type: String, required: true },
  /** El texto, tras generarse, lo ha editado una persona. Por defecto `false`. */
  reviewed: { type: Boolean, default: false },
})

const { t } = useI18n()
</script>

<style scoped>
.ai-notice {
  margin: 0 0 0.9rem; padding: 0.45rem 0.75rem;
  border-left: 3px solid var(--accent); border-radius: 0 6px 6px 0;
  background: var(--bg-card, transparent);
  color: var(--text-muted); font-size: var(--fs-sm, 0.85rem); line-height: 1.5;
}
.ai-notice-link { margin-left: 0.4rem; color: var(--accent); text-decoration: underline; }
</style>
