<template>
  <label class="language-select">
    <span class="sr-only">{{ t('language.label') }}</span>
    <select :value="selectedValue" :title="t('language.label')" :disabled="saving" @change="choose($event.target)">
      <option v-if="isAuthenticated" :value="FOLLOW_UPPER_LEVEL">{{ followUpperLevelLabel }}</option>
      <option v-for="option in LOCALE_OPTIONS" :key="option.code" :value="option.code" :lang="option.code">
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
 * Sin sesión, la elección solo se recuerda en este dispositivo. Con sesión se
 * guarda en el perfil, y el selector ofrece además volver a seguir el idioma
 * de la organización (o el de la plataforma, si no hay organización): la
 * elección de una persona es explícita, nunca se rellena por su cuenta.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { LOCALE_OPTIONS, localeName, setLocale } from '@/i18n'
import { activeLocale } from '@/i18n/locale.js'
import { useAuthStore } from '@/stores/authStore'
import { useAccountStore } from '@/stores/accountStore'
import { useProfileStore } from '@/stores/profileStore'

/** Valor de la opción «seguir el nivel de arriba»: se guarda como `null`. */
const FOLLOW_UPPER_LEVEL = ''

const { t } = useI18n()
const auth = useAuthStore()
const account = useAccountStore()
const profileStore = useProfileStore()

const saving = ref(false)

const isAuthenticated = computed(() => auth.isAuthenticated)

/**
 * Opción marcada: con sesión, lo que el usuario eligió en su perfil (o la de
 * seguir al nivel de arriba si no eligió); sin sesión, el idioma activo.
 */
const selectedValue = computed(() => (
  isAuthenticated.value ? (profileStore.profile.language ?? FOLLOW_UPPER_LEVEL) : activeLocale.value
))

/**
 * Rótulo de la opción de seguir al nivel de arriba, con el idioma que resulta
 * entre paréntesis para que se sepa qué se va a ver.
 *
 * Ese idioma solo se conoce con certeza cuando el usuario no ha elegido (el
 * efectivo es entonces el del nivel de arriba) o cuando la organización fija
 * uno; si el usuario eligió y su organización no fija ninguno, el de la
 * plataforma no llega a la interfaz y el rótulo va sin paréntesis.
 */
const followUpperLevelLabel = computed(() => {
  const label = t(account.organization ? 'language.followOrganization' : 'language.followPlatform')
  const upperLevel = profileStore.profile.language === null
    ? profileStore.profile.effectiveLanguage
    : account.organization?.defaultLanguage
  return upperLevel ? `${label} (${localeName(upperLevel)})` : label
})

/**
 * Aplica la opción elegida.
 *
 * Si el servidor no la guarda, el desplegable vuelve a la opción que había:
 * el valor ligado no ha cambiado, así que Vue no lo repintaría por su cuenta.
 *
 * @param {HTMLSelectElement} select - El desplegable; su `value` es el código
 *   del idioma o `FOLLOW_UPPER_LEVEL`.
 */
async function choose(select) {
  if (!isAuthenticated.value) {
    setLocale(select.value)
    return
  }
  saving.value = true
  try {
    const saved = await profileStore.updateLanguage(
      select.value === FOLLOW_UPPER_LEVEL ? null : select.value, t('language.saveFailed'),
    )
    if (!saved) select.value = selectedValue.value
  } finally {
    saving.value = false
  }
}
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
.language-select select:disabled { opacity: 0.6; cursor: wait; }
.language-select option { background: var(--surface); color: var(--text); }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
</style>
