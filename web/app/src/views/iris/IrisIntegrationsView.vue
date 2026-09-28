<template>
  <div class="integrations-page" data-module="iris">
    <StarBackground />
    <Topbar :title="'Iris'" :badge="t('iris.webhooks.badge')" back-to="/iris/analisis" :back-label="t('iris.batch.analysis')" />

    <div class="integrations-layout">
      <section class="panel">
        <p class="panel-eyebrow">{{ t('iris.webhooks.eyebrow') }}</p>
        <h2 class="panel-title">{{ t('iris.webhooks.title') }}</h2>
        <p class="panel-sub">{{ t('iris.webhooks.intro') }}</p>
        <p class="hint">{{ t('iris.webhooks.signatureHint') }}</p>

        <form class="webhook-form" @submit.prevent="create">
          <label class="field">
            <span class="field-label">{{ t('iris.webhooks.name') }}</span>
            <input v-model="draft.name" class="text-input" maxlength="80" required :placeholder="t('iris.webhooks.namePlaceholder')" />
          </label>
          <label class="field">
            <span class="field-label">{{ t('iris.webhooks.url') }}</span>
            <input v-model="draft.url" class="text-input" type="url" required :placeholder="t('iris.webhooks.urlPlaceholder')" />
          </label>
          <fieldset class="field events">
            <legend class="field-label">{{ t('iris.webhooks.eventsLabel') }}</legend>
            <label v-for="eventType in store.webhooks.availableEventTypes" :key="eventType" class="toggle">
              <input v-model="draft.eventTypes" type="checkbox" :value="eventType" />
              <span>{{ t(webhookEventKey(eventType)) }}</span>
            </label>
          </fieldset>
          <button type="submit" class="primary-btn" :disabled="!draft.eventTypes.length">{{ t('iris.webhooks.create') }}</button>
        </form>
      </section>

      <!-- El secreto solo existe en claro aquí y ahora: el servidor no lo vuelve a enseñar. -->
      <section v-if="store.webhooks.lastSecret" class="panel panel--secret" role="alert">
        <h3 class="list-title">{{ t('iris.webhooks.secretTitle') }}</h3>
        <p class="hint">{{ t('iris.webhooks.secretHint') }}</p>
        <div class="secret-row">
          <code class="secret-value">{{ store.webhooks.lastSecret.secret }}</code>
          <button type="button" class="ghost-btn" @click="copySecret">{{ t('iris.webhooks.copy') }}</button>
          <button type="button" class="ghost-btn" @click="store.webhooks.lastSecret = null">{{ t('iris.webhooks.secretSaved') }}</button>
        </div>
      </section>

      <section class="panel">
        <h3 class="list-title">{{ t('iris.webhooks.listTitle') }}</h3>
        <p v-if="store.webhooks.loading && !store.webhooks.loaded" class="empty">{{ t('common.loading') }}</p>
        <p v-else-if="!store.webhooks.items.length" class="empty">{{ t('iris.webhooks.empty') }}</p>
        <ul v-else class="webhook-list">
          <li v-for="hook in store.webhooks.items" :key="hook.subscriptionId" class="webhook">
            <div class="webhook-head">
              <strong class="webhook-name">{{ hook.name }}</strong>
              <span class="chip" :class="hook.isActive ? 'chip--ok' : 'chip--danger'">
                {{ hook.isActive ? t('iris.webhooks.active') : t('iris.webhooks.inactive') }}
              </span>
            </div>
            <code class="item-value">{{ hook.url }}</code>
            <div class="chips">
              <span v-for="eventType in hook.eventTypes" :key="eventType" class="chip">{{ t(webhookEventKey(eventType)) }}</span>
            </div>
            <p v-if="!hook.isActive" class="hint hint--warn">{{ t(disabledReasonKey(hook.disabledReason)) }}</p>
            <p class="item-meta">
              <span v-if="hook.lastSuccessAt">{{ t('iris.webhooks.lastSuccess', { date: formatDateTime(hook.lastSuccessAt) }) }}</span>
              <span v-if="hook.lastFailureAt"> · {{ t('iris.webhooks.lastFailure', { date: formatDateTime(hook.lastFailureAt) }) }}</span>
              <span v-if="!hook.lastSuccessAt && !hook.lastFailureAt">{{ t('iris.webhooks.neverSent') }}</span>
            </p>
            <div class="actions">
              <button type="button" class="ghost-btn" :disabled="!hook.isActive" @click="store.testWebhook(hook.subscriptionId)">{{ t('iris.webhooks.test') }}</button>
              <button type="button" class="ghost-btn" @click="toggleActive(hook)">{{ hook.isActive ? t('iris.webhooks.disable') : t('iris.webhooks.enable') }}</button>
              <button type="button" class="ghost-btn" @click="askRotate(hook)">{{ t('iris.webhooks.rotate') }}</button>
              <button type="button" class="ghost-btn" @click="toggleHistory(hook.subscriptionId)">{{ openHistory[hook.subscriptionId] ? t('iris.webhooks.hideHistory') : t('iris.webhooks.showHistory') }}</button>
              <button type="button" class="ghost-btn ghost-btn--danger" @click="askDelete(hook)">{{ t('common.delete') }}</button>
            </div>

            <div v-if="openHistory[hook.subscriptionId]" class="history">
              <p v-if="!(store.webhooks.deliveries[hook.subscriptionId] || []).length" class="empty">{{ t('iris.webhooks.noDeliveries') }}</p>
              <table v-else class="history-table">
                <thead>
                  <tr>
                    <th>{{ t('iris.webhooks.columns.event') }}</th>
                    <th>{{ t('iris.webhooks.columns.status') }}</th>
                    <th>{{ t('iris.webhooks.columns.attempts') }}</th>
                    <th>{{ t('iris.webhooks.columns.date') }}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="delivery in store.webhooks.deliveries[hook.subscriptionId]" :key="delivery.deliveryId">
                    <td>{{ t(webhookEventKey(delivery.eventType)) }}</td>
                    <td :title="delivery.lastError || ''">{{ t(deliveryStatusKey(delivery.status)) }}</td>
                    <td>{{ delivery.attempts }}</td>
                    <td>{{ formatDateTime(delivery.createdAt) }}</td>
                    <td>
                      <button
                        v-if="hook.isActive && (delivery.status === 'delivered' || delivery.status === 'failed')"
                        type="button" class="ghost-btn"
                        @click="store.replayWebhookDelivery(hook.subscriptionId, delivery.deliveryId)"
                      >{{ t('iris.webhooks.replay') }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </li>
        </ul>
      </section>
    </div>

    <ConfirmModal
      :show="confirm.open"
      :title="confirm.title"
      :message="confirm.message"
      :danger="true"
      :confirm-label="t('common.confirm')"
      @confirm="confirm.action()"
      @cancel="confirm.open = false"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { useIrisStore } from '@/stores/irisStore'
import { useToastStore } from '@/stores/toastStore'
import { formatDateTime } from '@/i18n/format'
import { deliveryStatusKey, disabledReasonKey, webhookEventKey } from '@/components/iris/webhooks'

const { t } = useI18n()
const store = useIrisStore()
const toast = useToastStore()

/** Borrador del alta: por defecto, todos los eventos marcados. */
const draft = reactive({ name: '', url: '', eventTypes: [] })
/** Qué historiales están desplegados, por id de webhook. */
const openHistory = reactive({})
const confirm = ref({ open: false, title: '', message: '', action: () => {} })

async function create() {
  const created = await store.createWebhook({ name: draft.name, url: draft.url, eventTypes: draft.eventTypes })
  if (created) Object.assign(draft, { name: '', url: '', eventTypes: [...store.webhooks.availableEventTypes] })
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(store.webhooks.lastSecret.secret)
    toast.show(t('iris.webhooks.copied'), 'success')
  } catch {
    toast.show(t('iris.webhooks.copyFailed'), 'error')
  }
}

