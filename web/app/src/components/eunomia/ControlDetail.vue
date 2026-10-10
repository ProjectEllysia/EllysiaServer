<template>
  <article class="detail" :aria-labelledby="`detail-title-${node.code}`">
    <header>
      <p class="code">{{ node.identifier }}</p>
      <h2 :id="`detail-title-${node.code}`">{{ node.title }}</h2>
      <p v-if="node.source" class="source">{{ node.source }}</p>
    </header>

    <p v-if="node.description" class="description">{{ node.description }}</p>

    <section v-if="node.actions.length">
      <h3>{{ t('eunomia.tree.actions') }}</h3>
      <ul><li v-for="action in node.actions" :key="action">{{ action }}</li></ul>
    </section>

    <section v-if="node.evidence.length">
      <h3>{{ t('eunomia.tree.evidence') }}</h3>
      <ul class="checklist"><li v-for="item in node.evidence" :key="item">{{ item }}</li></ul>
    </section>

    <details v-if="node.officialText" class="official">
      <summary>{{ t('eunomia.tree.officialText') }}</summary>
      <p>{{ node.officialText }}</p>
    </details>

    <form v-if="node.assessment" class="assessment" @submit.prevent="save">
      <h3>{{ t('eunomia.tree.assessment') }}</h3>

      <div class="field">
        <label :for="`status-${node.code}`">{{ t('eunomia.tree.status') }}</label>
        <select :id="`status-${node.code}`" v-model="form.status" :disabled="!canEdit">
          <option v-for="status in STATUSES" :key="status" :value="status">{{ t(`eunomia.status.${status}`) }}</option>
        </select>
      </div>

      <div v-if="form.status === 'not_applicable'" class="field">
        <label :for="`just-${node.code}`">{{ t('eunomia.tree.justification') }}</label>
        <textarea :id="`just-${node.code}`" v-model="form.justification" rows="3" maxlength="4000" required :disabled="!canEdit"></textarea>
      </div>

      <div class="field">
        <label :for="`notes-${node.code}`">{{ t('eunomia.tree.notes') }}</label>
        <textarea :id="`notes-${node.code}`" v-model="form.notes" rows="3" maxlength="8000" :disabled="!canEdit"></textarea>
      </div>

      <div class="row">
        <div class="field">
          <label :for="`resp-${node.code}`">{{ t('eunomia.tree.responsible') }}</label>
          <select :id="`resp-${node.code}`" v-model="form.responsibleUserId" :disabled="!canEdit">
            <option :value="null">—</option>
            <option v-for="person in people" :key="person.userId" :value="person.userId">{{ person.name }}</option>
          </select>
        </div>
        <div class="field">
          <label :for="`due-${node.code}`">{{ t('eunomia.tree.dueDate') }}</label>
          <input :id="`due-${node.code}`" v-model="form.dueDate" type="date" :disabled="!canEdit" />
        </div>
      </div>

      <p v-if="node.assessment.updatedAt" class="updated">
        {{ t('eunomia.tree.updatedBy', { name: node.assessment.updatedByName || '—', date: formatDateTime(node.assessment.updatedAt) }) }}
      </p>

      <p v-if="conflict" class="conflict" role="alert">
        {{ t('eunomia.tree.conflict') }}
        <button type="button" class="link-btn" @click="takeCurrent">{{ t('eunomia.tree.useCurrent') }}</button>
      </p>

      <button v-if="canEdit" type="submit" class="btn btn--primary" :disabled="saving">
        {{ saving ? t('common.saving') : t('eunomia.tree.save') }}
      </button>
    </form>

    <section v-if="node.assessment" class="history" :aria-label="t('eunomia.tree.history')">
      <h3>{{ t('eunomia.tree.history') }}</h3>
      <p v-if="!history.length" class="updated">{{ t('eunomia.tree.noHistory') }}</p>
      <ol v-else class="events">
        <li v-for="(event, index) in history" :key="index">
          <p class="event-head">
            <strong>{{ event.actorName || t('eunomia.tree.formerMember') }}</strong>
            · {{ formatDateTime(event.occurredAt) }}
          </p>
          <ul class="changes">
            <li v-for="line in changeLines(event.changes)" :key="line.field">
              <span class="field-name">{{ line.field }}:</span>
              <span class="from">{{ line.from }}</span> → <span class="to">{{ line.to }}</span>
            </li>
          </ul>
        </li>
      </ol>
    </section>
  </article>
</template>

