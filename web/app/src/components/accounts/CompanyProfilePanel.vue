<template>
  <section class="company-profile">
    <h2>{{ t('companyProfile.title') }}</h2>
    <p class="cp-desc">{{ t('companyProfile.desc') }}</p>

    <OrganizationManagedNotice :ownership="ownership" />

    <p v-if="loading" class="cp-desc">{{ t('common.loading') }}</p>

    <form v-else class="cp-form" @submit.prevent="save">
      <div class="cp-grid">
        <div v-for="field in TEXT_FIELDS" :key="field.key" class="cp-field" :class="{ 'cp-field--wide': field.wide }">
          <label :for="`cp-${field.key}`">{{ t(`companyProfile.fields.${field.key}`) }}</label>
          <input
            :id="`cp-${field.key}`"
            v-model="form[field.key]"
            :type="field.type || 'text'"
            :maxlength="field.max"
            :disabled="!canEdit"
            class="cp-input"
          />
        </div>

        <div class="cp-field">
          <label for="cp-companySize">{{ t('companyProfile.fields.companySize') }}</label>
          <select id="cp-companySize" v-model="form.companySize" :disabled="!canEdit" class="cp-input">
            <option value="">—</option>
            <option v-for="size in SIZES" :key="size" :value="size">{{ t(`companyProfile.sizes.${size}`) }}</option>
          </select>
        </div>

        <div class="cp-field">
          <label for="cp-workModel">{{ t('companyProfile.fields.workModel') }}</label>
          <select id="cp-workModel" v-model="form.workModel" :disabled="!canEdit" class="cp-input">
            <option value="">—</option>
            <option v-for="model in WORK_MODELS" :key="model" :value="model">{{ t(`companyProfile.workModels.${model}`) }}</option>
          </select>
        </div>

        <div class="cp-field cp-field--wide cp-logo">
          <span class="cp-label">{{ t('companyProfile.fields.brandLogo') }}</span>
          <img v-if="form.brandLogo" :src="form.brandLogo" :alt="t('whiteLabel.logoAlt')" class="cp-logo-preview" />
          <div v-if="canEdit" class="cp-logo-actions">
            <label class="cp-logo-file">
              <input type="file" accept="image/png,image/jpeg,image/gif" @change="onLogoFile" />
              <span>{{ form.brandLogo ? t('whiteLabel.changeImage') : t('whiteLabel.addImage') }}</span>
            </label>
            <button v-if="form.brandLogo" type="button" class="cp-logo-remove" @click="form.brandLogo = ''">
              {{ t('whiteLabel.removeLogo') }}
            </button>
          </div>
          <p v-if="logoError" class="cp-logo-error">{{ logoError }}</p>
          <p v-else-if="canEdit" class="cp-desc">{{ t('whiteLabel.logoFormats', { maxKb: LOGO_MAX_KB }) }}</p>
        </div>

        <div class="cp-field">
          <label for="cp-employeeCount">{{ t('companyProfile.fields.employeeCount') }}</label>
          <input
            id="cp-employeeCount"
            v-model.number="form.employeeCount"
            type="number"
            min="0"
            :disabled="!canEdit"
            class="cp-input"
          />
        </div>
      </div>

      <button v-if="canEdit" type="submit" class="cp-save" :disabled="saving">
        {{ saving ? t('companyProfile.saving') : t('companyProfile.save') }}
      </button>
    </form>
  </section>
</template>

<script setup>
/**
 * Los datos de identidad y de descripción de la empresa de la cuenta.
 *
 * Se guardan una vez y los usan el cumplimiento normativo, Aegis y los
 * documentos. Un miembro de una organización ve los de su dueño y no puede
 * editarlos: la API se lo impide y el formulario sale en solo lectura.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import OrganizationManagedNotice from '@/components/accounts/OrganizationManagedNotice.vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const { apiFetch, apiError } = useApi()
const toast = useToastStore()

/** Campos de texto, en el orden en que se enseñan. `wide` ocupa la fila entera. */
const TEXT_FIELDS = [
  { key: 'legalName', max: 255, wide: true },
  { key: 'taxId', max: 32 },
  { key: 'country', max: 2 },
  { key: 'addressLine', max: 255, wide: true },
  { key: 'postalCode', max: 16 },
  { key: 'city', max: 128 },
  { key: 'province', max: 128 },
  { key: 'sector', max: 128 },
  { key: 'jurisdiction', max: 128 },
  { key: 'securityContact', max: 128, type: 'email', wide: true },
]
const SIZES = ['micro', 'pequeña', 'mediana']
const WORK_MODELS = ['remoto', 'híbrido', 'presencial']

