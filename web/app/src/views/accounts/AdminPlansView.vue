<template>
  <div class="admin-page">
    <StarBackground />
    <Topbar :title="t('adminPlans.topbar')" backTo="/" />

    <main class="main">
      <p class="intro">{{ t('adminPlans.intro') }}</p>

      <section class="section">
        <div class="section-head">
          <h2>{{ t('adminPlans.catalog') }}</h2>
          <button class="btn btn--primary" @click="startCreate">{{ t('adminPlans.newPlan') }}</button>
        </div>

        <!-- Sin esto la tabla se quedaba vacía y en silencio, que es la peor
             respuesta posible: no distinguía "no hay planes" de "falló". -->
        <p v-if="loadError" class="state state--error">
          {{ loadError }}
        </p>
        <p v-else-if="loaded && !plans.length" class="state">
          {{ t('adminPlans.emptyCatalog') }}
          <code>{{ MIGRATE_COMMAND }}</code>
        </p>

        <table v-else-if="plans.length" class="table">
          <thead>
            <tr><th>{{ t('adminPlans.code') }}</th><th>{{ t('adminPlans.name') }}</th><th>{{ t('adminPlans.price') }}</th><th>{{ t('adminPlans.rank') }}</th><th>{{ t('organization.status') }}</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id" :class="{ 'row--active': plan.id === selectedId }">
              <td class="mono">{{ plan.code }}</td>
              <td>{{ plan.name }}</td>
              <td class="mono">{{ euros(plan.monthlyPriceCents) }}</td>
              <td class="mono">{{ plan.rank }}</td>
              <td>
                <span v-if="plan.isDefault" class="tag tag--default">{{ t('adminPlans.default') }}</span>
                <span v-if="!plan.isPublic" class="tag">{{ t('adminPlans.hidden') }}</span>
              </td>
              <td class="td-actions">
                <button class="btn-link" @click="startEdit(plan)">{{ t('common.edit') }}</button>
                <button class="btn-link" @click="select(plan)">{{ t('adminPlans.limits') }}</button>
                <button v-if="!plan.isDefault" class="btn-link" @click="makeDefault(plan)">
                  {{ t('adminPlans.makeDefault') }}
                </button>
                <button v-if="!plan.isDefault" class="btn-link btn-link--danger" @click="remove(plan)">
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Alta y edición de un plan: el mismo formulario -->
      <section v-if="editing" class="section">
        <h2>{{ editingId ? t('adminPlans.editTitle', { name: draft.name }) : t('adminPlans.newPlan') }}</h2>
        <p v-if="editingId" class="section-desc">{{ t('adminPlans.editDesc') }}</p>
        <p v-else class="section-desc">{{ t('adminPlans.createDesc') }}</p>
        <form class="grid-form" @submit.prevent="save">
          <div class="form-group">
            <label>{{ t('adminPlans.code') }}</label>
            <input v-model="draft.code" class="inp" required minlength="2" :disabled="!!editingId" />
          </div>
          <div class="form-group"><label>{{ t('adminPlans.name') }}</label><input v-model="draft.name" class="inp" required minlength="2" /></div>
          <div class="form-group form-group--wide"><label>{{ t('adminPlans.tagline') }}</label><input v-model="draft.tagline" class="inp" /></div>
          <div class="form-group"><label>{{ t('adminPlans.priceCents') }}</label><input v-model.number="draft.monthlyPriceCents" type="number" min="0" class="inp" /></div>
          <div class="form-group"><label>{{ t('adminPlans.orgAddon') }}</label><input v-model.number="draft.orgAddonPriceCents" type="number" min="0" class="inp" /></div>
          <div class="form-group"><label>{{ t('adminPlans.rank') }}</label><input v-model.number="draft.rank" type="number" class="inp" /></div>
          <div class="form-group">
            <label for="plan-public">{{ t('adminPlans.visibility') }}</label>
            <select id="plan-public" v-model="draft.isPublic" class="inp">
              <option :value="true">{{ t('adminPlans.public') }}</option>
              <option :value="false">{{ t('adminPlans.private') }}</option>
            </select>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" @click="editing = false">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn btn--primary" :disabled="savingPlan">
              {{ savingPlan ? t('common.saving') : (editingId ? t('profilePage.saveChanges') : t('adminPlans.create')) }}
            </button>
          </div>
        </form>
      </section>

      <!-- Asignar un plan a una cuenta -->
      <section class="section">
        <h2>{{ t('adminPlans.subscriptions') }}</h2>
        <p class="section-desc">{{ t('adminPlans.subscriptionsDesc') }}</p>

        <div class="sub-picker">
          <div class="form-group">
            <label for="sub-user">{{ t('adminPlans.account') }}</label>
            <select id="sub-user" v-model.number="subUserId" class="inp" @change="loadSubscription">
              <option :value="null">{{ t('adminPlans.chooseAccount') }}</option>
              <option v-for="user in users" :key="user.id" :value="user.id">
                {{ user.username }} — {{ user.email }}
              </option>
            </select>
          </div>
        </div>

        <template v-if="subUserId">
          <p class="sub-current">
            <template v-if="subscription">
              {{ t('adminPlans.now') }} <strong>{{ planName(subscription.planId) }}</strong> ·
              {{ subscriptionStatus(subscription.status) }}
              <span v-if="subscription.organizationEnabled"> · {{ t('adminPlans.withOrganization') }}</span>
              <span v-if="subscription.currentPeriodEnd">
                · {{ t('adminPlans.until', { date: shortDate(subscription.currentPeriodEnd) }) }}
              </span>
            </template>
            <template v-else>
              {{ t('adminPlans.noSubscription') }}
            </template>
          </p>

          <div class="sub-form">
            <div class="form-group">
              <label for="sub-op">{{ t('adminPlans.operation') }}</label>
              <select id="sub-op" v-model="operation" class="inp">
                <option v-for="op in OPERATIONS" :key="op" :value="op">{{ t(`adminPlans.operations.${op}`) }}</option>
              </select>
            </div>

            <div v-if="needsPlan" class="form-group">
              <label for="sub-plan">{{ t('adminPlans.plan') }}</label>
              <select id="sub-plan" v-model="opPlanCode" class="inp">
                <option v-for="plan in plans" :key="plan.code" :value="plan.code">
                  {{ plan.name }}
                </option>
              </select>
            </div>

            <div v-if="needsPeriodEnd" class="form-group">
              <label for="sub-end">{{ operation === 'start_trial' ? t('adminPlans.trialEnds') : t('adminPlans.validUntil') }}</label>
              <input id="sub-end" v-model="opPeriodEnd" type="date" class="inp" />
            </div>

            <div v-if="operation === 'mark_past_due'" class="form-group">
              <label for="sub-grace">{{ t('adminPlans.graceUntil') }}</label>
              <input id="sub-grace" v-model="opGraceUntil" type="date" class="inp" />
            </div>

            <div v-if="operation === 'activate'" class="form-group">
              <label for="sub-org">{{ t('adminPlans.organization') }}</label>
              <select id="sub-org" v-model="opOrgEnabled" class="inp">
                <option :value="false">{{ t('adminPlans.noOrganization') }}</option>
                <option :value="true">{{ t('adminPlans.canManageOrganization') }}</option>
              </select>
            </div>

            <div v-if="operation === 'cancel'" class="form-group">
              <label for="sub-immediate">{{ t('adminPlans.when') }}</label>
              <select id="sub-immediate" v-model="opImmediate" class="inp">
                <option :value="false">{{ t('adminPlans.atPeriodEnd') }}</option>
                <option :value="true">{{ t('adminPlans.immediately') }}</option>
              </select>
            </div>

            <div class="form-actions">
              <button class="btn btn--primary" :disabled="applying" @click="applyOperation">
                {{ applying ? t('adminPlans.applying') : t('common.apply') }}
              </button>
            </div>
          </div>
        </template>
      </section>

      <!-- Topes del plan seleccionado -->
      <section v-if="selected" class="section">
        <div class="section-head">
          <h2>{{ t('adminPlans.limitsOf', { name: selected.name }) }}</h2>
          <button class="btn btn--primary" @click="saveLimits" :disabled="saving">
            {{ saving ? t('common.saving') : t('adminPlans.saveLimits') }}
          </button>
        </div>
        <i18n-t keypath="adminPlans.limitsDesc" tag="p" class="section-desc">
          <template #unlimited><strong>{{ t('adminPlans.unlimitedWord') }}</strong></template>
          <template #zero><strong>0</strong></template>
        </i18n-t>

        <table class="table">
          <thead>
            <tr><th>{{ t('adminPlans.key') }}</th><th>{{ t('adminPlans.period') }}</th><th>{{ t('adminPlans.holder') }}</th><th>{{ t('organization.member') }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="key in limitKeys" :key="key.key">
              <td class="mono">{{ key.key }}</td>
              <td class="mono muted">{{ periodLabel(key.period) }}</td>
              <td><input v-model="holder[key.key]" type="number" min="0" class="inp inp--num" placeholder="∞" /></td>
              <td><input v-model="member[key.key]" type="number" min="0" class="inp inp--num" placeholder="∞" /></td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>

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
/**
 * Gestor del catálogo, solo para root.
 *
 * Las claves llegan del servidor (`GET /plans/limit-keys`) y se pintan como
 * filas fijas en vez de dejar escribirlas: una errata crearía una fila que
 * nadie consulta y dejaría la característica desactivada en silencio.
 *
 * El periodo tampoco se edita — lo dicta el catálogo de claves. Si lo eligiera
 * quien rellena, un contador mensual podría acabar declarado como existencias y
 * no reiniciarse nunca.
 */
import { ref, computed, onMounted } from 'vue'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { formatDate, formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch, apiError } = useApi()
const toast = useToastStore()

/** Orden que siembra el catálogo de planes en una base de datos recién desplegada. */
const MIGRATE_COMMAND = 'cd API && alembic upgrade head'

/** Periodos de una clave de límite con rótulo en `adminPlans.periods`. */
const PERIODS = ['month', 'day', 'stock', 'tier']

/** Rótulo de un periodo; uno que el servidor añada cae en «Desconocido». */
function periodLabel(period) {
  return PERIODS.includes(period) ? t(`adminPlans.periods.${period}`) : t('common.unknown')
}

/** Operaciones del ciclo de vida de una suscripción, en el orden del desplegable. */
const OPERATIONS = ['activate', 'start_trial', 'mark_past_due', 'resume', 'cancel', 'expire']

const plans = ref([])
const limitKeys = ref([])
const loadError = ref('')
const loaded = ref(false)
const selected = ref(null)
const selectedId = ref(null)
const holder = ref({})
const member = ref({})
const editing = ref(false)
/** `null` = alta; un id = edición. Distingue POST /plans de PUT /plans/<id>. */
const editingId = ref(null)
const savingPlan = ref(false)
const saving = ref(false)
const draft = ref(emptyDraft())
const confirm = ref({ open: false, title: '', message: '', action: () => {} })

/* ── Suscripciones ── */
/** Estados de suscripción con rótulo en `adminPlans.statuses`. */
const STATUSES = ['active', 'trialing', 'past_due', 'canceled']

/** Rótulo de un estado de suscripción; uno nuevo cae en «Desconocido». */
function subscriptionStatus(status) {
  return STATUSES.includes(status) ? t(`adminPlans.statuses.${status}`) : t('common.unknown')
}
const users = ref([])
const subUserId = ref(null)
const subscription = ref(null)
const operation = ref('activate')
const opPlanCode = ref('')
const opPeriodEnd = ref('')
const opGraceUntil = ref('')
const opOrgEnabled = ref(false)
const opImmediate = ref(false)
const applying = ref(false)

const needsPlan = computed(() => ['activate', 'start_trial'].includes(operation.value))
const needsPeriodEnd = computed(() => ['activate', 'start_trial'].includes(operation.value))

function planName(planId) {
  return plans.value.find((plan) => plan.id === planId)?.name ?? `#${planId}`
}

function shortDate(iso) {
  return formatDate(iso)
}

async function loadUsers() {
  const res = await apiFetch('/users')
  if (res?.ok) users.value = await res.json()
}

/** Sin suscripción llega `null`, y es un estado normal: la cuenta está en el
 *  plan por defecto. */
async function loadSubscription() {
  subscription.value = null
  if (!subUserId.value) return
  const res = await apiFetch(`/plans/subscriptions/${subUserId.value}`)
  if (res?.ok) subscription.value = (await res.json()).subscription ?? null
}

async function applyOperation() {
  applying.value = true
  try {
    const body = { operation: operation.value }
    if (needsPlan.value) body.planCode = opPlanCode.value || plans.value[0]?.code
    // El backend espera ISO-8601; <input type="date"> da 'YYYY-MM-DD'.
    if (needsPeriodEnd.value && opPeriodEnd.value) body.periodEnd = `${opPeriodEnd.value}T00:00:00`
    if (operation.value === 'mark_past_due' && opGraceUntil.value) {
      body.graceUntil = `${opGraceUntil.value}T00:00:00`
    }
    if (operation.value === 'activate') body.organizationEnabled = opOrgEnabled.value
    if (operation.value === 'cancel') body.immediate = opImmediate.value

    const res = await apiFetch(`/plans/subscriptions/${subUserId.value}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, t('adminPlans.toast.operationFailed')), 'error')
      return
    }
    subscription.value = await res.json()
    toast.show(t('adminPlans.toast.subscriptionUpdated'), 'success')
  } finally {
    applying.value = false
  }
}

function emptyDraft() {
  return {
    code: '', name: '', tagline: '',
    monthlyPriceCents: 0, orgAddonPriceCents: 0, rank: 0, isPublic: true,
  }
}

function euros(cents) {
  return formatNumber(cents / 100, { style: 'currency', currency: 'EUR' })
}

/**
 * El catálogo COMPLETO, no el público: /plans filtra por isPublic y un gestor
 * que no enseña los planes ocultos no deja gestionarlos.
 */
async function loadPlans() {
  loadError.value = ''
  const res = await apiFetch('/plans/all')
  if (!res?.ok) {
    loadError.value = await apiError(res, t('adminPlans.toast.catalogFailed'))
    return
  }
  plans.value = (await res.json()).plans ?? []
}

async function loadKeys() {
  const res = await apiFetch('/plans/limit-keys')
  if (!res?.ok) {
    limitKeys.value = []
    toast.show(await apiError(res, t('adminPlans.toast.keysFailed')), 'error')
    return
  }
  limitKeys.value = (await res.json()).keys ?? []
}

function select(plan) {
  selected.value = plan
  selectedId.value = plan.id
  holder.value = toForm(plan.limits?.holder)
  member.value = toForm(plan.limits?.member)
}

/**
 * Los topes de un ámbito, como formulario. Se rellenan **todas** las claves
 * del catálogo, no solo las que el plan declara.
 *
 * Una clave que el plan no declara vale `0` (no incluido), y antes se pintaba
 * como casilla vacía — que en esta tabla significa lo contrario, ilimitado. En
 * una pantalla que fija lo que cobra cada plan, esa casilla decía justo lo
 * opuesto de lo que el servidor iba a aplicar.
 */
function toForm(limits) {
  const form = {}
  for (const { key } of limitKeys.value) {
    const entry = limits?.[key]
    if (!entry) form[key] = 0                        // no declarada = no incluida
    else form[key] = entry.value === null ? '' : entry.value
  }
  return form
}

function startCreate() {
  draft.value = emptyDraft()
  editingId.value = null
  editing.value = true
}

function startEdit(plan) {
  draft.value = {
    code: plan.code,
    name: plan.name,
    tagline: plan.tagline ?? '',
    monthlyPriceCents: plan.monthlyPriceCents,
    orgAddonPriceCents: plan.orgAddonPriceCents,
    rank: plan.rank,
    isPublic: plan.isPublic,
  }
  editingId.value = plan.id
  editing.value = true
}

/**
 * Alta y edición por la misma puerta.
 *
 * En la edición no viaja `code`: el servidor lo rechaza a propósito
 * (`PlanUpdateSchema` no lo declara) porque cambiarlo rompería las
 * asignaciones que lo nombran.
 */
async function save() {
  savingPlan.value = true
  try {
    const { code, ...withoutCode } = draft.value
    const [path, method, body] = editingId.value
      ? [`/plans/${editingId.value}`, 'PUT', withoutCode]
      : ['/plans', 'POST', draft.value]

    const res = await apiFetch(path, { method, body: JSON.stringify(body) })
    if (!res?.ok) {
      toast.show(await apiError(res, t('adminPlans.toast.planSaveFailed')), 'error')
      return
    }
    toast.show(editingId.value ? t('adminPlans.toast.planUpdated') : t('adminPlans.toast.planCreated'), 'success')
    editing.value = false
    await loadPlans()
    // El panel de topes puede estar enseñando el plan que se acaba de editar:
    // sin esto seguiría con el nombre y el precio viejos hasta recargar.
    if (selectedId.value) {
      const fresh = plans.value.find((plan) => plan.id === selectedId.value)
      if (fresh) select(fresh)
    }
  } finally {
    savingPlan.value = false
  }
}

async function saveLimits() {
  // Sin el catálogo de claves el formulario está vacío, y como el servidor
  // REEMPLAZA el conjunto entero, guardar aquí borraría todos los topes del
  // plan. Es el único sitio de esta pantalla que puede destruir datos.
  if (!limitKeys.value.length) {
    toast.show(t('adminPlans.toast.keysMissing'), 'error')
    return
  }

  saving.value = true
  try {
    const limits = [
      ...toPayload(holder.value, 'holder'),
      ...toPayload(member.value, 'member'),
    ]
    const res = await apiFetch(`/plans/${selected.value.id}/limits`, {
      method: 'PUT',
      body: JSON.stringify({ limits }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, t('adminPlans.toast.limitsFailed')), 'error')
      return
    }
    toast.show(t('adminPlans.toast.limitsSaved'), 'success')
    await loadPlans()
    select(plans.value.find((plan) => plan.id === selectedId.value) ?? selected.value)
  } finally {
    saving.value = false
  }
}

/**
 * Se mandan **todas** las claves, porque `PUT /plans/<id>/limits` reemplaza el
 * conjunto entero: lo que no viaje deja de existir. Como el formulario ya trae
 * las quince con su valor real (0 incluido), lo que se ve es exactamente lo
 * que queda guardado.
 */
function toPayload(form, scope) {
  return Object.entries(form).map(([limitKey, value]) => ({
    limitKey,
    scope,
    value: value === '' ? null : Number(value),
  }))
}

function makeDefault(plan) {
  confirm.value = {
    open: true,
    title: t('adminPlans.confirmDefault.title', { name: plan.name }),
    message: t('adminPlans.confirmDefault.message'),
    action: async () => {
      confirm.value.open = false
      const res = await apiFetch(`/plans/${plan.id}/default`, { method: 'PUT' })
      if (!res?.ok) {
        toast.show(await apiError(res, t('adminPlans.toast.defaultFailed')), 'error')
        return
      }
      await loadPlans()
    },
  }
}

function remove(plan) {
  confirm.value = {
    open: true,
    title: t('adminPlans.confirmDelete.title', { name: plan.name }),
    message: t('adminPlans.confirmDelete.message'),
    action: async () => {
      confirm.value.open = false
      const res = await apiFetch(`/plans/${plan.id}`, { method: 'DELETE' })
      if (!res?.ok) {
        toast.show(await apiError(res, t('adminPlans.toast.deleteFailed')), 'error')
        return
      }
      if (selectedId.value === plan.id) selected.value = null
      await loadPlans()
    },
  }
}

onMounted(async () => {
  await Promise.all([loadPlans(), loadKeys(), loadUsers()])
  loaded.value = true
})
</script>

<style scoped>
/* Ver la nota de MyPlanView: Topbar fija + StarBackground opaco en z-index 0. */
.admin-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.main { max-width: 1080px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.intro { color: var(--text-muted); font-size: var(--fs-md); max-width: 62ch; }

.section {
  background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 12px; padding: 1.5rem;
}
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.section h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.section-desc { font-size: var(--fs-body); color: var(--text-muted); margin-top: 0.5rem; max-width: 72ch; }

.table { width: 100%; border-collapse: collapse; margin-top: 1.2rem; font-size: var(--fs-md); }
.table th {
  text-align: left; padding: 0.5rem 0.6rem;
  font-size: var(--fs-body); font-weight: 500; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border);
}
.table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--border); color: var(--text-dim); }
.row--active { background: var(--accent-dim); }
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); }
.muted { color: var(--text-muted); }
.td-actions { font-size: var(--fs-body); text-align: right; display: flex; gap: 0.8rem; justify-content: flex-end; height: 48.78px; }

.tag {
  display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px;
  font-size: var(--fs-body); color: var(--text-muted);
  border: 1px solid var(--border-med); margin-right: 0.3rem;
}
.tag--default { color: var(--accent-bright); border-color: var(--accent); }

.state {
  margin-top: 1.2rem; padding: 1rem 1.1rem; border-radius: 8px;
  background: var(--bg); border: 1px solid var(--border-med);
  color: var(--text-muted); font-size: var(--fs-md); line-height: 1.6;
}
.state--error { border-color: var(--danger); color: var(--text); }
.state code {
  display: inline-block; margin-top: 0.4rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body);
  color: var(--accent-bright); background: var(--accent-dim);
  padding: 0.15rem 0.45rem; border-radius: 4px;
}

.grid-form {
  margin-top: 1.2rem; display: grid; gap: 0.9rem;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}
.form-group { display: flex; flex-direction: column; gap: 0.35rem; }
.form-group--wide { grid-column: 1 / -1; }
.form-group label { font-size: var(--fs-body); color: var(--text-dim); }
.form-actions { grid-column: 1 / -1; display: flex; gap: 0.7rem; justify-content: flex-end; }

.inp {
  padding: 0.5rem 0.7rem; border-radius: 6px;
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border-med);
  width: 100%;
}
.inp:focus { outline: none; border-color: var(--accent); }
.inp--num { max-width: 110px; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }

.btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.55rem 1.1rem; border-radius: 3px;
  border: 1px solid var(--border-med); color: var(--text-dim);
  transition: all var(--transition);
}
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-link { font-size: var(--fs-body); color: var(--text-muted); }
.btn-link:hover { color: var(--text); }
.btn-link--danger:hover { color: var(--danger); }
</style>
