<template>
  <div class="shared-page" data-module="iris">
    <StarBackground />
    <Topbar :title="'Iris'" :badge="t('iris.shared.badge')" back-to="/iris/analisis" :back-label="t('iris.batch.analysis')" />

    <div class="shared-layout">
      <section class="panel">
        <p class="panel-eyebrow">{{ t('iris.shared.eyebrow') }}</p>
        <h2 class="panel-title">{{ t('iris.shared.title') }}</h2>
        <p class="panel-sub">{{ t('iris.shared.intro') }}</p>

        <details v-if="account.isOwner" class="create-panel">
          <summary>{{ t('iris.shared.create') }}</summary>
          <form class="create-form" @submit.prevent="submit">
            <label class="field">
              <span>{{ t('iris.shared.access') }}</span>
              <select v-model="form.provider">
                <option value="microsoft">{{ t('iris.shared.providers.microsoft') }}</option>
                <option value="gmail">{{ t('iris.shared.providers.gmail') }}</option>
                <option value="imap">{{ t('iris.shared.providers.imap') }}</option>
              </select>
            </label>
            <p class="field-hint">{{ t(`iris.shared.providerHints.${form.provider}`) }}</p>
            <label v-if="form.provider !== 'imap'" class="field">
              <span>{{ t('iris.shared.address') }}</span>
              <input v-model.trim="form.address" type="email" autocomplete="off" />
            </label>
            <ImapConnectFields v-else v-model="form.imap" />
            <label class="check">
              <input v-model="form.fullMessageMode" type="checkbox" />
              <span>{{ t('iris.shared.fullMessage') }}</span>
            </label>
            <div class="form-actions">
              <button type="submit" class="btn-primary" :disabled="store.saving || !isFormReady">{{ t('iris.shared.connect') }}</button>
            </div>
          </form>
        </details>
        <p v-else class="panel-note">{{ t('iris.shared.ownerOnly') }}</p>
      </section>

      <section class="panel">
        <p v-if="store.loading" class="state-msg">{{ t('iris.mailboxes.loading') }}</p>
        <p v-else-if="!store.mailboxes.length" class="state-msg">{{ t('iris.shared.empty') }}</p>
        <article v-for="mailbox in store.mailboxes" :key="mailbox.id" class="mailbox-card" :class="{ 'mailbox-card--open': selected?.id === mailbox.id }">
          <div class="mailbox-top">
            <span class="mailbox-email">{{ mailbox.accountEmail }}</span>
            <span class="chip">{{ t(`iris.shared.providers.${mailbox.provider}`) }}</span>
            <span class="chip">{{ t(`iris.shared.accessLevels.${mailbox.myAccess}`) }}</span>
            <span class="chip" :class="`chip--${mailbox.status}`">{{ t(`iris.shared.statuses.${mailbox.status}`) }}</span>
          </div>
          <p v-if="mailbox.lastError" class="mailbox-error">{{ mailbox.lastError }}</p>
          <div class="mailbox-actions">
            <button type="button" class="btn-secondary" @click="openAnalyses(mailbox)">{{ t('iris.shared.analyses') }}</button>
            <template v-if="mailbox.myAccess === 'manager'">
              <button type="button" class="btn-secondary" @click="openMembers(mailbox)">{{ t('iris.shared.members') }}</button>
              <button type="button" class="btn-secondary" @click="foldersMailbox = mailbox">{{ t('iris.folders.title') }}</button>
              <button v-if="mailbox.authMode === 'imap'" type="button" class="btn-secondary" @click="passwordMailbox = mailbox">{{ t('iris.imap.rotate') }}</button>
            </template>
          </div>

          <div v-if="selected?.id === mailbox.id && view === 'analyses'" class="detail">
            <p v-if="!analyses.length" class="state-msg">{{ t('iris.shared.noAnalyses') }}</p>
            <ul class="analysis-list">
              <li v-for="item in analyses" :key="item.analysisId">
                <button type="button" class="analysis-row" @click="openReport(item.analysisId)">
                  <span class="analysis-title">{{ item.title || t('iris.shared.untitled') }}</span>
                  <span class="chip">{{ item.verdict || item.status }}</span>
                  <span class="analysis-score">{{ item.totalScore ?? '' }}</span>
                </button>
              </li>
            </ul>
            <IrisReportViewer v-if="report" :report-id="report.analysisId" :report-data="report" />
          </div>

          <div v-if="selected?.id === mailbox.id && view === 'members'" class="detail">
            <ul class="member-list">
              <li v-for="member in members" :key="member.userId" class="member-row">
                <span class="member-name">{{ member.username }}</span>
                <select :value="member.access" @change="changeAccess(member.userId, $event.target.value)">
                  <option value="viewer">{{ t('iris.shared.accessLevels.viewer') }}</option>
                  <option value="manager">{{ t('iris.shared.accessLevels.manager') }}</option>
                </select>
                <button type="button" class="btn-icon btn-icon--danger" :aria-label="t('iris.shared.removeMember', { name: member.username })" @click="removeMember(member.userId)">&times;</button>
              </li>
            </ul>
            <form v-if="candidates.length" class="add-member" @submit.prevent="addMember">
              <select v-model="newMemberId">
                <option :value="null" disabled>{{ t('iris.shared.chooseMember') }}</option>
                <option v-for="person in candidates" :key="person.userId" :value="person.userId">{{ person.fullName || person.username }}</option>
              </select>
              <button type="submit" class="btn-primary" :disabled="!newMemberId">{{ t('iris.shared.addMember') }}</button>
            </form>
            <p class="field-hint">{{ t('iris.shared.membersHint') }}</p>
          </div>
        </article>
      </section>
    </div>

    <MailboxFoldersModal :connection="foldersMailbox" @close="foldersMailbox = null" @saved="afterChange('folders')" />
    <MailboxPasswordModal :connection="passwordMailbox" @close="passwordMailbox = null" @saved="afterChange('password')" />
  </div>
