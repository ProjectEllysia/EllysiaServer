<template>
  <div class="tool-page" :data-module="tool.module">
    <SiteHeader />

    <main class="tool-main">
      <router-link :to="`/${tool.module}`" class="tool-back">
        <span aria-hidden="true">←</span> {{ t('freeTools.backTo', { name: moduleName }) }}
      </router-link>

      <span class="tool-eyebrow">{{ t('freeTools.eyebrow') }} · {{ t(`freeTools.access.${tool.access}`) }}</span>
      <h1 class="tool-title">{{ t(`freeTools.items.${tool.id}.title`) }}</h1>
      <p class="tool-subtitle">{{ t(`freeTools.items.${tool.id}.subtitle`) }}</p>

      <!-- Herramienta con cuenta y visitante sin sesión: se enseña qué es y se
           invita a entrar, no se esconde la página. -->
      <div v-if="!canUse" class="tool-gate">
        <h2 class="tool-gate-title">{{ t('freeTools.gate.title') }}</h2>
        <p class="tool-gate-body">{{ t('freeTools.gate.body') }}</p>
        <router-link :to="{ path: '/login', query: { redirect: tool.path } }" class="tool-cta">{{ t('freeTools.gate.signIn') }}</router-link>
      </div>
      <div v-else class="tool-panel">
        <slot />
      </div>

      <!-- Lo que hay detrás: la herramienta completa del módulo. -->
      <aside v-if="hasMore" class="tool-more">
        <p class="tool-more-text">{{ t(`freeTools.items.${tool.id}.more`) }}</p>
        <router-link :to="moreTo" class="tool-more-link">
          {{ t(`freeTools.items.${tool.id}.moreCta`) }} <span aria-hidden="true">→</span>
        </router-link>
      </aside>
    </main>

    <SiteFooter />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { FREE_TOOLS, freeToolPath } from '@/freeTools/catalog'
import SiteHeader from '@/components/shared/SiteHeader.vue'
import SiteFooter from '@/components/shared/SiteFooter.vue'

/**
 * Marco común de las páginas de herramientas gratuitas: cabecera, vuelta al hub
 * del módulo, título, una línea que dice qué hace, el contenido de la
 * herramienta (slot por defecto) y la puerta a la herramienta completa.
 *
 * Los textos salen de `freeTools.items.<id>` (`title`, `subtitle` y, si hay
 * `moreTo`, `more` y `moreCta`). La herramienta solo aporta lo suyo.
 */
const props = defineProps({
  /** `id` de la herramienta en el catálogo (`freeTools/catalog.js`). */
  toolId: { type: String, required: true },
  /** Ruta de la herramienta completa a la que invita el pie; `null` no pinta pie. */
  moreTo: { type: String, default: null },
})

const { t } = useI18n()
const auth = useAuthStore()

const tool = computed(() => {
  const entry = FREE_TOOLS.find((candidate) => candidate.id === props.toolId)
  if (!entry) throw new Error(`Herramienta gratuita desconocida: ${props.toolId}`)
  return { ...entry, path: freeToolPath(entry) }
})

/** Nombre del módulo tal como se escribe en todos los idiomas. */
const moduleName = computed(() => tool.value.module.charAt(0).toUpperCase() + tool.value.module.slice(1))

/** Una herramienta con cuenta se bloquea sin sesión; las públicas, nunca. */
const canUse = computed(() => tool.value.access === 'public' || auth.isAuthenticated)
const hasMore = computed(() => Boolean(props.moreTo))
</script>

<style scoped>
.tool-page { min-height: 100vh; background: var(--bg); display: flex; flex-direction: column; }
.tool-main {
  flex: 1;
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  padding: 2.6rem 2rem 5rem;
}

.tool-back {
  display: inline-block;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  color: var(--text-dim);
  margin-bottom: 2.2rem;
  transition: color var(--transition);
}
.tool-back:hover { color: var(--accent-bright); }
.tool-back:focus-visible, .tool-cta:focus-visible, .tool-more-link:focus-visible {
  outline: 2px solid var(--accent-bright);
  outline-offset: 3px;
}

.tool-eyebrow {
  display: block;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.3em; text-transform: uppercase;
  color: var(--accent);
}
.tool-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: clamp(2rem, 4.6vw, 2.9rem);
  font-weight: 600;
  line-height: 1.15;
  color: var(--text);
  margin-top: 0.5rem;
  text-wrap: balance;
}
.tool-subtitle {
  font-size: var(--fs-lg);
  color: var(--text-dim);
  line-height: 1.6;
  margin-top: 0.8rem;
  max-width: 56ch;
}

.tool-panel, .tool-gate {
  margin-top: 2.2rem;
  padding: 1.6rem 1.7rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: var(--radius);
}
.tool-gate-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-xl); font-weight: 600;
  color: var(--text);
}
.tool-gate-body { color: var(--text-dim); font-size: var(--fs-md); margin-top: 0.5rem; }
.tool-cta {
  display: inline-block;
  margin-top: 1.2rem;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase;
  padding: 0.8rem 1.8rem;
  border-radius: 3px;
  background: var(--accent);
  color: var(--on-accent);
  transition: all var(--transition);
}
.tool-cta:hover { background: var(--accent-bright); box-shadow: 0 0 24px var(--accent-dim); }

.tool-more {
  margin-top: 2.4rem;
  padding: 1.1rem 1.3rem;
  border-left: 2px solid var(--accent);
  background: var(--accent-dim);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem 2rem; flex-wrap: wrap;
}
.tool-more-text { color: var(--text-dim); font-size: var(--fs-md); max-width: 46ch; }
.tool-more-link {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  color: var(--accent-bright);
  white-space: nowrap;
}
.tool-more-link:hover { text-decoration: underline; text-underline-offset: 4px; }

@media (max-width: 640px) {
  .tool-main { padding: 2rem 1.2rem 4rem; }
  .tool-panel, .tool-gate { padding: 1.3rem 1.2rem; }
}
</style>
