<template>
  <div class="plan-page">
    <StarBackground />
    <Topbar :title="t('myPlan.title')" />

    <main class="main">
      <div v-if="account.loading" class="skeleton skeleton--lg"></div>

      <template v-else-if="account.plan">
        <!-- Avisos: caducidad, impago o cancelación pendiente -->
        <div v-if="account.notice" class="notice" :class="`notice--${account.notice.kind}`">
          {{ account.notice.text }}
        </div>

        <section class="head">
          <div>
            <span class="head-eyebrow">{{ t('plansPage.yourPlan') }}</span>
            <h1 class="head-name">{{ account.plan.plan.name }}</h1>
            <p v-if="account.plan.plan.tagline" class="head-tagline">
              {{ account.plan.plan.tagline }}
            </p>
          </div>
          <router-link to="/planes" class="btn btn--secondary">{{ t('myPlan.compare') }}</router-link>
        </section>

        <section v-if="source" class="source">{{ source }}</section>

        <!-- Sin pasarela de pago no hay autoservicio real: el plan lo asigna
             root a mano. Decirlo aquí es más honesto que un botón "Cambiar
             de plan" que no haría nada al pulsarlo. -->
        <p class="upgrade-hint">{{ t('myPlan.upgradeHint') }}</p>

        <section class="section">
          <h2>{{ t('myPlan.usage') }}</h2>
          <p class="section-desc">{{ t('myPlan.usageDesc') }}</p>

          <ul class="limits">
            <li v-for="(entry, key) in sortedUsage" :key="key" class="row"
                :class="{ 'row--exceeded': entry.exceeded }">
              <div class="row-head">
                <span class="row-label">{{ label(key) }}</span>
                <span class="row-value">{{ describe(entry) }}</span>
              </div>
              <div class="bar" :aria-hidden="entry.value === null || entry.value === 0">
                <div class="bar-fill" :style="{ width: percent(entry) }"></div>
              </div>
              <p v-if="entry.exceeded" class="row-note">{{ t('myPlan.exceeded', { limit: entry.value }) }}</p>
              <p v-else-if="entry.resetsAt" class="row-note row-note--muted">
                {{ t('myPlan.renews', { date: account.formatDate(entry.resetsAt) }) }}
              </p>
            </li>
          </ul>
        </section>
      </template>

      <p v-else class="empty">{{ t('myPlan.loadFailed') }}</p>
    </main>
  </div>
</template>

<script setup>
/**
 * Consumo y límites de la cuenta.
 *
 * `plan` y `status` pueden no casar, y es intencionado: un Gold caducado
 * enseña los topes de Freemium con un aviso que dice cuándo terminó. Degradar
 * en silencio sería peor que degradar.
 */
import { computed, onMounted } from 'vue'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useAccountStore } from '@/stores/accountStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const account = useAccountStore()

/**
 * Rama de `myPlan.limits` de cada clave de límite. Las claves llevan puntos, y
 * vue-i18n los lee como niveles del árbol, así que se nombran aparte.
 */
const LABEL_IDS = {
  'themis.lybra.scans': 'lybraScans',
  'themis.thirdparty.scans': 'thirdPartyScans',
  'themis.scheduled': 'scheduledScans',
  'themis.reports.ai': 'aiReports',
  'aegis.pills': 'pills',
  'aegis.campaigns': 'campaigns',
  'aegis.recipients': 'recipients',
  'iris.analyses': 'mailAnalyses',
  'iris.ai_summaries': 'aiSummaries',
  'iris.mailbox.connections': 'mailboxes',
  'acheron.vaults': 'vaults',
  'acheron.items': 'secrets',
  'hygeia.assets': 'assets',
  'ai.requests': 'aiRequests',
  'organization.members': 'members',
}

/** Lo excedido primero: es lo único que exige una acción. */
const sortedUsage = computed(() => {
  const entries = Object.entries(account.usage)
  entries.sort(([, a], [, b]) => Number(b.exceeded) - Number(a.exceeded))
  return Object.fromEntries(entries)
})

const source = computed(() => {
  if (!account.plan) return ''
  if (account.plan.source === 'default') {
    return t('myPlan.freePlan')
  }
  return ''
})

function label(key) {
  return LABEL_IDS[key] ? t(`myPlan.limits.${LABEL_IDS[key]}`) : key
}

function describe(entry) {
  if (entry.value === 0) return t('planFormat.notIncluded')
  if (entry.used === null) return entry.value === null ? t('planFormat.unlimited') : t('myPlan.upTo', { limit: entry.value })
  if (entry.value === null) return t('myPlan.usedUnlimited', { used: entry.used })
  return `${entry.used} / ${entry.value}`
}

function percent(entry) {
  if (entry.value === null || entry.value === 0 || entry.used === null) return '0%'
  return `${Math.min(100, Math.round((entry.used / entry.value) * 100))}%`
}

onMounted(() => account.loadAll())
</script>

<style scoped>
/* `padding-top` porque la Topbar es `position: fixed`, y `z-index` en .main
   porque StarBackground es `position: fixed; inset: 0; z-index: 0` y OPACO:
   sin contexto de apilamiento propio, el contenido de bloque se pinta por
   debajo de él y la pantalla sale en blanco. Mismo patrón que el resto de
   vistas con Topbar + StarBackground. */
.plan-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.main { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; position: relative; z-index: 1; }
.empty { color: var(--text-muted); text-align: center; padding: 3rem 0; }

.notice {
  padding: 0.9rem 1.1rem; border-radius: 8px; margin-bottom: 1.5rem;
  font-size: var(--fs-md);
  border: 1px solid var(--border-med);
  background: var(--accent-dim);
  color: var(--text);
}
.notice--warn { border-color: var(--warning, #d4a04a); }

.head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1.5rem;
}
.head-eyebrow {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 500;
  letter-spacing: 0.3em; text-transform: uppercase; color: var(--accent);
}
.head-name {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: clamp(1.8rem, 4vw, 2.4rem);
  font-weight: 600; color: var(--text); margin-top: 0.3rem;
}
.head-tagline { color: var(--text-muted); margin-top: 0.2rem; }

.source { color: var(--text-muted); font-size: var(--fs-md); margin-bottom: 1.5rem; }
.upgrade-hint { color: var(--text-muted); font-size: var(--fs-body); margin: -0.8rem 0 1.5rem; }

.section {
  background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 12px; padding: 1.5rem;
}
.section h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.section-desc { font-size: var(--fs-body); color: var(--text-muted); margin-top: 0.3rem; }

.limits { list-style: none; margin-top: 1.4rem; display: flex; flex-direction: column; gap: 1.2rem; }
.row-head { display: flex; justify-content: space-between; gap: 1rem; margin-bottom: 0.4rem; }
.row-label { color: var(--text-dim); font-size: var(--fs-md); }
.row-value { color: var(--text); font-weight: 600; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); }

.bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.bar-fill { height: 100%; background: var(--accent); transition: width 0.4s ease; }
.row--exceeded .bar-fill { background: var(--danger); }

.row-note { font-size: var(--fs-body); color: var(--danger); margin-top: 0.4rem; }
.row-note--muted { color: var(--text-muted); }

.btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.6rem 1.2rem; border-radius: 3px;
  border: 1px solid var(--border-med); color: var(--text-dim);
  transition: all var(--transition);
}
.btn:hover { border-color: var(--accent); color: var(--accent-bright); }
</style>
