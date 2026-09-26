<template>
  <ModuleHub
    module-id="hygeia"
    :icon="hygeiaIcon"
    name="Hygeia"
    numeral="V"
    epigraph="Salus"
    :tagline="t('hygeiaHub.tagline')"
    :myth="t('hygeiaHub.myth')"
    :claim="t('landing.tools.hygeia.title')"
    tool-route="/hygeia/activos"
    :tool-label="t('hygeiaHub.toolLabel')"
    :shortcuts="shortcuts"
    :highlight="highlight"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="loading" class="metric-loading">{{ t('hygeiaHub.loading') }}</p>
      <template v-else-if="total">
        <span class="metric-label">{{ t('hygeiaHub.monitored') }}</span>
        <span class="metric-value">{{ total }}</span>
        <span class="metric-sub">{{ t('hygeiaHub.online', { count: online }) }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('hygeiaHub.empty') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import hygeiaIcon from '@/assets/images/hygeia/Hygeia-DarkGreen-BgN.png'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch } = useApi()
const auth = useAuthStore()

// Dato de producto para la visita pública (sin sesión no hay activos propios).
const highlight = computed(() => ({ label: t('hygeiaHub.highlight.label'), value: '< 1 min', sub: t('hygeiaHub.highlight.sub') }))

const shortcuts = computed(() => [
  { label: t('hygeia.list.tags'), to: '/hygeia/etiquetas' },
  { label: t('hygeia.tabs.estadisticas'), to: '/hygeia/estadisticas' },
  { label: t('hygeia.list.documents'), to: '/hygeia/documentos' },
])

const loading = ref(true)
const total = ref(0)
const online = ref(0)

/** Capacidades que se presentan; sus textos están en `hygeiaHub.features.<id>`. */
const features = computed(() => ['push', 'alerts', 'down', 'email'].map((id) => ({
  kicker: t(`hygeiaHub.features.${id}.kicker`),
  title: t(`hygeiaHub.features.${id}.title`),
  desc: t(`hygeiaHub.features.${id}.desc`),
})))

const resources = []

/** Estado actual de los activos propios — para la placa de actividad. */
async function loadAssetSummary() {
  loading.value = true
  try {
    const res = await apiFetch('/hygeia/assets')
    if (!res?.ok) return
    const { assets = [] } = await res.json()
    total.value = assets.length
    online.value = assets.filter((a) => a.status === 'online').length
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (auth.isAuthenticated) loadAssetSummary(); else loading.value = false })
</script>