<script setup>
/**
 * Detalle de un control: qué pide, qué hay que hacer, qué hay que guardar como prueba y su
 * evaluación. Dueño y miembros editan lo mismo; si alguien cambia el control mientras se
 * edita, el guardado devuelve un conflicto y se ofrece tomar el valor actual.
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { STATUSES } from '@/components/eunomia/tree'
import { formatDateTime } from '@/i18n/format'

const props = defineProps({
  node: { type: Object, required: true },
  people: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: true },
  saving: { type: Boolean, default: false },
  /** La evaluación actual si el último guardado dio conflicto; si no, `null`. */
  conflict: { type: Object, default: null },
  /** Cambios del control, del más reciente al más antiguo. */
  history: { type: Array, default: () => [] },
})
const emit = defineEmits(['save', 'take-current'])
const { t } = useI18n()

const form = ref(fromAssessment(props.node.assessment))

/** Pasa una evaluación al estado del formulario. */
function fromAssessment(assessment) {
  return {
    status: assessment?.status ?? 'pending',
    justification: assessment?.justification ?? '',
    notes: assessment?.notes ?? '',
    responsibleUserId: assessment?.responsibleUserId ?? null,
    dueDate: assessment?.dueDate ?? '',
  }
}

watch(() => [props.node.code, props.node.assessment?.updatedAt], () => {
  form.value = fromAssessment(props.node.assessment)
})

/** Envía el formulario con el testigo de concurrencia que vio el cliente. */
function save() {
  emit('save', {
    status: form.value.status,
    justification: form.value.justification,
    notes: form.value.notes,
    responsibleUserId: form.value.responsibleUserId,
    dueDate: form.value.dueDate || null,
    updatedAt: props.node.assessment?.updatedAt ?? null,
  })
}

/**
 * Un valor de un cambio, legible: el estado con su rótulo y lo vacío como un guion.
 *
 * @param {string} field - Campo que cambió.
 * @param {*} value - Valor anterior o nuevo.
 * @returns {string}
 */
function shown(field, value) {
  if (value === null || value === undefined || value === '') return '—'
  if (field === 'status') return t(`eunomia.status.${value}`)
  return String(value)
}

/**
 * Las líneas de un evento del historial.
 *
 * @param {object} changes - `{campo: {from, to}}`.
 * @returns {Array<{field: string, from: string, to: string}>}
 */
function changeLines(changes) {
  return Object.entries(changes || {}).map(([field, change]) => ({
    field: t(`eunomia.tree.fields.${field}`),
    from: shown(field, change.from),
    to: shown(field, change.to),
  }))
}

/** Descarta lo editado y toma el valor que dejó la otra persona. */
function takeCurrent() {
  emit('take-current')
}
</script>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 1rem; }
.code { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); color: var(--text-muted); }
h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
h3 { font-size: var(--fs-md); font-weight: 600; color: var(--text); margin-bottom: 0.4rem; }
.source { font-size: var(--fs-sm); color: var(--text-muted); }
.description { color: var(--text-dim); font-size: var(--fs-md); }
ul { padding-inline-start: 1.2rem; color: var(--text-dim); font-size: var(--fs-md); display: flex; flex-direction: column; gap: 0.3rem; }
.official summary { cursor: pointer; color: var(--accent); font-size: var(--fs-md); }
.official p { margin-top: 0.6rem; white-space: pre-line; color: var(--text-dim); font-size: var(--fs-body); }
.assessment { display: flex; flex-direction: column; gap: 0.8rem; padding-top: 1rem; border-top: 1px solid var(--border); }
.field { display: flex; flex-direction: column; gap: 0.3rem; flex: 1; }
.field label { font-size: var(--fs-body); color: var(--text-dim); }
.field select, .field textarea, .field input {
  padding: 0.5rem 0.7rem; border-radius: 6px; background: var(--bg); color: var(--text);
  border: 1px solid var(--border-med); font-family: inherit;
}
.row { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.history { padding-top: 1rem; border-top: 1px solid var(--border); }
.events { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.event-head { font-size: var(--fs-body); color: var(--text-dim); }
.changes { list-style: none; padding: 0; font-size: var(--fs-body); }
.field-name { color: var(--text-muted); margin-right: 0.35rem; }
.from { text-decoration: line-through; color: var(--text-muted); }
.updated { font-size: var(--fs-sm); color: var(--text-muted); }
.conflict { color: var(--danger); font-size: var(--fs-body); }
.link-btn { color: var(--accent); text-decoration: underline; margin-left: 0.5rem; }
.btn {
  align-self: flex-start; font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body);
  font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px;
  background: var(--accent-dim); border: 1px solid var(--accent); color: var(--accent-bright);
}
.btn:hover { background: var(--accent); color: var(--on-accent); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
