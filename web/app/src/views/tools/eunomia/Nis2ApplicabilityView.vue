<template>
  <ToolShell tool-id="nis2Applicability" more-to="/eunomia/marcos">
    <div class="na">
      <label class="na-check">
        <input v-model="hasEuActivity" type="checkbox" />
        <span>{{ t('freeTools.items.nis2Applicability.euActivity') }}</span>
      </label>

      <div class="na-field">
        <label class="na-label" for="na-activity">{{ t('freeTools.items.nis2Applicability.activityLabel') }}</label>
        <select id="na-activity" v-model="activityId" class="na-input" aria-describedby="na-activity-hint">
          <option value="" disabled>—</option>
          <optgroup v-for="group in groups" :key="group.annex" :label="group.label">
            <option v-for="option in group.options" :key="option.id" :value="option.id">{{ option.label }}</option>
          </optgroup>
          <option value="none">{{ t('freeTools.items.nis2Applicability.activityNone') }}</option>
        </select>
        <p id="na-activity-hint" class="na-hint">{{ t('freeTools.items.nis2Applicability.activityHint') }}</p>
      </div>

      <label v-if="isTrust" class="na-check">
        <input v-model="isQualifiedTrust" type="checkbox" />
        <span>{{ t('freeTools.items.nis2Applicability.qualifiedTrust') }}</span>
      </label>

      <fieldset class="na-size">
        <legend class="na-label">{{ t('freeTools.items.nis2Applicability.sizeTitle') }}</legend>
        <p class="na-hint">{{ t('freeTools.items.nis2Applicability.sizeHint') }}</p>
        <div class="na-size-fields">
          <div v-for="field in SIZE_FIELDS" :key="field" class="na-field">
            <label class="na-label" :for="`na-${field}`">{{ t(`freeTools.items.nis2Applicability.${field}`) }}</label>
            <input
              :id="`na-${field}`"
              v-model="figures[field]"
              class="na-input"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              :aria-invalid="isInvalid(field)"
            />
            <p v-if="isInvalid(field)" class="na-hint na-hint--error">{{ t('freeTools.items.nis2Applicability.invalidNumber') }}</p>
          </div>
        </div>
      </fieldset>

      <details class="na-more">
        <summary class="na-label">{{ t('freeTools.items.nis2Applicability.moreTitle') }}</summary>
        <label v-for="flag in FLAGS" :key="flag" class="na-check">
          <input v-model="flags[flag]" type="checkbox" />
          <span>{{ t(`freeTools.items.nis2Applicability.${FLAG_TEXT[flag]}`) }}</span>
        </label>
      </details>

      <section v-if="activityId" class="na-result" :data-outcome="outcome" aria-live="polite" aria-labelledby="na-result-title">
        <h2 id="na-result-title" class="na-result-title">{{ t('freeTools.items.nis2Applicability.resultTitle') }}</h2>
        <p v-if="result.missing" class="na-missing">{{ t('freeTools.items.nis2Applicability.missingSize') }}</p>
        <template v-else>
          <p class="na-outcome">{{ t(`freeTools.items.nis2Applicability.outcome.${outcome}.title`) }}</p>
          <p class="na-outcome-text">{{ t(`freeTools.items.nis2Applicability.outcome.${outcome}.text`) }}</p>

          <h3 class="na-sub">{{ t('freeTools.items.nis2Applicability.reasonsTitle') }}</h3>
          <ul class="na-list">
            <li v-for="reason in result.reasons" :key="reason">{{ t(`freeTools.items.nis2Applicability.reasons.${reason}`) }}</li>
          </ul>

          <template v-if="result.caveats.length">
            <h3 class="na-sub">{{ t('freeTools.items.nis2Applicability.caveatsTitle') }}</h3>
            <ul class="na-list">
              <li v-for="caveat in result.caveats" :key="caveat">{{ t(`freeTools.items.nis2Applicability.caveats.${caveat}`) }}</li>
            </ul>
          </template>
        </template>
      </section>

      <p class="na-note">{{ t('freeTools.items.nis2Applicability.note') }}</p>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import {
  ACTIVITIES,
  RULE_TRUST,
  assess,
  findActivity,
  parseAmount,
} from '@/components/freeTools/nis2Applicability'

/**
 * «¿Me aplica NIS2?» de Eunomia.
 *
 * Aplica los artículos 2 y 3 y los anexos I y II de la directiva a lo que se responde, en el
 * navegador y según se escribe. No manda nada a ningún servidor ni guarda las respuestas.
 */
