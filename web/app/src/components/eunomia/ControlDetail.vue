<template>
  <article class="detail" :class="{ 'detail--flat': !node.assessment }" :aria-labelledby="`detail-title-${node.code}`">
    <header class="plate">
      <div class="plate-top">
        <p class="code">{{ node.identifier }}</p>
        <span v-if="status" class="status" :class="`status--${status}`">
          <span class="dot" aria-hidden="true"></span>{{ t(`eunomia.status.${status}`) }}
        </span>
      </div>
      <h2 :id="`detail-title-${node.code}`">{{ node.title }}</h2>
      <p v-if="node.source" class="source">{{ node.source }}</p>
      <p v-if="systemCategory && node.applicability" class="scope" :class="`scope--${node.applicability}`">
        {{ t(`eunomia.category.applicability.${node.applicability}`, { category: t(`eunomia.category.${systemCategory}`).toLowerCase() }) }}
      </p>
      <span class="meander" aria-hidden="true"></span>
    </header>

    <div v-if="node.assessment" class="tabs" role="tablist" :aria-label="t('eunomia.tree.tabs.label')" @keydown="onTabKeydown">
      <button
        v-for="item in tabs" :key="item.key" type="button" role="tab" class="tab"
        :id="`tab-${item.key}-${node.code}`" :aria-controls="`panel-${item.key}-${node.code}`"
        :aria-selected="current === item.key" :tabindex="current === item.key ? 0 : -1"
        :class="{ 'tab--on': current === item.key }" @click="tab = item.key"
      >
        <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path :d="item.icon" />
        </svg>
        <span class="tab-label">{{ t(`eunomia.tree.tabs.${item.key}`) }}</span>
        <span v-if="item.count" class="tab-count">{{ item.count }}</span>
      </button>
    </div>

    <div v-show="current === 'requirements'" class="panel" :role="node.assessment ? 'tabpanel' : undefined"
         :id="`panel-requirements-${node.code}`" :aria-labelledby="node.assessment ? `tab-requirements-${node.code}` : undefined">
      <p v-if="node.description" class="description">{{ node.description }}</p>

      <section v-if="annexRow" class="zone zone--quiet">
        <SectionInscription tag="h3">{{ t('eunomia.category.annexTitle') }}</SectionInscription>
        <dl class="annex">
          <template v-for="category in CATEGORIES" :key="category">
            <dt :class="{ 'annex--mine': category === systemCategory }">{{ t(`eunomia.category.${category}`) }}</dt>
            <dd :class="{ 'annex--mine': category === systemCategory }">{{ annexRow[category] }}</dd>
          </template>
        </dl>
      </section>

      <section v-if="node.actions.length" class="zone zone--do">
        <SectionInscription tag="h3">{{ t('eunomia.tree.actions') }}</SectionInscription>
        <ul class="marks"><li v-for="action in node.actions" :key="action">{{ action }}</li></ul>
      </section>

      <section v-if="node.evidence.length" class="zone zone--proof">
        <SectionInscription tag="h3">{{ t('eunomia.tree.evidence') }}</SectionInscription>
        <ul class="marks"><li v-for="item in node.evidence" :key="item">{{ item }}</li></ul>
      </section>

      <details v-if="node.officialText" class="zone zone--quiet official">
        <summary>{{ t('eunomia.tree.officialText') }}</summary>
        <p>{{ node.officialText }}</p>
      </details>
    </div>

    <template v-if="node.assessment">
      <div v-show="current === 'evidence'" class="panel" role="tabpanel"
           :id="`panel-evidence-${node.code}`" :aria-labelledby="`tab-evidence-${node.code}`">
        <div class="zone zone--given">
          <EvidencePanel :node="node" :framework="framework" :can-edit="canEdit" @changed="$emit('evidence-changed')" />
        </div>
        <div class="zone zone--auto">
          <AutomaticEvidencePanel :node="node" :framework="framework" />
        </div>
        <div class="zone zone--hint">
          <SuggestionsPanel :node="node" :framework="framework" :can-edit="canEdit" @changed="$emit('evidence-changed')" />
        </div>
      </div>

      <div v-show="current === 'assessment'" class="panel" role="tabpanel"
           :id="`panel-assessment-${node.code}`" :aria-labelledby="`tab-assessment-${node.code}`">
        <form class="zone zone--given assessment" @submit.prevent="save">
          <div class="field">
            <label :for="`status-${node.code}`">{{ t('eunomia.tree.status') }}</label>
            <select :id="`status-${node.code}`" v-model="form.status" :disabled="!canEdit">
              <option v-for="option in STATUSES" :key="option" :value="option">{{ t(`eunomia.status.${option}`) }}</option>
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

          <p v-if="conflict" class="conflict" role="alert">
            {{ t('eunomia.tree.conflict') }}
            <button type="button" class="link-btn" @click="takeCurrent">{{ t('eunomia.tree.useCurrent') }}</button>
          </p>

          <div class="foot">
            <p v-if="node.assessment.updatedAt" class="updated">
              {{ t('eunomia.tree.updatedBy', { name: node.assessment.updatedByName || '—', date: formatDateTime(node.assessment.updatedAt) }) }}
            </p>
            <button v-if="canEdit" type="submit" class="btn btn--primary" :disabled="saving">
              {{ saving ? t('common.saving') : t('eunomia.tree.save') }}
            </button>
          </div>
        </form>
      </div>

      <div v-show="current === 'history'" class="panel" role="tabpanel"
           :id="`panel-history-${node.code}`" :aria-labelledby="`tab-history-${node.code}`">
        <p v-if="!history.length" class="updated">{{ t('eunomia.tree.noHistory') }}</p>
        <ol v-else class="events">
          <li v-for="(event, index) in history" :key="index">
            <p class="event-head">
              <strong>{{ event.actorName || t('eunomia.tree.formerMember') }}</strong>
              <time class="event-date">{{ formatDateTime(event.occurredAt) }}</time>
            </p>
            <ul class="changes">
              <li v-for="line in changeLines(event.changes)" :key="line.field">
                <span class="field-name">{{ line.field }}</span>
                <span class="from">{{ line.from }}</span>
                <span class="arrow" aria-hidden="true">→</span>
                <span class="to">{{ line.to }}</span>
              </li>
            </ul>
          </li>
        </ol>
      </div>
    </template>
  </article>
