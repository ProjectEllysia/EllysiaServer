<template>
  <p class="surface-closed" role="note">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
    <span>{{ message }}</span>
  </p>
</template>

<script setup>
/**
 * Aviso que sustituye a una función cerrada al público (general.launch).
 *
 * Se pinta donde estaría el formulario o el botón de la función, para que
 * quien entra sepa que existe y que todavía no se puede usar, en vez de
 * encontrarse un hueco.
 */
defineProps({
  /** Qué no está disponible, en una frase completa. */
  message: { type: String, required: true },
})
</script>

<style scoped>
.surface-closed {
  display: flex; align-items: center; gap: 0.6rem;
  margin: 0 0 1.1rem;
  padding: 0.8rem 1rem;
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text-dim);
  font-size: var(--fs-md);
}
.surface-closed svg { width: 16px; height: 16px; flex-shrink: 0; color: var(--text-muted); }
</style>
