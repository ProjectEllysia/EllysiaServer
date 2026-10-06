<template>
  <div class="engine-card" data-scope="cloud">
    <ScopeMotif scope="cloud" :active="running || launching" />
    <div class="engine-head">
      <div class="engine-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.78A6 6 0 0 0 4.5 12.5 3.5 3.5 0 0 0 6 19z"/></svg>
      </div>
      <div class="engine-title-wrap">
        <span class="engine-eyebrow">{{ t('lybra.scopeEyebrow.cloud') }}</span>
        <span class="engine-title">{{ t('lybra.cloud.title') }}</span>
        <span class="engine-sub">{{ t('lybra.cloud.subtitle') }}</span>
      </div>
      <Transition name="pop"><span v-if="running" class="engine-launched"><span class="pulse" aria-hidden="true"></span>{{ t('lybra.cloud.running') }}</span></Transition>
    </div>

    <div class="engine-fields">
      <!-- El dominio: su sello de autorización solo cuenta si se piden los
           subdominios, que es cuando el escaneo llama a sus nombres. -->
      <div class="field">
        <label for="cloud-domain">{{ t('lybra.cloud.domain') }}</label>
        <div class="target-wrap" :class="{ sealed: domainSeal }">
          <input id="cloud-domain" v-model="domain" :placeholder="t('lybra.cloud.domainPlaceholder')"
            autocomplete="off" spellcheck="false" @keyup.enter="handleLaunch" />
          <Transition name="fade-swap" mode="out-in">
            <span v-if="domainSeal === 'ok'" key="ok" class="target-seal ok" :title="t('lybra.launch.authorizedHint')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>
              {{ t('lybra.launch.authorized') }}
            </span>
            <button v-else-if="domainSeal === 'missing'" key="missing" type="button" class="target-seal missing"
              :title="t('lybra.launch.authorizeHint', { target: domain.trim() })"
              @click="$emit('authorize', domain.trim())">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><line x1="12" y1="9" x2="12" y2="15"/><line x1="9" y1="12" x2="15" y2="12"/></svg>
              {{ t('lybra.launch.authorize') }}
            </button>
          </Transition>
        </div>
        <Transition name="panel-slide"><p v-if="domain.trim() && !isDomainValid" class="field-error">{{ t('lybra.cloud.domainInvalid') }}</p></Transition>
      </div>

      <label class="check">
        <input v-model="checkSubdomains" type="checkbox" />
        <span>{{ t('lybra.cloud.checkSubdomains') }}</span>
      </label>

      <!-- Qué subdominios se van a comprobar: solo los que una búsqueda
           previa encontró. Sin ella se mira solo el dominio, y hay que decirlo
           antes de lanzar, no dejar creer que se revisó todo. -->
      <Transition name="fade-swap">
        <div v-if="isDomainValid && checkSubdomains" class="known" :class="knowledge.state" role="status">
          <p class="known-text">
            <span v-if="knowledge.state === 'searching'" class="pulse" aria-hidden="true"></span>
            {{ knowledgeText }}
          </p>
          <button type="button" class="btn-add" :disabled="discovering || knowledge.state === 'searching'"
            :title="t('lybra.cloud.discoverHint')" @click="$emit('discover', domain.trim())">
            {{ knowledge.state === 'known' ? t('lybra.cloud.discoverAgain') : t('lybra.cloud.discover') }}
          </button>
        </div>
      </Transition>

      <!-- Los recursos no se buscan: se declaran. Cada uno lleva su propio
           sello, porque cada uno se autoriza por separado. -->
      <div class="field">
        <label for="cloud-resource">{{ t('lybra.cloud.resources') }}</label>
        <div class="resource-add">
          <input id="cloud-resource" v-model="newResource" :placeholder="t('lybra.cloud.resourcePlaceholder')"
            autocomplete="off" spellcheck="false" @keyup.enter="addResource" />
          <button type="button" class="btn-add" :disabled="!isNewResourceValid" @click="addResource">{{ t('lybra.launch.add') }}</button>
        </div>
        <Transition name="panel-slide"><p v-if="newResource.trim() && !isNewResourceValid" class="field-error">{{ t('lybra.cloud.resourceInvalid') }}</p></Transition>
        <TransitionGroup v-if="resources.length" tag="ul" name="chip-item" class="resource-list">
          <li v-for="resource in resources" :key="resource" class="resource">
            <span class="resource-provider">{{ t(`lybra.cloud.providers.${cloudProviderKey(resource)}`) }}</span>
            <span class="mono resource-name">{{ resource }}</span>
            <span v-if="isAuthorized(resource)" class="resource-seal ok" :title="t('lybra.launch.authorizedHint')">{{ t('lybra.launch.authorized') }}</span>
            <button v-else type="button" class="resource-seal missing" :title="t('lybra.launch.authorizeHint', { target: resource })"
              @click="$emit('authorize', resource)">{{ t('lybra.launch.authorize') }}</button>
            <button type="button" class="resource-remove" :aria-label="t('lybra.cloud.removeResource', { resource })" @click="removeResource(resource)">×</button>
          </li>
        </TransitionGroup>
        <p v-else class="field-hint">{{ t('lybra.cloud.noResources') }}</p>
      </div>

      <Transition name="panel-slide">
        <p v-if="hasMissingAuthorization" class="auth-hint">{{ t('lybra.cloud.missingHint') }}</p>
      </Transition>

      <div class="engine-row">
        <button class="btn-launch" :class="{ loading: launching }" :disabled="launching || !canLaunch" @click="handleLaunch">
          <span class="btn-cloud" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.78A6 6 0 0 0 4.5 12.5 3.5 3.5 0 0 0 6 19z"/></svg></span>
          <span>{{ launching ? t('lybra.cloud.launching') : t('lybra.cloud.launch') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ScopeMotif from '../lybra/ScopeMotif.vue'
import { classifyTarget } from '../lybra/targetShapes'
import { cloudProviderKey, isCoveredByRegister, subdomainKnowledge } from '../lybra/beyondHost'
import { formatDate } from '@/i18n/format'

const { t } = useI18n()

const props = defineProps({
  launching: { type: Boolean, default: false },
  /** Si hay algún escaneo cloud en marcha, para el aviso de la cabecera. */
  running: { type: Boolean, default: false },
  /** El registro de objetivos autorizados del usuario. */
  authorizedTargets: { type: Array, default: () => [] },
  /** Las búsquedas de subdominios del usuario, de la más nueva a la más vieja. */
  subdomainSearches: { type: Array, default: () => [] },
  /** Si se está pidiendo una búsqueda de subdominios ahora mismo. */
  discovering: { type: Boolean, default: false },
})
const emit = defineEmits(['launch', 'authorize', 'discover'])

/** El servidor admite hasta 25 recursos por escaneo. */
const MAX_RESOURCES = 25

const domain = ref('')
const checkSubdomains = ref(true)
const newResource = ref('')
const resources = ref([])

const isDomainValid = computed(() => classifyTarget(domain.value) === 'domain')
const isNewResourceValid = computed(() =>
  classifyTarget(newResource.value) === 'cloud' && resources.value.length < MAX_RESOURCES)

function isAuthorized(target) { return isCoveredByRegister(target, props.authorizedTargets) }

/**
 * Sello del dominio: vacío si no aplica, `ok` si está autorizado y `missing`
 * si no lo está y hace falta (se piden los subdominios).
 */
const domainSeal = computed(() => {
  if (!isDomainValid.value || !checkSubdomains.value) return ''
  return isAuthorized(domain.value) ? 'ok' : 'missing'
})

/** Qué se sabe de los subdominios del dominio escrito. */
const knowledge = computed(() => subdomainKnowledge(domain.value, props.subdomainSearches))

const knowledgeText = computed(() => {
  const { state, count, finishedAt } = knowledge.value
  if (state === 'searching') return t('lybra.cloud.subdomainsSearching')
  if (state === 'failed') return t('lybra.cloud.subdomainsSearchFailed')
  if (state === 'none') return t('lybra.cloud.subdomainsUnknown')
  return t('lybra.cloud.subdomainsFound', { count, date: formatDate(finishedAt) }, count)
})

const hasMissingAuthorization = computed(() =>
  domainSeal.value === 'missing' || resources.value.some(resource => !isAuthorized(resource)))

const canLaunch = computed(() => isDomainValid.value && (checkSubdomains.value || resources.value.length > 0))

function addResource() {
  if (!isNewResourceValid.value) return
  const canonical = newResource.value.trim().toLowerCase()
  if (!resources.value.includes(canonical)) resources.value = [...resources.value, canonical]
  newResource.value = ''
}

function removeResource(resource) { resources.value = resources.value.filter(item => item !== resource) }

function handleLaunch() {
  if (!canLaunch.value || props.launching) return
  emit('launch', {
    domain: domain.value.trim(),
    cloudResources: resources.value,
    checkSubdomains: checkSubdomains.value,
  })
}
</script>

<style scoped>
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
/* Misma tarjeta de motor que LybraLaunchPanel.vue: es el mismo motor
   mirando otra cosa, y se tiene que reconocer como tal. */
.engine-card {
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--accent); border-radius: 12px; padding: 1.2rem 1.35rem; margin-bottom: 1.1rem;
  box-shadow: 0 0 0 1px var(--accent-dim), 0 12px 34px rgba(0,0,0,0.16);
  position: relative; isolation: isolate; overflow: hidden;
  animation: seq-fade-up 0.4s ease-out backwards;
}
.engine-head { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.7rem; }
.engine-mark {
  width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  color: var(--scope-tint); background: var(--scope-tint-dim); border: 1px solid var(--scope-tint);
}
.engine-mark svg { width: 21px; height: 21px; }
.engine-title-wrap { display: flex; flex-direction: column; min-width: 0; }
.engine-eyebrow { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.24em; text-transform: uppercase; color: var(--scope-tint); }
.engine-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: color-mix(in srgb, var(--text) 86%, var(--scope-tint)); }
.engine-sub { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-style: italic; font-size: var(--fs-md); color: var(--text-muted); }
.engine-launched { margin-left: auto; display: inline-flex; align-items: center; gap: 0.4rem; font-size: var(--fs-md); color: var(--accent-bright); }
/* Mismo anillo que el aviso de LybraLaunchPanel.vue: el motor está trabajando. */
.pulse { position: relative; width: 8px; height: 8px; border-radius: 50%; background: var(--accent-bright); }
.pulse::after { content: ''; position: absolute; inset: 0; border-radius: 50%; background: var(--accent-bright); animation: pulse-ring 1.6s ease-out infinite; }
@keyframes pulse-ring { from { transform: scale(1); opacity: 0.6; } to { transform: scale(2.6); opacity: 0; } }

