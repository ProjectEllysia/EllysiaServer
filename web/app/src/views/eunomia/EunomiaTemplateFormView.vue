<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.templates.title')" back-to="/eunomia/plantillas" :back-label="t('eunomia.templates.title')" />

    <main class="layout">
      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>

      <template v-else-if="data">
        <header class="head">
          <h1>{{ data.template.title }}</h1>
          <p class="sub">{{ data.template.summary }}</p>
          <p v-if="data.updatedAt" class="meta">
            {{ t('eunomia.templates.savedAt', { date: formatDate(data.updatedAt), name: data.updatedByName || '—' }) }}
          </p>
        </header>

        <form class="form" @submit.prevent="save">
          <div v-for="field in data.fields" :key="field.key" class="field">
            <label :for="`f-${field.key}`">
              {{ field.label }}<span v-if="field.isRequired" class="req" aria-hidden="true"> *</span>
            </label>
            <textarea
              v-if="field.type === 'longtext' || field.type === 'list'" :id="`f-${field.key}`"
              v-model="edited[field.key]" :rows="field.type === 'list' ? 5 : 4" maxlength="20000"
              :disabled="!canEdit" :required="field.isRequired"
            ></textarea>
            <input
              v-else :id="`f-${field.key}`" v-model="edited[field.key]"
              :type="field.type === 'date' ? 'date' : 'text'" maxlength="20000"
              :disabled="!canEdit" :required="field.isRequired"
            />
            <p v-if="field.help" class="help">{{ field.help }}</p>
            <p v-if="originLabel(field)" class="origin">
              {{ originLabel(field) }}
              <router-link v-if="routeOf(field)" :to="routeOf(field)" class="link">
                {{ t('eunomia.templates.editSource') }}
              </router-link>
            </p>
          </div>

          <p v-if="missing.length" class="state-msg">
            {{ t('eunomia.templates.missing', { count: missing.length }, missing.length) }}
          </p>
          <div class="actions">
            <button v-if="canEdit" type="submit" class="btn btn--primary" :disabled="saving">
              {{ t('eunomia.templates.save') }}
            </button>
          </div>
        </form>
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
import { missingRequired, sourceRoute, valuesToSave } from '@/components/eunomia/templates'
import { formatDate } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const route = useRoute()
const store = useEunomiaStore()
const toast = useToastStore()

const data = ref(null)
const loading = ref(true)
const error = ref('')
const saving = ref(false)
const edited = reactive({})
const canEdit = computed(() => true)
const missing = computed(() => (data.value ? missingRequired(data.value.fields, edited) : []))

/** Vuelca los valores que dio la API al formulario. */
function adopt(payload) {
  data.value = payload
  for (const field of payload.fields) edited[field.key] = field.value
}

/** El texto que dice de dónde viene un valor precargado; `''` si lo escribió el usuario. */
function originLabel(field) {
  return ['company', 'assessment'].includes(field.origin) ? t(`eunomia.templates.origin.${field.origin}`) : ''
}

function routeOf(field) {
  return sourceRoute(field, data.value.template.framework)
}

/** Guarda solo lo que el usuario escribió o cambió. */
async function save() {
  saving.value = true
  const result = await store.saveTemplateDraft(route.params.template, valuesToSave(data.value.fields, edited))
  saving.value = false
  if (!result.ok) { toast.show(result.message, 'error'); return }
  adopt(result.data)
  toast.show(t('eunomia.templates.saved'), 'success')
}

onMounted(async () => {
  const result = await store.loadTemplateDraft(route.params.template)
  loading.value = false
  if (!result.ok) { error.value = result.message || ''; return }
  adopt(result.data)
})
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 760px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.sub { color: var(--text-muted); margin-top: 0.4rem; font-size: var(--fs-md); }
.meta, .help, .origin { color: var(--text-muted); font-size: var(--fs-body); }
.form { display: flex; flex-direction: column; gap: 1.1rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field label { color: var(--text); font-size: var(--fs-md); font-weight: 600; }
.req { color: var(--danger); }
.field input, .field textarea { background: var(--surface); border: 1px solid var(--border-solid); border-radius: 6px; padding: 0.6rem 0.7rem; color: var(--text); font-size: var(--fs-md); font-family: inherit; }
.origin { color: var(--accent); }
.link { color: var(--accent); text-decoration: underline; margin-left: 0.4rem; }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.actions { display: flex; gap: 0.6rem; }
.btn { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px; border: 1px solid var(--border-med); color: var(--text-dim); transition: all var(--transition); }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
