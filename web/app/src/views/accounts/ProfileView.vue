<template>
  <div class="profile-page">
    <StarBackground />
    <Topbar :title="t('profilePage.topbar')" />

    <main class="main">
      <div v-if="store.loading" class="loading-block"><div class="skeleton skeleton--lg"></div></div>

      <template v-else>
        <section class="profile-header">
          <div class="profile-avatar">{{ initials }}</div>
          <h1 class="profile-display-name">{{ store.profile.first_name }} {{ store.profile.last_name }}</h1>
          <p class="profile-username">@{{ store.profile.username }}</p>
        </section>

        <section class="profile-section">
          <h2>{{ t('profilePage.personal') }}</h2>
          <form class="profile-form" @submit.prevent="handleProfileSubmit">
            <div class="form-row">
              <div class="form-group"><label for="first-name">{{ t('users.fields.firstName') }}</label><input id="first-name" v-model="firstName" type="text" required class="inp" :placeholder="t('profilePage.firstNamePlaceholder')" /></div>
              <div class="form-group"><label for="last-name">{{ t('users.fields.lastName') }}</label><input id="last-name" v-model="lastName" type="text" required class="inp" :placeholder="t('profilePage.lastNamePlaceholder')" /></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label for="profile-email">{{ t('users.fields.email') }}</label><input id="profile-email" type="email" :value="store.profile.email" disabled class="inp inp--disabled" /></div>
              <div class="form-group"><label for="profile-username">{{ t('users.fields.username') }}</label><input id="profile-username" type="text" :value="store.profile.username" disabled class="inp inp--disabled" /></div>
            </div>
            <div class="form-actions">
              <button type="button" class="btn btn--secondary" @click="$router.push('/')">{{ t('common.cancel') }}</button>
              <button type="submit" class="btn btn--primary" :disabled="savingProfile">{{ savingProfile ? t('common.saving') : t('profilePage.saveChanges') }}</button>
            </div>
          </form>
        </section>

        <section class="profile-section">
          <h2>{{ t('language.label') }}</h2>
          <p class="section-desc">{{ t('profilePage.languageDesc') }}</p>
          <LanguageSelect />
        </section>

        <ComplianceFrameworksPicker scope="user" class="profile-section">
          <h2>{{ t('profilePage.complianceTitle') }}</h2>
          <p class="section-desc">{{ t('profilePage.complianceDesc') }}</p>
        </ComplianceFrameworksPicker>

        <section class="profile-section">
          <h2>{{ t('profilePage.security') }}</h2>
          <form class="profile-form" @submit.prevent="handlePasswordSubmit">
            <div class="form-row form-row--single">
              <div class="form-group"><label for="current-pwd">{{ t('profilePage.currentPassword') }}</label><input id="current-pwd" v-model="currentPassword" type="password" required class="inp" placeholder="••••••••" /></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label for="new-pwd">{{ t('profilePage.newPassword') }}</label><input id="new-pwd" v-model="newPassword" type="password" required minlength="8" class="inp" :placeholder="t('users.create.passwordPlaceholder')" /></div>
              <div class="form-group"><label for="confirm-pwd">{{ t('profilePage.confirmPassword') }}</label><input id="confirm-pwd" v-model="confirmPassword" type="password" required minlength="8" class="inp" :placeholder="t('profilePage.repeatPassword')" /></div>
            </div>
            <p v-if="passwordError" class="form-error">{{ passwordError }}</p>
            <div class="form-actions">
              <button type="submit" class="btn btn--danger" :disabled="savingPassword">{{ savingPassword ? t('profilePage.changing') : t('profilePage.changePassword') }}</button>
            </div>
          </form>
        </section>

        <section id="mfa" class="profile-section">
          <h2>{{ t('profilePage.mfa.title') }}</h2>

          <Transition name="mfa-fade" mode="out-in">
            <!-- Códigos de recuperación: se muestran una sola vez tras confirmar -->
            <div v-if="recoveryCodes.length" key="recovery" class="mfa-recovery-codes">
              <p class="mfa-recovery-warning">{{ t('profilePage.mfa.recoveryWarning') }}</p>
              <ul class="mfa-recovery-list">
                <li v-for="c in recoveryCodes" :key="c"><code>{{ c }}</code></li>
              </ul>
              <div class="form-actions">
                <button type="button" class="btn btn--secondary" @click="downloadRecoveryCodes">{{ t('profilePage.mfa.download') }}</button>
                <button type="button" class="btn btn--primary" @click="recoveryCodes = []">{{ t('profilePage.mfa.saved') }}</button>
              </div>
            </div>

            <!-- Activado -->
            <div v-else-if="mfa.status.enabled" key="enabled">
              <p class="mfa-status-text mfa-status-text--on">{{ t('profilePage.mfa.enabled') }}</p>
              <form class="profile-form" @submit.prevent="handleDisableMfa">
                <div class="form-row form-row--single">
                  <div class="form-group">
                    <label for="disable-code">{{ t('profilePage.mfa.disableCode') }}</label>
                    <input id="disable-code" v-model="disableCode" type="text" class="inp" :placeholder="t('profilePage.mfa.disablePlaceholder')" required />
                  </div>
                </div>
                <div class="form-actions">
                  <button type="submit" class="btn btn--danger" :disabled="disabling">{{ disabling ? t('profilePage.mfa.disabling') : t('profilePage.mfa.disable') }}</button>
                </div>
              </form>
            </div>

            <!-- Sin activar -->
            <div v-else key="disabled">
              <p class="mfa-status-text">{{ t('profilePage.mfa.disabled') }}</p>
              <div class="form-actions">
                <button type="button" class="btn btn--primary" :disabled="startingSetup" @click="handleStartSetup">{{ startingSetup ? t('profilePage.mfa.generating') : t('session.enableMfa') }}</button>
              </div>
            </div>
          </Transition>
        </section>

        <!-- ───────── Baja de la cuenta ───────── -->
        <section class="profile-section profile-section--danger">
          <h2>{{ t('profilePage.delete.title') }}</h2>
          <p class="danger-text">{{ t('profilePage.delete.text') }}</p>

          <!-- La consecuencia sobre terceros: la que quien pulsa no tiene
               presente, y por eso va antes y destacada. -->
          <p v-if="deletion?.ownedOrganization" class="danger-warning">
            <strong>{{ t('profilePage.delete.orgDisappears', { name: deletion.ownedOrganization.name }) }}</strong>
            {{ membersWarning }}
            {{ t('profilePage.delete.membersKeep') }}
          </p>
          <p v-else-if="deletion?.leavesOrganizationId" class="danger-note">{{ t('profilePage.delete.leaves') }}</p>

          <form class="profile-form" @submit.prevent="askToDelete">
            <div class="form-row form-row--single">
              <div class="form-group">
                <label for="delete-pwd">{{ t('profilePage.delete.confirmPassword') }}</label>
                <input id="delete-pwd" v-model="deletePassword" type="password"
                       class="inp" placeholder="••••••••" required />
              </div>
            </div>
            <div class="form-actions">
              <button type="submit" class="btn btn--danger" :disabled="deleting">
                {{ deleting ? t('profilePage.delete.deleting') : t('profilePage.delete.title') }}
              </button>
            </div>
          </form>
        </section>
      </template>
    </main>

    <ConfirmModal
      :show="confirmDelete"
      :title="t('profilePage.delete.confirmTitle')"
      :message="confirmMessage"
      :danger="true"
      :confirm-label="t('profilePage.delete.confirmLabel')"
      @confirm="handleDelete"
      @cancel="confirmDelete = false"
    />

    <MfaSetupModal
      :open="!!mfa.pendingSetup.secret"
      :secret="mfa.pendingSetup.secret"
      :provisioning-uri="mfa.pendingSetup.provisioningUri"
      :confirming="confirming"
      @confirm="handleConfirmMfa"
      @cancel="mfa.cancelSetup()"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import LanguageSelect from '@/components/shared/LanguageSelect.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import MfaSetupModal from '@/components/shared/MfaSetupModal.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import ComplianceFrameworksPicker from '@/components/themis/ComplianceFrameworksPicker.vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { useProfileStore } from '@/stores/profileStore'