</template>

<script setup>
import SectionInscription from '@/components/eunomia/SectionInscription.vue'
/**
 * Detalle de un control: qué pide, qué hay que hacer, qué hay que guardar como prueba y su
 * evaluación. Dueño y miembros editan lo mismo; si alguien cambia el control mientras se
 * edita, el guardado devuelve un conflicto y se ofrece tomar el valor actual.
 *
 * La cabecera y las pestañas quedan fijas y cada pestaña es una hoja con su propio scroll, de
 * modo que el panel no crece más que la pantalla (el tope lo pone la vista que lo aloja).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import EvidencePanel from '@/components/eunomia/EvidencePanel.vue'
import SuggestionsPanel from '@/components/eunomia/SuggestionsPanel.vue'
import AutomaticEvidencePanel from '@/components/eunomia/AutomaticEvidencePanel.vue'
import { STATUSES, statusOf } from '@/components/eunomia/tree'
import { formatDateTime } from '@/i18n/format'

const props = defineProps({
  node: { type: Object, required: true },
  /** Clave del marco al que pertenece el control. */
  framework: { type: String, required: true },
  people: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: true },
  saving: { type: Boolean, default: false },
  /** La evaluación actual si el último guardado dio conflicto; si no, `null`. */
  conflict: { type: Object, default: null },
  /** Cambios del control, del más reciente al más antiguo. */
  history: { type: Array, default: () => [] },
  /** Categoría del sistema de la adopción (`basic`, `medium`, `high`), o `null` si no hay. */
  systemCategory: { type: String, default: null },
})

/** Las categorías del anexo II del ENS, en su orden. */
const CATEGORIES = ['basic', 'medium', 'high']

/** La fila del anexo II de una medida del ENS (`{basic, medium, high}`), o `null` si no tiene. */
const annexRow = computed(() => props.node.metadata?.categories ?? null)
const emit = defineEmits(['save', 'take-current', 'evidence-changed'])
const { t } = useI18n()

const form = ref(fromAssessment(props.node.assessment))
const status = computed(() => statusOf(props.node))

