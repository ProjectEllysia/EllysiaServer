<template>
  <TransitionGroup
    ref="treeEl"
    tag="ul"
    name="row"
    class="tree"
    role="tree"
    :aria-label="label"
    @keydown="onKeydown"
  >
    <li
      v-for="row in rows"
      :key="row.node.code"
      role="treeitem"
      :aria-level="row.level"
      :aria-expanded="row.hasChildren ? row.isExpanded : undefined"
      :aria-selected="row.node.code === selected"
      :tabindex="row.node.code === focused ? 0 : -1"
      :data-code="row.node.code"
      class="item"
      :class="{ 'item--selected': row.node.code === selected, 'item--path': row.node.isPathOnly }"
      :style="{ paddingInlineStart: `${(row.level - 1) * 1.1 + 0.4}rem` }"
      @click="select(row.node)"
      @focus="focused = row.node.code"
    >
      <button
        v-if="row.hasChildren"
        type="button"
        class="caret"
        :aria-label="row.isExpanded ? t('eunomia.tree.collapse') : t('eunomia.tree.expand')"
        tabindex="-1"
        :class="{ 'caret--open': row.isExpanded }"
        @click.stop="toggle(row.node.code)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="9 6 15 12 9 18" />
        </svg>
      </button>
      <span v-else class="caret caret--spacer" aria-hidden="true"></span>

      <span class="id">{{ row.node.identifier }}</span>
      <span class="title" :title="row.node.title">{{ row.node.title }}</span>

      <span v-if="row.node.progress && !row.node.assessment && row.node.progress.countable" class="group-progress">
        {{ percent(row.node.progress.percent) }}
      </span>

      <span v-if="row.node.evidenceState === 'expired'" class="evidence-flag">
        {{ t('eunomia.evidence.expiredFlag') }}
      </span>

      <span
        v-if="statusOf(row.node)" class="status" :class="`status--${statusOf(row.node)}`"
        :title="t(`eunomia.status.${statusOf(row.node)}`)"
      >
        <span class="dot" aria-hidden="true"></span>
        <span class="status-text">{{ t(`eunomia.status.${statusOf(row.node)}`) }}</span>
      </span>
    </li>
    <li v-if="!rows.length" key="__empty" class="empty" role="none">{{ t('eunomia.tree.noMatches') }}</li>
  </TransitionGroup>
</template>

<script setup>
/**
 * Árbol de controles de un marco, con el patrón ARIA de árbol. Pinta una lista plana de lo
 * visible (calculada por `tree.js`), así que no depende de la profundidad del marco.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { keyAction, statusOf, visibleNodes } from '@/components/eunomia/tree'
import { formatNumber } from '@/i18n/format'

const props = defineProps({
  /** Raíces del árbol (ya filtrado). */
  nodes: { type: Array, required: true },
  /** Código del nodo seleccionado. */
  selected: { type: String, default: '' },
  /** Códigos de los grupos desplegados; se edita con `update:expanded`. */
  expanded: { type: Object, required: true },
  label: { type: String, default: '' },
})
const emit = defineEmits(['select', 'update:expanded'])
const { t } = useI18n()

const treeEl = ref(null)
const focused = ref('')

const rows = computed(() => visibleNodes(props.nodes, props.expanded))

watch(rows, (list) => {
  if (!list.some((row) => row.node.code === focused.value)) focused.value = list[0]?.node.code ?? ''
}, { immediate: true })

/** Un porcentaje (0 a 100) con el formato del idioma activo. */
function percent(value) {
  return formatNumber(value / 100, { style: 'percent', maximumFractionDigits: 0 })
}

/** Abre o cierra un grupo. */
function toggle(code) {
  const next = new Set(props.expanded)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  emit('update:expanded', next)
}

/** Selecciona un nodo (y lo deja con el foco). */
function select(node) {
  focused.value = node.code
  emit('select', node)
}

/** Mueve el foco a un nodo y se lo da al elemento. */
async function focusCode(code) {
  focused.value = code
  await nextTick()
  treeEl.value?.$el?.querySelector(`[data-code="${CSS.escape(code)}"]`)?.focus()
}

