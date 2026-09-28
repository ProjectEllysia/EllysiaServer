<template>
  <div class="imap-fields">
    <label class="field">
      <span>{{ t('iris.imap.host') }}</span>
      <input v-model.trim="model.host" type="text" autocomplete="off" :placeholder="t('iris.imap.hostPlaceholder')" />
    </label>
    <label class="field field--port">
      <span>{{ t('iris.imap.port') }}</span>
      <input v-model.number="model.port" type="number" min="1" max="65535" />
    </label>
    <label class="field">
      <span>{{ t('iris.imap.username') }}</span>
      <input v-model.trim="model.username" type="text" autocomplete="off" />
    </label>
    <label class="field">
      <span>{{ t('iris.imap.password') }}</span>
      <input v-model="model.password" type="password" autocomplete="new-password" />
    </label>
    <p class="imap-hint">{{ t('iris.imap.hint') }}</p>
  </div>
</template>

<script setup>
/**
 * Campos de un buzón IMAP (servidor, puerto, usuario y contraseña de
 * aplicación). Solo IMAP con TLS directo: el puerto por defecto es el 993.
 */
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/** `{host, port, username, password}`; lo rellena quien usa el componente. */
const model = defineModel({ type: Object, required: true })
</script>

<style scoped>
.imap-fields { display: grid; grid-template-columns: 1fr 110px; gap: 0.6rem 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; font-size: var(--fs-sm); color: var(--text-dim); }
.field input {
  padding: 0.5rem 0.65rem; border: 1px solid var(--border-med); border-radius: 8px;
  background: var(--surface-2); color: var(--text); font-size: var(--fs-md);
}
.field:nth-child(3), .field:nth-child(4) { grid-column: span 1; }
.imap-hint { grid-column: 1 / -1; margin: 0; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
@media (max-width: 560px) { .imap-fields { grid-template-columns: 1fr; } }
</style>
