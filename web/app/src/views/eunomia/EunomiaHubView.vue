<template>
  <ModuleHub
    module-id="eunomia"
    :icon="eunomiaIcon"
    name="Eunomia"
    numeral="VI"
    epigraph="Ordo"
    :tagline="t(HUB_COPY_KEYS.eunomia.tagline)"
    :myth="t(HUB_COPY_KEYS.eunomia.myth)"
    :claim="t(HUB_COPY_KEYS.eunomia.claim)"
    tool-route="/eunomia/marcos"
    :tool-label="t('eunomiaHub.toolLabel')"
    :shortcuts="shortcuts"
    :highlight="highlight"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="loading" class="metric-loading">{{ t('eunomiaHub.loading') }}</p>
      <template v-else-if="adopted">
        <span class="metric-label">{{ t('eunomiaHub.adopted') }}</span>
        <span class="metric-value">{{ adopted }}</span>
        <span v-if="records" class="metric-sub">{{ t('eunomiaHub.records', { count: records }) }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('eunomiaHub.empty') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { HUB_COPY_KEYS, HUB_FEATURE_IDS } from '@/components/shared/moduleIdentity'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import eunomiaIcon from '@/assets/images/eunomia/Eunomia-Blue-BgN.png'

const { t } = useI18n()
const { apiFetch } = useApi()
const auth = useAuthStore()

// Dato de producto para la visita pública: sin sesión no hay marcos propios que contar.
const highlight = computed(() => ({
  label: t('eunomiaHub.highlight.label'), value: '4', sub: t('eunomiaHub.highlight.sub'),
}))

const shortcuts = computed(() => [
  { label: t('eunomiaHub.shortcuts.registers'), to: '/eunomia/registros' },
  { label: t('eunomiaHub.shortcuts.templates'), to: '/eunomia/plantillas' },
  { label: t('eunomiaHub.shortcuts.documents'), to: '/eunomia/documentos' },
])

/** Capacidades que se presentan; sus textos están en `eunomiaHub.features.<id>`. */
const features = computed(() => HUB_FEATURE_IDS.eunomia.map((id) => ({
  kicker: t(`eunomiaHub.features.${id}.kicker`),
  title: t(`eunomiaHub.features.${id}.title`),
  desc: t(`eunomiaHub.features.${id}.desc`),
})))

const resources = []

const loading = ref(true)
const adopted = ref(0)
const records = ref(0)

/** Cuántos marcos tiene adoptados el dueño de los datos y cuántas fichas tiene en sus registros. */
async function loadSummary() {
  loading.value = true
  try {
    const [frameworks, registers] = await Promise.all([apiFetch('/eunomia/adoptions'), apiFetch('/eunomia/registers')])
    if (frameworks?.ok) {
      const { adoptions = [] } = await frameworks.json()
      adopted.value = adoptions.filter((item) => !item.purgeAt).length
    }
    if (registers?.ok) {
      const { registers: list = [] } = await registers.json()
      records.value = list.reduce((sum, item) => sum + (item.recordCount ?? 0), 0)
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (auth.isAuthenticated) loadSummary(); else loading.value = false })
</script>
