<template>
  <div class="doc-page" :data-module="tool">
    <SiteHeader />

    <header class="doc-hero">
      <div class="doc-hero-inner">
        <img class="doc-hero-icon" :src="TOOL_ICONS[tool]" alt="" aria-hidden="true" width="96" height="96" />
        <div>
          <router-link to="/docs/tecnica" class="doc-eyebrow">{{ t('docs.technical.title') }}</router-link>
          <h1 class="doc-title">{{ page?.title ?? TOOL_NAMES[tool] }}</h1>
          <p v-if="page" class="doc-lede"><DocInline :text="page.lede" /></p>
        </div>
      </div>
    </header>

    <div v-if="page" class="doc-layout">
      <nav class="doc-toc" :aria-label="t('docs.technical.onThisPage')">
        <span class="doc-toc-title">{{ t('docs.technical.onThisPage') }}</span>
        <ol>
          <li v-for="section in page.sections" :key="section.id">
            <a :href="`#${section.id}`" :class="{ active: activeSectionId === section.id }" @click.prevent="goToSection(section.id)">
              {{ section.heading }}
            </a>
          </li>
        </ol>
      </nav>

      <article ref="articleRef" class="doc-article">
        <div class="doc-sheet">
          <template v-for="(section, index) in page.sections" :key="section.id">
            <!-- Entre sección y sección, el mismo sol de doble anillo que la
                 franja de la portada: separa temas, no pasos, así que no
                 lleva número. -->
            <div v-if="index > 0" class="doc-divider" aria-hidden="true">
              <span class="doc-divider-rule"></span>
              <span class="doc-divider-emblem">
                <span class="doc-divider-ring doc-divider-ring--inner"></span>
                <span class="doc-divider-ring doc-divider-ring--outer"></span>
              </span>
              <span class="doc-divider-rule"></span>
            </div>
            <DocSection :section="section" />
          </template>
        </div>

        <nav class="doc-pager" :aria-label="t('docs.technical.otherTools')">
          <router-link v-if="previousTool" :to="`/docs/tecnica/${previousTool}`" class="doc-pager-link" :data-module="previousTool">
            <span class="doc-pager-label">{{ t('docs.technical.previous') }}</span>
            <span class="doc-pager-name">{{ TOOL_NAMES[previousTool] }}</span>
          </router-link>
          <router-link v-if="nextTool" :to="`/docs/tecnica/${nextTool}`" class="doc-pager-link doc-pager-link--next" :data-module="nextTool">
            <span class="doc-pager-label">{{ t('docs.technical.next') }}</span>
            <span class="doc-pager-name">{{ TOOL_NAMES[nextTool] }}</span>
          </router-link>
        </nav>
      </article>
    </div>

    <SiteFooter />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SiteHeader from '@/components/shared/SiteHeader.vue'
import SiteFooter from '@/components/shared/SiteFooter.vue'
import DocInline from '@/components/documentation/DocInline.vue'
import DocSection from '@/components/documentation/DocSection.vue'
import { availableDocTools, loadToolDoc } from '@/content/documentation'
import { TOOL_ICONS, TOOL_NAMES } from '@/content/documentation/tools'

/**
 * Página de documentación técnica de una herramienta. La herramienta sale de
 * `meta.docTool` de la ruta y el contenido de `content/documentation/<idioma>/<herramienta>.json`,
 * que se descarga al abrir la página y se vuelve a pedir al cambiar de idioma.
 */

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const tool = computed(() => route.meta.docTool)
const page = ref(null)
const articleRef = ref(null)
const activeSectionId = ref(null)

const tools = availableDocTools()
const toolIndex = computed(() => tools.indexOf(tool.value))
const previousTool = computed(() => tools[toolIndex.value - 1] ?? null)
const nextTool = computed(() => tools[toolIndex.value + 1] ?? null)

let sectionObserver = null

/**
 * Marca en el índice lateral la sección que se está leyendo: la última cuyo
 * título ha pasado por la franja superior de la pantalla.
 */
function observeSections() {
  sectionObserver?.disconnect()
  if (!articleRef.value || typeof IntersectionObserver === 'undefined') return
  sectionObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting)
    if (visible.length) activeSectionId.value = visible[0].target.id
  }, { rootMargin: '-80px 0px -70% 0px' })
  articleRef.value.querySelectorAll('.doc-section').forEach((section) => sectionObserver.observe(section))
}

/**
 * Lleva a una sección y deja su ancla en la URL, para poder enlazarla.
 *
 * @param {string} sectionId - El `id` de la sección.
 */
