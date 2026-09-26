<template>
  <div class="org-page">
    <StarBackground />
    <Topbar :title="t('organization.topbar')" />

    <main class="main">
      <!-- Sin organización: crearla, o explicar por qué no se puede -->
      <section v-if="!account.organization" class="section section--empty">
        <h1>{{ t('organization.none') }}</h1>
        <p class="lede">{{ t('organization.lede') }}</p>

        <form v-if="canCreate" class="create-form" @submit.prevent="create">
          <div class="form-group">
            <label for="org-name">{{ t('organization.name') }}</label>
            <input id="org-name" v-model="newName" type="text" required minlength="2"
                   maxlength="128" class="inp" :placeholder="t('organization.namePlaceholder')" />
          </div>
          <button type="submit" class="btn btn--primary" :disabled="creating">
            {{ creating ? t('login.register.submitting') : t('organization.create') }}
          </button>
        </form>

        <p v-else class="hint">
          {{ t('organization.notInPlan') }}
          <router-link to="/planes" class="link">{{ t('organization.seePlans') }}</router-link>.
        </p>
      </section>

      <template v-else>
        <section class="head">
          <div>
            <span class="head-eyebrow">{{ account.isOwner ? t('organization.youManage') : t('organization.youBelong') }}</span>
            <h1 class="head-name">{{ account.organization.name }}</h1>
            <p class="head-meta">{{ t('organization.memberCount', { count: account.organization.memberCount }, account.organization.memberCount) }}</p>
          </div>
          <button v-if="!account.isOwner" class="btn btn--danger" @click="leave">
            {{ t('organization.leave') }}
          </button>
        </section>

        <p v-if="!account.isOwner" class="hint">{{ t('organization.memberHint') }}</p>

        <template v-if="account.isOwner">
          <section class="section">
            <h2>{{ t('language.label') }}</h2>
            <p class="section-desc">{{ t('organization.languageDesc') }}</p>
            <select class="inp language-inp" :value="account.organization.defaultLanguage ?? ''"
                    :disabled="savingLanguage" @change="saveLanguage($event.target.value)">
              <option value="">{{ t('organization.platformLanguage') }}</option>
              <option v-for="option in LOCALE_OPTIONS" :key="option.code" :value="option.code" :lang="option.code">
                {{ option.name }}
              </option>
            </select>
          </section>

          <ComplianceFrameworksPicker scope="organization" class="section">
            <h2>{{ t('profilePage.complianceTitle') }}</h2>
            <p class="section-desc">{{ t('organization.complianceDesc') }}</p>
          </ComplianceFrameworksPicker>

          <section class="section">
            <h2>{{ t('organization.inviteTitle') }}</h2>
            <p class="section-desc">{{ t('organization.inviteDesc') }}</p>
            <form class="invite-form" @submit.prevent="invite">
              <input v-model="inviteEmail" type="email" required class="inp"
                     :placeholder="t('organization.invitePlaceholder')" />
              <button type="submit" class="btn btn--primary" :disabled="inviting">
                {{ inviting ? t('login.recover.submitting') : t('organization.invite') }}
              </button>
            </form>
          </section>

          <section class="section">
            <h2>{{ t('organization.members') }}</h2>
            <table class="table">
              <thead>
                <tr><th>{{ t('users.fields.username') }}</th><th>{{ t('login.register.email') }}</th><th>{{ t('users.fields.role') }}</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="member in members" :key="member.userId">
                  <td>{{ member.fullName || member.username }}</td>
                  <td class="mono">{{ member.email }}</td>
                  <td>{{ member.role === 'owner' ? t('organization.owner') : t('organization.member') }}</td>
                  <td class="td-actions">
                    <button v-if="member.role !== 'owner'" class="btn-link btn-link--danger"
                            @click="expel(member)">
                      {{ t('organization.expel') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="section">
            <h2>{{ t('organization.invitations') }}</h2>
            <p v-if="!invitations.length" class="hint">{{ t('organization.noInvitations') }}</p>
            <table v-else class="table">
              <thead>
                <tr><th>{{ t('login.register.email') }}</th><th>{{ t('organization.status') }}</th><th>{{ t('organization.expires') }}</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="invitation in invitations" :key="invitation.id">
                  <td class="mono">{{ invitation.email }}</td>
                  <td>{{ statusLabel(invitation.status) }}</td>
                  <td>{{ account.formatDate(invitation.expiresAt) }}</td>
                  <td class="td-actions">
                    <button v-if="invitation.status === 'pending'" class="btn-link btn-link--danger"
                            @click="revoke(invitation)">
                      {{ t('organization.revoke') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>
      </template>
    </main>

    <ConfirmModal
      :show="confirm.open"
      :title="confirm.title"
      :message="confirm.message"
      :danger="true"
      :confirm-label="t('common.confirm')"
      @confirm="confirm.action()"
      @cancel="confirm.open = false"
    />
  </div>
</template>

<script setup>
/**
 * Gestión de la organización.
 *
 * Lo que el dueño ve de su gente es identidad y nada más — ni sus escaneos, ni
 * sus análisis, ni sus bóvedas. No es una carencia de esta pantalla: es la
 * garantía que se vende, y la API tampoco lo devuelve.
 */
import { ref, computed, onMounted } from 'vue'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import ComplianceFrameworksPicker from '@/components/themis/ComplianceFrameworksPicker.vue'
import { useApi } from '@/composables/useApi'
import { useAccountStore } from '@/stores/accountStore'
import { useProfileStore } from '@/stores/profileStore'
import { useToastStore } from '@/stores/toastStore'
import { LOCALE_OPTIONS } from '@/i18n'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const { apiFetch, apiError } = useApi()
const account = useAccountStore()
const toast = useToastStore()

/** Estados de invitación que tienen rótulo en `organization.statuses`. */
const STATUSES = ['pending', 'accepted', 'revoked', 'expired']

/**
 * Rótulo de un estado de invitación.
 *
 * @param {string} status - Estado que devuelve la API.
 * @returns {string} El rótulo, o «Desconocido» si el servidor manda uno nuevo.
 */
function statusLabel(status) {
  return STATUSES.includes(status) ? t(`organization.statuses.${status}`) : t('common.unknown')
}

const members = ref([])
const invitations = ref([])
const newName = ref('')
const inviteEmail = ref('')
const creating = ref(false)
const inviting = ref(false)
const confirm = ref({ open: false, title: '', message: '', action: () => {} })

const canCreate = computed(() => account.plan?.organizationEnabled === true)

const profileStore = useProfileStore()
const savingLanguage = ref(false)

/**
 * Guarda el idioma por defecto de la organización.
 *
 * Después se revalida el perfil propio: si el dueño no ha elegido idioma, el
 * suyo acaba de cambiar también.
 *
 * @param {string} value - Código del idioma, o '' para volver al de la plataforma.
 */
async function saveLanguage(value) {
  savingLanguage.value = true
  try {
    if (await account.setOrganizationLanguage(value || null)) await profileStore.refreshServerOwnedFields()
  } finally {
    savingLanguage.value = false
  }
}

async function load() {
  await account.loadOrganization()
  if (!account.organization || !account.isOwner) return

  const id = account.organization.id
  const [membersRes, invitationsRes] = await Promise.all([
    apiFetch(`/organizations/${id}/members`),
    apiFetch(`/organizations/${id}/invitations`),
  ])
  if (membersRes?.ok) members.value = (await membersRes.json()).members ?? []
  if (invitationsRes?.ok) invitations.value = (await invitationsRes.json()).invitations ?? []
}

async function create() {
  creating.value = true
  try {
    if (await account.createOrganization(newName.value)) {
      newName.value = ''
      await load()
    }
  } finally {
    creating.value = false
  }
}

async function invite() {
  inviting.value = true
  try {
    const res = await apiFetch(`/organizations/${account.organization.id}/invitations`, {
      method: 'POST',
      body: JSON.stringify({ email: inviteEmail.value }),
    })
    if (!res?.ok) {
      // El 402 ya lo avisa useApi; aquí solo el resto.
      if (res?.status !== 402) {
        toast.show(await apiError(res, t('organization.toast.inviteFailed')), 'error')
      }
      return
    }
    toast.show(t('organization.toast.invited'), 'success')
    inviteEmail.value = ''
    await load()
  } finally {
    inviting.value = false
  }
}

function expel(member) {
  confirm.value = {
    open: true,
    title: t('organization.confirmExpel.title', { username: member.username }),
    message: t('organization.confirmExpel.message'),
    action: async () => {
      confirm.value.open = false
      const res = await apiFetch(
        `/organizations/${account.organization.id}/members/${member.userId}`,
        { method: 'DELETE' },
      )
      if (!res?.ok) {
        toast.show(await apiError(res, t('organization.toast.expelFailed')), 'error')
        return
      }
      toast.show(t('organization.toast.expelled'), 'success')
      await load()
    },
  }
}

function revoke(invitation) {
  confirm.value = {
    open: true,
    title: t('organization.confirmRevoke.title'),
    message: t('organization.confirmRevoke.message', { email: invitation.email }),
    action: async () => {
      confirm.value.open = false
      const res = await apiFetch(`/organizations/invitations/${invitation.id}`, {
        method: 'DELETE',
      })
      if (!res?.ok) {
        toast.show(await apiError(res, t('organization.toast.revokeFailed')), 'error')
        return
      }
      await load()
    },
  }
}

function leave() {
  confirm.value = {
    open: true,
    title: t('organization.confirmLeave.title'),
    message: t('organization.confirmLeave.message'),
    action: async () => {
      confirm.value.open = false
      const res = await apiFetch('/organizations/mine', { method: 'DELETE' })
      if (!res?.ok) {
        toast.show(await apiError(res, t('organization.toast.leaveFailed')), 'error')
        return
      }
      toast.show(t('organization.toast.left'), 'success')
      await load()
    },
  }
}

onMounted(async () => {
  await account.loadPlan()
  await load()
})
</script>

<style scoped>
/* Ver la nota de MyPlanView: Topbar fija + StarBackground opaco en z-index 0. */
.org-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.main { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }

.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1.5rem; flex-wrap: wrap; }
.head-eyebrow {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 500;
  letter-spacing: 0.3em; text-transform: uppercase; color: var(--accent);
}
.head-name {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: clamp(1.8rem, 4vw, 2.4rem);
  font-weight: 600; color: var(--text); margin-top: 0.3rem;
}
.head-meta { color: var(--text-muted); margin-top: 0.2rem; }

.section {
  background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 12px; padding: 1.5rem;
}
.section h1 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.section h2 { font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.section-desc, .lede { font-size: var(--fs-md); color: var(--text-muted); margin-top: 0.5rem; max-width: 62ch; }
.hint { font-size: var(--fs-body); color: var(--text-muted); }
.link { color: var(--accent); text-decoration: underline; }

.create-form { margin-top: 1.4rem; display: flex; flex-direction: column; gap: 0.9rem; max-width: 380px; }
.invite-form { margin-top: 1.2rem; display: flex; gap: 0.7rem; flex-wrap: wrap; }
.invite-form .inp { flex: 1; min-width: 220px; }

.form-group { display: flex; flex-direction: column; gap: 0.35rem; }
.form-group label { font-size: var(--fs-body); color: var(--text-dim); }
.inp {
  padding: 0.6rem 0.8rem; border-radius: 6px;
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border-med);
}
.inp:focus { outline: none; border-color: var(--accent); }
.language-inp { margin-top: 0.8rem; max-width: 22rem; }

.table { width: 100%; border-collapse: collapse; margin-top: 1.2rem; font-size: var(--fs-md); }
.table th {
  text-align: left; padding: 0.5rem 0.6rem;
  font-size: var(--fs-body); font-weight: 500; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border);
}
.table td { padding: 0.65rem 0.6rem; border-bottom: 1px solid var(--border); color: var(--text-dim); }
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); }
.td-actions { text-align: right; }

.btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.6rem 1.2rem; border-radius: 3px;
  border: 1px solid var(--border-med); color: var(--text-dim);
  transition: all var(--transition);
}
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn--danger { border-color: var(--danger); color: var(--danger); }
.btn--danger:hover { background: var(--danger-dim); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-link { font-size: var(--fs-body); color: var(--text-muted); }
.btn-link:hover { color: var(--text); }
.btn-link--danger:hover { color: var(--danger); }
</style>