</template>

<script setup>
/**
 * Buzones compartidos de la organización (`soporte@`, `facturas@`…).
 *
 * El dueño de la organización los conecta con la cuenta de servicio de la
 * instalación o por IMAP; cada persona ve solo los buzones a los que tiene
 * acceso explícito, y quien los administra decide quién más los ve.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ImapConnectFields from '@/components/iris/ImapConnectFields.vue'
import MailboxFoldersModal from '@/components/iris/MailboxFoldersModal.vue'
import MailboxPasswordModal from '@/components/iris/MailboxPasswordModal.vue'
import IrisReportViewer from '@/components/iris/IrisReportViewer.vue'
import { useApi } from '@/composables/useApi'
import { useAccountStore } from '@/stores/accountStore'
import { useIrisSharedMailboxStore } from '@/stores/irisSharedMailboxStore'

const { t } = useI18n()
const { apiFetch } = useApi()
const account = useAccountStore()
const store = useIrisSharedMailboxStore()

/** Formulario de alta; `imap` solo se envía con `provider="imap"`. */
function emptyForm() {
  return { provider: 'microsoft', address: '', fullMessageMode: false,
           imap: { host: '', port: 993, username: '', password: '' } }
}
const form = ref(emptyForm())
const isFormReady = computed(() => form.value.provider === 'imap'
  ? Boolean(form.value.imap.host && form.value.imap.username && form.value.imap.password)
  : Boolean(form.value.address))

/** Buzón abierto y qué se enseña de él (`analyses` o `members`). */
const selected = ref(null)
const view = ref(null)
const analyses = ref([])
const report = ref(null)
const members = ref([])
const organizationMembers = ref([])
const newMemberId = ref(null)
const foldersMailbox = ref(null)
const passwordMailbox = ref(null)

/** Personas de la organización que aún no tienen acceso al buzón abierto. */
const candidates = computed(() => organizationMembers.value.filter(
  person => !members.value.some(member => member.userId === person.userId)))

onMounted(async () => {
  await account.loadOrganization()
  await store.fetchMailboxes()
})

async function submit() {
  const { provider, address, fullMessageMode, imap } = form.value
  const payload = provider === 'imap' ? { provider, fullMessageMode, imap: { ...imap } } : { provider, address, fullMessageMode }
  if (await store.createMailbox(payload)) form.value = emptyForm()
}

async function openAnalyses(mailbox) {
  selected.value = mailbox
  view.value = 'analyses'
  report.value = null
  analyses.value = (await store.fetchAnalyses(mailbox.id))?.analyses ?? []
}

