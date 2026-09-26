<template>
  <form class="trust-form" @submit.prevent="submit">
    <div class="trust-row">
      <label class="trust-field">
        <span class="trust-label">{{ t('iris.trust.trustIn') }}</span>
        <select v-model="kind" class="trust-input">
          <option value="domain">{{ t('iris.trust.theDomain') }}</option>
          <option value="sender">{{ t('iris.trust.onlyAddress') }}</option>
        </select>
      </label>
      <label class="trust-field trust-field--grow">
        <span class="trust-label">{{ kind === 'domain' ? t('iris.trust.domain') : t('iris.trust.address') }}</span>
        <input
          v-model="value"
          class="trust-input"
          type="text"
          maxlength="320"
          :placeholder="kind === 'domain' ? t('iris.trust.domainPlaceholder') : t('iris.trust.addressPlaceholder')"
          required
        />
      </label>
      <label class="trust-field">
        <span class="trust-label">{{ t('iris.trust.expiresIn') }}</span>
        <select v-model.number="expiresInDays" class="trust-input">
          <option v-for="days in EXPIRY_OPTIONS" :key="days" :value="days">{{ t('iris.trust.days', { count: days }) }}</option>
        </select>
      </label>
    </div>
    <label class="trust-field">
      <span class="trust-label">{{ t('iris.trust.reason') }}</span>
      <input
        v-model="reason"
        class="trust-input"
        type="text"
        maxlength="500"
        :placeholder="t('iris.trust.reasonPlaceholder')"
        required
      />
    </label>
    <p class="trust-hint">{{ t('iris.trust.hint') }}</p>
    <div class="trust-actions">
      <button type="submit" class="trust-save" :disabled="saving || !value.trim() || !reason.trim()">
        {{ saving ? t('common.saving') : t('iris.trust.save') }}
      </button>
      <button v-if="cancellable" type="button" class="trust-cancel" @click="$emit('cancel')">{{ t('common.cancel') }}</button>
    </div>
  </form>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useIrisStore } from '@/stores/irisStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  // Cabecera From del informe del que se parte, para rellenar el valor.
  fromHeader: { type: String, default: '' },
  cancellable: { type: Boolean, default: false },
})
const emit = defineEmits(['saved', 'cancel'])

const store = useIrisStore()
const EXPIRY_OPTIONS = [30, 90, 180, 365]

const kind = ref('domain')
const value = ref('')
const reason = ref('')
const expiresInDays = ref(90)
const saving = ref(false)

/** Dirección de un valor de cabecera From: la de entre ángulos si la hay. */
function addressOf(fromHeader) {
  const match = /<\s*([^<>\s]+@[^<>\s]+)\s*>/.exec(fromHeader) || /[\w.+'-]+@[\w.-]+/.exec(fromHeader)
  return match ? (match[1] ?? match[0]).toLowerCase() : ''
}

function prefill() {
  const address = addressOf(props.fromHeader || '')
  value.value = kind.value === 'domain' ? address.split('@')[1] ?? '' : address
}

watch(() => props.fromHeader, prefill, { immediate: true })
watch(kind, prefill)

async function submit() {
  saving.value = true
  const entry = await store.createTrustedSender({
    kind: kind.value,
    value: value.value.trim(),
    reason: reason.value.trim(),
    expiresInDays: expiresInDays.value,
  })
  saving.value = false
  if (entry) {
    reason.value = ''
    emit('saved', entry)
  }
}
</script>

<style scoped>
.trust-form { display: flex; flex-direction: column; gap: 0.6rem; }
.trust-row { display: flex; flex-wrap: wrap; gap: 0.6rem; }
.trust-field { display: flex; flex-direction: column; gap: 0.25rem; }
.trust-field--grow { flex: 1; min-width: 12rem; }
.trust-label { font-size: var(--fs-sm); color: var(--text-muted); }
.trust-input {
  padding: 0.45rem 0.6rem;
  font-size: var(--fs-md);
  background: var(--surface-2);
  border: 1px solid var(--border-solid);
  border-radius: 6px;
  color: var(--text);
}
.trust-input:focus { outline: none; border-color: var(--accent); }
.trust-hint { margin: 0; font-size: var(--fs-sm); color: var(--text-dim); line-height: 1.5; }
.trust-actions { display: flex; gap: 0.5rem; }
.trust-save,
.trust-cancel {
  padding: 0.4rem 0.9rem;
  font-size: var(--fs-sm);
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
}
.trust-save { border: none; background: var(--accent); color: var(--on-accent); }
.trust-save:disabled { opacity: 0.4; cursor: not-allowed; }
.trust-cancel { border: 1px solid var(--border-med); background: transparent; color: var(--text-dim); }
</style>
