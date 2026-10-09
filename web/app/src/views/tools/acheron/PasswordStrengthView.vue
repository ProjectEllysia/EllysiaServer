<template>
  <ToolShell tool-id="passwordStrength" more-to="/acheron/boveda">
    <div class="ps">
      <div class="ps-field">
        <label class="ps-label" for="ps-input">{{ t('freeTools.items.passwordStrength.inputLabel') }}</label>
        <div class="ps-row">
          <input
            id="ps-input"
            v-model="password"
            class="ps-input"
            :type="isShown ? 'text' : 'password'"
            maxlength="128"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            :placeholder="t('freeTools.items.passwordStrength.placeholder')"
          />
          <button type="button" class="ps-toggle" :aria-pressed="isShown" @click="isShown = !isShown">
            {{ isShown ? t('freeTools.items.passwordStrength.hide') : t('freeTools.items.passwordStrength.show') }}
          </button>
        </div>
        <p class="ps-privacy">{{ t('freeTools.items.passwordStrength.privacy') }}</p>
      </div>

      <p v-if="!password" class="ps-empty">{{ t('freeTools.items.passwordStrength.empty') }}</p>

      <template v-else>
        <div class="ps-verdict" :data-level="estimate.level" aria-live="polite">
          <div class="ps-segments" aria-hidden="true">
            <span v-for="step in 5" :key="step" class="ps-segment" :class="{ 'ps-segment--on': step <= estimate.level + 1 }" :style="{ '--i': step }"></span>
          </div>
          <p class="ps-level">
            {{ t(`freeTools.items.passwordStrength.levels.${estimate.level}`) }}
            <span class="ps-bits"><CountUp :value="estimate.bits" :duration="450" :format="(value) => t('freeTools.items.passwordStrength.bits', { count: value })" /></span>
          </p>
        </div>

        <!-- Escala logarítmica del tiempo que aguantaría: de un segundo a siglos. -->
        <div class="ps-ladder">
          <p class="ps-crack">
            {{ t('freeTools.items.passwordStrength.crackIntro') }}
            <strong>{{ crackText }}</strong>
          </p>
          <div class="ps-track" role="img" :aria-label="crackText">
            <span class="ps-track-fill" :style="{ width: `${scalePosition * 100}%` }"></span>
            <span class="ps-track-marker" :style="{ left: `${scalePosition * 100}%` }"></span>
            <span
              v-for="(tick, index) in TICKS"
              :key="tick.unit"
              class="ps-tick"
              :class="{ 'ps-tick--first': index === 0, 'ps-tick--last': index === TICKS.length - 1 }"
              :style="{ left: `${tick.position * 100}%` }">
              <span class="ps-tick-label">{{ t(`freeTools.items.passwordStrength.ticks.${tick.unit}`) }}</span>
            </span>
          </div>
          <p class="ps-assumption">{{ t('freeTools.items.passwordStrength.assumption') }}</p>
        </div>

        <section v-if="estimate.weaknesses.length" class="ps-section">
          <h3 class="ps-section-title">{{ t('freeTools.items.passwordStrength.weaknessesTitle') }}</h3>
          <ul class="ps-weaknesses">
            <li v-for="(code, index) in estimate.weaknesses" :key="code" class="mo-rise" :style="{ '--delay': `${index * 80}ms` }">{{ t(`freeTools.items.passwordStrength.weaknesses.${code}`) }}</li>
          </ul>
        </section>

        <section class="ps-section">
          <h3 class="ps-section-title">{{ t('freeTools.items.passwordStrength.breachTitle') }}</h3>
          <p class="ps-note">{{ t('freeTools.items.passwordStrength.breachNote') }}</p>
          <button type="button" class="ps-btn" :disabled="breach.state === 'loading'" @click="checkBreaches">
            {{ breach.state === 'loading' ? t('freeTools.items.passwordStrength.breachChecking') : t('freeTools.items.passwordStrength.breachCheck') }}
          </button>
          <p v-if="breach.state === 'found'" class="ps-result ps-result--bad" role="status">
            {{ t('freeTools.items.passwordStrength.breachFound', { count: formatNumber(breach.count) }, breach.count) }}
          </p>
          <p v-else-if="breach.state === 'clean'" class="ps-result ps-result--ok" role="status">
            {{ t('freeTools.items.passwordStrength.breachClean') }}
          </p>
          <p v-else-if="breach.state === 'error'" class="ps-result ps-result--bad" role="status">
            {{ t('freeTools.items.passwordStrength.breachFailed') }}
          </p>
        </section>

        <p class="ps-note">{{ t('freeTools.items.passwordStrength.estimateNote') }}</p>
      </template>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import CountUp from '@/components/shared/CountUp.vue'
import { formatNumber } from '@/i18n/format'
import {
  countInBreaches,
  crackScalePosition,
  crackSeconds,
  crackTimeParts,
  estimateStrength,
} from '@/components/freeTools/passwordStrength'

/**
 * Medidor de contraseñas gratuito de Acheron.
 *
 * El análisis es local: la contraseña no sale del navegador. Solo si el usuario
 * pulsa «Comprobar en filtraciones» viajan, a Have I Been Pwned, los cinco
 * primeros caracteres de su hash.
 */
const { t } = useI18n()

