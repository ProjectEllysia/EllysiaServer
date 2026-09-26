<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="show" class="compare-overlay" @click.self="$emit('close')">
        <div ref="boxRef" class="compare-box" role="dialog" aria-modal="true" aria-labelledby="compare-title">
          <header class="compare-header">
            <h2 id="compare-title" class="compare-title">{{ t('iris.compare.title') }}</h2>
            <button type="button" class="compare-close" :aria-label="t('iris.compare.close')" @click="$emit('close')">&times;</button>
          </header>

          <p v-if="loading" class="compare-state">{{ t('iris.compare.loading') }}</p>
          <p v-else-if="error" class="compare-state compare-state--error">{{ error }}</p>
          <template v-else-if="comparison">
            <div class="compare-columns">
              <section v-for="report in [left, right]" :key="report.analysisId" class="compare-card">
                <p class="compare-id">#{{ report.analysisId }} · {{ report.title || t('iris.untitled') }}</p>
                <p class="compare-verdict" :class="`verdict--${(report.verdict || '').toLowerCase()}`">
                  {{ t(verdictKey(report.verdict)) }} · {{ report.totalScore }}
                </p>
                <p class="compare-meta">
                  {{ ['high', 'medium', 'low'].includes(report.confidence) ? t('iris.hero.confidence', { level: t(`iris.hero.confidenceLevel.${report.confidence}`) }) : t('iris.compare.notEvaluated') }} ·
                  {{ report.coverage?.mode === 'headers_only' ? t('iris.hero.headersOnly') : t('iris.hero.fullMessage') }}
                </p>
                <p class="compare-meta">{{ report.previewHeaders?.from || '' }}</p>
                <ul v-if="report.gateReasons?.length" class="compare-gates">
                  <li v-for="(reason, i) in report.gateReasons" :key="i">{{ reason }}</li>
                </ul>
              </section>
            </div>

            <p class="compare-summary">
              {{ comparison.verdictChanged ? t('iris.compare.differentVerdicts') : t('iris.compare.sameVerdict') }}
              <template v-if="comparison.scoreDelta !== null"> · {{ t('iris.compare.scoreDelta', { delta: `${comparison.scoreDelta > 0 ? '+' : ''}${comparison.scoreDelta}` }) }}</template>
              · {{ t('iris.compare.changedRules', { count: comparison.changedCount }, comparison.changedCount) }}
            </p>

            <div class="compare-table-wrap">
              <table class="compare-table">
                <thead>
                  <tr><th>{{ t('iris.compare.rule') }}</th><th>#{{ left.analysisId }}</th><th>#{{ right.analysisId }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="entry in visibleRules" :key="entry.ruleName" :class="{ 'row--changed': entry.changed }">
                    <td>{{ entry.ruleName }}</td>
                    <td class="mono">{{ describe(entry.left) }}</td>
                    <td class="mono">{{ describe(entry.right) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button v-if="comparison.rules.length > comparison.changedCount" type="button" class="compare-toggle" @click="showAll = !showAll">
              {{ showAll ? t('iris.compare.onlyChanged') : t('iris.compare.showUnchanged', { count: comparison.rules.length - comparison.changedCount }) }}
            </button>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useIrisStore } from '@/stores/irisStore'
import { useModalA11y } from '@/composables/useModalA11y'
import { compareReports } from '@/components/iris/compare.js'
import { ruleVerdictKey, verdictKey } from '@/components/iris/verdict'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  show: { type: Boolean, default: false },
  // Los dos análisis a comparar: [izquierda, derecha].
  analysisIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])

const store = useIrisStore()
const boxRef = ref(null)
const left = ref(null)
const right = ref(null)
const loading = ref(false)
const error = ref(null)
const showAll = ref(false)


const comparison = computed(() => (left.value && right.value ? compareReports(left.value, right.value) : null))
const visibleRules = computed(() =>
  showAll.value ? comparison.value.rules : comparison.value.rules.filter(entry => entry.changed)
)

/**
 * Celda de una regla en la tabla comparativa: su resultado y su puntuación.
 *
 * @param {{verdict: string, score: number}|null} side - La regla en uno de
 *   los dos informes, o `null` si ese informe no la tiene.
 * @returns {string} «Correcto (0)», «Falla (-20)»…, o «—» si falta.
 */
function describe(side) {
  return side ? `${t(ruleVerdictKey(side.verdict))} (${side.score})` : '—'
}

watch(() => [props.show, ...props.analysisIds], async () => {
  if (!props.show || props.analysisIds.length !== 2) return
  loading.value = true
  error.value = null
  showAll.value = false
  const [leftReport, rightReport] = await Promise.all(props.analysisIds.map(id => store.fetchReportById(id)))
  left.value = leftReport
  right.value = rightReport
  if (!leftReport || !rightReport) error.value = t('iris.compare.onlyFinished')
  loading.value = false
}, { immediate: true })

useModalA11y(() => props.show, { boxRef, onClose: () => emit('close') })
</script>

<style scoped>
.compare-overlay {
  position: fixed; inset: 0; z-index: 210;
  display: flex; align-items: center; justify-content: center; padding: 1.5rem;
  background: rgba(11, 12, 16, 0.82); backdrop-filter: blur(6px);
}
.compare-box {
  width: min(1100px, 100%); max-height: 88vh; overflow-y: auto;
  padding: 1.25rem 1.5rem;
  background: var(--surface); border: 1px solid var(--border-med); border-radius: 16px;
}
.compare-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.9rem; }
.compare-title { margin: 0; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); color: var(--text); }
.compare-close { border: none; background: none; color: var(--text-muted); font-size: 1.6rem; cursor: pointer; }
.compare-state { color: var(--text-dim); }
.compare-state--error { color: var(--danger); }
.compare-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }
.compare-card { padding: 0.8rem 1rem; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); min-width: 0; }
.compare-id { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compare-verdict { margin: 0.3rem 0; font-size: var(--fs-lg); font-weight: 700; }
.verdict--legitimate { color: var(--success); }
.verdict--suspicious { color: var(--warn); }
.verdict--phishing { color: var(--danger); }
.compare-meta { margin: 0; font-size: var(--fs-sm); color: var(--text-dim); overflow-wrap: anywhere; }
.compare-gates { margin: 0.5rem 0 0; padding-left: 1.1rem; font-size: var(--fs-sm); color: var(--text-dim); }
.compare-summary { margin: 1rem 0 0.6rem; font-weight: 600; color: var(--text); }
.compare-table-wrap { overflow-x: auto; }
.compare-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.compare-table th, .compare-table td { padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); text-align: left; }
.compare-table th { color: var(--text-muted); font-weight: 600; }
.row--changed td { background: var(--warn-dim); }
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.compare-toggle { margin-top: 0.6rem; border: 1px solid var(--border-med); background: transparent; color: var(--text-dim); border-radius: 6px; padding: 0.3rem 0.7rem; cursor: pointer; }
@media (max-width: 720px) { .compare-columns { grid-template-columns: 1fr; } }
</style>