import { useAuthStore } from '@/stores/authStore'
import { useMfaStore } from '@/stores/mfaStore'
import { useUtils } from '@/composables/useUtils'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useProfileStore()
const auth = useAuthStore()
const mfa = useMfaStore()
const router = useRouter()

// Q15: tiempo para que el usuario alcance a leer el toast de éxito antes
// de que el cambio de contraseña fuerce el logout (revoca todos los tokens).
const POST_PASSWORD_CHANGE_LOGOUT_DELAY_MS = 2000
const { getInitials, triggerDownload } = useUtils()
const firstName = ref('')
const lastName = ref('')
const savingProfile = ref(false)
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const savingPassword = ref(false)
const passwordError = ref('')
const initials = computed(() => getInitials(store.profile.first_name, store.profile.last_name))

/* ── Baja de la cuenta ── */
const { apiFetch, apiError } = useApi()
const toast = useToastStore()

/** Lo que el servidor dice que se va a destruir. Se pide al entrar, no al
 *  pulsar: el aviso tiene que estar delante ANTES de escribir la contraseña. */
const deletion = ref(null)
const deletePassword = ref('')
const deleting = ref(false)
const confirmDelete = ref(false)

const membersWarning = computed(() => {
  const count = deletion.value?.ownedOrganization?.membersLosingAccess ?? 0
  return t('profilePage.delete.membersWarning', { count }, count)
})

