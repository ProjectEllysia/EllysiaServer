<template>
  <!-- Solo para correos que llegaron por un buzón conectado: en los demás no hay nada que mover. -->
  <section v-if="state && state.unavailableReason !== 'not_from_mailbox'" class="mailbox-actions">
    <h3 class="ma-title">{{ t('iris.remediation.title') }}</h3>
    <p class="ma-intro">{{ t('iris.remediation.intro') }}</p>

    <p class="ma-recommendation">
      {{ state.recommendedAction
        ? t('iris.remediation.recommended', { action: t(mailboxActionKey(state.recommendedAction)) })
        : t('iris.remediation.noRecommendation') }}
    </p>

    <p v-if="!state.canAct" class="ma-unavailable">{{ t(unavailableReasonKey(state.unavailableReason)) }}</p>
    <template v-else>
      <label class="ma-field">
        <span class="ma-label">{{ t('iris.remediation.reason') }}</span>
        <textarea v-model="reason" class="ma-input" rows="2" maxlength="1000" :placeholder="t('iris.remediation.reasonPlaceholder')"></textarea>
      </label>
      <div class="ma-buttons">
        <button
          v-for="option in state.actions" :key="option.action" type="button"
          class="ma-btn" :class="{ 'ma-btn--recommended': option.action === state.recommendedAction, 'ma-btn--danger': option.isDestructive }"
          :disabled="!canSubmit || hasInFlight"
          @click="ask(option)"
        >{{ t(mailboxActionKey(option.action)) }}</button>
      </div>
    </template>

    <div v-if="state.history.length" class="ma-history">
      <h4 class="ma-subtitle">{{ t('iris.remediation.history') }}</h4>
      <ul class="ma-list">
        <li v-for="entry in state.history" :key="entry.actionId" class="ma-entry">
          <span class="ma-chip">{{ t(mailboxActionStatusKey(entry.status)) }}</span>
          <span class="ma-entry-text">
            {{ t(mailboxActionKey(entry.action)) }}<template v-if="entry.isRollback"> ({{ t('iris.remediation.undoneBy') }})</template>
            · {{ entry.actor }} · {{ formatDateTime(entry.createdAt) }}
          </span>
          <span class="ma-reason" :title="entry.error || ''">«{{ entry.reason }}»</span>
          <button
            v-if="state.canAct && entry.status === 'succeeded' && !entry.isRollback"
            type="button" class="ma-btn ma-btn--small" :disabled="hasInFlight" @click="undo(entry)"
          >{{ t('iris.remediation.undo') }}</button>
        </li>
      </ul>
    </div>

    <ConfirmModal
      :show="pending !== null"
      :title="pending ? t('iris.remediation.confirmTitle', { action: t(mailboxActionKey(pending.action)) }) : ''"
      :message="t('iris.remediation.confirmMessage')"
      :danger="true"
      :confirm-label="t('common.confirm')"
      @confirm="submit(pending, true)"
      @cancel="pending = null"
    />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { useIrisStore } from '@/stores/irisStore'
import { formatDateTime } from '@/i18n/format'
import { isActionInFlight, mailboxActionKey, mailboxActionStatusKey, unavailableReasonKey } from '@/components/iris/remediation'

const props = defineProps({
  /** Análisis cuyo correo se enseña. */
  analysisId: { type: Number, required: true },
})

const { t } = useI18n()
const store = useIrisStore()

/** Mínimo de caracteres del motivo; el servidor exige lo mismo. */
const MIN_REASON_LENGTH = 5
/** Cada cuánto se vuelve a preguntar mientras una acción está en curso, en milisegundos. */
const POLL_INTERVAL_MS = 3000

const reason = ref('')
/** Acción destructiva a la espera de confirmación en el modal. */
const pending = ref(null)
let pollTimer = null

const state = computed(() => store.mailboxActions[props.analysisId] ?? null)
const canSubmit = computed(() => reason.value.trim().length >= MIN_REASON_LENGTH)
const hasInFlight = computed(() => (state.value?.history ?? []).some(isActionInFlight))

/** Las destructivas pasan por el modal de confirmación; etiquetar va directo. */
function ask(option) {
  if (option.isDestructive) pending.value = option
  else submit(option, false)
}

async function submit(option, confirm) {
  pending.value = null
  const requested = await store.requestMailboxAction(props.analysisId, {
    action: option.action, reason: reason.value.trim(), confirm,
  })
  if (requested) reason.value = ''
}

function undo(entry) {
  const text = reason.value.trim().length >= MIN_REASON_LENGTH ? reason.value.trim() : t('iris.remediation.undoReason')
  store.rollbackMailboxAction(props.analysisId, entry.actionId, text)
}

/** Mientras haya una acción en curso, vuelve a preguntar hasta que termine. */
function schedulePoll() {
  clearTimeout(pollTimer)
  if (!hasInFlight.value) return
  pollTimer = setTimeout(async () => {
    await store.fetchMailboxActions(props.analysisId)
    schedulePoll()
  }, POLL_INTERVAL_MS)
}

watch(hasInFlight, schedulePoll)
watch(() => props.analysisId, (id) => store.fetchMailboxActions(id))
onMounted(() => store.fetchMailboxActions(props.analysisId))
onBeforeUnmount(() => clearTimeout(pollTimer))
</script>

<style scoped>
.mailbox-actions { margin: 1.2rem 0; padding: 1rem 1.2rem; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.ma-title { margin: 0 0 0.3rem; font-size: var(--fs-lg); color: var(--text); }
.ma-subtitle { margin: 1rem 0 0.4rem; font-size: var(--fs-md); color: var(--text); }
.ma-intro, .ma-recommendation, .ma-unavailable { margin: 0 0 0.7rem; font-size: var(--fs-sm); color: var(--text-dim); line-height: 1.5; }
.ma-recommendation { color: var(--text); font-weight: 600; }
.ma-unavailable { color: var(--text-muted); }
.ma-field { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 0.6rem; }
.ma-label { font-size: var(--fs-xs); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.ma-input { padding: 0.45rem 0.6rem; font-size: var(--fs-sm); background: var(--surface-2); color: var(--text); border: 1px solid var(--border-med); border-radius: 6px; }
.ma-buttons { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.ma-btn { padding: 0.35rem 0.8rem; font-size: var(--fs-sm); border-radius: 6px; cursor: pointer; background: transparent; color: var(--text-dim); border: 1px solid var(--border-med); }
.ma-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ma-btn--recommended { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.ma-btn--danger.ma-btn--recommended { background: var(--accent); color: var(--on-accent); }
.ma-btn--small { padding: 0.15rem 0.55rem; font-size: var(--fs-xs); }
.ma-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.ma-entry { display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; font-size: var(--fs-sm); color: var(--text-dim); }
.ma-chip { padding: 0 0.45rem; font-size: var(--fs-xs); font-weight: 600; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.ma-reason { color: var(--text-muted); font-style: italic; }
</style>
