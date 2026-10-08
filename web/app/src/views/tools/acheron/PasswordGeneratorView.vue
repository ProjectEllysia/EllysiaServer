<template>
  <ToolShell tool-id="passwordGenerator" more-to="/acheron/boveda">
    <div class="pw">
      <div class="pw-result">
        <p class="pw-output" :aria-label="t('freeTools.items.passwordGenerator.generated')" data-testid="password-output">
          <span v-for="(character, index) in characters" :key="index" :class="`pw-char pw-char--${kindOf(character)}`">{{ character }}</span>
        </p>
        <div class="pw-actions">
          <button type="button" class="pw-btn pw-btn--solid" @click="copy">
            {{ isCopied ? t('freeTools.items.passwordGenerator.copied') : t('freeTools.items.passwordGenerator.copy') }}
          </button>
          <button type="button" class="pw-btn pw-btn--line" @click="regenerate">
            {{ t('freeTools.items.passwordGenerator.regenerate') }}
          </button>
        </div>
        <!-- Solo este aviso es región viva: la contraseña cambia con cada ajuste y leerla entera cada vez estorbaría. -->
        <span class="sr-only" role="status">{{ isCopied ? t('freeTools.items.passwordGenerator.copied') : '' }}</span>
      </div>

      <div class="pw-strength">
        <div class="pw-strength-head">
          <span class="pw-label">{{ t('freeTools.items.passwordGenerator.strengthLabel') }}</span>
          <span class="pw-strength-value" :style="{ color: strength.color }">{{ t(strengthLabelKey(strength.score)) }}</span>
        </div>
        <div class="pw-meter" aria-hidden="true">
          <span class="pw-meter-fill" :style="{ width: `${strength.percent}%`, background: strength.color }"></span>
        </div>
      </div>

      <div class="pw-controls">
        <div class="pw-length">
          <label class="pw-label" for="pw-length-range">{{ t('freeTools.items.passwordGenerator.length') }}</label>
          <input
            id="pw-length-range"
            v-model.number="settings.length"
            type="range"
            :min="PASSWORD_LENGTH.min"
            :max="PASSWORD_LENGTH.max"
            class="pw-range"
          />
          <input
            v-model.number="settings.length"
            type="number"
            :min="PASSWORD_LENGTH.min"
            :max="PASSWORD_LENGTH.max"
            class="pw-number"
            :aria-label="t('freeTools.items.passwordGenerator.length')"
            @change="settings.length = clampPasswordLength(settings.length)"
          />
        </div>

        <fieldset class="pw-classes">
          <legend class="pw-label">{{ t('freeTools.items.passwordGenerator.include') }}</legend>
          <label v-for="characterClass in CHARACTER_CLASSES" :key="characterClass" class="pw-check">
            <input v-model="settings[characterClass]" type="checkbox" :disabled="isLastActiveClass(settings, characterClass)" />
            <span>{{ t(`freeTools.items.passwordGenerator.classes.${characterClass}`) }}</span>
          </label>
          <label class="pw-check pw-check--wide">
            <input v-model="settings.excludeAmbiguous" type="checkbox" />
            <span>{{ t('freeTools.items.passwordGenerator.excludeAmbiguous') }}</span>
          </label>
        </fieldset>
      </div>

      <p class="pw-privacy">{{ t('freeTools.items.passwordGenerator.privacy') }}</p>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { generatePassword, scorePassword } from '@projectellysia/acheron-core-js'
import ToolShell from '@/components/shared/ToolShell.vue'
import { useToastStore } from '@/stores/toastStore'
import {
  CHARACTER_CLASSES,
  PASSWORD_LENGTH,
  characterKind,
  clampPasswordLength,
  isLastActiveClass,
  strengthLabelKey,
  toGeneratorOptions,
} from '@/components/freeTools/passwordGenerator'

/**
 * Generador de contraseñas gratuito de Acheron.
 *
 * Todo ocurre en el navegador: la contraseña se sortea con la Web Crypto API y
 * no se envía a ningún servidor, igual que en la bóveda.
 */
const { t } = useI18n()
const toast = useToastStore()

/** Cuánto se queda el botón en «Copiada» antes de volver a «Copiar». */
const COPIED_FEEDBACK_MS = 2000

