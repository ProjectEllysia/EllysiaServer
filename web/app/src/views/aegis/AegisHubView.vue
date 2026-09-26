<template>
  <ModuleHub
    module-id="aegis"
    :icon="aegisIcon"
    name="Aegis"
    numeral="II"
    epigraph="Praesidio"
    :tagline="t('aegisHub.tagline')"
    :myth="t('landing.tools.aegis.myth')"
    :claim="t('landing.tools.aegis.title')"
    tool-route="/aegis/generador"
    :tool-label="t('aegisHub.toolLabel')"
    :highlight="highlight"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="loading" class="metric-loading">{{ t('aegisHub.loading') }}</p>
      <template v-else-if="lastCampaign">
        <span class="metric-label">{{ t('aegisHub.lastCampaign', { name: lastCampaign.name }) }}</span>
        <span class="metric-value">{{ t('aegisHub.completed', { rate: completionRate }) }}</span>
        <span class="metric-sub">{{ t('aegisHub.recipients', { done: completedCount, total: totalRecipients }) }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('aegisHub.empty') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import aegisIcon from '@/assets/images/aegis/Ellysia-Aegis-Blue-BgN.png'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch } = useApi()
const auth = useAuthStore()

// Dato de producto para la visita pública (sin sesión no hay campañas propias).
const highlight = computed(() => ({ label: t('aegisHub.highlight.label'), value: t('aegisHub.highlight.value'), sub: t('aegisHub.highlight.sub') }))

const loading = ref(true)
const lastCampaign = ref(null)
const totalRecipients = ref(0)
const completedCount = ref(0)

const completionRate = computed(() =>
  totalRecipients.value ? Math.round((completedCount.value / totalRecipients.value) * 100) : 0
)

/** Capacidades que se presentan; sus textos están en `aegisHub.features.<id>`. */
const features = computed(() => ['pills', 'quiz', 'campaigns', 'evidence'].map((id) => ({
  kicker: t(`aegisHub.features.${id}.kicker`),
  title: t(`aegisHub.features.${id}.title`),
  desc: t(`aegisHub.features.${id}.desc`),
})))

const resources = computed(() => [
  { label: t('aegisHub.resources.incibe'), href: 'https://www.incibe.es/', external: true },
])

/** Última campaña lanzada (no en borrador) — para la placa de actividad. */
async function loadLastCampaignMetric() {
  loading.value = true
  try {
    const listRes = await apiFetch('/aegis/campaigns')
    if (!listRes?.ok) return
    const { campaigns = [] } = await listRes.json()

    const launched = campaigns
      .filter((c) => c.status !== 'draft' && c.launchedAt)
      .sort((a, b) => new Date(b.launchedAt) - new Date(a.launchedAt))

    if (!launched.length) return

    const detailRes = await apiFetch(`/aegis/campaigns/${launched[0].id}`)
    if (!detailRes?.ok) return
    const detail = await detailRes.json()

    lastCampaign.value = detail
    totalRecipients.value = detail.recipients?.length ?? 0
    completedCount.value = detail.recipients?.filter((r) => r.status === 'completed').length ?? 0
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (auth.isAuthenticated) loadLastCampaignMetric(); else loading.value = false })
</script>
