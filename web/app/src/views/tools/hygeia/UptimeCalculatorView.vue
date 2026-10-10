<template>
  <ToolShell tool-id="uptimeCalculator" more-to="/hygeia/activos">
    <div class="up">
      <section class="up-presets" :aria-label="t('freeTools.items.uptimeCalculator.presetsLabel')">
        <p class="up-label">{{ t('freeTools.items.uptimeCalculator.presetsLabel') }}</p>
        <div class="up-chips">
          <button
            v-for="preset in SLA_PRESETS"
            :key="preset"
            type="button"
            class="up-chip"
            :class="{ 'up-chip--on': sla === preset }"
            :aria-pressed="sla === preset"
            @click="slaText = formatNumber(preset, { maximumFractionDigits: 3 })"
          >
            {{ formatNumber(preset, { maximumFractionDigits: 3 }) }} %
          </button>
        </div>
      </section>

      <div class="up-field">
        <label class="up-label" for="up-sla">{{ t('freeTools.items.uptimeCalculator.slaLabel') }}</label>
        <input
          id="up-sla"
          v-model="slaText"
          class="up-input"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          :aria-invalid="sla === null"
          aria-describedby="up-sla-hint"
        />
        <p id="up-sla-hint" class="up-hint" :class="{ 'up-hint--error': sla === null }">
          {{ sla === null ? t('freeTools.items.uptimeCalculator.invalidSla') : t('freeTools.items.uptimeCalculator.slaHint') }}
        </p>
      </div>

      <!-- La caída permitida, una fila por periodo: la anual es la que se pacta. -->
      <table v-if="downtime" class="up-table" aria-live="polite">
        <thead>
          <tr>
            <th scope="col">{{ t('freeTools.items.uptimeCalculator.period') }}</th>
            <th scope="col">{{ t('freeTools.items.uptimeCalculator.downtime') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="period in PERIODS" :key="period" :class="{ 'up-row--year': period === 'year' }">
            <th scope="row">{{ t(`freeTools.items.uptimeCalculator.periods.${period}`) }}</th>
            <td>{{ formatDuration(downtime[period]) }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Al revés: de una caída que ya ocurrió a la disponibilidad que dejó. -->
      <section class="up-reverse" aria-labelledby="up-reverse-title">
        <h2 id="up-reverse-title" class="up-reverse-title">{{ t('freeTools.items.uptimeCalculator.reverse.title') }}</h2>
        <div class="up-reverse-fields">
          <div class="up-field">
            <label class="up-label" for="up-minutes">{{ t('freeTools.items.uptimeCalculator.reverse.downtimeLabel') }}</label>
            <input
              id="up-minutes"
              v-model="minutesText"
              class="up-input"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              :aria-invalid="isReverseInvalid"
              aria-describedby="up-minutes-hint"
            />
          </div>
          <div class="up-field">
            <label class="up-label" for="up-period">{{ t('freeTools.items.uptimeCalculator.reverse.periodLabel') }}</label>
            <select id="up-period" v-model="period" class="up-input">
              <option v-for="option in PERIODS" :key="option" :value="option">{{ t(`freeTools.items.uptimeCalculator.periods.${option}`) }}</option>
            </select>
          </div>
        </div>
        <p id="up-minutes-hint" class="up-hint" :class="{ 'up-hint--error': isReverseInvalid }" aria-live="polite">
          <template v-if="isReverseInvalid">{{ t('freeTools.items.uptimeCalculator.reverse.invalid') }}</template>
          <template v-else-if="availability !== null">
            {{ t('freeTools.items.uptimeCalculator.reverse.result') }}
            <strong class="up-availability">{{ formatNumber(availability, { maximumFractionDigits: 4 }) }} %</strong>
          </template>
        </p>
      </section>

      <p class="up-note">{{ t('freeTools.items.uptimeCalculator.note') }}</p>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { formatNumber } from '@/i18n/format'
import {
  PERIOD_SECONDS,
  SLA_PRESETS,
  allowedDowntime,
  availabilityFor,
  durationParts,
  parseSla,
} from '@/components/freeTools/uptime'

/**
 * Calculadora de disponibilidad gratuita de Hygeia.
 *
 * Pasa de un porcentaje de disponibilidad a la caída que permite en cada periodo, y
 * al revés. Todo se calcula en el navegador, según se escribe.
 */
const { t } = useI18n()

const PERIODS = Object.keys(PERIOD_SECONDS)

const slaText = ref(formatNumber(99.9))
const minutesText = ref('')
const period = ref('month')

const sla = computed(() => parseSla(slaText.value))
const downtime = computed(() => (sla.value === null ? null : allowedDowntime(sla.value)))
const availability = computed(() => availabilityFor(minutesText.value, period.value))
/** Con el campo vacío no hay error: aún no se ha escrito nada. */
const isReverseInvalid = computed(() => minutesText.value.trim() !== '' && availability.value === null)

/**
 * Escribe una duración con sus unidades, en el idioma activo.
 *
 * @param {number} seconds - Duración, en segundos.
 * @returns {string} Por ejemplo «8 h 45 min 58 s».
 */
function formatDuration(seconds) {
  return durationParts(seconds)
    .map(({ unit, value }) => t(`freeTools.items.uptimeCalculator.units.${unit}`, { value: formatNumber(value, { maximumFractionDigits: 2 }) }))
    .join(' ')
}
</script>

<style scoped>
.up { display: flex; flex-direction: column; gap: 1.4rem; }

.up-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Disponibilidades habituales ── */
.up-chips { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.55rem; }
.up-chip {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  padding: 0.45rem 0.9rem;
  color: var(--text-dim);
  border: 1px solid var(--border-med);
  border-radius: 3px;
  transition: all var(--transition);
}
.up-chip:hover { border-color: var(--accent); color: var(--text); }
.up-chip--on { background: var(--accent-dim); border-color: var(--accent); color: var(--text); font-weight: 600; }
.up-chip:focus-visible, .up-input:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

/* ── Campos ── */
.up-field { display: flex; flex-direction: column; gap: 0.45rem; max-width: 22rem; }
.up-input {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  padding: 0.65rem 0.8rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  min-width: 0;
}
.up-input[aria-invalid="true"] { border-color: var(--danger); }
.up-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.up-hint--error { color: var(--danger); }

/* ── Tabla de caídas ── */
.up-table { width: 100%; border-collapse: collapse; padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.up-table th, .up-table td { text-align: right; padding: 0.6rem 0; border-bottom: 1px solid var(--border); }
.up-table thead th {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm); font-weight: 400;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.up-table thead th:first-child, .up-table tbody th { text-align: left; }
.up-table tbody th { font-weight: 400; color: var(--text-dim); font-size: var(--fs-md); }
.up-table td { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--text); }
/* La fila anual es la que se pacta en un contrato: se lee primero. */
.up-row--year th, .up-row--year td { border-bottom: 0; border-top: 2px solid var(--accent); font-weight: 600; color: var(--accent-bright); padding-top: 0.8rem; }

/* ── Al revés ── */
.up-reverse { display: flex; flex-direction: column; gap: 0.9rem; padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.up-reverse-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-xl); font-weight: 600;
  color: var(--text);
}
.up-reverse-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 1.1rem 1.4rem; }
.up-availability { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--accent-bright); }
.up-note { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

@media (max-width: 520px) {
  .up-reverse-fields { grid-template-columns: 1fr; }
}
</style>
