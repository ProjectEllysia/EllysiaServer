<template>
  <ToolShell tool-id="powerCost" more-to="/hygeia/activos">
    <div class="pc">
      <section class="pc-presets" :aria-label="t('freeTools.items.powerCost.presetsLabel')">
        <p class="pc-label">{{ t('freeTools.items.powerCost.presetsLabel') }}</p>
        <div class="pc-chips">
          <button
            v-for="preset in POWER_PRESETS"
            :key="preset.id"
            type="button"
            class="pc-chip"
            :class="{ 'pc-chip--on': inputs.watts === String(preset.watts) }"
            :aria-pressed="inputs.watts === String(preset.watts)"
            @click="inputs.watts = String(preset.watts)"
          >
            {{ t('freeTools.items.powerCost.preset', { name: t(`freeTools.items.powerCost.presets.${preset.id}`), watts: preset.watts }) }}
          </button>
        </div>
      </section>

      <div class="pc-fields">
        <div v-for="field in MAIN_FIELDS" :key="field" class="pc-field">
          <label class="pc-label" :for="`pc-${field}`">{{ t(`freeTools.items.powerCost.fields.${field}.label`) }}</label>
          <input
            :id="`pc-${field}`"
            v-model="inputs[field]"
            class="pc-input"
            type="text"
            inputmode="decimal"
            autocomplete="off"
            :aria-invalid="isInvalid(field)"
            :aria-describedby="`pc-${field}-hint`"
          />
          <p :id="`pc-${field}-hint`" class="pc-hint" :class="{ 'pc-hint--error': isInvalid(field) }">
            {{ isInvalid(field) ? errorText(field) : t(`freeTools.items.powerCost.fields.${field}.hint`) }}
          </p>
        </div>
      </div>

      <details class="pc-more">
        <summary class="pc-label">{{ t('freeTools.items.powerCost.moreSettings') }}</summary>
        <div class="pc-field">
          <label class="pc-label" for="pc-pue">{{ t('freeTools.items.powerCost.fields.pue.label') }}</label>
          <input
            id="pc-pue"
            v-model="inputs.pue"
            class="pc-input"
            type="text"
            inputmode="decimal"
            autocomplete="off"
            :aria-invalid="isInvalid('pue')"
            aria-describedby="pc-pue-hint"
          />
          <p id="pc-pue-hint" class="pc-hint" :class="{ 'pc-hint--error': isInvalid('pue') }">
            {{ isInvalid('pue') ? errorText('pue') : t('freeTools.items.powerCost.fields.pue.hint') }}
          </p>
        </div>
      </details>

      <!-- El resultado se pinta como el recibo: una fila por periodo, con su energía y su coste. -->
      <section v-if="result" class="pc-bill" aria-live="polite">
        <table class="pc-table">
          <thead>
            <tr>
              <th scope="col"><span class="sr-only">{{ t('freeTools.items.powerCost.period') }}</span></th>
              <th scope="col">{{ t('freeTools.items.powerCost.energy') }}</th>
              <th scope="col">{{ t('freeTools.items.powerCost.cost') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="period in PERIODS" :key="period" :class="{ 'pc-row--year': period === 'year' }">
              <th scope="row">{{ t(`freeTools.items.powerCost.periods.${period}`) }}</th>
              <td>{{ t('freeTools.items.powerCost.kwh', { value: formatNumber(result.kwh[period], energyFormat(period)) }) }}</td>
              <td>{{ formatNumber(result.cost[period], { style: 'currency', currency: 'EUR' }) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="pc-co2">
          {{ t('freeTools.items.powerCost.co2', { value: formatNumber(result.co2Year, { maximumFractionDigits: 0 }) }) }}
        </p>
        <p class="pc-note">{{ t('freeTools.items.powerCost.note') }}</p>
      </section>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { formatNumber } from '@/i18n/format'
import {
  FIELD_LIMITS,
  POWER_PRESETS,
  calculatePowerCost,
  inputsToQuery,
  parseInputs,
  queryToInputs,
} from '@/components/freeTools/powerCost'

/**
 * Calculadora de consumo eléctrico gratuita de Hygeia.
 *
 * Todo se calcula en el navegador, según se escribe. Lo que no vale lo de por
 * defecto va en la URL para poder compartir el cálculo.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

/** Campos que se ven siempre; el PUE va en «Más ajustes». */
const MAIN_FIELDS = ['watts', 'hoursPerDay', 'devices', 'pricePerKwh', 'emissionFactor']
const PERIODS = ['day', 'month', 'year']

const inputs = reactive(queryToInputs(route.query))

const parsed = computed(() => parseInputs(inputs))
const result = computed(() => (parsed.value.values ? calculatePowerCost(parsed.value.values) : null))

/** Un campo es inválido si el cálculo lo ha rechazado. */
const isInvalid = (field) => parsed.value.invalid.includes(field)

/**
 * Texto del error de un campo.
 *
 * @param {string} field - Un campo de `FIELD_LIMITS`.
 * @returns {string} El rango permitido, o que tiene que ser entero.
 */
function errorText(field) {
  const limits = FIELD_LIMITS[field]
  return limits.integer
    ? t('freeTools.items.powerCost.errors.integer', { min: formatNumber(limits.min), max: formatNumber(limits.max) })
    : t('freeTools.items.powerCost.errors.range', { min: formatNumber(limits.min), max: formatNumber(limits.max) })
}

/**
 * Formato de la energía: con decimales hasta que el número es grande.
 *
 * @param {'day'|'month'|'year'} period - Periodo de la fila.
 * @returns {Intl.NumberFormatOptions} Opciones para `formatNumber`.
 */
function energyFormat(period) {
  return { maximumFractionDigits: period === 'day' ? 2 : 1 }
}

watch(inputs, () => {
  router.replace({ query: inputsToQuery(inputs) })
}, { deep: true })
</script>

<style scoped>
.pc { display: flex; flex-direction: column; gap: 1.4rem; }

.pc-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Potencias típicas ── */
.pc-chips { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.55rem; }
.pc-chip {
  font-size: var(--fs-md);
  padding: 0.45rem 0.9rem;
  color: var(--text-dim);
  border: 1px solid var(--border-med);
  border-radius: 3px;
  transition: all var(--transition);
}
.pc-chip:hover { border-color: var(--accent); color: var(--text); }
.pc-chip--on { background: var(--accent-dim); border-color: var(--accent); color: var(--text); font-weight: 600; }
.pc-chip:focus-visible, .pc-input:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

/* ── Campos ── */
.pc-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 1.1rem 1.4rem; }
.pc-field { display: flex; flex-direction: column; gap: 0.45rem; }
.pc-input {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  padding: 0.65rem 0.8rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  min-width: 0;
}
.pc-input[aria-invalid="true"] { border-color: var(--danger); }
.pc-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.pc-hint--error { color: var(--danger); }
.pc-more summary { cursor: pointer; margin-bottom: 0.9rem; }
.pc-more .pc-field { max-width: 22rem; }

/* ── Recibo ── */
.pc-bill { padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.pc-table { width: 100%; border-collapse: collapse; }
.pc-table th, .pc-table td { text-align: right; padding: 0.6rem 0; border-bottom: 1px solid var(--border); }
.pc-table thead th {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm); font-weight: 400;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.pc-table tbody th { text-align: left; font-weight: 400; color: var(--text-dim); font-size: var(--fs-md); }
.pc-table td { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--text); }
/* La fila anual es la que se lee primero: es la del presupuesto. */
.pc-row--year th, .pc-row--year td { border-bottom: 0; border-top: 2px solid var(--accent); font-weight: 600; color: var(--accent-bright); padding-top: 0.8rem; }
.pc-co2 { margin-top: 0.8rem; font-size: var(--fs-md); color: var(--text-dim); text-align: right; }
.pc-note { margin-top: 0.6rem; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@media (max-width: 520px) {
  .pc-fields { grid-template-columns: 1fr; }
}
</style>