function toggleActive(hook) {
  store.updateWebhook(hook.subscriptionId, { isActive: !hook.isActive })
}

async function toggleHistory(id) {
  openHistory[id] = !openHistory[id]
  if (openHistory[id]) await store.fetchWebhookDeliveries(id)
}

function askRotate(hook) {
  confirm.value = {
    open: true,
    title: t('iris.webhooks.confirmRotate.title', { name: hook.name }),
    message: t('iris.webhooks.confirmRotate.message'),
    action: async () => {
      confirm.value.open = false
      await store.rotateWebhookSecret(hook.subscriptionId)
    },
  }
}

function askDelete(hook) {
  confirm.value = {
    open: true,
    title: t('iris.webhooks.confirmDelete.title', { name: hook.name }),
    message: t('iris.webhooks.confirmDelete.message'),
    action: async () => {
      confirm.value.open = false
      await store.deleteWebhook(hook.subscriptionId)
    },
  }
}

onMounted(async () => {
  await store.fetchWebhooks()
  draft.eventTypes = [...store.webhooks.availableEventTypes]
})
</script>

<style scoped>
.integrations-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.integrations-layout {
  position: relative; z-index: 1;
  max-width: 900px; margin: 0 auto; padding: 2rem 1.25rem 3rem;
  display: flex; flex-direction: column; gap: 1.5rem;
}
.panel { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 1.4rem 1.6rem; }
.panel--secret { border-color: var(--accent); }
.panel-eyebrow {
  margin: 0 0 0.3rem; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs); letter-spacing: 0.28em; text-transform: uppercase; color: var(--accent);
}
.panel-title { margin: 0 0 0.5rem; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); font-weight: 700; color: var(--text); }
.panel-sub, .hint { margin: 0 0 0.9rem; font-size: var(--fs-md); line-height: 1.55; color: var(--text-dim); max-width: 70ch; }
.hint { font-size: var(--fs-sm); color: var(--text-muted); }
.hint--warn { color: var(--danger); margin: 0.3rem 0; }
.empty { margin: 0; color: var(--text-muted); font-size: var(--fs-md); }
.list-title { margin: 0 0 0.6rem; font-size: var(--fs-lg); color: var(--text); }
.webhook-form { display: flex; flex-direction: column; gap: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.events { border: none; padding: 0; margin: 0; }
.field-label { font-size: var(--fs-xs); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.toggle { display: flex; align-items: center; gap: 0.5rem; font-size: var(--fs-md); color: var(--text); }
.text-input {
  padding: 0.45rem 0.6rem; font-size: var(--fs-sm); font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border-med); border-radius: 6px;
}
.primary-btn { align-self: flex-start; padding: 0.4rem 0.9rem; font-size: var(--fs-sm); font-weight: 600; border-radius: 6px; cursor: pointer; border: none; background: var(--accent); color: var(--on-accent); }
.primary-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost-btn { padding: 0.3rem 0.7rem; font-size: var(--fs-sm); border-radius: 6px; cursor: pointer; background: transparent; color: var(--text-dim); border: 1px solid var(--border-med); }
.ghost-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost-btn--danger { color: var(--danger); }
.secret-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.secret-value { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text); word-break: break-all; padding: 0.3rem 0.5rem; background: var(--surface-2); border-radius: 6px; }
.webhook-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1rem; }
.webhook { border-top: 1px solid var(--border); padding-top: 0.9rem; display: flex; flex-direction: column; gap: 0.35rem; }
.webhook:first-child { border-top: none; padding-top: 0; }
.webhook-head { display: flex; align-items: center; gap: 0.6rem; }
.webhook-name { color: var(--text); font-size: var(--fs-md); }
.item-value { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); word-break: break-all; }
.item-meta { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); }
.chips { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip { padding: 0 0.45rem; font-size: var(--fs-xs); font-weight: 600; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.chip--ok { background: var(--success-dim); color: var(--success); }
.chip--danger { background: var(--danger-dim); color: var(--danger); }
.actions { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.3rem; }
.history { margin-top: 0.5rem; overflow-x: auto; }
.history-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); color: var(--text-dim); }
.history-table th { text-align: left; font-weight: 600; color: var(--text-muted); padding: 0.3rem 0.4rem; border-bottom: 1px solid var(--border); }
.history-table td { padding: 0.3rem 0.4rem; border-bottom: 1px solid var(--border); }
</style>
