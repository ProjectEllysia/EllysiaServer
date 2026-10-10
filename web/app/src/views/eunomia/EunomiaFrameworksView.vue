<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.frameworks.title')" back-to="/profile" :back-label="t('eunomia.frameworks.back')" />

    <main class="layout">
      <header class="head">
        <h1 class="head-title">{{ t('eunomia.frameworks.title') }}</h1>
        <p class="head-sub">{{ t('eunomia.frameworks.intro') }}</p>
      </header>

      <OrganizationManagedNotice :ownership="store.state.ownership" />

      <p v-if="store.state.loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="store.state.error" class="state-msg state-msg--error">
        {{ store.state.error }}
        <button type="button" class="link-btn" @click="store.load()">{{ t('common.retry') }}</button>
      </p>

      <template v-else>
        <section class="block" aria-labelledby="adopted-title">
          <h2 id="adopted-title">{{ t('eunomia.frameworks.adopted') }}</h2>
          <p v-if="!groups.active.length" class="empty">{{ t('eunomia.frameworks.noneAdopted') }}</p>
          <ul v-else class="cards">
            <li v-for="adoption in groups.active" :key="adoption.frameworkKey" class="card">
              <div class="card-main">
                <h3>{{ adoption.name }}</h3>
                <p class="meta">
                  {{ t('eunomia.frameworks.version', { version: adoption.catalogVersion }) }}
                  · {{ t('eunomia.frameworks.adoptedOn', { date: formatDate(adoption.adoptedAt) }) }}
                </p>
                <p v-if="adoption.hasNewerVersion" class="newer">
                  {{ t('eunomia.frameworks.newerVersion', { version: adoption.currentVersion }) }}
                </p>
              </div>
              <button
                v-if="canManage" type="button" class="btn btn--danger"
                :disabled="store.state.busyKey === adoption.frameworkKey"
                @click="askRemoval(adoption)"
              >{{ t('eunomia.frameworks.remove') }}</button>
            </li>
          </ul>
        </section>

        <section class="block" aria-labelledby="available-title">
          <h2 id="available-title">{{ t('eunomia.frameworks.available') }}</h2>
          <p v-if="!groups.available.length" class="empty">{{ t('eunomia.frameworks.noneAvailable') }}</p>
          <ul v-else class="cards">
            <li v-for="framework in groups.available" :key="framework.key" class="card">
              <div class="card-main">
                <h3>{{ framework.name }}</h3>
                <p class="meta">{{ t('eunomia.frameworks.version', { version: framework.current }) }}{{ isDraft(framework) ? ` · ${t('eunomia.frameworks.draft')}` : '' }}</p>
              </div>
              <button
                v-if="canManage" type="button" class="btn btn--primary"
                :disabled="store.state.busyKey === framework.key"
                @click="adopt(framework.key)"
              >{{ t('eunomia.frameworks.adopt') }}</button>
            </li>
          </ul>
        </section>

        <section v-if="groups.archived.length" class="block" aria-labelledby="archived-title">
          <h2 id="archived-title">{{ t('eunomia.frameworks.archived') }}</h2>
          <ul class="cards">
            <li v-for="adoption in groups.archived" :key="adoption.frameworkKey" class="card">
              <div class="card-main">
                <h3>{{ adoption.name }}</h3>
                <p class="meta">{{ t('eunomia.frameworks.purgeAt', { date: formatDate(adoption.purgeAt) }) }}</p>
              </div>
              <button
                v-if="canManage" type="button" class="btn btn--primary"
                :disabled="store.state.busyKey === adoption.frameworkKey"
                @click="restore(adoption.frameworkKey)"
              >{{ t('eunomia.frameworks.restore') }}</button>
            </li>
          </ul>
        </section>
      </template>
    </main>

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
import { hasLoss, removalFacts } from '@/components/eunomia/frameworks'
import { formatDate } from '@/i18n/format'
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
.block h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); margin-bottom: 0.8rem; }
.cards { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.card {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem 1.2rem;
}
.card h3 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); margin-top: 0.2rem; }
.newer { color: var(--accent); font-size: var(--fs-body); margin-top: 0.3rem; }
.empty, .state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.link-btn { color: var(--accent); text-decoration: underline; margin-left: 0.6rem; }
.btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px;
  border: 1px solid var(--border-med); color: var(--text-dim); transition: all var(--transition);
}
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn--danger { border-color: var(--danger); color: var(--danger); }
.btn--danger:hover { background: var(--danger-dim); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
