<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// One-click update of a source checkout (the "driver"). Nothing here runs by itself: checking reads the public
// release list and one signed manifest, and starting needs the operator to confirm this exact tag and commit.
const REPOSITORY = 'gptkiosk/mac-control-dashboard'
const POLL_MS = 2000, MAX_POLLS = 600 // twenty minutes; polling only reads, it never starts or repeats anything

interface Inspection {
  eligible: boolean; problems: string[]; checkout?: string; version?: string; commit?: string; short?: string
  tag?: string | null; branch?: string | null; remote?: string
}
interface Candidate { tag: string; version: string; notes: string; html_url: string | null; published_at: string | null; change: string; repository: string }
interface Check { inspection: Inspection; available: boolean; candidate: Candidate | null; verified: { commit: string; signer: string; version: string } | null; blockers: string[] }
interface Step { name: string; state: string; detail: string }
interface Operation {
  id: string; state: 'starting' | 'running' | 'succeeded' | 'failed' | 'rolled_back'; tag: string; commit: string; version: string
  from: { version: string; commit: string }; steps: Step[]; message: string
}
interface OperationStatus { operation: Operation | null; active: boolean; log: string[] }

const props = defineProps<{ inspection: Inspection }>()

const STEP_TEXT: Record<string, string> = {
  preflight: 'Safety checks', verify: 'Verify the signed release', fetch: 'Fetch the release from GitHub',
  upgrade: 'Back up, switch, rebuild, restart and check health', finish: 'Finish',
}
const found = ref<Check | null>(null), checkedAt = ref<number | null>(null)
const asking = ref(false), confirmed = ref(false), busy = ref(false)
const op = ref<OperationStatus | null>(null), reconnecting = ref(false)
const error = ref(''), notice = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let alive = true, polls = 0

const running = computed(() => !!op.value?.operation && ['starting', 'running'].includes(op.value.operation.state))
const finished = computed(() => (op.value?.operation && !running.value ? op.value.operation : null))
const candidate = computed(() => found.value?.candidate ?? null)
const verified = computed(() => found.value?.verified ?? null)
const blockers = computed(() => found.value?.blockers ?? [])
const releaseLink = computed(() => {
  const url = candidate.value?.html_url
  return url && url.startsWith(`https://github.com/${REPOSITORY}/`) ? url : null
})
const canStart = computed(() => !!candidate.value && !!verified.value && candidate.value.repository === REPOSITORY && blockers.value.length === 0 && !busy.value && !running.value)

function message(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required to update.'
  if (e instanceof ApiError && (e.status === 409 || e.status === 502)) {
    try {
      const body = JSON.parse(e.message) as { message?: string; blockers?: string[]; problems?: string[] }
      return [body.message, ...(body.blockers ?? []), ...(body.problems ?? [])].filter(Boolean).join(' ')
    } catch { /* plain message */ }
  }
  return e instanceof Error ? e.message : fallback
}

async function readOperation(): Promise<boolean> {
  try {
    op.value = await getJson<OperationStatus>('/api/app-updates/source/operation')
    reconnecting.value = false
    return true
  } catch (e) {
    // The service restarts in the middle of an update. A network error or 5xx is expected for a minute.
    reconnecting.value = running.value && (!(e instanceof ApiError) || e.status >= 500)
    if (!reconnecting.value) error.value = message(e, 'The update status could not be read.')
    return false
  }
}

// Read-only: the release list and the signed manifest of the newest stable release. Downloads no package.
async function check() {
  if (busy.value || running.value) return
  busy.value = true; error.value = ''; notice.value = ''; asking.value = false; confirmed.value = false
  try {
    found.value = await getJson<Check>('/api/app-updates/source/check')
    checkedAt.value = Date.now()
    if (!found.value.available) notice.value = 'This checkout is on the newest stable release.'
  } catch (e) {
    found.value = null
    error.value = message(e, 'Could not check for updates.')
  } finally { busy.value = false }
}

function ask() { asking.value = true; confirmed.value = false; error.value = ''; notice.value = '' }
function cancel() { asking.value = false; confirmed.value = false }

// The separate, explicit confirmation. The exact tag and the commit the signature names are sent back,
// so the server refuses if the newest release changed after the check.
async function start() {
  const c = candidate.value, v = verified.value
  if (!c || !v || !confirmed.value || !canStart.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await postJson('/api/app-updates/source/start', { tag: c.tag, commit: v.commit, confirm: true })
    asking.value = false; confirmed.value = false; polls = 0
    notice.value = `Update to ${c.tag} started on the host. The service restarts partway through; this page reconnects by itself.`
    await readOperation()
    schedule()
  } catch (e) {
    error.value = message(e, 'The update could not be started.')
    await check().catch(() => undefined)
  } finally { busy.value = false }
}

function schedule() { timer = setTimeout(poll, POLL_MS) }
async function poll() {
  if (!alive) return
  const ok = await readOperation()
  if (!ok && !reconnecting.value) return
  if (ok && !running.value) {
    const done = op.value?.operation
    if (done?.state === 'succeeded') notice.value = `${done.message} Reload this page to load the new interface.`
    return
  }
  polls++
  if (polls >= MAX_POLLS) { error.value = 'Still waiting after about 20 minutes. Check the host: scripts/driver-status.sh. Nothing more is started from here.'; return }
  schedule()
}

