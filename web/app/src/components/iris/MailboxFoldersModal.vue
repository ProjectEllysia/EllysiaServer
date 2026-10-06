<template>
  <Teleport to="body">
    <div v-if="connection" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box" role="dialog" aria-modal="true" :aria-label="t('iris.folders.title')">
        <div class="modal-header">
          <h3>{{ t('iris.folders.title') }}</h3>
          <button class="close-btn" :aria-label="t('confirm.close')" @click="$emit('close')">&times;</button>
        </div>
        <p class="modal-sub">{{ t('iris.folders.intro', { email: connection.accountEmail }) }}</p>
        <p v-if="loading" class="state-msg">{{ t('iris.mailboxes.loading') }}</p>
        <ul v-else class="folder-list">
          <li v-for="folder in folders" :key="folder.providerId">
            <label>
              <input
                type="checkbox"
                :checked="isWatched(folder.providerId)"
                :disabled="folder.providerId === primaryFolder"
                @change="toggle(folder.providerId)"
              />
              <span>{{ folder.displayName }}</span>
              <span v-if="folder.providerId === primaryFolder" class="folder-tag">{{ t('iris.folders.primary') }}</span>
            </label>
          </li>
        </ul>
        <div class="modal-footer">
          <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('confirm.cancel') }}</button>
          <button type="button" class="btn-primary" :disabled="loading || saving" @click="save">{{ t('iris.folders.save') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * Elige las carpetas que se vigilan además de la principal. Las opciones son
 * las carpetas reales de la cuenta, leídas en el momento; la principal no se
 * puede desmarcar aquí (se cambia desde la conexión).
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useIrisMailboxStore } from '@/stores/irisMailboxStore'

const { t } = useI18n()
const store = useIrisMailboxStore()

const props = defineProps({
  /** Conexión abierta (`connectionId`/`id`, `folder`, `additionalFolders`), o `null` con el modal cerrado. */
  connection: { type: [Object, null], default: null },
})
const emit = defineEmits(['close', 'saved'])

const folders = ref([])
const selected = ref(new Set())
const loading = ref(false)
const saving = ref(false)
const primaryFolder = ref(null)

function connectionId() { return props.connection?.connectionId ?? props.connection?.id }
function isWatched(id) { return id === primaryFolder.value || selected.value.has(id) }
function toggle(id) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

watch(() => props.connection, async (connection) => {
  if (!connection) return
  primaryFolder.value = connection.folder ?? (connection.provider === 'imap' ? 'INBOX' : null)
  selected.value = new Set((connection.additionalFolders ?? []).map(folder => folder.id))
  loading.value = true
  folders.value = (await store.fetchFolders(connectionId())) ?? []
  loading.value = false
}, { immediate: true })

async function save() {
  saving.value = true
  const isSaved = await store.setFolders(connectionId(), [...selected.value])
  saving.value = false
  if (isSaved) emit('saved')
}
</script>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 1rem; }
.modal-box { width: min(460px, 100%); background: var(--surface); border: 1px solid var(--border-med); border-radius: 12px; padding: 1.2rem 1.3rem; }
.modal-header { display: flex; justify-content: space-between; align-items: center; }
.modal-header h3 { margin: 0; color: var(--text); }
.close-btn { background: none; border: none; color: var(--text-muted); font-size: var(--fs-lg); cursor: pointer; }
.modal-sub { font-size: var(--fs-sm); color: var(--text-dim); line-height: 1.5; }
.folder-list { list-style: none; padding: 0; margin: 0.5rem 0 1rem; max-height: 320px; overflow: auto; }
.folder-list label { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; color: var(--text); }
.folder-tag { font-size: var(--fs-xs); color: var(--accent); }
.state-msg { color: var(--text-muted); }
.modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
