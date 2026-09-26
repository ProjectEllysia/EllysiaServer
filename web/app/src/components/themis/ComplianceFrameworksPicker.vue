<template>
  <!-- Sin preferencias no se pinta nada: o aún cargan, o el usuario no tiene
       acceso a los escaneos y la sección no le dice nada. -->
  <section v-if="preferences">
    <slot />

    <template v-if="scope === 'organization'">
      <label class="option option--impose">
        <input type="checkbox" :checked="isImposing" :disabled="saving" @change="setImposing($event.target.checked)" />
        <span>{{ t('themis.compliance.impose') }}</span>
      </label>
      <p v-if="!isImposing" class="hint">{{ t('themis.compliance.notImposing') }}</p>
    </template>

    <p v-else-if="preferences.isLockedByOrganization" class="hint">{{ t('themis.compliance.locked') }}</p>

    <div class="options">
      <label v-for="framework in preferences.frameworks" :key="framework.key" class="option">
        <input type="checkbox" :checked="selected.includes(framework.key)" :disabled="isDisabled"
               @change="toggle(framework.key)" />
        <span>{{ framework.name }}</span>
      </label>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/**
 * Elección de los marcos de cumplimiento (ISO 27001, ENS, NIS2) que salen en
 * los informes de Lybra.
 *
 * Con `scope="user"` guarda la elección propia; si la organización del usuario
 * ha fijado la suya, la enseña bloqueada, porque es la que manda. Con
 * `scope="organization"` guarda la que el dueño impone a sus miembros, o la
 * retira para que cada uno use la suya.
 *
 * El contenido del slot (título y descripción) lo pone la vista, con sus
 * propios estilos.
 */
const props = defineProps({
  /** 'user' para el perfil, 'organization' para la organización propia. */
  scope: { type: String, required: true, validator: value => ['user', 'organization'].includes(value) },
})

const { apiFetch, apiError } = useApi()
const toast = useToastStore()

const preferences = ref(null)
const saving = ref(false)

const isImposing = computed(() => preferences.value?.organization != null)
const isDisabled = computed(() => saving.value || (props.scope === 'organization'
  ? !isImposing.value
  : preferences.value.isLockedByOrganization))

/** Los marcos marcados: los que se aplican si manda la organización, si no los propios. */
const selected = computed(() => {
  if (props.scope === 'organization') return preferences.value.organization ?? []
  return preferences.value.isLockedByOrganization ? preferences.value.organization : (preferences.value.mine ?? [])
})

async function load() {
  const res = await apiFetch('/themis/compliance')
  if (res?.ok) preferences.value = await res.json()
}

/**
 * Guarda una elección y deja en pantalla la respuesta del servidor.
 *
 * @param {string[]|null} frameworks - Claves elegidas; null deja de elegir
 *   (en la organización, deja de imponerlas).
 */
async function save(frameworks) {
  saving.value = true
  try {
    const path = props.scope === 'organization' ? 'organization-frameworks' : 'frameworks'
    const res = await apiFetch(`/themis/compliance/${path}`, {
      method: 'PUT',
      body: JSON.stringify({ frameworks }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, t('themis.compliance.saveFailed')), 'error')
      return
    }
    preferences.value = await res.json()
    toast.show(t('themis.compliance.saved'), 'success')
  } finally {
    saving.value = false
  }
}

/**
 * Marca o desmarca un marco, conservando el orden del catálogo.
 *
 * @param {string} key - Clave del marco.
 */
function toggle(key) {
  const chosen = new Set(selected.value)
  if (chosen.has(key)) chosen.delete(key)
  else chosen.add(key)
  const frameworks = preferences.value.frameworks.map(framework => framework.key).filter(k => chosen.has(k))
  // Un usuario sin marcos vuelve a «no he elegido»; una organización que los
  // impone puede imponer «ninguno».
  save(props.scope === 'user' && !frameworks.length ? null : frameworks)
}

/**
 * Activa o retira los marcos que la organización impone a sus miembros.
 *
 * @param {boolean} on - true para imponerlos (empezando por ninguno), false para retirarlos.
 */
function setImposing(on) {
  save(on ? [] : null)
}

onMounted(load)
</script>

<style scoped>
.options { display: flex; flex-wrap: wrap; gap: 0.6rem 1.4rem; margin-top: 0.6rem; }
.option { display: inline-flex; align-items: center; gap: 0.45rem; font-size: var(--fs-md); cursor: pointer; }
.option--impose { margin: 0.6rem 0 0.4rem; font-weight: 600; }
.option input:disabled + span { color: var(--text-dim); }
.hint { font-size: var(--fs-sm); color: var(--text-dim); margin: 0 0 0.8rem; }
</style>