const confirmMessage = computed(() => {
  const base = t('profilePage.delete.confirmBase')
  if (!deletion.value?.ownedOrganization) return base
  return t('profilePage.delete.confirmWithOrg', {
    base, name: deletion.value.ownedOrganization.name, members: membersWarning.value,
  })
})

async function loadDeletionPreview() {
  const res = await apiFetch('/users/me/deletion-preview')
  if (res?.ok) deletion.value = await res.json()
}

function askToDelete() {
  confirmDelete.value = true
}

async function handleDelete() {
  confirmDelete.value = false
  deleting.value = true
  try {
    const res = await apiFetch('/users/me', {
      method: 'DELETE',
      body: JSON.stringify({ password: deletePassword.value }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, t('profilePage.delete.failed')), 'error')
      return
    }
    toast.show(t('profilePage.delete.done'), 'success')
    auth.logout()
  } finally {
    deleting.value = false
    deletePassword.value = ''
  }
}

/* ── MFA (TOTP) ── */
const startingSetup = ref(false)
const confirming = ref(false)
const disableCode = ref('')
const disabling = ref(false)
const recoveryCodes = ref([])

onMounted(async () => {
  await store.loadProfile()
  firstName.value = store.profile.first_name
  lastName.value = store.profile.last_name
  await mfa.loadStatus()
  if (router.currentRoute.value.hash === '#mfa') {
    await nextTick()
    const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
    document.getElementById('mfa')?.scrollIntoView({ behavior, block: 'start' })
  }
  await loadDeletionPreview()
})

async function handleProfileSubmit() { if (!firstName.value.trim() || !lastName.value.trim()) return; savingProfile.value = true; await store.updateProfile(firstName.value.trim(), lastName.value.trim()); savingProfile.value = false }
async function handlePasswordSubmit() {
  passwordError.value = ''
  if (newPassword.value.length < 8) { passwordError.value = t('users.create.passwordTooShort'); return }
  if (newPassword.value !== confirmPassword.value) { passwordError.value = t('profilePage.passwordMismatch'); return }
  if (newPassword.value === currentPassword.value) { passwordError.value = t('profilePage.passwordSame'); return }
  savingPassword.value = true
  const ok = await store.changePassword(currentPassword.value, newPassword.value)
  savingPassword.value = false
  if (ok) { currentPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''; setTimeout(() => auth.logout(), POST_PASSWORD_CHANGE_LOGOUT_DELAY_MS) }
}

async function handleStartSetup() {
  startingSetup.value = true
  await mfa.setupTotp()
  startingSetup.value = false
}

async function handleConfirmMfa(code) {
  confirming.value = true
  const codes = await mfa.confirmTotp(code)
  confirming.value = false
  if (codes) recoveryCodes.value = codes
}

async function handleDisableMfa() {
  const value = disableCode.value.trim()
  if (!value) return
  disabling.value = true
  const payload = value.includes('-') ? { recoveryCode: value } : { code: value }
  const ok = await mfa.disableTotp(payload)
  disabling.value = false
  if (ok) disableCode.value = ''
}

