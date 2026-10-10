<template>
  <section class="evidence" :aria-label="t('eunomia.evidence.title')">
    <h3>{{ t('eunomia.evidence.title') }}</h3>

    <p v-if="!node.linkedEvidence.length" class="muted">{{ t('eunomia.evidence.none') }}</p>
    <ul v-else class="list">
      <li v-for="item in node.linkedEvidence" :key="item.id">
        <button type="button" class="link-btn" @click="download(item)">{{ item.title }}</button>
        <span class="muted">{{ item.filename }} · {{ size(item.sizeBytes) }}</span>
        <span v-if="item.validUntil" class="muted">· {{ t('eunomia.evidence.validUntil', { date: formatDate(item.validUntil) }) }}</span>
        <button v-if="canEdit" type="button" class="link-btn link-btn--quiet" @click="unlink(item)">
          {{ t('eunomia.evidence.unlink') }}
        </button>
      </li>
    </ul>

    <div v-if="canEdit" class="add">
      <div v-if="available.length" class="field">
        <label :for="`link-${node.code}`">{{ t('eunomia.evidence.linkExisting') }}</label>
        <div class="inline">
          <select :id="`link-${node.code}`" v-model="chosen">
            <option :value="null">—</option>
            <option v-for="item in available" :key="item.id" :value="item.id">{{ item.title }}</option>
          </select>
          <button type="button" class="btn" :disabled="!chosen || busy" @click="link">{{ t('eunomia.evidence.link') }}</button>
        </div>
      </div>

      <div class="field">
        <label :for="`upload-${node.code}`">{{ t('eunomia.evidence.uploadNew') }}</label>
        <input :id="`upload-${node.code}`" v-model.trim="title" type="text" maxlength="255" :placeholder="t('eunomia.evidence.titlePlaceholder')" />
        <input type="date" v-model="validUntil" :aria-label="t('eunomia.evidence.validUntilLabel')" />
        <input ref="fileEl" type="file" :aria-label="t('eunomia.evidence.file')" />
        <button type="button" class="btn" :disabled="busy" @click="upload">{{ t('eunomia.evidence.upload') }}</button>
      </div>
    </div>
  </section>
</template>

<script setup>
/**
 * Las evidencias de un control: las enlazadas, enlazar una existente (una evidencia sirve a
 * varios controles de varios marcos) y subir una nueva. Avisa con `changed` para que la vista
 * recargue el árbol.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'
import { formatDate, formatNumber } from '@/i18n/format'

const props = defineProps({
  node: { type: Object, required: true },
  framework: { type: String, required: true },
  canEdit: { type: Boolean, default: true },
})
const emit = defineEmits(['changed'])
const { t } = useI18n()
const store = useEunomiaStore()
const toast = useToastStore()

const all = ref([])
const chosen = ref(null)
const title = ref('')
const validUntil = ref('')
const fileEl = ref(null)
const busy = ref(false)

/** Las evidencias del dueño que todavía no están enlazadas con este control. */
const available = computed(() => {
  const linked = new Set(props.node.linkedEvidence.map((item) => item.id))
  return all.value.filter((item) => !linked.has(item.id))
})

/** Tamaño en MB o KB, con el formato del idioma. */
function size(bytes) {
  return bytes >= 1048576
    ? `${formatNumber(bytes / 1048576, { maximumFractionDigits: 1 })} MB`
    : `${formatNumber(Math.max(1, Math.round(bytes / 1024)))} KB`
}

async function refresh() { all.value = await store.loadEvidence() }

async function download(item) {
  if (!(await store.downloadEvidence(item))) toast.show(t('eunomia.evidence.downloadFailed'), 'error')
}

async function link() {
  busy.value = true
  const result = await store.setEvidenceLink(chosen.value, props.framework, props.node.identifier, true)
  busy.value = false
  if (!result.ok) { toast.show(result.message, 'error'); return }
  chosen.value = null
  emit('changed')
  await refresh()
}

async function unlink(item) {
  const result = await store.setEvidenceLink(item.id, props.framework, props.node.identifier, false)
  if (!result.ok) { toast.show(result.message, 'error'); return }
  emit('changed')
  await refresh()
}

async function upload() {
  const file = fileEl.value?.files?.[0]
  if (!file) { toast.show(t('eunomia.evidence.pickFile'), 'error'); return }
  busy.value = true
  const uploaded = await store.uploadEvidence(file, { title: title.value, validUntil: validUntil.value })
  if (!uploaded.ok) { busy.value = false; toast.show(uploaded.message, 'error'); return }
  const linked = await store.setEvidenceLink(uploaded.evidence.id, props.framework, props.node.identifier, true)
  busy.value = false
  if (!linked.ok) toast.show(linked.message, 'error')
  title.value = ''
  validUntil.value = ''
  fileEl.value.value = ''
  emit('changed')
  await refresh()
}

onMounted(refresh)
</script>

<style scoped>
.evidence { padding-top: 1rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.8rem; }
h3 { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.muted { color: var(--text-muted); font-size: var(--fs-body); }
.list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.list li { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: baseline; font-size: var(--fs-md); }
.link-btn { color: var(--accent); text-decoration: underline; }
.link-btn--quiet { color: var(--text-muted); margin-left: auto; }
.add { display: flex; flex-direction: column; gap: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.35rem; }
.field label { font-size: var(--fs-body); color: var(--text-dim); }
.inline { display: flex; gap: 0.5rem; }
.field select, .field input[type="text"], .field input[type="date"] {
  padding: 0.5rem 0.7rem; border-radius: 6px; background: var(--bg); color: var(--text);
  border: 1px solid var(--border-med); font-family: inherit;
}
.btn {
  align-self: flex-start; font-size: var(--fs-body); font-weight: 600; padding: 0.5rem 1rem; border-radius: 3px;
  background: var(--accent-dim); border: 1px solid var(--accent); color: var(--accent-bright);
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
