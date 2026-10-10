<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="data?.register.title || ''" back-to="/eunomia/registros" :back-label="t('eunomia.registers.title')" />

    <main class="layout">
      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>

      <template v-else-if="data">
        <header class="head">
          <h1>{{ data.register.title }}</h1>
          <p class="sub">{{ data.register.summary }}</p>
          <p v-if="counts.overdue || counts.upcoming" class="meta">
            {{ t('eunomia.registers.deadlineCounts', { overdue: counts.overdue, upcoming: counts.upcoming }) }}
          </p>
          <div class="actions">
            <button type="button" class="btn btn--primary" @click="startNew">{{ t('eunomia.registers.newRecord') }}</button>
            <button v-if="data.register.hasExamples && !data.records.length" type="button" class="btn" @click="addExamples">
              {{ t('eunomia.registers.addExamples') }}
            </button>
            <button type="button" class="btn" @click="download('csv')">CSV</button>
            <button type="button" class="btn" @click="download('pdf')">PDF</button>
          </div>
        </header>

        <p v-for="message in data.advice" :key="message" class="advice">{{ message }}</p>

        <form v-if="editing" class="form" @submit.prevent="save">
          <h2>{{ editing.id ? t('eunomia.registers.editRecord') : t('eunomia.registers.newRecord') }}</h2>
          <div v-for="field in data.register.fields" :key="field.key" class="field">
            <label :for="`f-${field.key}`">{{ field.label }}<span v-if="field.isRequired" class="req"> *</span></label>
            <select v-if="field.type === 'select'" :id="`f-${field.key}`" v-model="form[field.key]">
              <option value="">—</option>
              <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <textarea v-else-if="field.type === 'longtext' || field.type === 'list'" :id="`f-${field.key}`" v-model="form[field.key]" rows="4" maxlength="20000"></textarea>
            <input v-else :id="`f-${field.key}`" v-model="form[field.key]" maxlength="20000"
                   :type="field.type === 'date' ? 'date' : field.type === 'datetime' ? 'datetime-local' : 'text'" />
            <p v-if="field.help" class="meta">{{ field.help }}</p>
          </div>
          <p v-if="conflict" class="state-msg state-msg--error">{{ t('apiErrors.recordConflict') }}</p>
          <div class="actions">
            <button type="submit" class="btn btn--primary" :disabled="saving || missing.length > 0">{{ t('eunomia.registers.save') }}</button>
            <button type="button" class="btn" @click="editing = null">{{ t('eunomia.registers.cancel') }}</button>
          </div>
        </form>

        <p v-if="!data.records.length" class="state-msg">{{ t('eunomia.registers.empty') }}</p>
        <ul v-else class="rows">
          <li v-for="record in data.records" :key="record.id" class="row">
            <div class="row-main">
              <h2>{{ record.title || `#${record.id}` }}</h2>
              <p class="meta">{{ t('eunomia.registers.updated', { date: formatDate(record.updatedAt), name: record.updatedByName || '—' }) }}</p>
              <ul v-if="record.deadlines.length" class="deadlines">
                <li v-for="deadline in record.deadlines" :key="deadline.key" :class="`deadline--${deadline.status}`">
                  {{ deadline.label }} ·
                  <template v-if="deadline.dueAt">{{ formatDate(deadline.dueAt) }} · </template>{{ t(`eunomia.registers.deadline.${deadline.status}`) }}
                </li>
              </ul>
            </div>
            <div class="actions">
              <router-link
                v-for="template in data.templates" :key="template.key"
                :to="`/eunomia/plantillas/${template.key}?recordId=${record.id}`" class="btn"
              >{{ template.title }}</router-link>
              <button type="button" class="btn" @click="edit(record)">{{ t('eunomia.registers.edit') }}</button>
              <button type="button" class="btn btn--danger" @click="archive(record)">{{ t('eunomia.registers.archive') }}</button>
            </div>
          </li>
        </ul>
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { deadlineCounts, missingFields, recordValues, toDatetimeLocal } from '@/components/eunomia/registers'
import { formatDate } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const route = useRoute()
const store = useEunomiaStore()
const toast = useToastStore()

const key = computed(() => String(route.params.register))
const data = ref(null)
const loading = ref(true)
const error = ref('')
const editing = ref(null)
const saving = ref(false)
const conflict = ref(false)
const form = reactive({})

const counts = computed(() => deadlineCounts(data.value?.records ?? []))
const missing = computed(() => (data.value ? missingFields(data.value.register.fields, form) : []))

async function load() {
  const result = await store.loadRegister(key.value)
  loading.value = false
  error.value = result.message || ''
  if (result.ok) data.value = result.data
}

/** Abre el formulario con los valores de una ficha (o vacío). */
function open(record) {
  conflict.value = false
  for (const field of data.value.register.fields) {
    const value = record?.values?.[field.key] ?? ''
    form[field.key] = field.type === 'datetime' ? toDatetimeLocal(value) : value
  }
  editing.value = record ? { id: record.id, updatedAt: record.updatedAt } : { id: null, updatedAt: null }
}

const startNew = () => open(null)
const edit = (record) => open(record)

async function save() {
  saving.value = true
  const values = recordValues(data.value.register.fields, form)
  const path = editing.value.id ? `${key.value}/records/${editing.value.id}` : `${key.value}/records`
  const result = await store.writeRegister(path, editing.value.id ? 'PUT' : 'POST',
    { values, ...(editing.value.id ? { updatedAt: editing.value.updatedAt } : {}) })
  saving.value = false
  if (result.conflict) { conflict.value = true; return }
  if (!result.ok) { toast.show(result.message, 'error'); return }
  editing.value = null
  await load()
}

async function archive(record) {
  const result = await store.writeRegister(`${key.value}/records/${record.id}/archive`, 'POST')
  if (!result.ok) { toast.show(result.message, 'error'); return }
  await load()
}

async function addExamples() {
  const result = await store.writeRegister(`${key.value}/examples`, 'POST')
  if (!result.ok) { toast.show(result.message, 'error'); return }
  await load()
}

async function download(format) {
  if (!(await store.exportRegister(key.value, format))) toast.show(t('eunomia.registers.exportFailed'), 'error')
}

onMounted(load)
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 960px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.sub { color: var(--text-muted); margin-top: 0.4rem; max-width: 62ch; font-size: var(--fs-md); }
.meta { color: var(--text-muted); font-size: var(--fs-body); }
.actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.8rem; }
.form { background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1.2rem; display: flex; flex-direction: column; gap: 1rem; }
.form h2, .row h2 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field label { color: var(--text); font-size: var(--fs-md); font-weight: 600; }
.req { color: var(--danger); }
.field input, .field textarea, .field select { background: var(--bg); border: 1px solid var(--border-solid); border-radius: 6px; padding: 0.6rem 0.7rem; color: var(--text); font-size: var(--fs-md); font-family: inherit; }
.rows { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.row { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem 1.2rem; }
.deadlines { list-style: none; padding: 0; margin-top: 0.5rem; display: flex; flex-direction: column; gap: 0.2rem; font-size: var(--fs-body); color: var(--text-dim); }
.advice { background: var(--surface); border-inline-start: 3px solid var(--accent); padding: 0.8rem 1rem; color: var(--text-dim); font-size: var(--fs-md); }
.deadline--overdue { color: var(--danger); }
.deadline--done { color: var(--accent); }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.btn { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px; border: 1px solid var(--border-med); color: var(--text-dim); transition: all var(--transition); }
a.btn { text-decoration: none; }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn--danger { border-color: var(--danger); color: var(--danger); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