async function openReport(analysisId) {
  report.value = await store.fetchAnalysis(selected.value.id, analysisId)
}

async function openMembers(mailbox) {
  selected.value = mailbox
  view.value = 'members'
  newMemberId.value = null
  members.value = (await store.fetchMembers(mailbox.id)) ?? []
  if (account.organization) {
    const res = await apiFetch(`/organizations/${account.organization.id}/members`)
    organizationMembers.value = res?.ok ? ((await res.json()).members ?? []) : []
  }
}

async function changeAccess(userId, access) {
  await store.setMember(selected.value.id, userId, access)
  members.value = (await store.fetchMembers(selected.value.id)) ?? []
}

async function addMember() {
  if (await store.setMember(selected.value.id, newMemberId.value, 'viewer')) {
    newMemberId.value = null
    members.value = (await store.fetchMembers(selected.value.id)) ?? []
  }
}

async function removeMember(userId) {
  if (await store.removeMember(selected.value.id, userId)) {
    members.value = (await store.fetchMembers(selected.value.id)) ?? []
  }
}

/**
 * Cierra el modal que acaba de guardar y recarga la lista.
 *
 * @param {'folders'|'password'} which - Modal que guardó.
 */
async function afterChange(which) {
  if (which === 'folders') foldersMailbox.value = null
  else passwordMailbox.value = null
  await store.fetchMailboxes()
}
</script>

<style scoped>
.shared-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.shared-layout { position: relative; z-index: 1; max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem 3rem; display: flex; flex-direction: column; gap: 1.5rem; }
.panel { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 1.4rem 1.6rem; }
.panel-eyebrow { margin: 0 0 0.3rem; font-family: var(--font-mono); font-size: var(--fs-xs); letter-spacing: 0.28em; text-transform: uppercase; color: var(--accent); }
.panel-title { margin: 0 0 0.5rem; font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 700; color: var(--text); }
.panel-sub, .panel-note { margin: 0 0 1rem; font-size: var(--fs-md); line-height: 1.55; color: var(--text-dim); max-width: 66ch; }
.create-panel summary { cursor: pointer; font-weight: 700; color: var(--text); }
.create-form { display: flex; flex-direction: column; gap: 0.7rem; margin-top: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; font-size: var(--fs-sm); color: var(--text-dim); }
.field input, .field select, .member-row select, .add-member select {
  padding: 0.5rem 0.65rem; border: 1px solid var(--border-med); border-radius: 8px; background: var(--surface-2); color: var(--text);
}
.field-hint { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.check { display: flex; align-items: center; gap: 0.5rem; color: var(--text); font-size: var(--fs-md); }
.form-actions { display: flex; justify-content: flex-end; }
.state-msg { color: var(--text-muted); }
.mailbox-card { border: 1px solid var(--border-med); border-radius: 10px; padding: 0.9rem 1rem; margin-bottom: 0.8rem; background: var(--surface-2); }
.mailbox-top { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.mailbox-email { font-weight: 700; color: var(--text); margin-right: auto; }
.chip { font-size: var(--fs-xs); padding: 0.15rem 0.5rem; border-radius: 999px; border: 1px solid var(--border-med); color: var(--text-dim); }
.chip--reauth_required, .chip--paused { border-color: var(--danger, #e5484d); color: var(--danger, #e5484d); }
.mailbox-error { margin: 0.4rem 0 0; font-size: var(--fs-sm); color: var(--text-muted); }
.mailbox-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.7rem; }
.detail { margin-top: 0.9rem; border-top: 1px solid var(--border); padding-top: 0.8rem; }
.analysis-list, .member-list { list-style: none; padding: 0; margin: 0 0 0.8rem; }
.analysis-row { width: 100%; display: flex; gap: 0.6rem; align-items: center; background: none; border: none; border-bottom: 1px solid var(--border); padding: 0.45rem 0; color: var(--text); cursor: pointer; text-align: left; }
.analysis-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.analysis-score { font-family: var(--font-mono); color: var(--text-dim); }
.member-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.35rem 0; }
.member-name { flex: 1; color: var(--text); }
.add-member { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
</style>
