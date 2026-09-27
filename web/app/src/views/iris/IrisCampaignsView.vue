<template>
  <div class="campaigns-page" data-module="iris">
    <StarBackground />
    <Topbar :title="'Iris'" :badge="t('iris.campaigns.badge')" back-to="/iris/analisis" :back-label="t('iris.batch.analysis')" />

    <div class="campaigns-layout">
      <!-- Campañas: los mensajes parecidos del usuario, agrupados. -->
      <section class="panel list-panel">
        <p class="intro">{{ t('iris.campaigns.intro') }}</p>
        <p v-if="store.campaigns.loading && !store.campaigns.items.length" class="empty">{{ t('common.loading') }}</p>
        <p v-else-if="!store.campaigns.items.length" class="empty">{{ t('iris.campaigns.empty') }}</p>
        <ul v-else class="campaign-list">
          <li
            v-for="entry in store.campaigns.items"
            :key="entry.campaignId"
            class="campaign-row"
            :class="{ 'campaign-row--active': detail?.campaignId === entry.campaignId }"
            tabindex="0"
            @click="store.fetchCampaign(entry.campaignId)"
            @keydown.enter="store.fetchCampaign(entry.campaignId)"
          >
            <span class="campaign-title">{{ campaignName(entry) }}</span>
            <span class="campaign-meta">
              {{ t('iris.campaigns.messageCount', { count: entry.messageCount }) }} ·
              {{ t('iris.campaigns.seenBetween', { first: formatDate(entry.firstSeenAt), last: formatDate(entry.lastSeenAt) }) }}
            </span>
            <span class="campaign-meta">
              <span v-for="(count, verdict) in entry.verdicts" :key="verdict" class="chip" :class="`chip--${verdictClass(verdict)}`">
                {{ t(verdictKey(verdict)) }} · {{ count }}
              </span>
            </span>
          </li>
        </ul>
        <nav v-if="pageCount > 1" class="pager" :aria-label="t('iris.campaigns.badge')">
          <button type="button" class="ghost-btn" :disabled="store.campaigns.page <= 1" @click="store.fetchCampaigns(store.campaigns.page - 1)">{{ t('pagination.previous') }}</button>
          <span class="campaign-meta">{{ t('pagination.position', { current: store.campaigns.page, total: pageCount }) }}</span>
          <button type="button" class="ghost-btn" :disabled="store.campaigns.page >= pageCount" @click="store.fetchCampaigns(store.campaigns.page + 1)">{{ t('pagination.next') }}</button>
        </nav>
      </section>

      <!-- Detalle: lo que comparten sus mensajes y cada mensaje. -->
      <section class="panel detail-panel">
        <p v-if="!detail" class="empty">{{ t('iris.campaigns.pick') }}</p>
        <template v-else>
          <h2 class="detail-title">{{ campaignName(detail) }}</h2>
          <p class="campaign-meta">
            {{ t('iris.campaigns.messageCount', { count: detail.messageCount }) }} ·
            {{ t('iris.campaigns.seenBetween', { first: formatDateTime(detail.firstSeenAt), last: formatDateTime(detail.lastSeenAt) }) }}
          </p>
          <p v-if="detail.brands.length" class="campaign-meta">
            {{ t('iris.campaigns.brands', { brands: detail.brands.join(', ') }) }}
          </p>

          <h3 class="section-title">{{ t('iris.campaigns.shared') }}</h3>
          <p class="hint">{{ t('iris.campaigns.sharedHint') }}</p>
          <p v-if="!detail.sharedIndicators.length" class="empty">{{ t('iris.campaigns.noShared') }}</p>
          <ul v-else class="indicator-list">
            <li v-for="indicator in detail.sharedIndicators" :key="`${indicator.kind}:${indicator.value}`" class="indicator-row">
              <span class="chip">{{ t(indicatorKindKey(indicator.kind)) }}</span>
              <code class="indicator-value">{{ defang(indicator.value) }}</code>
              <span class="campaign-meta">{{ t('iris.campaigns.inMessages', { count: indicator.analysisCount }) }}</span>
            </li>
          </ul>

          <h3 class="section-title">{{ t('iris.campaigns.messages', { count: detail.analyses.length }) }}</h3>
          <ul class="analysis-list">
            <li v-for="analysis in detail.analyses" :key="analysis.analysisId" class="analysis-row">
              <button type="button" class="link-btn" @click="openAnalysis(analysis.analysisId)">
                #{{ analysis.analysisId }} · {{ analysis.title || t('iris.untitled') }}
              </button>
              <span class="campaign-meta">
                <span class="chip" :class="`chip--${verdictClass(analysis.verdict)}`">{{ t(verdictKey(analysis.verdict)) }}</span>
                {{ formatDateTime(analysis.receivedAt) }}
              </span>
              <span v-if="analysis.matchedSignals.length" class="campaign-meta">
                {{ t('iris.campaigns.matchedBy') }}
                <span v-for="signal in analysis.matchedSignals" :key="signal" class="chip chip--signal">{{ t(campaignSignalKey(signal)) }}</span>
              </span>
            </li>
          </ul>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useIrisStore } from '@/stores/irisStore'