/** Marcas de la escala: segundos a partir de los que arranca cada unidad. */
const TICKS = [
  { unit: 'second', seconds: 1 },
  { unit: 'minute', seconds: 60 },
  { unit: 'hour', seconds: 3600 },
  { unit: 'day', seconds: 86400 },
  { unit: 'year', seconds: 86400 * 365 },
  { unit: 'century', seconds: 86400 * 365 * 100 },
].map((tick) => ({ ...tick, position: crackScalePosition(tick.seconds) }))

const password = ref('')
const isShown = ref(false)
const breach = reactive({ state: 'idle', count: 0 }) // idle | loading | found | clean | error

const estimate = computed(() => estimateStrength(password.value))
const seconds = computed(() => crackSeconds(estimate.value.bits))
const scalePosition = computed(() => crackScalePosition(seconds.value))
const crackText = computed(() => {
  const { unit, value } = crackTimeParts(seconds.value)
  return value === null
    ? t(`freeTools.items.passwordStrength.units.${unit}`)
    : t(`freeTools.items.passwordStrength.units.${unit}`, { count: formatNumber(value) }, value)
})

// Lo comprobado vale para esa contraseña y no para la siguiente.
watch(password, () => {
  breach.state = 'idle'
  breach.count = 0
})

/** Pregunta cuántas veces aparece la contraseña en filtraciones conocidas. */
async function checkBreaches() {
  breach.state = 'loading'
  try {
    breach.count = await countInBreaches(password.value)
    breach.state = breach.count > 0 ? 'found' : 'clean'
  } catch {
    breach.state = 'error'
  }
}
</script>

<style scoped>
.ps { display: flex; flex-direction: column; gap: 1.5rem; }

.ps-label, .ps-section-title, .ps-bits {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Campo ── */
.ps-field { display: flex; flex-direction: column; gap: 0.55rem; }
.ps-row { display: flex; gap: 0.7rem; }
.ps-input {
  flex: 1; min-width: 0;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  letter-spacing: 0.04em;
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.ps-input:focus-visible, .ps-toggle:focus-visible, .ps-btn:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.ps-toggle, .ps-btn {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  padding: 0.6rem 1rem;
  color: var(--text);
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  border-radius: 3px;
  transition: all var(--transition);
}
.ps-toggle:hover, .ps-btn:hover:not(:disabled) { background: var(--accent); color: var(--on-accent); }
.ps-btn:disabled { opacity: 0.6; cursor: progress; }
.ps-privacy, .ps-note, .ps-assumption { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.55; }
.ps-empty { font-size: var(--fs-md); color: var(--text-dim); }

/* ── Veredicto: cinco tramos que se llenan ── */
.ps-verdict { --tone: var(--danger); }
.ps-verdict[data-level="2"] { --tone: var(--warn); }
.ps-verdict[data-level="3"], .ps-verdict[data-level="4"] { --tone: var(--success); }
.ps-segments { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.35rem; }
.ps-segment { height: 0.5rem; border-radius: 2px; background: var(--border-med); transition: background 0.3s ease calc(var(--i) * 70ms); }
.ps-segment--on { background: var(--tone); }
.ps-level {
  display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  margin-top: 0.7rem;
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-2xl); font-weight: 600;
  color: var(--tone);
}

/* ── Escala del tiempo ── */
.ps-ladder { padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.ps-crack { font-size: var(--fs-md); color: var(--text-dim); }
.ps-crack strong { color: var(--text); font-weight: 600; }
.ps-track {
  position: relative;
  height: 0.5rem;
  margin: 1.3rem 0 2.1rem;
  border-radius: 3px;
  background: var(--border-med);
}
.ps-track-fill { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: var(--accent); transition: width 0.3s ease; }
.ps-track-marker {
  position: absolute; top: 50%;
  width: 0.9rem; height: 0.9rem;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: var(--bg);
  border: 2px solid var(--accent-bright);
  transition: left 0.3s ease;
}
.ps-tick { position: absolute; top: 100%; width: 1px; height: 0.45rem; background: var(--text-muted); }
.ps-tick-label {
  position: absolute; top: 0.55rem; left: 0;
  transform: translateX(-50%);
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs);
  color: var(--text-muted);
  white-space: nowrap;
}
/* La primera y la última marca se alinean al borde para no salirse de la caja. */
.ps-tick--first .ps-tick-label { transform: none; }
.ps-tick--last .ps-tick-label { transform: translateX(-100%); }

/* ── Secciones ── */
.ps-section { display: flex; flex-direction: column; align-items: flex-start; gap: 0.6rem; }
.ps-weaknesses { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }
.ps-weaknesses li { font-size: var(--fs-md); color: var(--text-dim); padding-left: 1.1rem; position: relative; }
.ps-weaknesses li::before { content: ''; position: absolute; left: 0; top: 0.6em; width: 0.5rem; height: 2px; background: var(--warn); }
.ps-result { font-size: var(--fs-md); font-weight: 600; }
.ps-result--bad { color: var(--danger); }
.ps-result--ok { color: var(--success); }

@media (max-width: 520px) {
  .ps-tick-label { font-size: var(--fs-xs); }
}
@media (prefers-reduced-motion: reduce) {
  .ps-track-fill, .ps-track-marker, .ps-segment { transition: none; }
}
</style>
