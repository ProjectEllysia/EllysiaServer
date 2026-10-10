<template>
  <ul
    ref="treeEl"
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
        @click.stop="toggle(row.node.code)"
      >{{ row.isExpanded ? '▾' : '▸' }}</button>
      <span v-else class="caret caret--spacer" aria-hidden="true"></span>

      <span class="id">{{ row.node.identifier }}</span>
      <span class="title">{{ row.node.title }}</span>

      <span v-if="row.node.progress && !row.node.assessment && row.node.progress.countable" class="group-progress">
        {{ percent(row.node.progress.percent) }}
      </span>

      <span v-if="row.node.evidenceState === 'expired'" class="evidence-flag">
        {{ t('eunomia.evidence.expiredFlag') }}
      </span>

      <span v-if="statusOf(row.node)" class="status" :class="`status--${statusOf(row.node)}`">
        <span class="dot" aria-hidden="true"></span>
        <span class="status-text">{{ t(`eunomia.status.${statusOf(row.node)}`) }}</span>
      </span>
    </li>
    <li v-if="!rows.length" class="empty" role="none">{{ t('eunomia.tree.noMatches') }}</li>
  </ul>
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
  treeEl.value?.querySelector(`[data-code="${CSS.escape(code)}"]`)?.focus()
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
.tree { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.item {
  display: flex; align-items: center; gap: 0.5rem; padding-block: 0.4rem; padding-inline-end: 0.6rem;
  border-radius: 6px; cursor: pointer; color: var(--text-dim); font-size: var(--fs-md);
}
.item:hover { background: var(--surface-2, var(--bg)); }
.item:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: -2px; }
.item--selected { background: var(--accent-dim); color: var(--text); }
.item--path { opacity: 0.7; }
.caret { width: 1rem; flex: none; color: var(--text-muted); text-align: center; }
.caret--spacer { display: inline-block; }
.id { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); color: var(--text-muted); flex: none; }
.title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.evidence-flag { flex: none; font-size: var(--fs-sm); color: var(--danger); }
.group-progress { flex: none; font-size: var(--fs-sm); color: var(--text-muted); font-variant-numeric: tabular-nums; }
.status { display: inline-flex; align-items: center; gap: 0.35rem; flex: none; font-size: var(--fs-sm); }
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--text-muted); }
.status--implemented .dot { background: var(--success, #4caf7a); }
.status--in_progress .dot { background: var(--warning, #d4a04a); }
.status--not_applicable .dot { background: var(--border-med); }
.empty { color: var(--text-muted); padding: 1rem; font-size: var(--fs-md); }
</style>
