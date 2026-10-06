<template>
  <InfoPage :eyebrow="t('docs.eyebrow')" :title="t('docs.technical.title')">
    <p>{{ t('docs.technical.intro') }}</p>

    <nav class="doc-cards">
      <router-link v-for="tool in tools" :key="tool" :to="`/docs/tecnica/${tool}`" class="doc-card" :data-module="tool" :aria-label="t('docs.technical.readPage', { name: TOOL_NAMES[tool] })">
        <img :src="TOOL_ICONS[tool]" alt="" aria-hidden="true" width="56" height="56" />
        <span class="doc-card-text">
          <span class="doc-card-name">{{ TOOL_NAMES[tool] }}</span>
          <span class="doc-card-blurb">{{ t(`moduleHub.modules.${tool}`) }}</span>
        </span>
        <span class="doc-card-arrow" aria-hidden="true">→</span>
      </router-link>
    </nav>
  </InfoPage>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'
import { availableDocTools } from '@/content/documentation'
import { TOOL_ICONS, TOOL_NAMES } from '@/content/documentation/tools'

/**
 * Portada de la documentación técnica: una tarjeta por cada herramienta que
 * ya tiene página. Las que todavía no la tienen no se anuncian.
 */

const { t } = useI18n()

const tools = availableDocTools()
</script>

<style scoped>
.doc-cards { margin-top: 2.2rem; display: flex; flex-direction: column; gap: 0.9rem; }
.doc-card {
  display: flex; align-items: center; gap: 1.3rem;
  padding: 1.2rem 1.4rem;
  border: 1px solid var(--border-med); border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--accent-dim), transparent 70%);
  text-decoration: none;
  transition: border-color 0.15s, transform 0.15s;
}
.doc-card:hover { border-color: var(--accent); transform: translateX(3px); }
.doc-card img { width: 56px; height: 56px; object-fit: contain; flex-shrink: 0; }
.doc-card-text { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; flex: 1; }
.doc-card-name { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 600; color: var(--accent-bright); }
.doc-card-blurb { font-size: var(--fs-body); line-height: 1.5; color: var(--text-dim); }
.doc-card-arrow { font-size: var(--fs-xl); color: var(--accent); }
</style>
