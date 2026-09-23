<template>
  <div class="picker" @focusout="onFocusOut">
    <input
      :id="inputId" ref="field"
      v-model="query"
      type="text" class="picker-field" autocomplete="off" spellcheck="false"
      :placeholder="placeholder"
      role="combobox" aria-autocomplete="list" :aria-expanded="isOpen"
      :aria-controls="listId"
      :aria-activedescendant="isOpen && highlighted !== null ? optionId(highlighted) : undefined"
      @focus="onFocus" @keydown="onKeydown"
    />

    <!-- Aspa para vaciar lo escrito sin tener que borrarlo a mano. No está
         cuando el campo está vacío: un botón que no hace nada estorba. -->
    <button
      v-if="query" type="button" class="picker-clear"
      aria-label="Vaciar la búsqueda" @click="clearQuery"
    >×</button>

    <!-- La lista se monta solo mientras está abierta: así no hay nada que un
         lector de pantalla pueda recorrer cuando no se ve. -->
    <div v-if="isOpen" class="picker-pop">
      <ul :id="listId" class="picker-list" role="listbox" :aria-label="listLabel">
        <li
          v-for="asset in visible" :key="asset.id"
          :id="optionId(asset.id)"
          class="picker-option" :class="{ 'picker-option--on': asset.id === highlighted }"
          role="option" :aria-selected="asset.id === modelValue"
          @mousemove="highlighted = asset.id"
          @mousedown.prevent="choose(asset.id)"
        >
          <span class="pulse" :class="assetPresence(asset).pulseClass" aria-hidden="true"></span>
          <span class="picker-text">
            <span class="picker-host">
              <span
                v-for="(part, index) in highlightParts(asset.hostname, query)" :key="index"
                :class="{ 'picker-hit': part.isMatch }"
              >{{ part.text }}</span>
            </span>
            <span class="picker-meta">
              {{ assetPresence(asset).label }}<template v-if="asset.os"> · {{ asset.os }}</template>
            </span>
          </span>
          <span v-if="asset.tags?.length" class="picker-tags">
            <TagBadge v-for="tag in asset.tags.slice(0, MAX_OPTION_TAGS)" :key="tag.id" :tag="tag" small />
            <span v-if="asset.tags.length > MAX_OPTION_TAGS" class="picker-tags-more">
              +{{ asset.tags.length - MAX_OPTION_TAGS }}
            </span>
          </span>
        </li>
      </ul>

      <p v-if="!matches.length" class="picker-note">
        Ningún activo se parece a «{{ query }}».
      </p>
      <!-- Decir cuántos quedan fuera es lo que convierte un recorte en un
           aviso: sin esta línea, el tope parecería que el activo no existe. -->
      <p v-else-if="matches.length > visible.length" class="picker-note">
        <template v-if="query.trim()">
          {{ matches.length - visible.length }} activos más coinciden. Escribe algo más para acotar.
        </template>
        <template v-else>
          Tienes {{ matches.length }} activos. Escribe para buscar el que quieras.
        </template>
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, useId, watch } from 'vue'
import TagBadge from '@/components/hygeia/TagBadge.vue'
import { assetPresence } from '@/components/hygeia/format'
import { highlightParts, searchAssets } from '@/components/hygeia/assetSearch'

/**
 * Buscador de un activo del parque.
 *
 * Sustituye al desplegable de toda la vida, que con cientos de máquinas no
 * servía: aquí se escribe parte del nombre y aparecen debajo los que se le
 * parecen, ordenados por lo bien que encajan (`assetSearch.js`). Sin nada
 * escrito enseña el parque por orden alfabético, así que para cuatro máquinas
 * se comporta igual que el desplegable que sustituye.
 *
 * Sigue el patrón *combobox* de WAI-ARIA: el campo anuncia si la lista está
 * abierta y cuál es la opción resaltada, y la lista y sus opciones llevan sus
 * papeles. El foco no se mueve nunca de la caja de texto —lo que recorren las
 * flechas es el resaltado, no el foco—, que es lo que permite seguir
 * escribiendo mientras se elige.
 */
const props = defineProps({
  /** Parque completo, tal y como lo sirve `GET /hygeia/assets`. */
  assets: { type: Array, required: true },
  /** Id del activo elegido, o `null` si todavía no hay ninguno. */
  modelValue: { type: Number, default: null },
  /** Id del `<input>`, para poder atarlo a un `<label for>` de fuera. */
  inputId: { type: String, default: undefined },
  placeholder: { type: String, default: 'Busca un activo por nombre…' },
})

