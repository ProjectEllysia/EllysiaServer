<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="show" class="modal-overlay" @click.self="$emit('cancel')">
        <div class="modal-box" role="dialog" aria-modal="true" :aria-label="t('authorizeTarget.title', { target })">
          <div class="modal-header">
            <h3>{{ t('authorizeTarget.title', { target }) }}</h3>
            <button type="button" class="close-btn" :aria-label="t('confirm.close')" @click="$emit('cancel')">&times;</button>
          </div>
          <div class="modal-body">
            <p class="intro">{{ t('authorizeTarget.intro') }}</p>
            <label class="declaration">
              <input v-model="accepted" type="checkbox" />
              <span>{{ t('authorizeTarget.declaration') }}</span>
            </label>
            <p class="evidence">{{ t('authorizeTarget.evidence') }}
              <router-link to="/terminos" target="_blank">{{ t('authorizeTarget.policy') }}</router-link>
            </p>
            <div class="modal-footer">
              <button type="button" class="btn-secondary" @click="$emit('cancel')">{{ t('confirm.cancel') }}</button>
              <button type="button" class="btn-primary" :disabled="!accepted" @click="$emit('confirm')">
                {{ t('authorizeTarget.confirm') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
/**
 * Declaración del titular que se firma al autorizar un objetivo: el usuario
 * afirma que el sistema es suyo o que su titular le ha autorizado a analizarlo.
 * El botón no se activa hasta que marca la casilla, y el servidor guarda la
 * versión del texto (`authorizationDeclaration.js`), la fecha y la IP.
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  /** Si el modal está abierto. */
  show: { type: Boolean, default: false },
  /** Objetivo que se va a autorizar, tal como lo escribió el usuario. */
  target: { type: String, default: '' },
})
defineEmits(['confirm', 'cancel'])

const { t } = useI18n()
const accepted = ref(false)

// Cada vez que se abre, la casilla vuelve a estar sin marcar: la declaración se
// acepta objetivo a objetivo, no una vez por sesión.
watch(() => props.show, () => { accepted.value = false })
</script>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 9999; padding: 1rem; }
.modal-box { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; width: 100%; max-width: 520px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 0.85rem 1.1rem; border-bottom: 1px solid var(--border); }
.modal-header h3 { margin: 0; font-size: var(--fs-xl); color: var(--text); overflow-wrap: anywhere; }
.close-btn { background: none; border: none; color: var(--text-muted); font-size: var(--fs-xl); cursor: pointer; }
.modal-body { padding: 1rem 1.1rem; }
.intro { margin: 0 0 1rem; color: var(--text-dim); font-size: var(--fs-lg); line-height: 1.6; }
.declaration { display: flex; gap: 0.6rem; align-items: flex-start; padding: 0.8rem 0.9rem; border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: var(--fs-lg); line-height: 1.5; cursor: pointer; }
.declaration input { margin-top: 0.3rem; }
.evidence { margin: 0.9rem 0 0; color: var(--text-muted); font-size: var(--fs-md); line-height: 1.5; }
.evidence a { color: var(--accent); }
.modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 0.75rem 0 0; }
.btn-secondary, .btn-primary { padding: 0.45rem 0.9rem; border-radius: 6px; font-size: var(--fs-lg); font-weight: 500; cursor: pointer; transition: all 0.2s; }
.btn-secondary { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); }
.btn-secondary:hover { border-color: var(--text-muted); color: var(--text); }
.btn-primary { background: var(--accent); border: 1px solid var(--accent); color: var(--on-accent); }
.btn-primary:hover { opacity: 0.9; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.modal-enter-active, .modal-leave-active { transition: opacity 0.2s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .modal-enter-active, .modal-leave-active { transition: none !important; }
}
</style>