.engine-fields { display: flex; flex-direction: column; gap: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.35rem; }
.field label { font-size: var(--fs-label); color: var(--text-dim); }
.field input, .resource-add input {
  width: 100%; box-sizing: border-box; padding: 0.5rem 0.7rem; background: var(--surface-2);
  border: 1px solid var(--border-solid); border-radius: 7px; color: var(--text); font-size: var(--fs-input); outline: none;
}
.field input, .resource-add input { transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.field input:focus, .resource-add input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
.field-error { margin: 0; font-size: var(--fs-sm); color: var(--danger); }
.field-hint { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); }

.target-wrap { position: relative; display: flex; align-items: center; }
.target-wrap input { padding-right: 7.5rem; }
.target-seal {
  position: absolute; right: 0.35rem; display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.5rem; border-radius: 999px; font-size: var(--fs-sm); font-weight: 600; border: 1px solid transparent;
}
.target-seal svg { width: 13px; height: 13px; }
.target-seal.ok { color: var(--success); background: var(--success-dim); }
/* El sello se estampa al pasar a «autorizado»: cae desde algo más grande y rebota. */
.target-seal.ok, .resource-seal.ok { animation: seal-stamp 0.42s cubic-bezier(0.34, 1.56, 0.64, 1); }
@keyframes seal-stamp { from { transform: scale(1.5) rotate(-6deg); opacity: 0; } to { transform: scale(1) rotate(0); opacity: 1; } }
.target-seal.missing { color: var(--warn); background: var(--warn-dim); border-color: var(--warn); cursor: pointer; }
.target-seal.missing:hover { background: var(--warn); color: var(--on-accent); }

