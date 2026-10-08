<template>
  <ToolShell tool-id="cvssCalculator" more-to="/aegis/generador">
    <div class="cv">
      <!-- El resultado queda a la vista mientras se marcan las métricas. -->
      <section class="cv-result" :data-severity="result.severity" aria-live="polite">
        <div class="cv-score-row">
          <p class="cv-score">{{ formatNumber(result.score, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) }}</p>
          <div>
            <p class="cv-severity">{{ t(`freeTools.items.cvssCalculator.severity.${result.severity}`) }}</p>
            <p class="cv-caption">{{ t('freeTools.items.cvssCalculator.scoreLabel') }}</p>
          </div>
          <dl class="cv-sub">
            <div>
              <dt>{{ t('freeTools.items.cvssCalculator.exploitability') }}</dt>
              <dd>{{ formatNumber(result.exploitability, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) }}</dd>
            </div>
            <div>
              <dt>{{ t('freeTools.items.cvssCalculator.impact') }}</dt>
              <dd>{{ formatNumber(Math.max(result.impact, 0), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) }}</dd>
            </div>
          </dl>
        </div>

        <!-- Escala de 0 a 10 con las cuatro franjas de la especificación. -->
        <div class="cv-scale" role="img" :aria-label="t('freeTools.items.cvssCalculator.scaleLabel', { score: formatNumber(result.score, { minimumFractionDigits: 1 }) })">
          <span class="cv-band cv-band--low"></span>
          <span class="cv-band cv-band--medium"></span>
          <span class="cv-band cv-band--high"></span>
          <span class="cv-band cv-band--critical"></span>
          <span class="cv-marker" :style="{ left: `${result.score * 10}%` }"></span>
        </div>

        <div class="cv-vector">
          <code class="cv-vector-text">{{ vector }}</code>
          <button type="button" class="cv-btn" @click="copyVector">
            {{ isCopied ? t('freeTools.items.cvssCalculator.copied') : t('freeTools.items.cvssCalculator.copy') }}
          </button>
        </div>
      </section>

      <fieldset v-for="metric in METRICS" :key="metric.key" class="cv-metric">
        <legend class="cv-metric-name">{{ t(`freeTools.items.cvssCalculator.metrics.${metric.key}.name`) }}</legend>
        <p class="cv-metric-hint">{{ t(`freeTools.items.cvssCalculator.metrics.${metric.key}.hint`) }}</p>
        <div class="cv-options">
          <label v-for="value in metric.values" :key="value" class="cv-option" :class="{ 'cv-option--on': metrics[metric.key] === value }">
            <input v-model="metrics[metric.key]" type="radio" class="cv-radio" :name="`cv-${metric.key}`" :value="value" />
            <span>{{ t(`freeTools.items.cvssCalculator.metrics.${metric.key}.values.${value}`) }}</span>
          </label>
        </div>
      </fieldset>

      <div class="cv-load">
        <label class="cv-metric-name" for="cv-draft">{{ t('freeTools.items.cvssCalculator.loadLabel') }}</label>
        <input
          id="cv-draft"
          class="cv-input"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :value="draft"
          :aria-invalid="Boolean(draftError)"
          aria-describedby="cv-draft-hint"
          @input="loadVector($event.target.value)"
        />
        <p id="cv-draft-hint" class="cv-metric-hint" :class="{ 'cv-metric-hint--error': draftError }">
          {{ draftError ? t(`freeTools.items.cvssCalculator.errors.${draftError}`) : t('freeTools.items.cvssCalculator.loadHint') }}
        </p>
      </div>

      <p class="cv-note">{{ t('freeTools.items.cvssCalculator.baseOnly') }}</p>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { useToastStore } from '@/stores/toastStore'
import { formatNumber } from '@/i18n/format'
import { DEFAULT_METRICS, METRICS, buildVector, calculateBaseScore, parseVector } from '@/components/freeTools/cvss'

/**
 * Calculadora CVSS 3.1 gratuita de Aegis.
 *
 * Todo se calcula en el navegador. El vector va en `?v=` para poder compartir la
 * puntuación con un enlace.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const toast = useToastStore()

/** Cuánto se queda el botón en «Copiado» antes de volver a «Copiar vector». */
const COPIED_FEEDBACK_MS = 2000

// Un enlace compartido (`?v=CVSS:3.1/…`) abre la calculadora ya rellena. Se lee antes
// de que nada reescriba la URL con los valores por defecto.
const linked = typeof route.query.v === 'string' ? parseVector(route.query.v) : null
const metrics = reactive({ ...(linked?.ok ? linked.metrics : DEFAULT_METRICS) })
const draft = ref('')
const draftError = ref(null)
const isCopied = ref(false)
let copiedTimer = null

const vector = computed(() => buildVector(metrics))
const result = computed(() => calculateBaseScore(metrics))

// El campo de carga muestra siempre el vector actual, salvo mientras se escribe uno que aún no es válido.
watch(vector, (current) => {
  draft.value = current
  draftError.value = null
  router.replace({ query: { v: current } })
}, { immediate: true })

