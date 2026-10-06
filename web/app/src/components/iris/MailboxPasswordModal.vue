<template>
  <Teleport to="body">
    <div v-if="connection" class="modal-overlay" @click.self="$emit('close')">
      <form class="modal-box" role="dialog" aria-modal="true" :aria-label="t('iris.imap.rotateTitle')" @submit.prevent="save">
        <div class="modal-header">
          <h3>{{ t('iris.imap.rotateTitle') }}</h3>
          <button type="button" class="close-btn" :aria-label="t('confirm.close')" @click="$emit('close')">&times;</button>
        </div>
        <p class="modal-sub">{{ t('iris.imap.rotateIntro', { email: connection.accountEmail }) }}</p>
        <label class="field">
          <span>{{ t('iris.imap.password') }}</span>
          <input v-model="password" type="password" autocomplete="new-password" required />
        </label>
        <div class="modal-footer">
          <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('confirm.cancel') }}</button>
          <button type="submit" class="btn-primary" :disabled="!password || saving">{{ t('iris.imap.rotate') }}</button>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * Cambia la contraseña de aplicación de una conexión IMAP. El servidor la
 * prueba antes de guardarla y, si la conexión pedía reconectar, la reactiva.
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useIrisMailboxStore } from '@/stores/irisMailboxStore'

const { t } = useI18n()
const store = useIrisMailboxStore()

const props = defineProps({
  /** Conexión IMAP abierta (`connectionId`/`id`, `accountEmail`), o `null` con el modal cerrado. */
  connection: { type: [Object, null], default: null },
})
const emit = defineEmits(['close', 'saved'])

const password = ref('')
const saving = ref(false)

watch(() => props.connection, () => { password.value = '' })

async function save() {
  saving.value = true
  const isSaved = await store.rotateCredentials(props.connection.connectionId ?? props.connection.id, password.value)
  saving.value = false
  if (isSaved) {
    password.value = ''
    emit('saved')
  }
}
</script>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 1rem; }
.modal-box { width: min(420px, 100%); background: var(--surface); border: 1px solid var(--border-med); border-radius: 12px; padding: 1.2rem 1.3rem; }
.modal-header { display: flex; justify-content: space-between; align-items: center; }
.modal-header h3 { margin: 0; color: var(--text); }
.close-btn { background: none; border: none; color: var(--text-muted); font-size: var(--fs-lg); cursor: pointer; }
.modal-sub { font-size: var(--fs-sm); color: var(--text-dim); line-height: 1.5; }
.field { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 1rem; font-size: var(--fs-sm); color: var(--text-dim); }
.field input { padding: 0.5rem 0.65rem; border: 1px solid var(--border-med); border-radius: 8px; background: var(--surface-2); color: var(--text); }
.modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