const tab = ref('requirements')
/** Un control sin evaluación (un grupo) solo tiene requisitos. */
const current = computed(() => (props.node.assessment ? tab.value : 'requirements'))
/** Trazos de los iconos (rejilla de 24, sin relleno): lista, clip, check y reloj. */
const tabs = computed(() => [
  { key: 'requirements', count: 0, icon: 'M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01' },
  { key: 'evidence', count: props.node.linkedEvidence?.length ?? 0,
    icon: 'm21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48' },
  { key: 'assessment', count: 0, icon: 'M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3' },
  { key: 'history', count: props.history.length, icon: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM12 6v6l4 2' },
])

/** Flechas, inicio y fin mueven entre pestañas (patrón ARIA de pestañas). */
function onTabKeydown(event) {
  const keys = tabs.value.map((item) => item.key)
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
  let next = null
  if (step) next = keys[(keys.indexOf(current.value) + step + keys.length) % keys.length]
  else if (event.key === 'Home') next = keys[0]
  else if (event.key === 'End') next = keys[keys.length - 1]
  if (next === null) return
  event.preventDefault()
  tab.value = next
  event.currentTarget.querySelector(`#tab-${next}-${props.node.code}`)?.focus()
}

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
.detail { display: flex; flex-direction: column; min-height: 0; flex: 1; }

/* Cabecera: la placa del control, con una greca estática al pie (la del friso de los hubs,
   sin el brillo que la recorre allí) para separarla de las hojas. */
.plate { flex: none; display: flex; flex-direction: column; gap: 0.35rem; padding-bottom: 0.7rem; }
.plate-top { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; flex-wrap: wrap; }
.code {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); color: var(--accent-bright);
  padding: 0.1rem 0.55rem; border: 1px solid var(--accent); border-radius: 4px; background: var(--accent-dim);
}
.status { display: inline-flex; align-items: center; gap: 0.4rem; font-size: var(--fs-sm); color: var(--text-dim); }
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--text-muted); }
.status--implemented .dot { background: var(--success, #4caf7a); }
.status--in_progress .dot { background: var(--warning, #d4a04a); }
.status--not_applicable .dot { background: var(--border-med); }
h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); overflow-wrap: anywhere; }
.source { font-size: var(--fs-sm); color: var(--text-muted); }
.meander {
  display: block; height: 10px; margin-top: 0.4rem; background: var(--accent); opacity: 0.5;
  --meander: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='15' height='10' viewBox='0 0 24 16'%3E%3Cpath d='M0 15H24M3 15V3H21V11H9V7H15' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='square'/%3E%3C/svg%3E");
  -webkit-mask: var(--meander) repeat-x left center / 15px 10px;
  mask: var(--meander) repeat-x left center / 15px 10px;
}

/* Pestañas como solapas de carpeta: la activa se funde con su hoja. */
.tabs { flex: none; display: flex; gap: 0.25rem; padding-inline-start: 0.4rem; }
.tab {
  position: relative; z-index: 1; display: inline-flex; align-items: center; justify-content: center; gap: 0.45rem;
  flex: 1 1 0; min-width: 0; max-width: 11rem; margin-bottom: -1px; padding: 0.5rem 0.7rem;
  border: 1px solid transparent; border-bottom: 0; border-radius: 8px 8px 0 0;
  font-size: var(--fs-md); color: var(--text-muted);
  transition: color 0.2s ease, background-color 0.2s ease;
}
.tab:hover { color: var(--text); background: color-mix(in srgb, var(--surface-2) 55%, transparent); }
.tab--on, .tab--on:hover {
  color: var(--accent-bright); background: var(--surface-2); border-color: var(--border-med);
  box-shadow: inset 0 2px 0 var(--accent);
}
.tab:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: -2px; }
.tab-icon { width: 1.05rem; height: 1.05rem; flex: none; }
.tab-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tab-count {
  flex: none; min-width: 1.3rem; padding: 0 0.35rem; border-radius: 999px; text-align: center; line-height: 1.3rem;
  font-size: var(--fs-sm); font-variant-numeric: tabular-nums; background: var(--accent-dim); color: var(--text-dim);
}

/* La hoja: cada pestaña tiene la suya y es la que hace scroll. */
.panel {
  flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 0.9rem; padding: 1rem;
  background: var(--surface-2); border: 1px solid var(--border-med); border-radius: 0 10px 10px 10px;
}
.detail--flat .panel { border-radius: 10px; }
.scope { margin-top: 0.4rem; font-size: var(--fs-body); color: var(--text-dim); }
.scope--required { color: var(--accent); }
.annex { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 1rem; margin: 0; font-size: var(--fs-body); }
.annex dt { color: var(--text-muted); }
.annex dd { margin: 0; color: var(--text-dim); }
.annex .annex--mine { color: var(--text); font-weight: 600; }

.description {
  margin: 0; padding-inline-start: 0.8rem; border-inline-start: 2px solid var(--border-med);
  color: var(--text-dim); font-size: var(--fs-md); line-height: 1.5;
}

/* Bloques: cada uno con su tono (la franja y la inscripción lo toman de --tone). */
.zone {
  --tone: var(--accent);
  display: flex; flex-direction: column; gap: 0.7rem; padding: 0.9rem 1rem 0.9rem 1.2rem;
  background: var(--surface); border: 1px solid var(--border-med); border-radius: 8px;
  box-shadow: inset 3px 0 0 var(--tone);
}
.zone:empty { display: none; }
details.zone { display: block; }
.zone--proof, .zone--auto { --tone: var(--info); }
/* Una correspondencia es una sugerencia, no un hecho: borde discontinuo. */
.zone--hint { --tone: var(--text-dim); border-style: dashed; }
.zone--quiet { --tone: var(--border-med); background: transparent; border-style: dashed; padding-block: 0.6rem; }

ul { padding-inline-start: 1.2rem; color: var(--text-dim); font-size: var(--fs-md); display: flex; flex-direction: column; gap: 0.3rem; }
.marks { list-style: none; padding-inline-start: 0; gap: 0.5rem; }
.marks li { position: relative; padding-inline-start: 1.2rem; }
.marks li::before {
  content: ''; position: absolute; inset-inline-start: 0.1rem; top: 0.55em; width: 7px; height: 7px;
  transform: rotate(45deg); border: 1px solid var(--tone); background: color-mix(in srgb, var(--tone) 18%, transparent);
}
.official summary { cursor: pointer; color: var(--accent); font-size: var(--fs-md); }
.official p { margin-top: 0.6rem; white-space: pre-line; color: var(--text-dim); font-size: var(--fs-body); }

.assessment { gap: 0.9rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; flex: 1; }
.field label { font-size: var(--fs-body); color: var(--text-dim); }
.field select, .field textarea, .field input {
  padding: 0.5rem 0.7rem; border-radius: 6px; background: var(--bg); color: var(--text);
  border: 1px solid var(--border-med); font-family: inherit;
}
.row { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.foot {
  display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; flex-wrap: wrap;
  padding-top: 0.8rem; border-top: 1px dashed var(--border-med);
}

/* Historial: una línea de tiempo (es lo único del panel que de verdad es una secuencia). */
.events {
  list-style: none; margin: 0 0 0 0.4rem; padding: 0 0 0 1.1rem; border-inline-start: 1px solid var(--border-med);
  display: flex; flex-direction: column; gap: 1.1rem;
}
.events > li { position: relative; }
.events > li::before {
  content: ''; position: absolute; inset-inline-start: calc(-1.1rem - 4.5px); top: 0.4em; width: 8px; height: 8px;
  transform: rotate(45deg); border: 1px solid var(--accent); background: var(--surface-2);
}
.events > li:first-child::before { background: var(--accent); }
.event-head { display: flex; gap: 0.6rem; align-items: baseline; flex-wrap: wrap; font-size: var(--fs-body); color: var(--text); }
.event-date { color: var(--text-muted); font-size: var(--fs-sm); }
.changes { list-style: none; padding: 0; margin-top: 0.3rem; font-size: var(--fs-body); gap: 0.2rem; }
.changes li { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: baseline; }
.field-name { color: var(--text-muted); margin-right: 0.2rem; }
.field-name::after { content: ':'; }
.from { text-decoration: line-through; color: var(--text-muted); }
.arrow { color: var(--text-muted); }
.to { color: var(--text); }
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

@media (prefers-reduced-motion: reduce) { .tab { transition: none; } }
</style>