function goToSection(sectionId) {
  router.replace({ hash: `#${sectionId}` })
  document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

watch([tool, locale], async ([currentTool, currentLocale]) => {
  const loaded = await loadToolDoc(currentTool, currentLocale)
  if (currentTool !== tool.value) return
  page.value = loaded
  await nextTick()
  observeSections()
  // El ancla de la URL apunta a una sección que no existía hasta ahora: el
  // scroll del router ya pasó cuando el contenido todavía no había llegado.
  if (route.hash) document.getElementById(route.hash.slice(1))?.scrollIntoView({ block: 'start' })
}, { immediate: true })

onBeforeUnmount(() => sectionObserver?.disconnect())
</script>

<style scoped>
.doc-page { min-height: 100vh; background: var(--bg); display: flex; flex-direction: column; }

.doc-hero {
  border-bottom: 1px solid var(--border-med);
  background: radial-gradient(ellipse at 20% 0%, var(--accent-dim), transparent 65%);
}
.doc-hero-inner {
  max-width: 1160px; margin: 0 auto;
  padding: 4rem 2rem 3rem;
  display: flex; align-items: center; gap: 2rem;
}
.doc-hero-icon { width: 96px; height: 96px; object-fit: contain; flex-shrink: 0; filter: drop-shadow(0 0 22px var(--accent-dim)); }
.doc-eyebrow {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-sm); font-weight: 600;
  letter-spacing: 0.3em; text-transform: uppercase;
  color: var(--accent); text-decoration: none;
}
.doc-eyebrow:hover { color: var(--accent-bright); }
.doc-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-4xl); font-weight: 600; line-height: 1.1;
  color: var(--text);
  margin-top: 0.4rem;
}
.doc-lede { margin-top: 0.8rem; max-width: 62ch; font-size: var(--fs-lg); line-height: 1.6; color: var(--text-dim); }

.doc-layout {
  flex: 1;
  width: 100%; max-width: 1160px;
  margin: 0 auto;
  padding: 3.5rem 2rem 5rem;
  display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 4rem;
}

/* El índice y el texto se apoyan en superficies propias para despegarse del
   fondo de la página; el índice, más tenue, porque es secundario. */
.doc-toc {
  position: sticky; top: 5.5rem; align-self: start;
  max-height: calc(100vh - 7rem); overflow-y: auto;
  padding: 1.3rem 1.2rem 1.3rem 1.1rem;
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.doc-toc-title {
  display: block; margin-bottom: 0.9rem;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-sm); font-weight: 600;
  letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--text-muted);
}
.doc-toc ol { list-style: none; display: flex; flex-direction: column; border-left: 1px solid var(--border-med); }
.doc-toc a {
  display: block;
  padding: 0.38rem 0 0.38rem 1rem; margin-left: -1px;
  border-left: 2px solid transparent;
  font-size: var(--fs-body); line-height: 1.4;
  color: var(--text-muted); text-decoration: none;
  transition: color 0.15s, border-color 0.15s;
}
.doc-toc a:hover { color: var(--text); }
.doc-toc a.active { color: var(--accent-bright); border-left-color: var(--accent); }

.doc-article { min-width: 0; }
.doc-sheet {
  max-width: 76ch;
  padding: 2.8rem 3.2rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  font-size: var(--fs-md); line-height: 1.75; color: var(--text-dim);
}

/* Separador entre secciones: dos trazos de 2px que se desvanecen hacia los
   bordes y, en medio, el emblema de la portada a escala de texto. */
.doc-divider { display: flex; align-items: center; gap: 0.9rem; margin: 3.2rem 0 2.8rem; }
.doc-divider-rule { flex: 1; height: 2px; border-radius: 2px; }
.doc-divider-rule:first-child { background: linear-gradient(to right, transparent, var(--accent)); }
.doc-divider-rule:last-child { background: linear-gradient(to left, transparent, var(--accent)); }
.doc-divider-emblem { position: relative; width: 26px; height: 26px; flex: none; display: grid; place-items: center; }
.doc-divider-ring { position: absolute; border-radius: 50%; }
.doc-divider-ring--inner { width: 9px; height: 9px; background: var(--accent); box-shadow: 0 0 10px var(--accent-dim); }
.doc-divider-ring--outer { width: 24px; height: 24px; border: 1.5px dashed var(--accent); }

.doc-pager { max-width: 76ch; margin-top: 2rem; display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.doc-pager-link {
  display: flex; flex-direction: column; gap: 0.2rem;
  padding: 1rem 1.2rem;
  border: 1px solid var(--border-med); border-radius: var(--radius-sm);
  text-decoration: none;
  transition: border-color 0.15s, background 0.15s;
}
.doc-pager-link:hover { border-color: var(--accent); background: var(--accent-dim); }
.doc-pager-link--next { grid-column: 2; text-align: right; }
.doc-pager-label { font-size: var(--fs-xs); letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-muted); }
.doc-pager-name { font-family: var(--font-display); font-size: var(--fs-xl); color: var(--accent); }

@media (max-width: 900px) {
  .doc-layout { grid-template-columns: 1fr; gap: 2rem; padding-top: 2rem; }
  .doc-toc { position: static; max-height: none; }
}
@media (max-width: 640px) {
  .doc-hero-inner { flex-direction: column; align-items: flex-start; gap: 1.2rem; padding: 2.5rem 1rem 2rem; }
  .doc-hero-icon { width: 64px; height: 64px; }
  .doc-layout { padding: 1.5rem 1rem 4rem; }
  .doc-sheet { padding: 1.8rem 1.2rem; }
  .doc-pager { grid-template-columns: 1fr; }
  .doc-pager-link--next { grid-column: auto; }
}
</style>
