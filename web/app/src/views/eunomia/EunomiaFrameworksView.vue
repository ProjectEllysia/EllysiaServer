<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.frameworks.title')" back-to="/profile" :back-label="t('eunomia.frameworks.back')" />

    <main class="layout">
      <header class="head">
        <h1 class="head-title">{{ t('eunomia.frameworks.title') }}</h1>
        <p class="head-sub">{{ t('eunomia.frameworks.intro') }}</p>
        <router-link to="/eunomia/plantillas" class="templates-link">{{ t('eunomia.templates.title') }}</router-link>
        <router-link to="/eunomia/registros" class="templates-link">{{ t('eunomia.registers.title') }}</router-link>
      </header>

      <OrganizationManagedNotice :ownership="store.state.ownership" />

      <p v-if="store.state.loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="store.state.error" class="state-msg state-msg--error">
        {{ store.state.error }}
        <button type="button" class="link-btn" @click="store.load()">{{ t('common.retry') }}</button>
      </p>

      <template v-else>
        <section class="block" aria-labelledby="adopted-title">
          <SectionInscription id="adopted-title" :tally="groups.active.length">{{ t('eunomia.frameworks.adopted') }}</SectionInscription>
          <p v-if="!groups.active.length" class="empty">{{ t('eunomia.frameworks.noneAdopted') }}</p>
          <TransitionGroup v-else tag="ul" name="card" class="cards">
            <li v-for="adoption in groups.active" :key="adoption.frameworkKey" class="card">
              <div class="card-main">
                <span class="card-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/></svg>
              </span>
              <div class="card-text">
                <h3>{{ adoption.name }}</h3>
                <p class="meta">
                  {{ t('eunomia.frameworks.version', { version: adoption.catalogVersion }) }}
                  · {{ t('eunomia.frameworks.adoptedOn', { date: formatDate(adoption.adoptedAt) }) }}
                </p>
                </div>
                <div v-if="adoption.progress" class="card-progress">
                  <ProgressBar :percent="adoption.progress.percent" :label="adoption.name" />
                  <span class="pct">{{ adoption.progress.countable ? percent(adoption.progress.percent) : '—' }}</span>
                </div>
                <p v-if="adoption.hasNewerVersion" class="newer">
                  {{ t('eunomia.frameworks.newerVersion', { version: adoption.currentVersion }) }}
                </p>
              </div>
              <div class="card-actions">
                <router-link :to="`/eunomia/marcos/${adoption.frameworkKey}`" class="btn btn--primary">
                  {{ t('eunomia.tree.open') }}
                </router-link>
                <button
                  v-if="canManage && adoption.hasNewerVersion" type="button" class="btn"
                  :disabled="store.state.busyKey === adoption.frameworkKey"
                  @click="askUpgrade(adoption)"
                >{{ t('eunomia.frameworks.upgrade') }}</button>
                <button
                  v-if="canManage" type="button" class="btn btn--danger"
                  :disabled="store.state.busyKey === adoption.frameworkKey"
                  @click="askRemoval(adoption)"
                >{{ t('eunomia.frameworks.remove') }}</button>
              </div>
            </li>
          </TransitionGroup>
        </section>

        <section class="block" aria-labelledby="available-title">
          <SectionInscription id="available-title" :tally="groups.available.length">{{ t('eunomia.frameworks.available') }}</SectionInscription>
          <p v-if="!groups.available.length" class="empty">{{ t('eunomia.frameworks.noneAvailable') }}</p>
          <TransitionGroup v-else tag="ul" name="card" class="cards">
            <li v-for="framework in groups.available" :key="framework.key" class="card">
              <div class="card-main">
                <span class="card-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/></svg>
              </span>
              <div class="card-text">
                <h3>{{ framework.name }}</h3>
                <p class="meta">{{ t('eunomia.frameworks.version', { version: framework.current }) }}{{ isDraft(framework) ? ` · ${t('eunomia.frameworks.draft')}` : '' }}</p>
                </div>
              </div>
              <div class="card-actions">
              <button
                v-if="canManage" type="button" class="btn btn--primary"
                :disabled="store.state.busyKey === framework.key"
                @click="adopt(framework.key)"
              >{{ t('eunomia.frameworks.adopt') }}</button>
              </div>
            </li>
          </TransitionGroup>
        </section>

        <section v-if="groups.archived.length" class="block" aria-labelledby="archived-title">
          <SectionInscription id="archived-title" :tally="groups.archived.length">{{ t('eunomia.frameworks.archived') }}</SectionInscription>
          <TransitionGroup tag="ul" name="card" class="cards">
            <li v-for="adoption in groups.archived" :key="adoption.frameworkKey" class="card">
              <div class="card-main">
                <span class="card-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/></svg>
              </span>
              <div class="card-text">
                <h3>{{ adoption.name }}</h3>
                <p class="meta">{{ t('eunomia.frameworks.purgeAt', { date: formatDate(adoption.purgeAt) }) }}</p>
                </div>
              </div>
              <div class="card-actions">
              <button
                v-if="canManage" type="button" class="btn btn--primary"
                :disabled="store.state.busyKey === adoption.frameworkKey"
                @click="restore(adoption.frameworkKey)"
              >{{ t('eunomia.frameworks.restore') }}</button>
              </div>
            </li>
          </TransitionGroup>
        </section>
      </template>
    </main>

    <ConfirmModal
      :show="!!upgrading"
      :title="t('eunomia.frameworks.upgradeTitle', { name: upgrading?.name ?? '', version: upgrading?.currentVersion ?? '' })"
      :message="upgradeMessage"
      :confirm-label="t('eunomia.frameworks.upgradeConfirm')"
      @confirm="confirmUpgrade"
      @cancel="upgrading = null"
    />

    <ConfirmModal
      :show="!!pending"
      :title="t('eunomia.frameworks.removeTitle', { name: pending?.name ?? '' })"
      :emphasis="removalEmphasis"
      :message="removalMessage"
      :confirm-label="t('eunomia.frameworks.removeConfirm')"
      danger
      @confirm="confirmRemoval"
      @cancel="pending = null"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import OrganizationManagedNotice from '@/components/accounts/OrganizationManagedNotice.vue'
