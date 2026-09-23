<template>
  <Transition name="preview-banner">
    <aside v-if="isVisible" class="preview-banner" role="status">
      <span class="preview-dot" aria-hidden="true"></span>
      <span>Ellysia está en vista previa. Algunas funciones están cerradas mientras completamos su marco legal.</span>
      <button type="button" class="preview-close" aria-label="Cerrar el aviso de vista previa" @click="dismiss">&times;</button>
    </aside>
  </Transition>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useLaunch } from '@/composables/useLaunch'

/**
 * Aviso de que la instalación está en vista previa (general.launch).
 *
 * Solo aparece cuando el servidor ha confirmado el modo: antes de la
 * respuesta todo cuenta como cerrado, pero anunciar una vista previa que
 * quizá no lo es sería decir algo falso. Se puede cerrar, y queda cerrado
 * durante la visita (sessionStorage), no para siempre: quien vuelve otro día
 * tiene que volver a saberlo.
 */

const DISMISSED_KEY = 'ellysia_preview_banner_dismissed'

const { isLoaded, isPreview } = useLaunch()

/** Lee si ya se cerró en esta visita; sin almacenamiento, no se recuerda. */
function readDismissed() {
  try {
    return sessionStorage.getItem(DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

const isDismissed = ref(readDismissed())
const isVisible = computed(() => isLoaded.value && isPreview.value && !isDismissed.value)

/** Oculta el aviso y lo recuerda hasta que termine la visita. */
function dismiss() {
  isDismissed.value = true
  try {
    sessionStorage.setItem(DISMISSED_KEY, '1')
  } catch {
    /* sin almacenamiento, el aviso volverá en la próxima carga */
  }
}
</script>

<style scoped>
.preview-banner {
  position: fixed; left: 50%; bottom: 1rem; transform: translateX(-50%);
  z-index: 900;
  display: flex; align-items: center; gap: 0.6rem;
  max-width: min(640px, calc(100vw - 2rem));
  padding: 0.55rem 0.6rem 0.55rem 0.9rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 999px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  color: var(--text-dim);
  font-size: var(--fs-md);
}
.preview-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
.preview-close {
  flex-shrink: 0;
  width: 1.6rem; height: 1.6rem; border-radius: 50%;
  border: none; background: none; color: var(--text-muted);
  font-size: 1.15rem; line-height: 1; cursor: pointer;
}
.preview-close:hover { background: var(--surface-2); color: var(--text); }
.preview-banner-enter-active, .preview-banner-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.preview-banner-enter-from, .preview-banner-leave-to { opacity: 0; transform: translate(-50%, 8px); }
@media (max-width: 600px) {
  .preview-banner { border-radius: 12px; bottom: 0.75rem; }
}
</style>