const { t, locale } = useI18n()

const SIZE_FIELDS = ['employees', 'turnover', 'balance']
const FLAGS = ['isCriticalEntity', 'isIdentifiedByState', 'isDomainRegistrar']
const FLAG_TEXT = { isCriticalEntity: 'critical', isIdentifiedByState: 'identified', isDomainRegistrar: 'registrar' }

const hasEuActivity = ref(true)
/** `''` hasta que se elige; `'none'` es «ninguna de las de los anexos». */
const activityId = ref('')
const isQualifiedTrust = ref(false)
const figures = reactive({ employees: '', turnover: '', balance: '' })
const flags = reactive({ isCriticalEntity: false, isIdentifiedByState: false, isDomainRegistrar: false })

/** El texto de un nombre bilingüe de los datos, en el idioma activo. */
const localized = (names) => (locale.value === 'en' ? names.en : names.es)

/** Las actividades agrupadas por anexo, con «sector · actividad» cuando el sector tiene varias. */
const groups = computed(() => ['I', 'II'].map((annex) => ({
  annex,
  label: t(`freeTools.items.nis2Applicability.annex.${annex}`),
  options: ACTIVITIES.filter((activity) => activity.annex === annex).map((activity) => {
    const sector = localized(activity.sector)
    const name = localized(activity)
    return { id: activity.id, label: sector === name ? name : `${sector} · ${name}` }
  }),
})))

const isTrust = computed(() => findActivity(activityId.value)?.rule === RULE_TRUST)

/** Una cifra mal escrita (no vacía y no válida). */
const isInvalid = (field) => parseAmount(figures[field]) === undefined

const answers = computed(() => {
  const amount = (field) => {
    const value = parseAmount(figures[field])
    return value === undefined ? null : value
  }
  return {
    hasEuActivity: hasEuActivity.value,
    activityId: activityId.value && activityId.value !== 'none' ? activityId.value : null,
    employees: amount('employees'),
    turnover: amount('turnover'),
    balance: amount('balance'),
    isQualifiedTrust: isTrust.value && isQualifiedTrust.value,
    ...flags,
  }
})

const result = computed(() => assess(answers.value))
const outcome = computed(() => result.value.outcome)
</script>

<style scoped>
.na { display: flex; flex-direction: column; gap: 1.4rem; }

.na-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.na-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.na-hint--error { color: var(--danger); }

.na-field { display: flex; flex-direction: column; gap: 0.45rem; min-width: 0; }
.na-input {
  font-size: var(--fs-md);
  padding: 0.65rem 0.8rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  min-width: 0;
  max-width: 100%;
}
.na-input:focus-visible, .na-check input:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.na-input[aria-invalid="true"] { border-color: var(--danger); }

.na-check { display: flex; gap: 0.7rem; align-items: flex-start; color: var(--text-dim); font-size: var(--fs-md); line-height: 1.5; cursor: pointer; }
.na-check input { margin-top: 0.3rem; accent-color: var(--accent); }

.na-size { border: 0; padding: 1.2rem 0 0; margin: 0; border-top: 1px solid var(--border-med); display: flex; flex-direction: column; gap: 0.8rem; }
.na-size-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem 1.2rem; }

.na-more { border-top: 1px solid var(--border-med); padding-top: 1.1rem; display: flex; flex-direction: column; gap: 0.9rem; }
.na-more summary { cursor: pointer; margin-bottom: 0.8rem; }
.na-more .na-check + .na-check { margin-top: 0.8rem; }

/* ── Resultado: el borde lleva el color de lo que dice ── */
.na-result {
  border: 1px solid var(--border-med);
  border-left: 4px solid var(--text-muted);
  border-radius: var(--radius-sm);
  padding: 1.2rem 1.4rem;
  background: var(--surface);
}
.na-result[data-outcome="essential"], .na-result[data-outcome="important"], .na-result[data-outcome="unclassified"] { border-left-color: var(--accent-bright); }
.na-result-title {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm); font-weight: 400;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 0.6rem;
}
.na-outcome { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.na-outcome-text { margin-top: 0.5rem; color: var(--text-dim); line-height: 1.6; }
.na-missing { color: var(--text-dim); line-height: 1.6; }
.na-sub { margin-top: 1.2rem; font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.na-list { margin: 0.5rem 0 0; padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.5rem; color: var(--text-dim); line-height: 1.55; }

.na-note { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

@media (max-width: 620px) {
  .na-size-fields { grid-template-columns: 1fr; }
}
</style>
