<template>
  <Teleport to="body">
    <Transition name="modal">
      <!-- `data-module` en el overlay, no en la página: Teleport saca este nodo
           de la raíz de la vista y sin esto heredaría el acento dorado. -->
      <div v-if="show" class="modal-overlay" data-module="hygeia" @click.self="$emit('close')">
        <div class="modal-box">
          <div class="modal-header">
            <h3>{{ t('hygeia.inventoryReport.title') }}</h3>
            <button class="close-btn" :aria-label="t('common.close')" @click="$emit('close')">&times;</button>
          </div>

          <form class="modal-body" @submit.prevent="submit">
            <fieldset class="scope">
              <legend class="field-label">{{ t('hygeia.inventoryReport.include') }}</legend>

              <label class="option">
                <input v-model="scope" type="radio" value="user" />
                <span class="option-title">{{ t('hygeia.inventoryReport.mine') }}</span>
                <small class="option-hint">{{ ownScopeHint }}</small>
              </label>

              <label class="option" :class="{ 'option--off': !canUseOrganization }">
                <input v-model="scope" type="radio" value="organization" :disabled="!canUseOrganization" />
                <span class="option-title">{{ t('hygeia.inventoryReport.organization') }}</span>
                <small class="option-hint">{{ organizationHint }}</small>
              </label>
            </fieldset>

            <label class="option">
              <input v-model="includeSoftware" type="checkbox" />
              <span class="option-title">{{ t('hygeia.inventoryReport.software') }}</span>
              <small class="option-hint">{{ t('hygeia.inventoryReport.softwareHint') }}</small>
            </label>

            <p class="note">{{ t('hygeia.inventoryReport.note') }}</p>

            <div class="modal-footer">
              <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.cancel') }}</button>
              <button type="submit" class="btn-primary" :disabled="generating">
                {{ generating ? t('hygeia.inventoryReport.requesting') : t('hygeia.inventoryReport.submit') }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  show: { type: Boolean, default: false },
  /** Cuántos activos propios hay, solo para que la opción diga algo concreto. */
  assetCount: { type: Number, default: 0 },
  /** La organización del usuario, o null. Viene de `accountStore.organization`. */
  organization: { type: Object, default: null },
  /** Si la petición del documento está en curso; desactiva el botón. */
  generating: { type: Boolean, default: false },
})
const emit = defineEmits(['submit', 'close'])

const scope = ref('user')
const includeSoftware = ref(false)

/**
 * El ámbito de organización es solo del dueño.
 *
 * Hoy no hay rol intermedio entre `owner` y `member`, y el informe lista los
 * hostnames y el software de todos los compañeros: el backend lo rechaza con
 * un 403, y aquí se refleja en vez de dejar pulsar para fallar después.
 */
const canUseOrganization = computed(() => props.organization?.isOwner === true)

/** «Los 1 activos» no lo dice nadie: la clave tiene forma singular. */
const ownScopeHint = computed(() =>
  t('hygeia.inventoryReport.mineHint', { count: props.assetCount }, props.assetCount),
)

/** Se deshabilita con explicación, no se oculta: una opción que desaparece
 *  parece que no existe; una deshabilitada que dice por qué, enseña. */
const organizationHint = computed(() => {
  if (!props.organization) return t('hygeia.inventoryReport.noOrganization')
  if (!canUseOrganization.value) {
    return t('hygeia.inventoryReport.ownerOnly', { name: props.organization.name })
  }
  const count = props.organization.memberCount ?? 0
  return t('hygeia.inventoryReport.organizationHint', { count, name: props.organization.name }, count)
})

watch(() => props.show, (visible) => {
  if (!visible) return
  scope.value = 'user'
  includeSoftware.value = false
})

function submit() {
  emit('submit', { scope: scope.value, includeSoftware: includeSoftware.value })
}
</script>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 9999; padding: 1rem; }
.modal-box { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; width: 100%; max-width: 440px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 0.85rem 1.1rem; border-bottom: 1px solid var(--border); }
.modal-header h3 { margin: 0; font-size: var(--fs-xl); color: var(--text); }
.close-btn { background: none; border: none; color: var(--text-muted); font-size: var(--fs-xl); cursor: pointer; }
.modal-body { padding: 1rem 1.1rem; }

.field-label { font-size: var(--fs-sm); color: var(--text-muted); padding: 0; }
.scope { border: none; margin: 0 0 0.85rem; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }

/* Rejilla de dos filas en vez de flex con `margin-top` a ojo: el control y su
   título comparten la fila 1, así que `align-items: center` los alinea entre
   sí, y la explicación cae en la fila 2 bajo el título. Con flex había que
   empujar el control con un margen fijo, y las fuentes de aquí son fluidas
   (`--fs-md` es un `clamp()`): el número acertaba a un ancho de ventana y
   fallaba en todos los demás. */
.option {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 0.5rem;
  row-gap: 0.1rem;
  align-items: center;
  cursor: pointer;
}
.option input {
  grid-column: 1; grid-row: 1;
  margin: 0;
  accent-color: var(--accent);
}
.option-title {
  grid-column: 2; grid-row: 1;
  font-size: var(--fs-md); color: var(--text);
}
.option-hint {
  grid-column: 2; grid-row: 2;
  font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.4;
}
.option--off { cursor: not-allowed; opacity: 0.55; }

/* La casilla del anexo es una opción más, con el mismo molde, pero separada
   del grupo de ámbito: no es una alternativa, es un añadido. */
.scope + .option { margin-bottom: 0.85rem; }

.note { color: var(--text-muted); font-size: var(--fs-sm); line-height: 1.5; margin: 0 0 0.6rem; }

.modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.4rem; }
.btn-secondary, .btn-primary { padding: 0.45rem 0.9rem; border-radius: 6px; font-size: var(--fs-md); font-weight: 600; cursor: pointer; }
.btn-secondary { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); }
.btn-secondary:hover { border-color: var(--text-muted); color: var(--text); }
.btn-primary { background: var(--accent); border: 1px solid var(--accent); color: var(--on-accent); }
.btn-primary:hover:not(:disabled) { background: var(--accent-bright); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

.modal-enter-active, .modal-leave-active { transition: opacity 0.2s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
