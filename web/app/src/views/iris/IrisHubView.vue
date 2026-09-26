<template>
  <ModuleHub
    module-id="iris"
    :icon="irisIcon"
    name="Iris"
    numeral="III"
    epigraph="Veritas"
    :tagline="t('irisHub.tagline')"
    :myth="t('landing.tools.iris.myth')"
    :claim="t('landing.tools.iris.title')"
    tool-route="/iris/analisis"
    :tool-label="t('irisHub.toolLabel')"
    :highlight="highlight"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="loading" class="metric-loading">{{ t('irisHub.loading') }}</p>
      <template v-else-if="recentTotal">
        <span class="metric-label">{{ t('irisHub.examined') }}</span>
        <span class="metric-value">{{ recentTotal }}</span>
        <span class="metric-sub">{{ t('irisHub.flagged', { count: phishingCount, rate: phishingRate }) }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('irisHub.empty') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import irisIcon from '@/assets/images/iris/Iris-Red-BgN.png'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch } = useApi()
const auth = useAuthStore()

// Dato de producto para la visita pública (sin sesión no hay análisis propios).
const highlight = computed(() => ({ label: t('irisHub.highlight.label'), value: t('irisHub.highlight.value'), sub: t('irisHub.highlight.sub') }))

const loading = ref(true)
const recentTotal = ref(0)
const phishingCount = ref(0)

const phishingRate = computed(() =>
  recentTotal.value ? Math.round((phishingCount.value / recentTotal.value) * 100) : 0
)

/** Capacidades que se presentan; sus textos están en `irisHub.features.<id>`. */
const features = computed(() => ['rules', 'quishing', 'iocs', 'verdict'].map((id) => ({
  kicker: t(`irisHub.features.${id}.kicker`),
  title: t(`irisHub.features.${id}.title`),
  desc: t(`irisHub.features.${id}.desc`),
})))

const resources = computed(() => [
  { label: t('irisHub.resources.osi'), href: 'https://www.osi.es/', external: true },
])

/** Actividad reciente (hasta 100 análisis más nuevos) — para la placa de actividad. */
async function loadRecentActivity() {
  loading.value = true
  try {
    const res = await apiFetch('/iris/results?page=1&per_page=100')
    if (!res?.ok) return
    const { analyses = [] } = await res.json()
    recentTotal.value = analyses.length
    phishingCount.value = analyses.filter((a) => a.verdict === 'Phishing').length
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (auth.isAuthenticated) loadRecentActivity(); else loading.value = false })
</script>