onMounted(async () => {
  // A page opened during or after an update shows it: the helper keeps its state in a file on the host.
  await readOperation()
  if (running.value) schedule()
})
onBeforeUnmount(() => { alive = false; if (timer) clearTimeout(timer) })
</script>
<template>
  <div class="source-update" aria-labelledby="source-update-title">
    <h3 id="source-update-title">Update this checkout</h3>
    <p class="muted">This copy runs from a source checkout. One click updates it to the newest official stable release, after you confirm the exact version. Nothing runs on a timer.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="reconnecting" class="muted" role="status">Reconnecting to the service. It is restarting, so this can take a minute. Nothing is started again from here.</p>

    <template v-if="!inspection.eligible">
      <p class="status" role="status">One-click update is not available here.</p>
      <ul class="updates"><li v-for="p in inspection.problems" :key="p">{{ p }}</li></ul>
    </template>
    <template v-else>
      <p class="muted small">Running {{ inspection.version }} (commit {{ inspection.short }}{{ inspection.tag ? `, ${inspection.tag}` : '' }}) from {{ inspection.checkout }}. Remote: {{ inspection.remote }}</p>
      <div class="actions">
        <button class="btn" :disabled="busy || running" @click="check">Check for updates</button>
        <span v-if="checkedAt" class="muted small">Checked GitHub {{ new Date(checkedAt).toLocaleString() }}</span>
      </div>

      <article v-if="candidate && verified" class="release">
        <h4>Update available: {{ candidate.version }}</h4>
        <p class="muted small">{{ candidate.tag }} · stable · published {{ candidate.published_at ?? 'unknown' }}</p>
        <dl class="facts">
          <dt>From</dt><dd>{{ inspection.version }} ({{ inspection.short }})</dd>
          <dt>To</dt><dd>{{ candidate.version }} (<span class="mono">{{ verified.commit }}</span>)</dd>
          <dt>Source repository</dt><dd>{{ candidate.repository }}</dd>
          <dt>Signature</dt><dd>valid, {{ verified.signer }}; the tag must point at the signed commit</dd>
        </dl>
        <h4>Release notes (plain text)</h4>
        <pre class="notes">{{ candidate.notes || 'This release has no notes.' }}</pre>
        <a v-if="releaseLink" :href="releaseLink" target="_blank" rel="noopener noreferrer">View this release on GitHub</a>
        <ul v-if="blockers.length" class="updates" aria-label="Work that must finish first">
          <li v-for="b in blockers" :key="b">{{ b }}</li>
        </ul>
        <p v-if="blockers.length" class="muted small">Drain first. Nothing is stopped or cancelled for you. Check again when it is done.</p>
        <button v-else class="btn primary" :disabled="!canStart" @click="ask">Update to {{ candidate.version }}</button>
      </article>

      <section v-if="asking && candidate && verified" class="confirm" aria-labelledby="source-confirm-title">
        <h4 id="source-confirm-title">Update to {{ candidate.version }}</h4>
        <p>The service restarts for a short time. A data backup is taken first, and if the new version does not report exactly this release as healthy, the previous version is put back automatically. A log of every step is kept on the host.</p>
        <ul class="preflight">
          <li>Exact release: <strong>{{ candidate.tag }}</strong>, commit <span class="mono">{{ verified.commit.slice(0, 12) }}</span>.</li>
          <li>The official repository and a clean checkout are re-checked, and so is idleness, right before anything changes.</li>
          <li>Nothing is running, queued, waiting for approval or dispatching: the server checks again before it stops anything.</li>
        </ul>
        <label class="check"><input v-model="confirmed" type="checkbox" />I have read this and want to update to {{ candidate.tag }}.</label>
        <div class="actions">
          <button class="btn primary" :disabled="!confirmed || !canStart" @click="start">Update to {{ candidate.version }}</button>
          <button class="btn" :disabled="busy" @click="cancel">Cancel</button>
        </div>
      </section>
    </template>

    <section v-if="op?.operation" class="operation" aria-label="Update progress">
      <h4>{{ running ? `Updating to ${op.operation.tag}` : `Update to ${op.operation.tag}: ${op.operation.state.replace('_', ' ')}` }}</h4>
      <p :class="op.operation.state === 'succeeded' ? 'status' : (running ? 'muted' : 'notice-warn')" :role="running ? 'status' : 'alert'">{{ op.operation.message }}</p>
      <ol class="steps">
        <li v-for="s in op.operation.steps" :key="s.name" :data-state="s.state">{{ STEP_TEXT[s.name] ?? s.name }}: {{ s.state }}<span v-if="s.detail" class="muted small"> · {{ s.detail }}</span></li>
      </ol>
      <details v-if="op.log.length">
        <summary>Log</summary>
        <pre class="notes">{{ op.log.join('\n') }}</pre>
      </details>
    </section>
  </div>
</template>
<style scoped>
.source-update { display: grid; gap: var(--gap-sm); border-top: 1px solid var(--surface-border); padding-top: var(--gap); }
h3, h4 { margin: 0; }
.status { font-weight: 600; margin: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.updates { display: grid; gap: var(--gap-sm); padding-left: var(--gap); }
.release, .confirm, .operation { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); justify-items: start; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--gap-xs) var(--gap); margin: 0; font-size: var(--font-size-sm); }
.facts dt { color: var(--text-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--font-size-xs); }
.notes { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 16rem; overflow: auto; margin: 0; width: 100%; box-sizing: border-box; padding: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); }
.steps { margin: 0; padding-left: var(--gap); }
.steps li[data-state='failed'] { font-weight: 600; }
.preflight { margin: 0; padding-left: var(--gap); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
</style>