/**
 * Rellena las métricas con el vector que se está escribiendo.
 *
 * @param {string} text - Lo escrito en el campo de carga.
 */
function loadVector(text) {
  draft.value = text
  const parsed = parseVector(text)
  if (parsed.ok) {
    Object.assign(metrics, parsed.metrics)
    draftError.value = null
  } else {
    draftError.value = text.trim() === '' ? null : parsed.reason
  }
}

/** Copia el vector al portapapeles y lo avisa un instante en el botón. */
async function copyVector() {
  try {
    await navigator.clipboard.writeText(vector.value)
  } catch {
    toast.show(t('freeTools.items.cvssCalculator.copyFailed'), 'error')
    return
  }
  isCopied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { isCopied.value = false }, COPIED_FEEDBACK_MS)
}

onBeforeUnmount(() => clearTimeout(copiedTimer))
</script>

<style scoped>
.cv { display: flex; flex-direction: column; gap: 1.4rem; }

.cv-metric-name, .cv-sub dt {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
  padding: 0;
}

/* ── Resultado ── */
.cv-result {
  --tone: var(--text-muted);
  position: sticky; top: 4.5rem; z-index: 2;
  padding: 1.1rem 1.2rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-top: 3px solid var(--tone);
  border-radius: var(--radius-sm);
}
.cv-result[data-severity="low"] { --tone: var(--success); }
.cv-result[data-severity="medium"] { --tone: var(--accent-bright); }
.cv-result[data-severity="high"] { --tone: var(--warn); }
.cv-result[data-severity="critical"] { --tone: var(--danger); }
.cv-score-row { display: flex; align-items: center; gap: 1.2rem 1.6rem; flex-wrap: wrap; }
.cv-score {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-3xl); font-weight: 600;
  line-height: 1;
  color: var(--tone);
}
.cv-severity { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.cv-caption { font-size: var(--fs-sm); color: var(--text-muted); }
.cv-sub { display: flex; gap: 1.6rem; margin-left: auto; }
.cv-sub dd { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--text); margin-top: 0.15rem; }

/* Franjas proporcionales: 0,1-3,9 · 4-6,9 · 7-8,9 · 9-10. */
.cv-scale { position: relative; display: flex; height: 0.5rem; margin: 1rem 0 0.9rem; border-radius: 3px; background: var(--border-med); }
.cv-band { height: 100%; opacity: 0.55; }
.cv-band--low { width: 40%; background: var(--success); border-radius: 3px 0 0 3px; }
.cv-band--medium { width: 30%; background: var(--accent-bright); }
.cv-band--high { width: 20%; background: var(--warn); }
.cv-band--critical { width: 10%; background: var(--danger); border-radius: 0 3px 3px 0; }
.cv-marker {
  position: absolute; top: 50%;
  width: 0.95rem; height: 0.95rem;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: var(--bg);
  border: 2px solid var(--text);
  transition: left 0.25s ease;
}

.cv-vector { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
.cv-vector-text {
  flex: 1 1 16rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  color: var(--text-dim);
  word-break: break-all;
}
.cv-btn {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.4rem 0.9rem;
  color: var(--text);
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  border-radius: 3px;
  transition: all var(--transition);
}
.cv-btn:hover { background: var(--accent); color: var(--on-accent); }
.cv-btn:focus-visible, .cv-input:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

/* ── Métricas ── */
.cv-metric { border: 0; padding: 0; margin: 0; min-width: 0; }
.cv-metric-hint { font-size: var(--fs-sm); color: var(--text-muted); margin: 0.2rem 0 0.55rem; }
.cv-metric-hint--error { color: var(--danger); }
.cv-options { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.cv-option {
  position: relative;
  padding: 0.5rem 1rem;
  font-size: var(--fs-md);
  color: var(--text-dim);
  border: 1px solid var(--border-med);
  border-radius: 3px;
  cursor: pointer;
  transition: all var(--transition);
}
.cv-option:hover { border-color: var(--accent); color: var(--text); }
.cv-option--on { background: var(--accent-dim); border-color: var(--accent); color: var(--text); font-weight: 600; }
/* El radio se esconde sin quitarlo del teclado; el foco se ve en la etiqueta. */
.cv-radio { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.cv-option:has(.cv-radio:focus-visible) { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

/* ── Cargar un vector ── */
.cv-load { display: flex; flex-direction: column; gap: 0.4rem; padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.cv-input {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.7rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.cv-input[aria-invalid="true"] { border-color: var(--danger); }
.cv-note { font-size: var(--fs-sm); color: var(--text-muted); }

/* El resultado fijo solo cuando sobra altura: en una pantalla baja taparía las métricas. */
@media (max-height: 700px), (max-width: 600px) {
  .cv-result { position: static; }
}
@media (max-width: 520px) {
  .cv-sub { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .cv-marker { transition: none; }
}
</style>
