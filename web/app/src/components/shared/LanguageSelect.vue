<template>
  <label class="language-select">
    <span class="sr-only">{{ t('language.label') }}</span>
    <select :value="activeLocale" :title="t('language.label')" @change="setLocale($event.target.value)">
      <option v-for="option in options" :key="option.code" :value="option.code" :lang="option.code">
        {{ option.name }}
      </option>
    </select>
  </label>
</template>

<script setup>
/**
 * Selector del idioma de la interfaz.
 *
 * Cada idioma se ofrece con su propio nombre («Español», «English»), no
 * traducido al idioma activo: quien no entiende el idioma en que está la
 * pantalla tiene que poder reconocer el suyo. El nombre sale de la clave
 * `language.name` de cada fichero de `locales/`, así que un idioma nuevo
 * aparece aquí solo con añadir su fichero.
 *
 * La elección se recuerda en este dispositivo (ver `setLocale`).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { AVAILABLE_LOCALES, i18n, setLocale } from '@/i18n'
import { activeLocale } from '@/i18n/locale.js'

const { t } = useI18n()

/**
 * Idiomas disponibles, cada uno con el nombre que se da a sí mismo.
 *
 * @type {import('vue').ComputedRef<Array<{ code: string, name: string }>>}
 */
const options = computed(() => AVAILABLE_LOCALES.map((code) => ({
  code,
  name: i18n.global.getLocaleMessage(code)?.language?.name ?? code,
})))
</script>

<style scoped>
.language-select select {
  height: 40px;
  padding: 0 0.7rem;
  border-radius: 20px;
  border: 1px solid var(--border-med);
  background: transparent;
  color: var(--accent);
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 500;
  letter-spacing: 0.08em;
  cursor: pointer;
  transition: all var(--transition);
}
.language-select select:hover { border-color: var(--accent); box-shadow: 0 0 12px var(--accent-dim); }
.language-select select:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }
.language-select option { background: var(--surface); color: var(--text); }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
</style>
