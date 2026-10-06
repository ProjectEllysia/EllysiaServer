<template>
  <div class="connections-page" data-module="iris">
    <StarBackground />
    <Topbar :title="'Iris'" :badge="t('iris.connections.badge')" back-to="/iris/analisis" :back-label="t('iris.batch.analysis')" />

    <div class="connections-layout">
      <section class="connect-panel">
        <p class="panel-eyebrow">{{ t('iris.connections.eyebrow') }}</p>
        <h2 class="panel-title">{{ t('iris.connections.title') }}</h2>
        <i18n-t keypath="iris.connections.intro" tag="p" class="panel-sub">
          <template #history>
            <router-link to="/iris/analisis" class="inline-link">{{ t('iris.connections.history') }}</router-link>
          </template>
        </i18n-t>

        <label class="remediation-toggle">
          <input v-model="remediationEnabled" type="checkbox" />
          <span>
            <strong>{{ t('iris.connections.remediation') }}</strong>
            <span class="remediation-hint">{{ t('iris.connections.remediationHint') }}</span>
          </span>
        </label>

        <div v-if="store.providers.length" class="provider-grid">
          <button
            v-for="(provider, index) in store.providers"
            :key="provider"
            type="button"
            class="provider-card"
            :style="{ '--card-delay': index * 60 + 'ms' }"
            :disabled="store.connecting"
            @click="store.connect(provider, { remediationEnabled })"
          >
            <span class="provider-icon">
              <svg v-if="provider === 'gmail'" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="2" y="4" width="20" height="16" rx="2" fill="#ea4335" opacity="0.14" />
                <rect x="2" y="4" width="20" height="16" rx="2" fill="none" stroke="#ea4335" stroke-width="1.4" />
                <path d="M2.5 6.2l9.5 6.6 9.5-6.6" fill="none" stroke="#ea4335" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <svg v-else-if="provider === 'microsoft'" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="2" y="2" width="9" height="9" fill="#f35325" />
                <rect x="13" y="2" width="9" height="9" fill="#81bc06" />
                <rect x="2" y="13" width="9" height="9" fill="#05a6f0" />
                <rect x="13" y="13" width="9" height="9" fill="#ffba08" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <rect x="2" y="4" width="20" height="16" rx="2" /><path d="m2 7 10 6 10-6" />
              </svg>
            </span>
            <span class="provider-text">
              <span class="provider-label">{{ providerLabel(provider) }}</span>
              <span class="provider-cta">{{ store.connecting ? t('iris.connections.connecting') : t('iris.connections.connect') }}</span>
            </span>
            <svg class="provider-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18l6-6-6-6" /></svg>
          </button>
        </div>

        <details class="imap-panel">
          <summary>{{ t('iris.imap.title') }}</summary>
          <p class="panel-sub">{{ t('iris.imap.intro') }}</p>
          <form @submit.prevent="submitImap">
            <ImapConnectFields v-model="imapForm" />
            <div class="imap-actions">
              <button type="submit" class="btn-primary" :disabled="store.connecting || !isImapReady">
                {{ store.connecting ? t('iris.connections.connecting') : t('iris.connections.connect') }}
              </button>
            </div>
          </form>
        </details>
      </section>

      <section class="list-panel">
        <MailboxConnectionList
          :connections="store.connections"
          :loading="store.loading"
          :error="store.listError"
          :syncing-ids="store.syncingIds"
          @refresh="store.fetchConnections"
          @reconnect="conn => store.connect(conn.provider, { remediationEnabled: conn.remediationEnabled })"
          @toggle-pause="handleTogglePause"
          @sync="handleSync"
          @delete="handleDeleteRequest"
          @folders="conn => (foldersConnection = conn)"
          @rotate="conn => (passwordConnection = conn)"
        />
      </section>
    </div>

    <MailboxFoldersModal :connection="foldersConnection" @close="foldersConnection = null" @saved="foldersConnection = null" />
    <MailboxPasswordModal :connection="passwordConnection" @close="passwordConnection = null" @saved="passwordConnection = null" />

    <ConfirmModal
      :show="pendingDelete !== null"
      :title="t('iris.connections.deleteTitle')"
      danger
      :confirm-label="t('common.delete')"
      :message="pendingDelete ? t('iris.connections.deleteMessage', { email: pendingDelete.accountEmail }) : ''"
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import MailboxConnectionList from '@/components/iris/MailboxConnectionList.vue'
import ImapConnectFields from '@/components/iris/ImapConnectFields.vue'
import MailboxFoldersModal from '@/components/iris/MailboxFoldersModal.vue'
import MailboxPasswordModal from '@/components/iris/MailboxPasswordModal.vue'
import { useIrisMailboxStore } from '@/stores/irisMailboxStore'
import { useToastStore } from '@/stores/toastStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useIrisMailboxStore()
const toast = useToastStore()
const route = useRoute()
const router = useRouter()

const pendingDelete = ref(null)
/** Si la próxima conexión pide permiso para actuar sobre el buzón (por defecto, solo lectura). */
const remediationEnabled = ref(false)
/** Conexión cuyas carpetas se están eligiendo, o null. */
const foldersConnection = ref(null)
/** Conexión IMAP cuya contraseña se está cambiando, o null. */
const passwordConnection = ref(null)
/** Formulario de un buzón IMAP; solo TLS directo, de ahí el 993. */
const imapForm = ref({ host: '', port: 993, username: '', password: '' })
const isImapReady = computed(() => Boolean(imapForm.value.host && imapForm.value.username && imapForm.value.password))