/** Teclado según el patrón de árbol de ARIA. */
function onKeydown(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    const row = rows.value.find((item) => item.node.code === focused.value)
    if (row) { event.preventDefault(); select(row.node) }
    return
  }
  const action = keyAction(rows.value, focused.value, event.key)
  if (action.focus === null && action.toggle === null) return
  event.preventDefault()
  if (action.toggle) toggle(focused.value)
  if (action.focus) focusCode(action.focus)
}
</script>

<style scoped>
/* El contenedor mide su propio ancho: cuando el panel es estrecho, el estado pasa a
   ser solo el punto (con su nombre en el título) y el nombre del control gana sitio. */
.tree { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; container-type: inline-size; }
.item {
  display: flex; align-items: center; gap: 0.5rem; padding-block: 0.4rem; padding-inline-end: 0.6rem;
  margin-bottom: 0.25rem; border: 1px solid var(--border); border-radius: 8px; cursor: pointer;
  background: var(--surface-2, var(--bg)); color: var(--text-dim); font-size: var(--fs-md);
  transition: background-color 0.28s var(--ease-settle), border-color 0.28s var(--ease-settle),
    box-shadow 0.28s var(--ease-settle), transform 0.28s var(--ease-settle), color 0.28s ease;
}
.item:hover {
  background: color-mix(in srgb, var(--accent-dim) 55%, var(--surface-2, var(--bg)));
  border-color: var(--border-med); transform: translateX(2px);
}
.item:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: -2px; }
.item--selected, .item--selected:hover {
  background: var(--accent-dim); border-color: var(--accent); color: var(--text);
  box-shadow: inset 3px 0 0 var(--accent);
}
.item--path { opacity: 0.7; }

/* Despliegue: las filas que aparecen crecen desde cero y las que se van se pliegan, de
   modo que las de debajo se deslizan en vez de saltar. */
.row-enter-active, .row-leave-active {
  overflow: hidden; max-height: 8rem;
  transition: max-height 0.38s var(--ease-settle), opacity 0.3s ease, transform 0.38s var(--ease-settle),
    padding-block 0.38s var(--ease-settle), margin-bottom 0.38s var(--ease-settle), border-width 0.38s ease;
}
.row-enter-from, .row-leave-to {
  max-height: 0; opacity: 0; transform: translateX(-10px);
  padding-block: 0; margin-bottom: 0; border-width: 0;
}

/* El botón de desplegar es un blanco de 1,75 rem, no un triangulito. */
.caret {
  width: 1.75rem; height: 1.75rem; flex: none; display: grid; place-items: center;
  border-radius: 6px; color: var(--text-muted); background: transparent;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.caret svg { width: 1.05rem; height: 1.05rem; transition: transform 0.32s var(--ease-settle); }
.caret--open svg { transform: rotate(90deg); }
.caret:hover { background: var(--accent-dim); color: var(--accent-bright); }
.caret--spacer { display: block; }
.id { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); color: var(--text-muted); flex: none; }
/* Dos líneas como máximo; el control seleccionado se enseña entero (y el título
   completo está siempre en el atributo `title`). */
.title {
  flex: 1; min-width: 0; overflow-wrap: anywhere; line-height: 1.3;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden;
}
.item--selected .title { -webkit-line-clamp: unset; line-clamp: unset; }
.evidence-flag { flex: none; font-size: var(--fs-sm); color: var(--danger); }
.group-progress { flex: none; font-size: var(--fs-sm); color: var(--text-muted); font-variant-numeric: tabular-nums; }
.status { display: inline-flex; align-items: center; gap: 0.35rem; flex: none; font-size: var(--fs-sm); }
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--text-muted); transition: background-color 0.3s ease; }
.status--implemented .dot { background: var(--success, #4caf7a); }
.status--in_progress .dot { background: var(--warning, #d4a04a); }
.status--not_applicable .dot { background: var(--border-med); }
.empty { color: var(--text-muted); padding: 1rem; font-size: var(--fs-md); }
@container (max-width: 30rem) { .status-text { display: none; } }

@media (prefers-reduced-motion: reduce) {
  .item, .caret, .caret svg, .dot, .row-enter-active, .row-leave-active { transition: none !important; }
  .item:hover { transform: none; }
}
</style>
