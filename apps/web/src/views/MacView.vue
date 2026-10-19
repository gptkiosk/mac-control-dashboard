<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import TimeSeriesChart, { type ChartLine } from '@/components/TimeSeriesChart.vue'
import ChipTag from '@/components/ChipTag.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import type { IconName } from '@/icons/icons'
import { navIcon } from '@/router/routes'
import type {
  SeriesPayload,
  SeriesRange,
  TailscalePayload,
  TopProcessesPayload,
  UpdatesPayload,
} from '@/lib/api'
import {
  DASH,
  formatBytes,
  formatGB,
  formatKBps,
  formatPct,
  formatTemp,
  formatWatts,
} from '@/lib/format'

const RANGES: SeriesRange[] = ['1h', '24h', '7d', '30d', '1y']
const range = ref<SeriesRange>('1h')

const FIELDS = [
  'cpu_pct', 'ecpu_pct', 'pcpu_pct', 'gpu_pct', 'mem_used', 'swap_used',
  'cpu_temp', 'gpu_temp', 'sys_power', 'cpu_power', 'gpu_power', 'net_rx_bps', 'net_tx_bps',
]

const series = usePolledJson<SeriesPayload>(
  () => `/api/metrics/series?range=${range.value}&fields=${FIELDS.join(',')}`,
  () => (range.value === '1h' ? 30_000 : 300_000),
)
const apps = usePolledJson<TopProcessesPayload>('/api/processes/top?limit=15', 10_000)
const tailscale = usePolledJson<TailscalePayload>('/api/tailscale', 30_000)
const updates = usePolledJson<UpdatesPayload>('/api/updates', 300_000)

const payload = computed(() => series.data.value?.series ?? null)

const charts: { title: string; icon: IconName; lines: ChartLine[]; format: (v: number | null | undefined) => string; zeroBased: boolean }[] = [
  {
    title: 'CPU %',
    icon: 'cpu',
    lines: [
      { field: 'cpu_pct', label: 'CPU' },
      { field: 'ecpu_pct', label: 'E-cores' },
      { field: 'pcpu_pct', label: 'P-cores' },
    ],
    format: (v) => formatPct(v, 0),
    zeroBased: true,
  },
  {
    title: 'GPU %',
    icon: 'gpu',
    lines: [{ field: 'gpu_pct', label: 'GPU' }],
    format: (v) => formatPct(v, 0),
    zeroBased: true,
  },
  {
    title: 'Memory',
    icon: 'memory',
    lines: [
      { field: 'mem_used', label: 'Memory used' },
      { field: 'swap_used', label: 'Swap used' },
    ],
    format: formatGB,
    zeroBased: true,
  },
  {
    title: 'Temperature',
    icon: 'temperature',
    lines: [
      { field: 'cpu_temp', label: 'CPU' },
      { field: 'gpu_temp', label: 'GPU' },
    ],
    format: formatTemp,
    zeroBased: false,
  },
  {
    title: 'Power',
    icon: 'power',
    lines: [
      { field: 'sys_power', label: 'System' },
      { field: 'cpu_power', label: 'CPU' },
      { field: 'gpu_power', label: 'GPU' },
    ],
    format: formatWatts,
    zeroBased: true,
  },
  {
    title: 'Network',
    icon: 'network',
    lines: [
      { field: 'net_rx_bps', label: 'Down' },
      { field: 'net_tx_bps', label: 'Up' },
    ],
    format: formatKBps,
    zeroBased: true,
  },
]


const ts = computed(() => (tailscale.data.value && 'error' in tailscale.data.value ? null : tailscale.data.value))
const tsError = computed(() => {
  const t = tailscale.data.value
  return t && 'error' in t ? t.error : null
})
const upd = computed(() => {
  const u = updates.data.value
  return u && 'updates' in u ? u.updates : null
})
const updError = computed(() => {
  const u = updates.data.value
  return u && 'error' in u ? u.error : null
})

function connection(p: { online: boolean; direct_addr: string | null; relay: string | null }): string {
  if (!p.online) return DASH
  if (p.direct_addr) return 'direct'
  if (p.relay) return `relay (${p.relay})`
  return DASH
}

function lastSeen(iso: string | null): string {
  if (!iso) return DASH
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? DASH : d.toLocaleString()
}
</script>

