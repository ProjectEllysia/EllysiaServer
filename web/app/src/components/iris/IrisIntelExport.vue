<template>
  <div class="intel-export" role="group" :aria-label="t('iris.intelExport.label')">
    <span class="intel-export-label" :title="t('iris.intelExport.hint')">{{ t('iris.intelExport.label') }}</span>
    <button
      v-for="format in FORMATS"
      :key="format"
      type="button"
      class="intel-export-btn"
      :disabled="busy"
      :title="t(`iris.intelExport.formats.${format}.hint`)"
      @click="download(format)"
    >{{ t(`iris.intelExport.formats.${format}.name`) }}</button>
  </div>
</template>

<script setup>
/**
 * Botones para llevarse los indicadores de un análisis o de una campaña a un
 * SIEM: el JSON de Iris (desactivado), STIX 2.1 o MISP.
 */
import { ref } from 'vue'
import { useIrisStore } from '@/stores/irisStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  /** Recurso de exportación de la API (`/iris/results/<id>/export/intel`…). */
  url: { type: String, required: true },
})

const FORMATS = ['json', 'stix', 'misp']

const store = useIrisStore()
const busy = ref(false)

async function download(format) {
  busy.value = true
  try {
    await store.downloadIntelExport(props.url, format)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.intel-export { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
.intel-export-label { font-size: var(--fs-xs); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.intel-export-btn {
  padding: 0.2rem 0.6rem; font-size: var(--fs-sm); font-weight: 600; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--border-med); background: transparent; color: var(--text-dim);
}
.intel-export-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-bright); }
.intel-export-btn:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