import { hasLoss, removalFacts, upgradeFacts } from '@/components/eunomia/frameworks'
import SectionInscription from '@/components/eunomia/SectionInscription.vue'
import ProgressBar from '@/components/eunomia/ProgressBar.vue'
import { formatDate, formatNumber } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const store = useEunomiaStore()
const toast = useToastStore()

const groups = computed(() => store.grouped())
const canManage = computed(() => store.state.ownership.isOwnData === true)

/** Un marco del catálogo cuya versión vigente sigue en borrador. */
function isDraft(framework) {
  return framework.versions?.find((item) => item.version === framework.current)?.status === 'draft'
}

/** Un porcentaje (0 a 100) con el formato del idioma activo. */
function percent(value) {
  return formatNumber(value / 100, { style: 'percent', maximumFractionDigits: 0 })
}

const pending = ref(null)
const preview = ref(null)

/**
 * Pide la vista previa y abre la confirmación: el aviso dice qué se pierde, no que «es
 * irreversible».
 *
 * @param {object} adoption - Adopción que se quiere quitar.
 */
async function askRemoval(adoption) {
  const result = await store.previewRemoval(adoption.frameworkKey)
  if (!result) return
  preview.value = result
  pending.value = adoption
}

const removalEmphasis = computed(() =>
  preview.value && hasLoss(preview.value) ? t('eunomia.frameworks.removeWarning') : '')

const removalMessage = computed(() => {
  if (!preview.value) return ' '
  const facts = removalFacts(preview.value)
  const lines = facts.length
    ? facts.map((fact) => t(`eunomia.frameworks.loss.${fact.key}`, { count: fact.count }, fact.count))
    : [t('eunomia.frameworks.lossNone')]
  lines.push(t('eunomia.frameworks.removeWhen', {
    days: preview.value.retentionDays, date: formatDate(preview.value.purgeAt),
  }))
  return lines.join(' ')
})

const upgrading = ref(null)
const upgradePlan = ref(null)

/**
 * Pide qué pasaría al pasar el marco a la versión vigente y abre la confirmación.
 *
 * @param {object} adoption - Adopción que se quiere actualizar.
 */
async function askUpgrade(adoption) {
  const plan = await store.previewUpgrade(adoption.frameworkKey)
  if (!plan) return
  upgradePlan.value = plan
  upgrading.value = adoption
}

const upgradeMessage = computed(() => {
  if (!upgradePlan.value) return ' '
  const facts = upgradeFacts(upgradePlan.value)
  return facts.length
    ? facts.map((fact) => t(`eunomia.frameworks.upgradeFact.${fact.key}`, { count: fact.count }, fact.count)).join(' ')
    : t('eunomia.frameworks.upgradeNothing')
})