function downloadRecoveryCodes() {
  const content = t('profilePage.mfa.recoveryFile', { codes: recoveryCodes.value.join('\n') })
  const blob = new Blob([content], { type: 'text/plain' })
  triggerDownload(blob, `ellysia-recovery-codes-${new Date().toISOString().split('T')[0]}.txt`)
}
</script>

<style scoped>
/* ── Baja de la cuenta ── */
.profile-section--danger { border-color: var(--danger); }
.profile-section--danger h2 { color: var(--danger); }
.section-desc { font-size: var(--fs-md); color: var(--text-dim); margin: 0 0 0.85rem; }
.danger-text { color: var(--text-muted); font-size: var(--fs-md); margin-top: 0.5rem; }
.danger-warning {
  margin-top: 1rem; padding: 0.9rem 1.1rem; border-radius: 8px;
  background: var(--danger-dim); border: 1px solid var(--danger);
  color: var(--text); font-size: var(--fs-md); line-height: 1.55;
}
.danger-note { margin-top: 1rem; color: var(--text-muted); font-size: var(--fs-md); }

.profile-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.main { max-width: 1020px; margin: 0 auto; padding: 1.75rem 1.1rem; position: relative; z-index: 1; }
.profile-header { text-align: center; margin-bottom: 2rem; }
.profile-avatar { width: 72px; height: 72px; border-radius: 50%; background: var(--accent); color: var(--on-accent); font-size: var(--fs-3xl); font-weight: 700; font-family: var(--font-display); font-size-adjust: var(--fsa-display); display: flex; align-items: center; justify-content: center; margin: 0 auto 0.75rem; }
.profile-display-name { font-size: var(--fs-2xl); font-weight: 700; color: var(--text); margin: 0 0 0.2rem; font-family: var(--font-display); font-size-adjust: var(--fsa-display); }
.profile-username { font-size: var(--fs-lg); color: var(--text-muted); margin: 0; }
.profile-section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; margin-bottom: 1.1rem; }
.profile-section[id="mfa"] { scroll-margin-top: calc(var(--topbar-h) + 1rem); }
.profile-section h2 { font-size: var(--fs-xl); font-weight: 600; margin: 0 0 0.85rem; color: var(--text); font-family: var(--font-display); font-size-adjust: var(--fsa-display); }
.profile-form { display: flex; flex-direction: column; gap: 0.85rem; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; }
.form-row--single { grid-template-columns: 1fr; }
.form-group { display: flex; flex-direction: column; gap: 0.3rem; }
.form-group label { font-size: var(--fs-md); font-weight: 600; color: var(--text-dim); }
.inp { background: var(--bg); border: 1px solid var(--border-solid); border-radius: 6px; padding: 0.5rem 0.65rem; color: var(--text); font-size: var(--fs-input); outline: none; transition: border-color 0.2s; }
.inp:focus { border-color: var(--accent); }
.inp--disabled { opacity: 0.55; cursor: not-allowed; }
.form-error { color: var(--danger); font-size: var(--fs-lg); margin: 0; }
.form-actions { display: flex; gap: 0.6rem; justify-content: flex-end; padding-top: 0.35rem; }
.mfa-status-text { font-size: var(--fs-lg); color: var(--text-dim); margin: 0 0 0.85rem; }
.mfa-status-text--on { color: var(--success, #2e9c5b); }
.mfa-fade-enter-active, .mfa-fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.mfa-fade-enter-from { opacity: 0; transform: translateY(4px); }
.mfa-fade-leave-to { opacity: 0; transform: translateY(-4px); }
.mfa-recovery-warning { font-size: var(--fs-lg); color: var(--text-dim); margin: 0 0 0.75rem; }
.mfa-recovery-list {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 1rem;
  list-style: none; margin: 0 0 1rem; padding: 0.75rem; background: var(--bg);
  border: 1px solid var(--border-solid); border-radius: 6px;
}
.mfa-recovery-list code { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--text); }
.loading-block { padding: 3.5rem 0; display: flex; justify-content: center; }
.skeleton { background: var(--surface); border-radius: 8px; animation: pulse 1.4s ease-in-out infinite; }
.skeleton--lg { width: 100%; height: 240px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
</style>