const emit = defineEmits(['update:modelValue'])

// Tope de opciones a la vista. Con más, la lista deja de ser una respuesta y
// vuelve a ser el muro del que se venía huyendo; lo que sobra se cuenta en el
// pie, que es información más útil que otras cien filas.
const MAX_VISIBLE = 8

/** Etiquetas por opción antes de resumir el resto en un «+N». */
const MAX_OPTION_TAGS = 1

const field = ref(null)
const query = ref('')
const isOpen = ref(false)
const highlighted = ref(null)

const listId = useId()
const optionId = (id) => `${listId}-${id}`

const selected = computed(() => props.assets.find((asset) => asset.id === props.modelValue) ?? null)

const matches = computed(() => searchAssets(props.assets, query.value))

/**
 * Rótulo de la lista para un lector de pantalla. Sin nada escrito, la lista es
 * el parque; con texto, lo que se le parece.
 *
 * @type {import('vue').ComputedRef<string>}
 */
const listLabel = computed(() => (query.value.trim()
  ? `Activos que se parecen a «${query.value.trim()}»`
  : 'Tus activos'))
const visible = computed(() => matches.value.slice(0, MAX_VISIBLE))

/**
 * Con el buscador cerrado, el campo enseña el activo elegido: es el rótulo de
 * la selección, no el rastro de la última búsqueda. Al elegir desde fuera
 * (una vuelta atrás del navegador, por ejemplo) el nombre aparece solo.
 */
watch(selected, (asset) => {
  if (!isOpen.value) query.value = asset?.hostname ?? ''
}, { immediate: true })

// Escribir reabre la lista y lleva el resaltado al mejor candidato: al teclear
// otra letra, lo resaltado antes puede haber dejado de encajar.
watch(query, () => {
  if (isOpen.value) highlighted.value = visible.value[0]?.id ?? null
})

/**
 * Abre la lista y selecciona lo escrito, para que la primera tecla reemplace
 * el nombre del activo elegido en vez de añadirse a él: quien vuelve al campo
 * casi siempre viene a cambiar de máquina, no a corregir una letra.
 */
function onFocus() {
  isOpen.value = true
  highlighted.value = props.modelValue ?? visible.value[0]?.id ?? null
  field.value?.select()
}

/** Cierra al salir del componente, incluso si el foco se va a otra ventana. */
function onFocusOut(event) {
  if (event.currentTarget.contains(event.relatedTarget)) return
  close()
}

/**
 * Cierra la lista y devuelve al campo el nombre del activo elegido, para no
 * dejar escrito un texto que no se corresponde con la selección.
 */
function close() {
  isOpen.value = false
  highlighted.value = null
  query.value = selected.value?.hostname ?? ''
}

function choose(id) {
  emit('update:modelValue', id)
  isOpen.value = false
  highlighted.value = null
  query.value = props.assets.find((asset) => asset.id === id)?.hostname ?? ''
}

function clearQuery() {
  query.value = ''
  isOpen.value = true
  highlighted.value = visible.value[0]?.id ?? null
  field.value?.focus()
}

/**
 * Mueve el resaltado `step` posiciones dentro de lo visible, dando la vuelta
 * en los extremos, y se asegura de que la opción resaltada esté a la vista
 * cuando la lista lleva desplazamiento.
 *
 * @param {number} step - `1` para bajar, `-1` para subir.
 */
async function moveHighlight(step) {
  const ids = visible.value.map((asset) => asset.id)
  if (!ids.length) return
  const current = ids.indexOf(highlighted.value)
  highlighted.value = ids[(current + step + ids.length) % ids.length]
  await nextTick()
  document.getElementById(optionId(highlighted.value))?.scrollIntoView({ block: 'nearest' })
}

/**
 * Teclado del combobox: flechas para recorrer los resultados, Inicio y Fin
 * para ir a los extremos, Intro para elegir el resaltado y Escape para cerrar
 * sin cambiar nada. El resto de teclas escriben, que es el caso normal.
 *
 * @param {KeyboardEvent} event - Pulsación recibida en el campo.
 */