const settings = reactive({
  length: PASSWORD_LENGTH.initial,
  uppercase: true,
  lowercase: true,
  digits: true,
  symbols: true,
  excludeAmbiguous: true,
})

const password = ref('')
const isCopied = ref(false)
let copiedTimer = null

const characters = computed(() => [...password.value])
const strength = computed(() => scorePassword(password.value))
const kindOf = characterKind

/** Sortea una contraseña nueva con los ajustes de ahora. */
function regenerate() {
  password.value = generatePassword(toGeneratorOptions(settings))
  isCopied.value = false
}

/** Copia la contraseña al portapapeles y lo avisa un instante en el botón. */
async function copy() {
  try {
    await navigator.clipboard.writeText(password.value)
  } catch {
    toast.show(t('freeTools.items.passwordGenerator.copyFailed'), 'error')
    return
  }
  isCopied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { isCopied.value = false }, COPIED_FEEDBACK_MS)
}

// Cualquier ajuste (longitud, tipos de carácter) sortea de nuevo: lo que se ve
// siempre corresponde a lo que está marcado.
watch(settings, regenerate, { deep: true, immediate: true })
onBeforeUnmount(() => clearTimeout(copiedTimer))
</script>

<style scoped>
.pw { display: flex; flex-direction: column; gap: 1.5rem; }

.pw-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Resultado ── */
.pw-result { display: flex; flex-direction: column; gap: 1rem; }
.pw-output {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: clamp(1.25rem, 3.4vw, 1.7rem);
  line-height: 1.5;
  letter-spacing: 0.04em;
  word-break: break-all;
  padding: 1rem 1.1rem;
  min-height: 4.2rem;
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  user-select: all;
}
/* Cifras y símbolos con color propio: la contraseña se lee de un vistazo. */
.pw-char--letter { color: var(--text); }
.pw-char--digit { color: var(--accent-bright); }
.pw-char--symbol { color: var(--warn); }

.pw-actions { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.pw-btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.7rem 1.5rem;
  border-radius: 3px;
  border: 1px solid var(--accent);
  transition: all var(--transition);
}
.pw-btn--solid { background: var(--accent); color: var(--on-accent); min-width: 8.5rem; }
.pw-btn--solid:hover { background: var(--accent-bright); border-color: var(--accent-bright); }
.pw-btn--line { background: var(--accent-dim); color: var(--text); }
.pw-btn--line:hover { background: var(--accent); color: var(--on-accent); }
.pw-btn:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }

/* ── Solidez ── */
.pw-strength-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.45rem; }
.pw-strength-value { font-size: var(--fs-md); font-weight: 600; }
.pw-meter { height: 6px; border-radius: 3px; background: var(--border-med); overflow: hidden; }
.pw-meter-fill { display: block; height: 100%; border-radius: 3px; transition: width 0.25s ease, background 0.25s ease; }

/* ── Ajustes ── */
.pw-controls { display: flex; flex-direction: column; gap: 1.3rem; padding-top: 1.3rem; border-top: 1px solid var(--border-med); }
.pw-length { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 1rem; }
.pw-range { width: 100%; accent-color: var(--accent); }
.pw-number {
  width: 4.6rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  text-align: center;
  padding: 0.4rem 0.3rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.pw-number:focus-visible, .pw-range:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

.pw-classes {
  border: 0; padding: 0; margin: 0;
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.7rem 1.5rem;
}
.pw-classes .pw-label { grid-column: 1 / -1; padding: 0; margin-bottom: 0.1rem; }
.pw-check { display: flex; align-items: center; gap: 0.6rem; font-size: var(--fs-md); color: var(--text-dim); cursor: pointer; }
.pw-check input { width: 1.05rem; height: 1.05rem; accent-color: var(--accent); }
.pw-check input:disabled + span { opacity: 0.6; }
.pw-check--wide { grid-column: 1 / -1; }

.pw-privacy { font-size: var(--fs-sm); color: var(--text-muted); }

.sr-only {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 520px) {
  .pw-length { grid-template-columns: 1fr auto; }
  .pw-length .pw-label { grid-column: 1 / -1; }
  .pw-classes { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .pw-meter-fill { transition: none; }
}
</style>