/** Confirma: pasa el marco a la versión vigente y avisa. */
async function confirmUpgrade() {
  const target = upgrading.value
  upgrading.value = null
  const result = await store.upgrade(target.frameworkKey)
  if (result.ok) toast.show(t('eunomia.frameworks.upgraded', { name: target.name }), 'success')
  else toast.show(result.message, 'error')
}

/** Confirma: archiva el marco y avisa. */
async function confirmRemoval() {
  const target = pending.value
  pending.value = null
  const result = await store.archive(target.frameworkKey)
  if (result.ok) toast.show(t('eunomia.frameworks.removed', { name: target.name }), 'success')
  else toast.show(result.message, 'error')
}

/**
 * Adopta un marco. Si ya estuvo adoptado y está archivado, la API lo dice y el usuario lo
 * restaura desde la lista de quitados, en vez de empezar de cero.
 *
 * @param {string} key - Clave del marco.
 */
async function adopt(key) {
  const result = await store.adopt(key)
  if (result.ok) toast.show(t('eunomia.frameworks.adoptedToast'), 'success')
  else toast.show(result.message, 'error')
}

/**
 * Restaura un marco archivado.
 *
 * @param {string} key - Clave del marco.
 */
async function restore(key) {
  const result = await store.restore(key)
  if (result.ok) toast.show(t('eunomia.frameworks.restoredToast'), 'success')
  else toast.show(result.message, 'error')
}

onMounted(() => store.load())
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.head-sub { color: var(--text-muted); margin-top: 0.4rem; max-width: 62ch; font-size: var(--fs-md); }
.templates-link { display: inline-block; margin-top: 0.6rem; margin-right: 1rem; color: var(--accent); text-decoration: underline; font-size: var(--fs-md); }
.block > :first-child { margin-bottom: 0.9rem; }
.cards { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.7rem; position: relative; }
/* Tarjeta con el tono de los paneles de Lybra: filete de acento, resplandor interior y
   las acciones siempre al pie, alineadas a la derecha. */
.card {
  display: flex; flex-direction: column; gap: 0.9rem;
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--border-solid); border-radius: 12px; padding: 1.1rem 1.3rem;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
  transition: border-color 0.3s var(--ease-settle), box-shadow 0.3s var(--ease-settle), transform 0.3s var(--ease-settle);
}
.card:hover { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-dim), 0 14px 34px rgba(0, 0, 0, 0.2); transform: translateY(-1px); }
.card-main { display: flex; gap: 0.9rem; align-items: flex-start; flex: 1; }
.card-text { flex: 1; min-width: 0; }
.card-mark {
  width: 40px; height: 40px; border-radius: 50%; flex: none; display: grid; place-items: center;
  color: var(--accent); background: var(--accent-dim); border: 1px solid var(--accent);
}
.card-mark svg { width: 21px; height: 21px; }
.card-actions { display: flex; gap: 0.6rem; flex-wrap: wrap; justify-content: flex-end; margin-top: auto; }
.card h3 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); margin-top: 0.2rem; }
.card-enter-active { transition: opacity 0.4s ease, transform 0.45s var(--ease-settle); }
.card-leave-active { transition: opacity 0.25s ease; position: absolute; width: 100%; }
.card-move { transition: transform 0.4s var(--ease-settle); }
.card-enter-from { opacity: 0; transform: translateY(12px) scale(0.98); }
.card-leave-to { opacity: 0; }
.card-progress { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.6rem; }
.card-progress .progress { flex: 1; }
.pct { font-variant-numeric: tabular-nums; color: var(--text-muted); font-size: var(--fs-body); }
.newer { color: var(--accent); font-size: var(--fs-body); margin-top: 0.3rem; }
.empty, .state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.link-btn { color: var(--accent); text-decoration: underline; margin-left: 0.6rem; }
.btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px;
  border: 1px solid var(--border-med); color: var(--text-dim); transition: background-color 0.28s var(--ease-settle), color 0.28s ease, border-color 0.28s ease, transform 0.28s var(--ease-settle);
}
.btn:hover:not(:disabled) { transform: translateY(-1px); }
a.btn { text-decoration: none; }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn--danger { border-color: var(--danger); color: var(--danger); }
.btn--danger:hover { background: var(--danger-dim); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) {
  .card, .btn, .card-enter-active, .card-leave-active, .card-move { transition: none !important; }
  .card:hover, .btn:hover:not(:disabled) { transform: none; }
}
</style>