function onKeydown(event) {
  if (event.key === 'Escape') {
    if (!isOpen.value) return
    event.preventDefault()
    close()
    return
  }
  if (event.key === 'Enter') {
    if (!isOpen.value || highlighted.value === null) return
    event.preventDefault()
    choose(highlighted.value)
    return
  }
  const steps = { ArrowDown: 1, ArrowUp: -1 }
  if (event.key in steps) {
    event.preventDefault()
    if (!isOpen.value) { onFocus(); return }
    moveHighlight(steps[event.key])
    return
  }
  // Inicio y Fin solo saltan dentro de la lista cuando hay lista; con ella
  // cerrada siguen siendo lo que son en un campo de texto.
  if ((event.key === 'Home' || event.key === 'End') && isOpen.value && visible.value.length) {
    event.preventDefault()
    highlighted.value = event.key === 'Home'
      ? visible.value[0].id
      : visible.value[visible.value.length - 1].id
  }
}
</script>

<style scoped>
.picker { position: relative; }

/* Mismas medidas y mismo fondo que los `select` de al lado: el buscador es un
   control más de la misma barra, y la base global de `input` es algo más alta
   que ellos. La clase `.inp` de la vista no sirve aquí — un estilo con ámbito
   no cruza a los hijos de un componente. */
.picker-field {
  width: 100%;
  padding: 0.4rem 1.7rem 0.4rem 0.55rem;
  background: var(--bg); border: 1px solid var(--border-med); border-radius: 6px;
  color: var(--text); font-size: var(--fs-md);
}

.picker-clear {
  position: absolute; top: 0; right: 0;
  width: 1.7rem; height: 100%;
  background: none; border: none;
  color: var(--text-muted); font-size: var(--fs-lg); line-height: 1; cursor: pointer;
}
.picker-clear:hover { color: var(--text); }
.picker-clear:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 4px; }

/* Flotante y por encima del resto del selector: la lista no debe empujar los
   controles que tiene al lado cada vez que se escribe una letra. */
.picker-pop {
  position: absolute; z-index: 10; top: calc(100% + 0.25rem); left: 0;
  /* Más ancha que el campo para que quepa el nombre de una máquina entero,
     pero nunca más que la pantalla: en un móvil el campo ya ocupa el ancho
     completo y un mínimo fijo sacaría la lista fuera. */
  width: max(100%, min(340px, calc(100vw - 3rem))); max-height: 19rem; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border-med); border-radius: 6px;
  box-shadow: 0 8px 20px rgb(0 0 0 / 35%);
}

.picker-list { list-style: none; margin: 0; padding: 0.2rem; }
.picker-option {
  display: flex; align-items: center; gap: 0.55rem;
  padding: 0.4rem 0.5rem; border-radius: 4px; cursor: pointer;
}
.picker-option--on { background: var(--accent-dim); }

.pulse { width: 9px; height: 9px; flex-shrink: 0; border-radius: 50%; background: var(--text-muted); }
.pulse--online { background: var(--success); }
.pulse--stale { background: var(--warn); }
.pulse--offline { background: var(--danger); }
.pulse--pending { background: var(--text-muted); box-shadow: inset 0 0 0 1px var(--border-med); }
/* Caído a propósito: apagado, no en alarma. */
.pulse--dormant { background: transparent; box-shadow: inset 0 0 0 1.5px var(--text-muted); }

.picker-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.picker-host {
  font-size: var(--fs-md); color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* La parte que coincide, marcada donde está: es lo que explica por qué este
   activo salió y por qué está en esta posición de la lista. */
.picker-hit { color: var(--accent-bright); font-weight: 600; }
.picker-meta {
  font-size: var(--fs-sm); color: var(--text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Las etiquetas ceden antes que el nombre: son el porqué de que el activo
   salga en la lista, pero quien elige lee el nombre. Cuando no caben, lo que
   se recorta es el texto de la etiqueta, nunca la etiqueta a media pastilla:
   «europa-o…» se lee, media pastilla parece un fallo de pintado. */
.picker-tags { display: flex; align-items: center; gap: 0.2rem; flex-shrink: 0; max-width: 38%; }
.picker-tags :deep(.tag-badge) { min-width: 0; }
.picker-tags :deep(.tag-name) { overflow: hidden; text-overflow: ellipsis; }
.picker-tags-more { font-size: var(--fs-sm); color: var(--text-muted); }

.picker-note {
  margin: 0; padding: 0.45rem 0.7rem;
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.4;
}
/* Sin resultados no hay lista de la que separarse. */
.picker-list:empty + .picker-note { border-top: none; }
</style>