<template>
  <section class="page" aria-labelledby="mac-title">
    <PageHead id="mac-title" title="Mac" :icon="navIcon('mac')" sub="CPU, GPU, memory, network and the apps using them." help="hardware">
      <div class="ranges" role="group" aria-label="Time range">
        <button
          v-for="r in RANGES"
          :key="r"
          type="button"
          class="range"
          :aria-pressed="range === r ? 'true' : 'false'"
          @click="range = r"
        >
          {{ r }}
        </button>
      </div>
    </PageHead>

    <p v-if="series.error.value" class="error" role="alert">Could not load history: {{ series.error.value }}</p>
    <p v-else-if="series.pending.value" class="muted" role="status">Collecting first samples…</p>

    <div class="charts">
      <TimeSeriesChart
        v-for="c in charts"
        :key="c.title"
        :title="c.title"
        :icon="c.icon"
        :series="payload"
        :lines="c.lines"
        :format="c.format"
        :zero-based="c.zeroBased"
      />
    </div>

    <section class="card" aria-labelledby="apps-title">
      <h2 id="apps-title" class="section-title has-icon">
        <AppIcon name="apps" />
        Top apps
      </h2>
      <p v-if="apps.error.value" class="error" role="alert">Could not load apps: {{ apps.error.value }}</p>
      <div v-if="apps.data.value" class="table-scroll">
        <table class="data-table">
          <caption class="sr-only">Apps using the most memory</caption>
          <thead>
            <tr>
              <th scope="col">App</th>
              <th scope="col" class="num">Memory</th>
              <th scope="col" class="num">CPU %</th>
              <th scope="col" class="num">Processes</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in apps.data.value.apps" :key="a.app">
              <th scope="row" class="plain">{{ a.app }}</th>
              <td class="num">{{ formatBytes(a.rss) }}</td>
              <td class="num">{{ formatPct(a.cpu_pct) }}</td>
              <td class="num">{{ a.count ?? DASH }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card" aria-labelledby="ts-title">
      <h2 id="ts-title" class="section-title has-icon">
        <AppIcon name="peers" />
        Tailscale
      </h2>
      <p v-if="tsError" class="muted">Tailscale unavailable: {{ tsError }}</p>
      <p v-else-if="tailscale.error.value" class="error" role="alert">
        Could not load Tailscale: {{ tailscale.error.value }}
      </p>
      <template v-if="ts">
        <p>
          <ChipTag :tone="ts.backend_state === 'Running' ? 'ok' : 'warn'">{{ ts.backend_state }}</ChipTag>
          <span class="muted small gap-left">{{ ts.tailnet }}</span>
        </p>
        <p>
          <strong>{{ ts.self.hostname }}</strong>
          <span class="muted small gap-left">{{ ts.self.ips.join(' · ') }}</span>
        </p>
        <div v-if="ts.peers.length" class="table-scroll">
          <table class="data-table">
            <caption class="sr-only">Tailscale peers</caption>
            <thead>
              <tr>
                <th scope="col">Peer</th>
                <th scope="col">Status</th>
                <th scope="col">Connection</th>
                <th scope="col">Last seen</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in ts.peers" :key="p.dns_name || p.hostname">
                <th scope="row" class="plain">
                  {{ p.hostname }}
                  <span v-if="p.os" class="muted small"> · {{ p.os }}</span>
                </th>
                <td><ChipTag :tone="p.online ? 'ok' : 'muted'">{{ p.online ? 'online' : 'offline' }}</ChipTag></td>
                <td>{{ connection(p) }}</td>
                <td>{{ p.online ? DASH : lastSeen(p.last_seen) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">No peers on this tailnet.</p>
      </template>
    </section>

    <section class="card" aria-labelledby="upd-title">
      <h2 id="upd-title" class="section-title has-icon">
        <AppIcon name="updates" />
        Pending updates
      </h2>
      <p class="muted small">Updates are read-only here. Install them from System Settings.</p>
      <p v-if="updError" class="muted">Could not check for updates: {{ updError }}</p>
      <p v-else-if="updates.pending.value" class="muted" role="status">Checking for updates…</p>
      <p v-else-if="updates.error.value" class="error" role="alert">{{ updates.error.value }}</p>
      <p v-else-if="upd && upd.length === 0" class="muted">Everything is up to date.</p>
      <ul v-else-if="upd" class="updates">
        <li v-for="u in upd" :key="u.label">
          <span class="title">{{ u.title }}</span>
          <span v-if="u.version" class="muted small">{{ u.version }}</span>
          <ChipTag v-if="u.requires_restart" tone="warn">Restart needed</ChipTag>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
}

.page > p {
  margin: 0;
}

.error {
  color: var(--danger);
}

.ranges {
  display: inline-flex;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  overflow: hidden;
}

.range {
  padding: var(--gap-sm) var(--gap);
  background: var(--panel);
  color: var(--text-muted);
  border: 0;
  border-right: 1px solid var(--panel-border);
  font: inherit;
  cursor: pointer;
}

.range:last-child {
  border-right: 0;
}

.range:hover {
  background: var(--panel-raised);
  color: var(--text);
}

.range[aria-pressed='true'] {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: var(--font-weight-strong);
}

.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, var(--card-min-width)), 1fr));
  gap: var(--gap);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.plain {
  color: var(--text);
  font-weight: var(--font-weight);
  white-space: normal;
}

.gap-left {
  margin-left: var(--gap-sm);
}

.updates {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.updates li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.title {
  font-weight: var(--font-weight-strong);
}
</style>
