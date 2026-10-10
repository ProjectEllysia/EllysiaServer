<template>
  <section v-if="items === null || items.length" class="automatic" :aria-label="t('eunomia.automatic.title')">
    <h3>{{ t('eunomia.automatic.title') }}</h3>
    <p class="muted">{{ t('eunomia.automatic.intro') }}</p>
    <p v-if="items === null" class="muted">{{ t('eunomia.automatic.unavailable') }}</p>
    <ul v-else>
      <li v-for="(item, index) in items" :key="`${item.providerKey}-${index}`" :class="`status--${item.status}`">
        <p class="line">
          <strong>{{ item.title }}</strong>
          <span class="badge">{{ t(`eunomia.automatic.status.${item.status}`) }}</span>
        </p>
        <p v-if="item.summary" class="summary">{{ item.summary }}</p>
        <p class="meta">
          {{ item.providerName }}
          <template v-if="item.dataDate"> · {{ t('eunomia.automatic.dataDate', { date: formatDate(item.dataDate) }) }}</template>
          <router-link v-if="item.link" :to="item.link" class="link">{{ t('eunomia.automatic.open') }}</router-link>
        </p>
      </li>
    </ul>
  </section>
</template>

<script setup>
/**
 * Lo que otros módulos (Themis, Aegis, Hygeia…) ya saben y demuestra este control. No se sube
 * nada: se calcula al abrir el control.
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatDate } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'

const props = defineProps({
  node: { type: Object, required: true },
  framework: { type: String, required: true },
})
const { t } = useI18n()
const store = useEunomiaStore()

/** `[]` sin datos, `null` si no se pudo cargar. */
const items = ref([])

watch(() => props.node.identifier, async (identifier) => {
  items.value = []
  items.value = await store.loadAutomaticEvidence(props.framework, identifier)
}, { immediate: true })
</script>

<style scoped>
.automatic { padding-top: 1rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.6rem; }
h3 { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.muted, .meta { color: var(--text-muted); font-size: var(--fs-body); }
ul { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
li { border-inline-start: 3px solid var(--border-med); padding-inline-start: 0.7rem; }
.status--ok { border-color: var(--accent); }
.status--warning, .status--unavailable { border-color: var(--danger); }
.line { display: flex; gap: 0.6rem; align-items: center; color: var(--text-dim); font-size: var(--fs-md); }
.badge { color: var(--text-muted); font-size: var(--fs-body); }
.summary { color: var(--text-dim); font-size: var(--fs-md); }
.link { color: var(--accent); text-decoration: underline; margin-left: 0.6rem; }
</style>