.check { display: flex; align-items: center; gap: 0.5rem; font-size: var(--fs-body); color: var(--text-dim); cursor: pointer; }
.check input { accent-color: var(--accent); width: 15px; height: 15px; }

.known {
  display: flex; align-items: center; justify-content: space-between; gap: 0.7rem;
  padding: 0.5rem 0.7rem; border-radius: 7px; background: var(--surface-2); border: 1px solid var(--border-solid);
}
.known.none, .known.failed { background: var(--warn-dim); border-color: var(--warn); }
.known-text { margin: 0; display: flex; align-items: center; gap: 0.45rem; font-size: var(--fs-body); color: var(--text-dim); line-height: 1.4; }
.known-text .pulse { flex: none; }

.resource-add { display: flex; gap: 0.4rem; }
.btn-add {
  padding: 0.4rem 0.9rem; background: var(--surface-2); border: 1px solid var(--accent); color: var(--accent-bright);
  font-size: var(--fs-btn); font-weight: 600; border-radius: 7px; cursor: pointer; white-space: nowrap;
}
.btn-add { transition: background 0.2s ease, transform 0.12s ease; }
.btn-add:hover:not(:disabled) { background: var(--accent-dim); }
.btn-add:active:not(:disabled), .btn-launch:active:not(:disabled) { transform: scale(0.96); }
.btn-add:disabled { opacity: 0.4; cursor: not-allowed; }

