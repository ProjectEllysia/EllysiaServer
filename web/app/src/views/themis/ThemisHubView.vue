<template>
  <ModuleHub
    module-id="themis"
    :icon="themisIcon"
    name="Themis"
    numeral="I"
    epigraph="Iudicium"
    :tagline="t('themisHub.tagline')"
    :myth="t('landing.tools.themis.myth')"
    :claim="t('landing.tools.themis.title')"
    tool-route="/themis/escaneos"
    :tool-label="t('themisHub.toolLabel')"
    :highlight="highlight"
    :shortcuts="shortcuts"
    :features="features"
    :resources="resources"
  >
    <template #metric>
      <p v-if="store.loadingStats" class="metric-loading">{{ t('themisHub.loadingStats') }}</p>
      <template v-else-if="store.stats.total">
        <span class="metric-label">{{ t('themisHub.scansIssued') }}</span>
        <span class="metric-value">{{ store.stats.total }}</span>
        <span class="metric-sub">Lybra {{ store.stats.lybra }} · Nmap {{ store.stats.nmap }} · Nikto {{ store.stats.nikto }} · Nuclei {{ store.stats.nuclei }}</span>
      </template>
      <p v-else class="metric-empty">{{ t('themisHub.noScans') }}</p>
    </template>
  </ModuleHub>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import ModuleHub from '@/components/shared/ModuleHub.vue'
import { useThemisStore } from '@/stores/themisStore'
import { useAuthStore } from '@/stores/authStore'
import themisIcon from '@/assets/images/themis/Themis-Turqoise-BgN.png'

const { t } = useI18n()
const store = useThemisStore()
const auth = useAuthStore()

/** Capacidades que se presentan, en orden; sus textos están en `themisHub.features.<id>`. */
const FEATURE_IDS = ['engine', 'classics', 'reports', 'schedule']

// Dato de producto para la visita pública (sin sesión no hay actividad propia).
const highlight = computed(() => ({ label: t('themisHub.highlight.label'), value: 'Lybra', sub: t('themisHub.highlight.sub') }))

const shortcuts = computed(() => [
  { label: t('themisHub.shortcuts.newLybra'), to: '/themis/escaneos?world=lybra' },
  { label: t('themisHub.shortcuts.external'), to: '/themis/escaneos?world=external' },
  { label: t('themisHub.shortcuts.history'), to: '/themis/escaneos?world=lybra&view=history' },
])

const features = computed(() => FEATURE_IDS.map((id) => ({
  kicker: t(`themisHub.features.${id}.kicker`),
  title: t(`themisHub.features.${id}.title`),
  desc: t(`themisHub.features.${id}.desc`),
})))

const resources = [
  { label: 'NVD — National Vulnerability Database', href: 'https://nvd.nist.gov/', external: true },
  { label: 'OWASP', href: 'https://owasp.org/', external: true },
]

onMounted(() => { if (auth.isAuthenticated) store.loadStats() })
</script>
