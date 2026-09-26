// Registro único de tipos de escaneo de Themis.
//
// Antes cada componente (panel de programados, historial, su gráfico, la
// vista previa) mantenía su propia lista de tipos escrita a mano, y añadir
// Lybra a los escaneos programados dejó claro el problema: siempre se
// quedaba alguna sin actualizar. HistoryPanel, HistoryChart, ScheduledScansPanel
// y ScanPreviewModal leen de aquí y solo de aquí. ScanTabs, ScanForm, ScanTable,
// StatsRow, ThemisView, ThemisHubView y ConfigView todavía tienen su propia
// lista escrita a mano — retirar un tipo (o añadir uno) exige tocarlos también.
//
// Los textos visibles son getters: se piden al diccionario (`scanTypes.<tipo>`)
// cada vez que se leen, así que siguen al idioma activo sin que quien los usa
// tenga que saberlo.
import { i18n } from '@/i18n'

const text = (key, params) => i18n.global.t(`scanTypes.${key}`, params)

export const SCAN_TYPES = {
  nmap: {
    label: 'Nmap',
    get fullLabel() { return text('nmap.full') },
    get previewLabel() { return text('preview', { name: 'Nmap' }) },
    chartColor: 'var(--info)',
    scheduleFields: [
      { key: 'target_host', get label() { return text('fields.host') }, size: 'lg', placeholder: '192.168.1.0/24' },
      { key: 'target_ports', get label() { return text('fields.ports') }, size: 'md', get placeholder() { return text('fields.portsPlaceholder') } },
    ],
    defaultArgs: { target_host: '', target_ports: '1-1000' },
    formatArgs: (args) => {
      const parts = []
      if (args?.target_host) parts.push(args.target_host)
      if (args?.target_ports) parts.push(text('portsSummary', { ports: args.target_ports }))
      return parts.length ? parts.join(' · ') : '—'
    },
  },
  nikto: {
    label: 'Nikto',
    get fullLabel() { return text('nikto.full') },
    get previewLabel() { return text('preview', { name: 'Nikto' }) },
    chartColor: 'var(--warn)',
    scheduleFields: [
      { key: 'target_domain', get label() { return text('fields.domain') }, size: 'lg', placeholder: 'example.com' },
    ],
    defaultArgs: { target_domain: '' },
    formatArgs: (args) => args?.target_domain || '—',
  },
  lybra: {
    label: 'Lybra',
    get fullLabel() { return text('lybra.full') },
    get previewLabel() { return text('preview', { name: 'Lybra' }) },
    chartColor: 'var(--accent)',
    scheduleFields: [
      { key: 'target', get label() { return text('fields.singleIp') }, size: 'lg', placeholder: '192.168.1.1' },
    ],
    defaultArgs: { target: '' },
    formatArgs: (args) => args?.target || '—',
  },
  nuclei: {
    label: 'Nuclei',
    get fullLabel() { return text('nuclei.full') },
    get previewLabel() { return text('preview', { name: 'Nuclei' }) },
    chartColor: 'var(--info)',
    scheduleFields: [
      { key: 'target', get label() { return text('fields.url') }, size: 'lg', placeholder: 'https://example.com' },
    ],
    defaultArgs: { target: '' },
    formatArgs: (args) => args?.target || '—',
  },
}

export const SCAN_TYPE_ORDER = Object.keys(SCAN_TYPES)

export function scanTypeLabel(type) {
  return SCAN_TYPES[type]?.label ?? type
}
