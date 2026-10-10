<template>
  <p v-if="isManagedByOwner" class="managed-notice" role="note">
    <i18n-t keypath="organizationManaged.notice" tag="span">
      <template #organization><strong>{{ info.organizationName }}</strong></template>
      <template #owner><strong>{{ info.ownerDisplayName }}</strong></template>
    </i18n-t>
  </p>
</template>

<script setup>
/**
 * Aviso para un miembro de una organización: los datos corporativos los
 * gestiona su dueño, así que los ve en solo lectura, y los suyos siguen
 * guardados.
 *
 * No pinta nada para quien trabaja sobre sus propios datos. Recibe la
 * titularidad (`ownership`, lo que devuelve `describe_data_ownership`) de quien
 * ya la tiene —el perfil de empresa la trae en su respuesta— o la pide a
 * `/organizations/data-ownership` si no se le pasa.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useApi } from '@/composables/useApi'

const props = defineProps({
  /** `{ isOwnData, organizationName, ownerDisplayName }`; si falta, se consulta a la API. */
  ownership: { type: Object, default: null },
})

const { apiFetch } = useApi()
const fetched = ref(null)

const info = computed(() => props.ownership ?? fetched.value ?? { isOwnData: true })
const isManagedByOwner = computed(() => info.value.isOwnData === false)

/** Pide la titularidad solo cuando el padre no la trae. */
async function load() {
  if (props.ownership) return
  const res = await apiFetch('/organizations/data-ownership')
  if (res.ok) fetched.value = await res.json()
}

onMounted(load)
watch(() => props.ownership, load)
</script>

<style scoped>
.managed-notice {
  margin-top: 0.9rem; padding: 0.8rem 1rem; border-radius: 6px;
  border: 1px solid var(--border-med); background: var(--surface-2, var(--bg));
  color: var(--text-dim); font-size: var(--fs-body); max-width: 62ch;
}
.managed-notice strong { color: var(--text); font-weight: 600; }
</style>