import { formatDate, formatDateTime } from '@/i18n/format'
import { verdictClass, verdictKey } from '@/components/iris/verdict'
import { campaignSignalKey, defang, indicatorKindKey } from '@/components/iris/indicators'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useIrisStore()
const route = useRoute()
const router = useRouter()

const detail = computed(() => store.currentCampaign)
const pageCount = computed(() => Math.max(1, Math.ceil(store.campaigns.total / store.campaigns.perPage)))

/** Nombre de una campaña: su asunto o, si no tenía, su número. */
function campaignName(campaign) {
  return campaign.label || t('iris.campaigns.unnamed', { id: campaign.campaignId })
}

function openAnalysis(analysisId) {
  store.selectAnalysis(analysisId)
  router.push('/iris/analisis')
}

onMounted(() => {
  store.fetchCampaigns(1)
  // El informe de un análisis enlaza aquí con `?id=` para abrir su campaña.
  const campaignId = Number(route.query.id)
  if (campaignId) store.fetchCampaign(campaignId)
})
</script>

<style scoped>
.campaigns-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.campaigns-layout {
  position: relative; z-index: 1;
  max-width: 1200px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem;
  display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 1.25rem; align-items: start;
}
.panel { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 1.1rem 1.25rem; min-width: 0; }
.intro, .hint { margin: 0 0 0.8rem; font-size: var(--fs-sm); color: var(--text-dim); }
.empty { color: var(--text-muted); font-size: var(--fs-md); }
.campaign-list, .analysis-list, .indicator-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.campaign-row { padding: 0.55rem 0.7rem; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; display: flex; flex-direction: column; gap: 0.25rem; }
.campaign-row:hover, .campaign-row:focus-visible { border-color: var(--border-med); background: var(--surface-2); outline: none; }
.campaign-row--active { border-color: var(--accent); background: var(--accent-dim); }
.campaign-title { font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.campaign-meta { font-size: var(--fs-sm); color: var(--text-muted); display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin: 0; }
.chip { padding: 0 0.45rem; font-size: var(--fs-xs); font-weight: 600; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.chip--phish { background: var(--danger-dim); color: var(--danger); }
.chip--susp { background: var(--warn-dim); color: var(--warn); }
.chip--legit { background: var(--success-dim); color: var(--success); }
.chip--signal { background: var(--accent-dim); color: var(--accent-bright); }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.8rem; }
.ghost-btn { padding: 0.35rem 0.8rem; font-size: var(--fs-sm); font-weight: 600; border-radius: 6px; cursor: pointer; border: 1px solid var(--border-med); background: transparent; color: var(--text-dim); }
.ghost-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.detail-title { margin: 0 0 0.3rem; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); color: var(--text); overflow-wrap: anywhere; }
.section-title { margin: 1.1rem 0 0.4rem; font-size: var(--fs-md); color: var(--text); }
.indicator-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.indicator-value { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); word-break: break-all; }
.analysis-row { display: flex; flex-direction: column; gap: 0.2rem; padding-bottom: 0.4rem; border-bottom: 1px solid var(--border); }
.link-btn { border: none; background: none; padding: 0; color: var(--accent-bright); cursor: pointer; font-size: var(--fs-md); text-align: left; }
@media (max-width: 900px) { .campaigns-layout { grid-template-columns: 1fr; } }
</style>