.resource-list { position: relative; list-style: none; margin: 0.2rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.resource {
  display: flex; align-items: center; gap: 0.55rem; padding: 0.35rem 0.4rem 0.35rem 0.6rem;
  background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 8px;
}
.resource-provider {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-xs); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); flex: none; min-width: 5.5em;
}
.resource-name { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: var(--fs-body); color: var(--text); }
.resource-seal { flex: none; font-size: var(--fs-sm); font-weight: 600; padding: 0.12rem 0.5rem; border-radius: 999px; border: 1px solid transparent; }
.resource-seal.ok { color: var(--success); background: var(--success-dim); }
.resource-seal.missing { color: var(--warn); background: var(--warn-dim); border-color: var(--warn); cursor: pointer; }
.resource-seal.missing:hover { background: var(--warn); color: var(--on-accent); }
.resource-remove {
  width: 22px; height: 22px; display: grid; place-items: center; border-radius: 50%; flex: none;
  background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: var(--fs-xl); line-height: 1;
}
.resource-remove:hover { background: var(--danger-dim); color: var(--danger); }

.auth-hint { margin: 0; padding: 0.5rem 0.7rem; border-radius: 7px; font-size: var(--fs-body); color: var(--text-dim); background: var(--warn-dim); border: 1px solid var(--warn); }

.engine-row { display: flex; justify-content: flex-end; }
.btn-launch {
  display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.6rem 1.3rem;
  background: var(--accent); border: 1px solid var(--accent); border-radius: 8px; color: var(--on-accent);
  font-size: var(--fs-btn); font-weight: 600; cursor: pointer; transition: opacity 0.2s;
}
.btn-cloud { display: grid; place-items: center; }
.btn-cloud svg { width: 17px; height: 17px; }
/* La nube del botón flota al pasar por encima y mientras se lanza: el motor
   está mirando lo que el dominio deja a la vista. */
.btn-launch:hover:not(:disabled) .btn-cloud svg { animation: cloud-float 1.6s ease-in-out infinite; }
.btn-launch.loading .btn-cloud svg { animation: cloud-float 1.1s ease-in-out infinite; }
@keyframes cloud-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
.btn-launch:hover:not(:disabled) { opacity: 0.9; }
.btn-launch.loading:disabled { opacity: 0.85; cursor: progress; }
.btn-launch:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-launch:focus-visible, .btn-add:focus-visible, .target-seal:focus-visible, .resource-seal:focus-visible, .resource-remove:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

.pop-enter-active, .pop-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.9); }
.fade-swap-enter-active, .fade-swap-leave-active { transition: opacity 0.15s ease; }
.fade-swap-enter-from, .fade-swap-leave-to { opacity: 0; }
.chip-item-enter-active { transition: opacity 0.25s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); animation: chip-flash 0.9s ease-out; }
.chip-item-enter-from { opacity: 0; transform: translateY(-6px) scale(0.96); }
.chip-item-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; position: absolute; inset-inline: 0; }
.chip-item-leave-to { opacity: 0; transform: translateX(12px); }
.chip-item-move { transition: transform 0.25s ease; }
@keyframes chip-flash { from { background: var(--accent-dim); border-color: var(--accent); } }
/* Avisos y errores se despliegan con su altura, en vez de aparecer de golpe. */
.panel-slide-enter-active, .panel-slide-leave-active { transition: max-height 0.25s ease, opacity 0.2s ease, margin 0.25s ease, padding 0.25s ease; overflow: hidden; }
.panel-slide-enter-from, .panel-slide-leave-to { max-height: 0; opacity: 0; margin-top: -0.4rem; padding-top: 0; padding-bottom: 0; }
.panel-slide-enter-to, .panel-slide-leave-from { max-height: 8rem; opacity: 1; }

@media (max-width: 640px) {
  .engine-card { padding: 1rem; }
  .engine-launched { display: none; }
  .btn-launch { width: 100%; justify-content: center; }
  .resource { flex-wrap: wrap; }
  .known { flex-direction: column; align-items: stretch; }
}
@media (prefers-reduced-motion: reduce) {
  .pulse::after, .btn-cloud svg { animation: none !important; }
  .pop-enter-active, .pop-leave-active, .fade-swap-enter-active, .fade-swap-leave-active,
  .chip-item-enter-active, .chip-item-leave-active, .chip-item-move, .panel-slide-enter-active, .panel-slide-leave-active,
  .btn-launch, .btn-add, .field input, .resource-add input { transition: none !important; }
  .engine-card, .target-seal.ok, .resource-seal.ok, .chip-item-enter-active { animation: none !important; }
}
</style>
