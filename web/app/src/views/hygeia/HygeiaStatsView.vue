<template>
  <div class="stats-page" data-module="hygeia">
    <StarBackground />
    <Topbar title="Hygeia" badge="Estadísticas" back-to="/hygeia/activos" back-label="Activos" />

    <main class="stats-layout">
      <header class="head">
        <div class="head-text">
          <h2 class="head-title">Estadísticas</h2>
          <p class="head-sub">
            El histórico agregado de lo que ya se recolecta: máximos, medias y percentiles de un
            activo, de una etiqueta o de todo el parque. Los números los calcula el servidor; aquí
            solo se leen.
          </p>
        </div>
      </header>

      <!-- Panorama del parque: una foto del ahora, sin periodo. Es la pantalla
           de aterrizaje, y por eso no depende del selector. -->
      <section class="overview" aria-label="Panorama del parque">
        <!-- Tarjetas fantasma con la silueta de las reales (rótulo, cifra y
             pie): reservan el alto y el panorama no empuja la página al llegar. -->
        <div
          v-if="store.state.overviewLoading && !store.state.overview"
          class="tiles" aria-busy="true" aria-label="Cargando el panorama"
        >
          <div v-for="n in OVERVIEW_TILE_COUNT" :key="n" class="tile" aria-hidden="true">
            <span class="tile-label"><span class="skeleton skeleton--line skeleton-inline skeleton--w60"></span></span>
            <span class="tile-value"><span class="skeleton skeleton--line skeleton-inline skeleton--w40"></span></span>
            <span class="tile-sub"><span class="skeleton skeleton--line skeleton-inline skeleton--w80"></span></span>
          </div>
        </div>
        <p v-else-if="store.state.overviewError" class="state-msg state-msg--error">
          {{ store.state.overviewError }}
        </p>
        <div v-else-if="store.state.overview" class="tiles tiles--ready">
          <div class="tile">
            <span class="tile-label">Activos</span>
            <span class="tile-value">{{ store.state.overview.assetCount }}</span>
            <span class="tile-sub">{{ onlineCount }} en línea</span>
          </div>
          <div class="tile">
            <span class="tile-label">Anomalías abiertas</span>
            <span class="tile-value">{{ openAnomalies }}</span>
            <span class="tile-sub">{{ criticalAnomalies }} críticas</span>
          </div>
          <div class="tile">
            <span class="tile-label">Reconocidas</span>
            <span class="tile-value">{{ store.state.overview.acknowledgedAnomalyCount }}</span>
            <span class="tile-sub">ya tienen quien las mire</span>
          </div>
          <div class="tile">
            <span class="tile-label">Última actividad</span>
            <span class="tile-value tile-value--text">
              {{ timeAgo(store.state.overview.lastActivityAt) }}
            </span>
            <span class="tile-sub">el último latido del parque</span>
          </div>
        </div>
      </section>

      <!-- Selector común a las dos pestañas: sobre qué (alcance), cómo se
           combinan los activos y durante cuánto. La métrica del ranking no
           está aquí porque solo la usa «Resumen», y la gráfica elige sus
           métricas con sus propios botones. -->
      <section class="controls" aria-label="Selector de estadísticas">
        <div class="control">
          <label class="control-label" for="scope-select">Alcance</label>
          <select id="scope-select" class="inp" :value="store.state.scope" @change="onScopeChange">
            <option v-for="option in STATS_SCOPES" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div v-if="store.state.scope === 'asset'" class="control">
          <label class="control-label" for="asset-select">Activo</label>
          <select id="asset-select" v-model.number="store.state.assetId" class="inp">
            <option :value="null" disabled>Elige un activo…</option>
            <option v-for="asset in assets" :key="asset.id" :value="asset.id">
              {{ asset.hostname }}
            </option>
          </select>
        </div>

        <div v-if="store.state.scope === 'tag'" class="control">
          <label class="control-label" for="tag-select">Etiqueta</label>
          <select id="tag-select" v-model.number="store.state.tagId" class="inp">
            <option :value="null" disabled>Elige una etiqueta…</option>
            <option v-for="tag in tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
          </select>
        </div>

        <div v-if="store.state.scope !== 'asset'" class="control">
          <label class="control-label" for="agg-select">Combinar</label>
          <select id="agg-select" v-model="store.state.aggregation" class="inp">
            <option
              v-for="option in aggregationOptions" :key="option.value"
              :value="option.value" :disabled="option.disabled"
            >{{ option.label }}</option>
          </select>
        </div>

        <div class="control">
          <span class="control-label">Periodo</span>
          <div class="periods">
            <button
              v-for="option in STATS_PERIODS" :key="option.value"
              type="button" class="period-btn"
              :class="{ 'period-btn--on': store.state.period === option.value }"
              :aria-pressed="store.state.period === option.value"
              @click="store.state.period = option.value"
            >{{ option.label }}</button>
          </div>
        </div>
      </section>

      <!-- Dos preguntas distintas sobre la misma selección: los números del
           periodo y cómo evolucionan en el tiempo. Solo se pide lo de la
           pestaña visible. Teclado según el patrón de tablist: flechas para
           moverse, Inicio/Fin a los extremos, y solo la activa es tabulable. -->
      <div class="tabs" role="tablist" aria-label="Vistas de estadísticas" @keydown="onTabKeydown">
        <button
          v-for="tab in STATS_TABS" :key="tab.id"
          :id="`tab-${tab.id}`" ref="tabButtons"
          type="button" class="tab" :class="{ 'tab--on': activeTab === tab.id }"
          role="tab" :aria-selected="activeTab === tab.id" :aria-controls="`panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="selectTab(tab.id)"
        >{{ tab.label }}</button>
      </div>

      <section
        v-if="activeTab === 'resumen'"
        id="panel-resumen" class="results" role="tabpanel" aria-labelledby="tab-resumen"
      >
        <div class="results-bar">
          <div v-if="store.state.scope === 'fleet'" class="control">
            <label class="control-label" for="metric-select">Métrica</label>
            <select id="metric-select" v-model="store.state.metric" class="inp">
              <option v-for="metric in STATS_METRICS" :key="metric.key" :value="metric.key">
                {{ metric.name }}
              </option>
            </select>
          </div>
          <button
            class="btn-export" type="button"
            :disabled="!isSelectionComplete || store.state.exporting"
            :title="isSelectionComplete ? 'Descargar en CSV lo que hay en pantalla'
              : 'Elige un alcance completo para poder exportar'"
            @click="exportCsv"
          >{{ store.state.exporting ? 'Exportando…' : 'Exportar CSV' }}</button>
        </div>

        <!-- Tabla fantasma con las mismas columnas y el mismo número de filas
             que la que va a llegar, para que el panel no cambie de alto. -->
        <div
          v-if="store.state.scopeLoading" class="table-ghost"
          aria-busy="true" aria-label="Calculando las estadísticas"
        >
          <span class="table-ghost-caption" aria-hidden="true">
            <span class="skeleton skeleton--line skeleton-inline skeleton--w40"></span>
          </span>
          <div
            v-for="row in ghostTable.rows" :key="row" class="table-ghost-row"
            :class="{ 'table-ghost-row--head': row === 1 }"
            :style="{ gridTemplateColumns: ghostTable.template }" aria-hidden="true"
          >
            <span v-for="column in ghostTable.columns" :key="column" class="table-ghost-cell">
              <span
                class="skeleton skeleton--line skeleton-inline"
                :class="column === 1 ? 'skeleton--w60' : 'skeleton--w40'"
              ></span>
              <span v-if="row > 1 && column === ghostTable.sublineColumn" class="table-ghost-sub">
                <span class="skeleton skeleton--line skeleton-inline skeleton--w60"></span>
              </span>
            </span>
          </div>
        </div>
        <p v-else-if="store.state.scopeError" class="state-msg state-msg--error">
          {{ store.state.scopeError }}
        </p>
        <p v-else-if="!isSelectionComplete" class="state-msg">
          {{ store.state.scope === 'asset' ? 'Elige un activo para ver su resumen.'
            : 'Elige una etiqueta para ver sus métricas agregadas.' }}
        </p>

        <!-- Un activo: el resumen completo, una fila por métrica. -->
        <template v-else-if="store.state.scope === 'asset' && store.state.summary">
          <table class="table reveal">
            <caption class="table-caption">
              Resumen del activo. {{ describeCoverage(store.state.summary) }}
            </caption>
            <thead>
              <tr>
                <th scope="col">Métrica</th>
                <th scope="col">Mín.</th>
                <th scope="col">Media</th>
                <th scope="col">p95</th>
                <th scope="col">Máx.</th>
                <th scope="col">Ahora</th>
                <th scope="col">Muestras</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in summaryTable" :key="row.key" :class="{ 'row--empty': !row.hasData }">
                <th scope="row" class="row-name">{{ row.name }}</th>
                <td><Stat :value="row.min" /></td>
                <td><Stat :value="row.avg" /></td>
                <td><Stat :value="row.p95" /></td>
                <td>
                  <Stat :value="row.max" />
                  <span v-if="row.timestampOfMax" class="cell-sub">
                    {{ timeAgo(row.timestampOfMax) }}
                  </span>
                </td>
                <td><Stat :value="row.current" /></td>
                <td class="cell-num">{{ row.hasData ? row.sampleCount : 'sin datos' }}</td>
              </tr>
            </tbody>
          </table>
        </template>

        <!-- Una etiqueta: una fila por métrica, ya combinada entre sus activos. -->
        <template v-else-if="store.state.scope === 'tag' && store.state.tagStats">
          <table class="table reveal">
            <caption class="table-caption">
              {{ store.state.tagStats.assetCount }}
              {{ store.state.tagStats.assetCount === 1 ? 'activo lleva' : 'activos llevan' }}
              esta etiqueta. {{ describeCoverage(store.state.tagStats) }}
            </caption>
            <thead>
              <tr>
                <th scope="col">Métrica</th>
                <th scope="col">{{ aggregationLabel }}</th>
                <th scope="col">Activos con datos</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in tagTable" :key="row.key" :class="{ 'row--empty': !row.hasData }">
                <th scope="row" class="row-name">{{ row.name }}</th>
                <td><Stat :value="row.value" /></td>
                <td class="cell-num">{{ row.assetsWithData }}</td>
              </tr>
            </tbody>
          </table>
        </template>

        <!-- El parque: el ranking por la métrica elegida. -->
        <template v-else-if="store.state.scope === 'fleet' && store.state.ranking">
          <table class="table reveal">
            <caption class="table-caption">
              Los activos con mayor {{ aggregationLabel.toLowerCase() }} de
              {{ metricName }}, de {{ store.state.ranking.assetsWithData }} con datos sobre
              {{ store.state.ranking.assetCount }}. {{ describeCoverage(store.state.ranking) }}
            </caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Activo</th>
                <th scope="col">{{ metricName }}</th>
                <th scope="col">Muestras</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rankingTable" :key="row.assetId">
                <td class="cell-num">{{ row.position }}</td>
                <th scope="row" class="row-name">{{ row.hostname }}</th>
                <td><Stat :value="row.value" /></td>
                <td class="cell-num">{{ row.sampleCount }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!rankingTable.length" class="state-msg">
            Ningún activo reportó esta métrica en el periodo.
          </p>
        </template>
      </section>

      <!-- Gráfica comparativa: varias métricas superpuestas sobre el mismo eje
           temporal. Cada una lleva su propia escala vertical, porque son
           unidades distintas y compartir eje aplastaría el porcentaje contra el
           suelo; lo que se compara es la forma de las curvas. -->
      <section
        v-if="activeTab === 'evolucion'"
        id="panel-evolucion" class="compare" role="tabpanel" aria-labelledby="tab-evolucion"
      >
        <header class="compare-head">
          <h3 class="compare-title">Comparar métricas</h3>
          <div class="metric-toggles" role="group" aria-label="Métricas superpuestas">
            <button
              v-for="metric in STATS_METRICS" :key="metric.key"
              type="button" class="toggle"
              :class="{ 'toggle--on': store.state.comparisonMetrics.includes(metric.key) }"
              :aria-pressed="store.state.comparisonMetrics.includes(metric.key)"
              :disabled="isToggleDisabled(metric.key)"
              @click="store.toggleComparisonMetric(metric.key)"
            >{{ metric.name }}</button>
          </div>
        </header>

        <p v-if="!canCompare" class="state-msg">
          {{ compareUnavailableReason }}
        </p>
        <p v-else-if="store.state.seriesLoading" class="state-msg">Cargando las series…</p>
        <p v-else-if="store.state.seriesError" class="state-msg state-msg--error">
          {{ store.state.seriesError }}
        </p>
        <p v-else-if="!lanes.length" class="state-msg">
          Ninguna de las métricas elegidas tiene datos en el periodo.
        </p>
        <template v-else>
          <svg
            class="chart" :viewBox="`0 0 ${PLOT.width} ${PLOT.height + AXIS_HEIGHT}`"
            preserveAspectRatio="none" role="img" :aria-label="chartLabel"
          >
            <!-- Rejilla horizontal: solo orientación. No lleva rótulos porque
                 cada línea tiene su escala y un único eje Y numérico sería
                 falso para dos de las tres. -->
            <line
              v-for="fraction in [0, 0.25, 0.5, 0.75, 1]" :key="fraction"
              class="grid" x1="0" :x2="PLOT.width"
              :y1="fraction * PLOT.height" :y2="fraction * PLOT.height"
            />
            <polyline
              v-for="segment in segments" :key="segment.id"
              class="line" :points="segment.points" :style="{ stroke: segment.color }"
            />
            <text
              v-for="tick in axisTicks" :key="tick.at"
              class="tick" :x="tick.x" :y="PLOT.height + 14"
              :text-anchor="tick.anchor"
            >{{ tick.label }}</text>
          </svg>

          <ul class="legend">
            <li v-for="lane in lanes" :key="lane.key" class="legend-item">
              <span class="legend-dot" :style="{ background: lane.color }"></span>
              <span class="legend-name">{{ lane.name }}</span>
              <span class="legend-range">{{ describeLaneRange(lane) }}</span>
            </li>
          </ul>
          <p class="compare-note">
            Cada línea usa su propia escala vertical: se comparan las formas en el tiempo, no las
            alturas entre sí. Cubo de {{ fmtDuration(bucketMs) }}, el mismo para las
            {{ lanes.length === 1 ? 'series' : 'tres series' }}, así que los puntos caen en los
            mismos instantes.
          </p>
        </template>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { timeAgo } from '@/components/hygeia/format'
import { fmtDuration, formatTimeTick, timeTicks } from '@/components/hygeia/chartMath'
import {
  MAX_COMPARISON_METRICS, STATS_METRICS, STATS_PERIODS, STATS_SCOPES, STATS_AGGREGATIONS,
  alignComparisonSeries, comparisonPath, describeCoverage, describeLaneRange,
  isAggregationAllowed, metricOf, rankingRows, summaryRows, tagMetricRows,
} from '@/components/hygeia/statsMath'
import { useHygeiaStore } from '@/stores/hygeiaStore'
import { useHygeiaStatsStore } from '@/stores/hygeiaStatsStore'
import { useHygeiaTagsStore } from '@/stores/hygeiaTagsStore'

const store = useHygeiaStatsStore()
const assetsStore = useHygeiaStore()
const tagsStore = useHygeiaTagsStore()
const route = useRoute()
const router = useRouter()

/* ── Pestañas ── */

/**
 * Pestañas de la vista. El `id` es también el valor de `?vista=` en la URL,
 * para que una pestaña se pueda enlazar y sobreviva a recargar.
 */
const STATS_TABS = [
  { id: 'resumen', label: 'Resumen' },
  { id: 'evolucion', label: 'Evolución' },
]

/**
 * Pestaña visible, leída de la URL: la de `?vista=` si es una pestaña
 * conocida, y `'resumen'` sin parámetro o con uno inválido.
 *
 * @type {import('vue').ComputedRef<'resumen'|'evolucion'>}
 */
const activeTab = computed(() =>
  STATS_TABS.some((tab) => tab.id === route.query.vista) ? route.query.vista : 'resumen',
)

const tabButtons = ref([])

/**
 * Cambia de pestaña reemplazando la entrada del historial, no añadiendo una:
 * alternar entre pestañas no debería llenar el botón «atrás» del navegador.
 *
 * @param {'resumen'|'evolucion'} id - Pestaña a mostrar.
 */
function selectTab(id) {
  if (id === activeTab.value) return
  router.replace({ query: { ...route.query, vista: id } })
}

/**
 * Navegación por teclado del tablist: flechas izquierda/derecha para pasar a
 * la pestaña contigua (dando la vuelta en los extremos), Inicio y Fin para ir
 * a la primera y la última. Mueve también el foco, que es lo que anuncia un
 * lector de pantalla.
 *
 * @param {KeyboardEvent} event - Pulsación recibida en el tablist.
 */
async function onTabKeydown(event) {
  const current = STATS_TABS.findIndex((tab) => tab.id === activeTab.value)
  const targets = {
    ArrowRight: current + 1,
    ArrowLeft: current - 1,
    Home: 0,
    End: STATS_TABS.length - 1,
  }
  if (!(event.key in targets)) return
  event.preventDefault()
  const index = (targets[event.key] + STATS_TABS.length) % STATS_TABS.length
  selectTab(STATS_TABS[index].id)
  await nextTick()
  tabButtons.value[index]?.focus()
}

/**
 * Celda de una cifra: el número y su unidad con estilos distintos.
 *
 * Es un componente funcional en línea y no un `.vue` aparte porque no tiene
 * lógica ni estado: son dos `span`, y las cifras aparecen en las tres tablas.
 */
const Stat = (props) => [
  h('span', { class: 'cell-value' }, props.value.text),
  props.value.unit ? h('span', { class: 'cell-unit' }, props.value.unit) : null,
]

// Caja de dibujo en unidades SVG; el `viewBox` la estira al ancho real, así
// que estos números son proporciones, no píxeles.
const PLOT = { width: 600, height: 160 }
const AXIS_HEIGHT = 20

// El servidor admite hasta 50 activos en una serie multi-activo. Por encima de
// eso la gráfica de parque no se pide: mandarla volvería como un error de
// validación, y decirlo es mejor que dejar la gráfica en blanco.
const MAX_FLEET_SERIES_ASSETS = 50

const assets = computed(() => assetsStore.state.assets)
const tags = computed(() => tagsStore.state.tags)

const onlineCount = computed(() => store.state.overview?.assetsByStatus?.online ?? 0)
const openAnomalies = computed(() => {
  const bySeverity = store.state.overview?.openAnomaliesBySeverity ?? {}
  return Object.values(bySeverity).reduce((total, count) => total + count, 0)
})
const criticalAnomalies = computed(
  () => store.state.overview?.openAnomaliesBySeverity?.critical ?? 0,
)

const metricName = computed(() => metricOf(store.state.metric)?.name ?? store.state.metric)

/**
 * Opciones de agregación, con «Total» desactivado en las métricas que no se
 * pueden sumar entre activos: el servidor las rechaza con un 400, y ofrecer la
 * opción sería invitar al usuario a provocar el error.
 */
const aggregationOptions = computed(() => STATS_AGGREGATIONS.map((option) => ({
  ...option,
  disabled: !isAggregationAllowed(store.state.metric, option.value),
})))

const aggregationLabel = computed(
  () => STATS_AGGREGATIONS.find((o) => o.value === store.state.aggregation)?.label ?? '',
)

const isSelectionComplete = computed(() => {
  if (store.state.scope === 'asset') return Boolean(store.state.assetId)
  if (store.state.scope === 'tag') return Boolean(store.state.tagId)
  return true
})

/* ── Gráfica comparativa ── */

const fleetAssetIds = computed(() => assets.value.map((asset) => asset.id))

/** Si la comparación se puede pedir con la selección actual. */
const canCompare = computed(() => {
  if (!isSelectionComplete.value) return false
  return store.state.scope !== 'fleet'
    || (fleetAssetIds.value.length > 0
      && fleetAssetIds.value.length <= MAX_FLEET_SERIES_ASSETS)
})

const compareUnavailableReason = computed(() => {
  if (!isSelectionComplete.value) return 'Elige un alcance completo para ver la gráfica.'
  if (!fleetAssetIds.value.length) return 'Todavía no hay activos que comparar.'
  return `La gráfica del parque abarca hasta ${MAX_FLEET_SERIES_ASSETS} activos; `
    + `este parque tiene ${fleetAssetIds.value.length}. Compara por etiqueta o por activo.`
})

/**
 * Una métrica no seleccionada se desactiva cuando ya hay tres, y la única
 * seleccionada se desactiva para no dejar la gráfica sin ninguna línea.
 */
function isToggleDisabled(key) {
  const selected = store.state.comparisonMetrics
  if (selected.includes(key)) return selected.length === 1
  return selected.length >= MAX_COMPARISON_METRICS
}

const aligned = computed(() => alignComparisonSeries(
  store.state.comparisonMetrics
    .map((key) => store.state.series.find((series) => series.key === key))
    .filter(Boolean),
))

const lanes = computed(() => aligned.value.lanes)

/** Un `polyline` por tramo continuo de cada línea; los huecos la cortan. */
const segments = computed(() => lanes.value.flatMap((lane) =>
  comparisonPath(lane, aligned.value.instants, PLOT).map((points, index) => ({
    id: `${lane.key}-${index}`, points, color: lane.color,
  })),
))

const bucketMs = computed(() => (store.state.bucket ?? 0) * 1000)

/** Marcas del eje temporal, con el mismo formato que la gráfica del activo. */
const axisTicks = computed(() => {
  const instants = aligned.value.instants
  if (instants.length < 2) return []
  const first = instants[0]
  const last = instants[instants.length - 1]
  const span = last - first
  return timeTicks(first, last).map((at, index, all) => ({
    at,
    x: ((at - first) / span) * PLOT.width,
    label: formatTimeTick(at, span),
    anchor: index === 0 ? 'start' : index === all.length - 1 ? 'end' : 'middle',
  }))
})

const chartLabel = computed(
  () => `Comparación de ${lanes.value.map((lane) => lane.name).join(', ')} en el periodo elegido`,
)

const summaryTable = computed(() => summaryRows(store.state.summary?.metrics))
const tagTable = computed(() => tagMetricRows(store.state.tagStats?.metrics))
const rankingTable = computed(() => rankingRows(store.state.ranking?.assets, store.state.metric))

/** Tarjetas del panorama, las mismas que pinta la plantilla con datos. */
const OVERVIEW_TILE_COUNT = 4

// Filas que se suponen en un ranking que todavía no se ha cargado nunca.
const DEFAULT_RANKING_GHOST_ROWS = 5

// Filas del último ranking mostrado. Se guarda aparte porque el store descarta
// el ranking al cambiar de alcance, y al volver al parque la silueta debe
// tener el tamaño del que se vio, no uno supuesto.
const lastRankingRowCount = ref(DEFAULT_RANKING_GHOST_ROWS)
watch(
  () => rankingTable.value.length,
  (count) => { if (count) lastRankingRowCount.value = count },
  { immediate: true },
)

/**
 * Forma de la tabla fantasma mientras se calcula el resultado, calcada de la
 * tabla que va a sustituirla para que el panel no cambie de alto.
 *
 * Un activo y una etiqueta traen siempre una fila por métrica del catálogo;
 * el ranking tiene tantas filas como activos con datos, así que se toma el
 * número del último ranking mostrado.
 *
 * @type {import('vue').ComputedRef<{columns: number, rows: number, sublineColumn: number|null, template: string}>}
 *   `columns` son las columnas de la tabla de ese alcance (7 en un activo,
 *   3 en una etiqueta, 4 en el parque); `rows`, sus filas contando la de
 *   cabecera; `sublineColumn`, la columna (desde 1) cuyas celdas llevan una
 *   segunda línea —en un activo, la del máximo, que dice cuándo ocurrió— o
 *   `null` si ninguna la lleva; y `template`, el `grid-template-columns` de
 *   cada fila, con la columna del nombre más ancha que las de cifras.
 */
const ghostTable = computed(() => {
  const shape = store.state.scope === 'asset'
    ? { columns: 7, rows: STATS_METRICS.length + 1, sublineColumn: 5 }
    : store.state.scope === 'tag'
      ? { columns: 3, rows: STATS_METRICS.length + 1, sublineColumn: null }
      : {
        columns: 4,
        rows: lastRankingRowCount.value + 1,
        sublineColumn: null,
      }
  return { ...shape, template: `2fr repeat(${shape.columns - 1}, 1fr)` }
})

/**
 * Descarga en CSV exactamente lo que hay en la tabla.
 *
 * El nombre del fichero lleva el alcance, así que hace falta el rótulo del
 * activo o de la etiqueta elegidos; el parque no tiene ninguno.
 */
function exportCsv() {
  const scopeLabel = store.state.scope === 'asset'
    ? assets.value.find((asset) => asset.id === store.state.assetId)?.hostname
    : store.state.scope === 'tag'
      ? tags.value.find((tag) => tag.id === store.state.tagId)?.name
      : null
  store.downloadCsv(scopeLabel ?? null)
}

function onScopeChange(event) {
  store.selectScope(event.target.value)
}

/**
 * Si la métrica elegida deja de admitir la agregación activa, se cae a la
 * media en vez de mandar una combinación que el servidor rechaza.
 */
watch(() => store.state.metric, (metric) => {
  if (!isAggregationAllowed(metric, store.state.aggregation)) store.state.aggregation = 'avg'
})

/*
 * Cada pestaña se identifica por la selección de la que dependen sus datos.
 * La tabla depende de la métrica del ranking; la gráfica no, pero sí de qué
 * métricas se superponen y de qué activos forman el parque.
 */
const scopeSelectionKey = computed(() => [
  store.state.scope, store.state.assetId, store.state.tagId,
  store.state.metric, store.state.period, store.state.aggregation,
].join('|'))

const comparisonSelectionKey = computed(() => [
  store.state.scope, store.state.assetId, store.state.tagId,
  store.state.period, store.state.aggregation,
  store.state.comparisonMetrics.join(','), fleetAssetIds.value.join(','),
].join('|'))

// Selección con la que se pidió por última vez cada pestaña. Al volver a una
// pestaña solo se pide de nuevo si la selección cambió mientras no se veía.
let lastScopeSelection = null
let lastComparisonSelection = null

/**
 * Pide los datos de la pestaña visible si su selección no es la que ya tiene
 * cargada. La pestaña oculta no pide nada: sus datos se traen al abrirla.
 */
function refreshVisibleTab() {
  if (activeTab.value === 'resumen') {
    if (scopeSelectionKey.value === lastScopeSelection) return
    lastScopeSelection = scopeSelectionKey.value
    store.fetchScope()
    return
  }
  if (!canCompare.value || comparisonSelectionKey.value === lastComparisonSelection) return
  lastComparisonSelection = comparisonSelectionKey.value
  store.fetchComparison(fleetAssetIds.value)
}

// Cualquier cambio del selector o de pestaña vuelve a pedir sin recargar.
watch([activeTab, scopeSelectionKey, comparisonSelectionKey], refreshVisibleTab)

onMounted(() => {
  store.fetchOverview()
  if (!assets.value.length) assetsStore.fetchAssets()
  if (!tags.value.length) tagsStore.fetchTags()
  refreshVisibleTab()
})
</script>

<style scoped>
.stats-page {
  min-height: 100vh;
  background: var(--bg);
  padding-top: var(--topbar-h);
  position: relative;
}

.stats-layout {
  position: relative;
  z-index: 1;
  max-width: 1000px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 3rem;
}

.btn-export {
  margin-left: auto;
  padding: 0.45rem 0.9rem; flex-shrink: 0;
  background: var(--accent-dim); border: 1px solid var(--accent); border-radius: 6px;
  color: var(--accent-bright); font-size: var(--fs-body); font-weight: 600; cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.btn-export:hover:not(:disabled) { background: var(--accent); color: var(--on-accent); }
.btn-export:disabled { opacity: 0.55; cursor: not-allowed; }

.head-title { margin: 0 0 0.3rem; font-size: var(--fs-2xl); font-weight: 600; color: var(--text); }
.head-sub { margin: 0; max-width: 64ch; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.5; }

/* ── Panorama ── */
.overview { margin: 1.4rem 0 0.4rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; }
.tile {
  display: flex; flex-direction: column; gap: 0.15rem;
  padding: 0.7rem 0.85rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
.tile-label { font-size: var(--fs-sm); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.tile-value { font-size: var(--fs-xl); font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.tile-value--text { font-size: var(--fs-lg); }
.tile-sub { font-size: var(--fs-sm); color: var(--text-muted); }

/* ── Selector ── */
.controls {
  display: flex; align-items: flex-end; gap: 0.8rem; flex-wrap: wrap;
  margin: 1.2rem 0 1rem; padding: 0.8rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
.control { display: flex; flex-direction: column; gap: 0.25rem; min-width: 140px; }
.control-label { font-size: var(--fs-sm); color: var(--text-muted); }

.inp {
  padding: 0.4rem 0.55rem;
  background: var(--bg); border: 1px solid var(--border-med); border-radius: 6px;
  color: var(--text); font-size: var(--fs-md);
}
.inp:focus { outline: none; border-color: var(--accent); }

.periods { display: flex; gap: 0.25rem; }
.period-btn {
  padding: 0.35rem 0.7rem;
  background: transparent; border: 1px solid var(--border-med); border-radius: 999px;
  color: var(--text-muted); font-size: var(--fs-sm); cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.period-btn:hover { color: var(--text-dim); }
.period-btn--on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); font-weight: 600; }

/* ── Pestañas: mismo aspecto que las de la ficha de un activo ── */
.tabs {
  display: flex; gap: 0.2rem; margin: 0 0 0.8rem;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.25rem;
}
.tab {
  flex: 1; padding: 0.5rem 0.85rem;
  background: none; border: none; border-radius: 6px;
  color: var(--text-muted); font-size: var(--fs-lg); font-weight: 500; cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.tab:hover { color: var(--text-dim); }
.tab--on { background: var(--surface-2); color: var(--text); font-weight: 600; }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

/* ── Paneles de las pestañas ── */
.results,
.compare {
  margin: 0 0 1.6rem; padding: 0.9rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
.results-bar { display: flex; align-items: flex-end; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 0.9rem; }

/* ── Tablas ── */
.table { width: 100%; border-collapse: collapse; font-size: var(--fs-md); }
.table-caption {
  caption-side: top; text-align: left;
  padding-bottom: 0.5rem;
  font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5;
}
.table th, .table td { padding: 0.45rem 0.5rem; text-align: right; border-bottom: 1px solid var(--border); }
.table thead th { font-size: var(--fs-sm); color: var(--text-muted); font-weight: 600; white-space: nowrap; }
.table th:first-child, .table td:first-child, .row-name { text-align: left; }
.row-name { color: var(--text); font-weight: 600; }
.row--empty { color: var(--text-muted); }

.cell-value { font-variant-numeric: tabular-nums; color: var(--text); }
.row--empty .cell-value { color: var(--text-muted); }
.cell-unit { margin-left: 0.2rem; font-size: var(--fs-sm); color: var(--text-muted); }
.cell-sub { display: block; font-size: var(--fs-sm); color: var(--text-muted); }
.cell-num { font-variant-numeric: tabular-nums; color: var(--text-dim); }

/* ── Gráfica comparativa ── */
.compare-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.8rem; flex-wrap: wrap; }
.compare-title { margin: 0; font-size: var(--fs-lg); font-weight: 600; color: var(--text); }

.metric-toggles { display: flex; gap: 0.25rem; flex-wrap: wrap; }
.toggle {
  padding: 0.3rem 0.6rem;
  background: transparent; border: 1px solid var(--border-med); border-radius: 999px;
  color: var(--text-muted); font-size: var(--fs-sm); cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.toggle:hover:not(:disabled) { color: var(--text-dim); }
.toggle--on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); font-weight: 600; }
.toggle:disabled { opacity: 0.45; cursor: not-allowed; }

.chart { display: block; width: 100%; height: 190px; margin: 0.8rem 0 0.4rem; overflow: visible; }
.grid { stroke: var(--border); stroke-width: 1; vector-effect: non-scaling-stroke; }
.line { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.tick { fill: var(--text-muted); font-size: 11px; }

.legend { list-style: none; margin: 0.2rem 0 0; padding: 0; display: flex; gap: 1rem; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 0.35rem; font-size: var(--fs-sm); }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.legend-name { color: var(--text); font-weight: 600; }
.legend-range { color: var(--text-muted); font-variant-numeric: tabular-nums; }

.compare-note { margin: 0.6rem 0 0; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

/* ── Carga y llegada de datos ── */
/* En línea y centrada: así la silueta ocupa el alto de una línea del texto
   que sustituye, no solo el de la barra gris. */
.skeleton-inline { display: inline-block; vertical-align: middle; }

.table-ghost-caption { display: block; padding-bottom: 0.5rem; font-size: var(--fs-sm); line-height: 1.5; }
.table-ghost-row { display: grid; gap: 0.5rem; border-bottom: 1px solid var(--border); font-size: var(--fs-md); }
.table-ghost-cell { padding: 0.45rem 0.5rem; text-align: right; }
.table-ghost-cell:first-child { text-align: left; }
.table-ghost-row--head { font-size: var(--fs-sm); }
.table-ghost-sub { display: block; font-size: var(--fs-sm); }

/* Los datos entran con un fundido corto; las tarjetas, escalonadas. */
.reveal,
.tiles--ready .tile { animation: seq-fade-up 0.35s cubic-bezier(0.22, 1, 0.36, 1) backwards; }
.tiles--ready .tile:nth-child(2) { animation-delay: 40ms; }
.tiles--ready .tile:nth-child(3) { animation-delay: 80ms; }
.tiles--ready .tile:nth-child(4) { animation-delay: 120ms; }

@media (prefers-reduced-motion: reduce) {
  .reveal,
  .tiles--ready .tile { animation: none; }
}

.state-msg { margin: 1.2rem 0; font-size: var(--fs-md); color: var(--text-muted); }
.state-msg--error { color: var(--danger); }

@media (max-width: 640px) {
  .table { font-size: var(--fs-sm); }
  .control { min-width: 100%; }
}
</style>
