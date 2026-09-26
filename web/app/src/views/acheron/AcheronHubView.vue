<template>
  <ModuleHub
    module-id="acheron"
    :icon="acheronIcon"
    name="Acheron"
    numeral="IV"
    epigraph="Custodia"
    :tagline="t('acheronHub.tagline')"
    :myth="t('acheronHub.myth')"
    :claim="t('acheronHub.claim')"
    tool-route="/acheron/boveda"
    :tool-label="t('acheronHub.toolLabel')"
    :highlight="highlight"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="loading" class="metric-loading">{{ t('acheronHub.loading') }}</p>
      <template v-else-if="itemCount">
        <span class="metric-label">{{ t('acheronHub.secrets') }}</span>
        <span class="metric-value">{{ itemCount }}</span>
        <span v-if="lastUpdated" class="metric-sub">{{ t('acheronHub.lastUpdated', { date: lastUpdatedLabel }) }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('acheronHub.empty') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import acheronIcon from '@/assets/images/acheron/Acheron-Purple-BgN.png'
import { formatDate } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch } = useApi()
const auth = useAuthStore()

// Dato de producto para la visita pública (sin sesión no hay bóveda propia).
const highlight = computed(() => ({ label: t('acheronHub.highlight.label'), value: t('acheronHub.highlight.value'), sub: t('acheronHub.highlight.sub') }))

const loading = ref(true)
const itemCount = ref(0)
const lastUpdated = ref(null)

const lastUpdatedLabel = computed(() =>
  lastUpdated.value ? formatDate(lastUpdated.value) : ''
)

/** Capacidades que se presentan; sus textos están en `acheronHub.features.<id>`. */
const features = computed(() => ['local', 'types', 'generator', 'lybra'].map((id) => ({
  kicker: t(`acheronHub.features.${id}.kicker`),
  title: t(`acheronHub.features.${id}.title`),
  desc: t(`acheronHub.features.${id}.desc`),
})))

const resources = computed(() => [
  { label: t('acheronHub.resources.nist'), href: 'https://pages.nist.gov/800-63-3/sp800-63b.html', external: true },
])

/**
 * El recuento de secretos y la fecha de última modificación son metadatos en
 * claro (título y timestamps no van cifrados, solo el contenido sensible de
 * cada tipo) — por eso se pueden mostrar sin pedir la contraseña maestra,
 * igual que ya hace AcheronView para decidir si la bóveda existe.
 */
async function loadVaultMetric() {
  loading.value = true
  try {
    const res = await apiFetch('/acheron/vault')
    if (!res?.ok) return
    const data = await res.json()

    const lists = Object.values(data).filter((v) => Array.isArray(v))
    itemCount.value = lists.reduce((sum, list) => sum + list.length, 0)

    const timestamps = lists.flat().map((item) => item.updatedAt).filter(Boolean)
    if (timestamps.length) lastUpdated.value = timestamps.sort().at(-1)
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (auth.isAuthenticated) loadVaultMetric(); else loading.value = false })
</script>
