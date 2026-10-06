<template>
  <div class="org-page" data-module="iris">
    <StarBackground />
    <Topbar :title="'Iris'" :badge="t('iris.organization.badge')" back-to="/iris/analisis" :back-label="t('iris.batch.analysis')" />

    <div class="org-layout">
      <section class="panel">
        <p class="panel-eyebrow">{{ t('iris.organization.eyebrow') }}</p>
        <h2 class="panel-title">{{ intel ? intel.organization.name : t('iris.organization.title') }}</h2>
        <p class="panel-sub">{{ t('iris.organization.intro', { count: intel?.minMembers ?? 3 }) }}</p>

        <p v-if="store.organizationIntel.loading && !store.organizationIntel.loaded" class="empty">{{ t('common.loading') }}</p>
        <p v-else-if="store.organizationIntel.notInOrganization" class="empty">{{ t('iris.organization.noOrganization') }}</p>
        <template v-else-if="intel">
          <p class="status-line">
            {{ intel.sharingEnabled ? t('iris.organization.sharingOn') : t('iris.organization.sharingOff') }}
            · {{ t('iris.organization.contributing', { count: intel.contributingMembers }) }}
          </p>
          <label class="toggle">
            <input type="checkbox" :checked="intel.hasConsented" @change="store.setOrganizationConsent($event.target.checked)" />
            <span>{{ t('iris.organization.consent') }}</span>
          </label>
          <p class="hint">{{ t('iris.organization.consentHint') }}</p>
        </template>
      </section>

      <!-- Solo el dueño fija la política de la organización. -->
      <section v-if="intel?.isOwner" class="panel">
        <h3 class="list-title">{{ t('iris.organization.policyTitle') }}</h3>
        <form class="policy-form" @submit.prevent="savePolicy">
          <label class="toggle">
            <input v-model="policy.sharingEnabled" type="checkbox" />
            <span>{{ t('iris.organization.enableSharing') }}</span>
          </label>
          <label class="field">
            <span class="field-label">{{ t('iris.organization.protectedDomains') }}</span>
            <textarea v-model="policy.domains" class="text-input" rows="3" :placeholder="t('iris.organization.protectedDomainsHint')"></textarea>
          </label>
          <label class="field">
            <span class="field-label">{{ t('iris.organization.protectedBrands') }}</span>
            <textarea v-model="policy.brands" class="text-input" rows="2" :placeholder="t('iris.organization.protectedBrandsHint')"></textarea>
          </label>
          <button type="submit" class="primary-btn">{{ t('common.save') }}</button>
        </form>
      </section>

      <section v-if="intel?.sharingEnabled && intel?.hasConsented" class="panel">
        <h3 class="list-title">{{ t('iris.organization.sharedTitle') }}</h3>
        <p class="hint">{{ t('iris.organization.sharedHint', { days: intel.windowDays }) }}</p>
        <p v-if="!intel.sharedIndicators.length" class="empty">{{ t('iris.organization.noShared') }}</p>
        <ul v-else class="item-list">
          <li v-for="indicator in intel.sharedIndicators" :key="`${indicator.kind}:${indicator.value}`" class="item">
            <span class="chip">{{ t(indicatorKindKey(indicator.kind)) }}</span>
            <code class="item-value">{{ defang(indicator.value) }}</code>
            <span class="item-meta">{{ t('iris.organization.seenBy', { count: indicator.memberCount }) }} · {{ formatDate(indicator.lastSeenAt) }}</span>
            <span v-if="indicator.imitatesProtected" class="chip chip--danger">{{ t('iris.organization.imitates', { domain: indicator.imitatesProtected }) }}</span>
          </li>
        </ul>

        <h3 class="list-title list-title--spaced">{{ t('iris.organization.frequentTitle') }}</h3>
        <p v-if="!intel.frequentDomains.length" class="empty">{{ t('iris.organization.noFrequent') }}</p>
        <ul v-else class="item-list">
          <li v-for="entry in intel.frequentDomains" :key="entry.domain" class="item">
            <code class="item-value">{{ entry.domain }}</code>
            <span class="item-meta">{{ t('iris.organization.seenBy', { count: entry.memberCount }) }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, watch } from 'vue'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useIrisStore } from '@/stores/irisStore'
import { formatDate } from '@/i18n/format'
import { defang, indicatorKindKey } from '@/components/iris/indicators'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useIrisStore()
const intel = computed(() => store.organizationIntel.data)

/** Borrador de la política que edita el dueño (una entrada por línea o separadas por comas). */
const policy = reactive({ sharingEnabled: false, domains: '', brands: '' })

watch(intel, (value) => {
  if (!value) return
  policy.sharingEnabled = value.sharingEnabled
  policy.domains = value.protectedDomains.join('\n')
  policy.brands = value.protectedBrands.join('\n')
}, { immediate: true })

/** Parte un texto en entradas no vacías, por líneas o comas. */
function splitEntries(text) {
  return text.split(/[\n,]/).map((entry) => entry.trim()).filter(Boolean)
}

function savePolicy() {
  store.updateOrganizationPolicy({
    sharingEnabled: policy.sharingEnabled,
    protectedDomains: splitEntries(policy.domains),
    protectedBrands: splitEntries(policy.brands),
  })
}

onMounted(() => store.fetchOrganizationIntel())
</script>

<style scoped>
.org-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.org-layout {
  position: relative; z-index: 1;
  max-width: 820px; margin: 0 auto; padding: 2rem 1.25rem 3rem;
  display: flex; flex-direction: column; gap: 1.5rem;
}
.panel { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 1.4rem 1.6rem; }
.panel-eyebrow {
  margin: 0 0 0.3rem; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs); letter-spacing: 0.28em; text-transform: uppercase; color: var(--accent);
}
.panel-title { margin: 0 0 0.5rem; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); font-weight: 700; color: var(--text); }
.panel-sub, .hint { margin: 0 0 0.9rem; font-size: var(--fs-md); line-height: 1.55; color: var(--text-dim); max-width: 64ch; }
.hint { font-size: var(--fs-sm); color: var(--text-muted); }
.status-line { margin: 0 0 0.7rem; font-size: var(--fs-md); color: var(--text); }
.empty { margin: 0; color: var(--text-muted); font-size: var(--fs-md); }
.toggle { display: flex; align-items: center; gap: 0.5rem; font-size: var(--fs-md); color: var(--text); margin-bottom: 0.4rem; }
.list-title { margin: 0 0 0.6rem; font-size: var(--fs-lg); color: var(--text); }
.list-title--spaced { margin-top: 1.4rem; }
.policy-form { display: flex; flex-direction: column; gap: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field-label { font-size: var(--fs-xs); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.text-input {
  padding: 0.45rem 0.6rem; font-size: var(--fs-sm); font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border-med); border-radius: 6px;
}
.primary-btn { align-self: flex-start; padding: 0.4rem 0.9rem; font-size: var(--fs-sm); font-weight: 600; border-radius: 6px; cursor: pointer; border: none; background: var(--accent); color: var(--on-accent); }
.item-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.item { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.item-value { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); word-break: break-all; }
.item-meta { font-size: var(--fs-sm); color: var(--text-muted); }
.chip { padding: 0 0.45rem; font-size: var(--fs-xs); font-weight: 600; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.chip--danger { background: var(--danger-dim); color: var(--danger); }
</style>
