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
        <p v-if="store.state.overviewLoading" class="state-msg">Cargando el panorama…</p>
        <p v-else-if="store.state.overviewError" class="state-msg state-msg--error">
          {{ store.state.overviewError }}
        </p>
        <div v-else-if="store.state.overview" class="tiles">
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

      <!-- Selector: los tres ejes del roadmap (alcance, métrica, periodo) más
           la agregación, que solo significa algo en los alcances que combinan
           varios activos. -->
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

        <div v-if="store.state.scope === 'fleet'" class="control">
          <label class="control-label" for="metric-select">Métrica</label>
          <select id="metric-select" v-model="store.state.metric" class="inp">
            <option v-for="metric in STATS_METRICS" :key="metric.key" :value="metric.key">
              {{ metric.name }}
            </option>
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

      <!-- Gráfica comparativa: varias métricas superpuestas sobre el mismo eje
           temporal. Cada una lleva su propia escala vertical, porque son
           unidades distintas y compartir eje aplastaría el porcentaje contra el
           suelo; lo que se compara es la forma de las curvas. -->
      <section class="compare" aria-label="Gráfica comparativa">
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

      <section class="results" aria-label="Resultado">
        <p v-if="store.state.scopeLoading" class="state-msg">Calculando…</p>
        <p v-else-if="store.state.scopeError" class="state-msg state-msg--error">
          {{ store.state.scopeError }}
        </p>
        <p v-else-if="!isSelectionComplete" class="state-msg">
          {{ store.state.scope === 'asset' ? 'Elige un activo para ver su resumen.'
            : 'Elige una etiqueta para ver sus métricas agregadas.' }}
        </p>

        <!-- Un activo: el resumen completo, una fila por métrica. -->
        <template v-else-if="store.state.scope === 'asset' && store.state.summary">
          <table class="table">
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
          <table class="table">
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
          <table class="table">
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
    </main>
  </div>
</template>

<script setup>
import { computed, h, onMounted, watch } from 'vue'
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

// Cualquier cambio del selector vuelve a pedir, sin recargar la página: es el
// criterio de cierre de la necesidad.
watch(
  () => [
    store.state.scope, store.state.assetId, store.state.tagId,
    store.state.metric, store.state.period, store.state.aggregation,
  ],
  () => store.fetchScope(),
)

// La gráfica depende del alcance, del periodo y de qué métricas se superponen,
// pero no de la métrica del ranking: son dos preguntas distintas sobre la
// misma pantalla.
watch(
  () => [
    store.state.scope, store.state.assetId, store.state.tagId,
    store.state.period, store.state.aggregation,
    store.state.comparisonMetrics.join(','), fleetAssetIds.value.join(','),
  ],
  () => { if (canCompare.value) store.fetchComparison(fleetAssetIds.value) },
)

onMounted(() => {
  store.fetchOverview()
  if (!assets.value.length) assetsStore.fetchAssets()
  if (!tags.value.length) tagsStore.fetchTags()
  store.fetchScope()
  if (canCompare.value) store.fetchComparison(fleetAssetIds.value)
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
.compare {
  margin: 0 0 1.6rem; padding: 0.9rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
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

.state-msg { margin: 1.2rem 0; font-size: var(--fs-md); color: var(--text-muted); }
.state-msg--error { color: var(--danger); }

@media (max-width: 640px) {
  .table { font-size: var(--fs-sm); }
  .control { min-width: 100%; }
}
</style>