async function submitImap() {
  if (await store.connectImap({ ...imapForm.value })) {
    imapForm.value = { host: '', port: 993, username: '', password: '' }
  }
}

const PROVIDER_LABELS = { microsoft: 'Microsoft 365', gmail: 'Gmail' }
function providerLabel(provider) { return PROVIDER_LABELS[provider] || provider }

/** Errores con los que vuelve el callback OAuth; texto en `iris.connections.callbackErrors`. */
const CALLBACK_ERRORS = ['consent_denied', 'missing_code', 'invalid_state', 'connection_failed']

onMounted(async () => {
  // El backend redirige aquí tras el callback OAuth con ?connected=1 o
  // ?error=... en la URL (no hay Bearer token disponible en esa navegación
  // de servidor, así que el resultado viaja por query string). Se limpia
  // con router.replace para que un refresco de página no repita el toast.
  if (route.query.connected) {
    toast.show(t('iris.connections.connected'), 'success')
    router.replace({ query: {} })
  } else if (route.query.error) {
    toast.show(CALLBACK_ERRORS.includes(route.query.error) ? t(`iris.connections.callbackErrors.${route.query.error}`) : t('iris.connections.failed'), 'error')
    router.replace({ query: {} })
  }

  await store.fetchProviders()
  await store.fetchConnections()
})

function handleTogglePause(connection) {
  const nextStatus = connection.status === 'paused' ? 'active' : 'paused'
  store.updateConnection(connection.connectionId, { status: nextStatus })
}

// Los emits de MailboxConnectionList llevan siempre la conexión completa.
function handleSync(connection) {
  store.syncConnection(connection.connectionId)
}

function handleDeleteRequest(connection) {
  pendingDelete.value = connection
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  await store.deleteConnection(pendingDelete.value.connectionId)
  pendingDelete.value = null
}
</script>

<style scoped>
.connections-page {
  min-height: 100vh;
  background: var(--bg);
  padding-top: var(--topbar-h);
  position: relative;
}

.connections-layout {
  position: relative;
  z-index: 1;
  max-width: 820px;
  margin: 0 auto;
  padding: 2rem 1.25rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.connect-panel {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  padding: 1.4rem 1.6rem;
  animation: seq-fade-up 0.35s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}
.list-panel {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  padding: 1.4rem 1.6rem;
  animation: seq-fade-up 0.35s cubic-bezier(0.22, 1, 0.36, 1) backwards;
  animation-delay: 0.08s;
}

.panel-eyebrow {
  margin: 0 0 0.3rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs);
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--accent);
}
.panel-title { margin: 0 0 0.5rem; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); font-weight: 700; color: var(--text); }
.panel-sub { margin: 0 0 1.2rem; font-size: var(--fs-body); line-height: 1.55; color: var(--text-dim); max-width: 62ch; }
.inline-link { color: var(--accent-bright); text-decoration: underline; text-underline-offset: 2px; }

.remediation-toggle {
  display: flex; align-items: flex-start; gap: 0.6rem; margin: 0 0 1rem;
  font-size: var(--fs-md); color: var(--text);
}
.remediation-toggle input { margin-top: 0.25rem; }
.remediation-hint { display: block; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.imap-panel { margin-top: 1.2rem; border-top: 1px solid var(--border); padding-top: 1rem; }
.imap-panel summary { cursor: pointer; font-weight: 700; color: var(--text); margin-bottom: 0.6rem; }
.imap-actions { display: flex; justify-content: flex-end; margin-top: 0.8rem; }
.provider-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 0.75rem; }

.provider-card {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--border-med); border-radius: 10px;
  background: var(--surface-2);
  cursor: pointer;
  text-align: left;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s, background 0.15s;
  animation: seq-fade-up 0.3s cubic-bezier(0.22, 1, 0.36, 1) backwards;
  animation-delay: var(--card-delay, 0ms);
}
.provider-card:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--surface-3);
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(0,0,0,0.22);
}
.provider-card:disabled { opacity: 0.6; cursor: default; }

.provider-icon { width: 34px; height: 34px; flex-shrink: 0; border-radius: 7px; overflow: hidden; }
.provider-icon svg { width: 100%; height: 100%; }

.provider-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.1rem; }
.provider-label { font-size: var(--fs-lg); font-weight: 700; color: var(--text); }
.provider-cta { font-size: var(--fs-sm); color: var(--text-muted); }

.provider-arrow { width: 16px; height: 16px; flex-shrink: 0; color: var(--text-muted); transition: transform 0.15s, color 0.15s; }
.provider-card:hover:not(:disabled) .provider-arrow { transform: translateX(3px); color: var(--accent-bright); }

@media (prefers-reduced-motion: reduce) {
  .connect-panel, .list-panel, .provider-card { animation: none; }
  .provider-card:hover:not(:disabled) { transform: none; }
  .provider-card:hover:not(:disabled) .provider-arrow { transform: none; }
}
</style>