const form = reactive({
  legalName: '', taxId: '', addressLine: '', postalCode: '', city: '', province: '', country: '',
  sector: '', companySize: '', employeeCount: null, jurisdiction: '', workModel: '', securityContact: '', brandLogo: '',
})
// Mismos límites que valida el servidor; aquí solo evitan un viaje que iba a fallar.
const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/gif']
const LOGO_MAX_KB = 200
const logoError = ref('')

const ownership = ref({ isOwnData: true })
const loading = ref(true)
const saving = ref(false)

/** Solo quien es dueño de estos datos puede editarlos. */
const canEdit = computed(() => ownership.value.isOwnData === true)

/**
 * Vuelca en el formulario lo que devuelve la API.
 *
 * @param {object} payload - Respuesta de `/organizations/company-profile`.
 */
function apply(payload) {
  for (const key of Object.keys(form)) form[key] = payload[key] ?? form[key]
  ownership.value = payload.ownership ?? { isOwnData: true }
}

/**
 * Lee el logo elegido como data URI, que es como lo guarda la API.
 *
 * @param {Event} event - `change` del `<input type="file">`.
 */
function onLogoFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  logoError.value = ''
  if (!LOGO_TYPES.includes(file.type)) {
    logoError.value = t('whiteLabel.unsupportedFormat')
    return
  }
  if (file.size > LOGO_MAX_KB * 1024) {
    logoError.value = t('whiteLabel.tooLarge', { sizeKb: Math.round(file.size / 1024), maxKb: LOGO_MAX_KB })
    return
  }
  const reader = new FileReader()
  reader.onerror = () => { logoError.value = t('whiteLabel.unreadable') }
  reader.onload = () => { form.brandLogo = String(reader.result || '') }
  reader.readAsDataURL(file)
}

/** Carga el perfil que ve el usuario (el suyo o el del dueño de su organización). */
async function load() {
  loading.value = true
  try {
    const res = await apiFetch('/organizations/company-profile')
    if (res.ok) apply(await res.json())
    else toast.show(await apiError(res, t('companyProfile.loadFailed')), 'error')
  } finally {
    loading.value = false
  }
}

/** Guarda el formulario; la API rechaza con 403 a un miembro y con 400 un NIF inválido. */
async function save() {
  saving.value = true
  try {
    const res = await apiFetch('/organizations/company-profile', {
      method: 'PUT',
      body: JSON.stringify(form),
    })
    if (res.ok) {
      apply(await res.json())
      toast.show(t('companyProfile.saved'), 'success')
    } else {
      toast.show(await apiError(res, t('companyProfile.saveFailed')), 'error')
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.company-profile h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.cp-desc { font-size: var(--fs-md); color: var(--text-muted); margin-top: 0.5rem; max-width: 62ch; }
.cp-form { margin-top: 1.2rem; display: flex; flex-direction: column; gap: 1.2rem; }
.cp-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.9rem; }
.cp-field { display: flex; flex-direction: column; gap: 0.35rem; }
.cp-field--wide { grid-column: 1 / -1; }
.cp-field label { font-size: var(--fs-body); color: var(--text-dim); }
.cp-input {
  padding: 0.6rem 0.8rem; border-radius: 6px;
  background: var(--bg); color: var(--text); border: 1px solid var(--border-med);
}
.cp-input:focus { outline: none; border-color: var(--accent); }
.cp-input:disabled { opacity: 0.75; cursor: not-allowed; }
.cp-save {
  align-self: flex-start;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.6rem 1.2rem; border-radius: 3px;
  background: var(--accent-dim); border: 1px solid var(--accent); color: var(--accent-bright);
  transition: all var(--transition);
}
.cp-save:hover { background: var(--accent); color: var(--on-accent); }
.cp-save:disabled { opacity: 0.6; cursor: not-allowed; }
.cp-label { font-size: var(--fs-body); color: var(--text-dim); }
.cp-logo-preview { max-height: 64px; max-width: 220px; object-fit: contain; align-self: flex-start; }
.cp-logo-actions { display: flex; gap: 0.8rem; align-items: center; }
.cp-logo-file { cursor: pointer; color: var(--accent); text-decoration: underline; font-size: var(--fs-body); }
.cp-logo-file input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.cp-logo-remove { color: var(--text-muted); font-size: var(--fs-body); }
.cp-logo-remove:hover { color: var(--danger); }
.cp-logo-error { color: var(--danger); font-size: var(--fs-body); }
@media (max-width: 640px) { .cp-grid { grid-template-columns: 1fr; } }
</style>
