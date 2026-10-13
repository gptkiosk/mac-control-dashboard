<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, getJson, postJson } from '@/lib/api'

// Shape of GET /api/app-updates. Everything comes from this host: no network, no provider call.
interface Version { id: string; complete: boolean; version: string | null; channel: string | null; change: string | null; repository: string | null; authenticity: string | null; staged_at: number | null }
interface Last { tx: string | null; kind: string | null; outcome: string; detail: string; target: string | null; from: string | null; at: number }
interface Install { current: string | null; previous: string | null; versions: Version[]; tx: { id: string; kind: string; phase: string; target: string } | null; last: Last | null; needs_recovery: boolean }
interface UpdateStatus { kind: string; detail: string; configured: boolean; problems: string[]; manual_instructions: string[]; install?: Install; blockers?: string[] }
interface Pending { kind: 'install' | 'rollback'; version: Version }
interface Operation { kind: Pending['kind']; target: string; beforeTx: string | null; sawTx: boolean; polls: number }

const PHASES: Record<string, string> = {
  staging: 'Staging the package', prepared: 'Stopping the service and saving a data snapshot', switching: 'Switching versions',
  starting: 'Starting the service and checking its health', rolling_back: 'Health check failed; rolling back', restoring: 'Restoring the data snapshot',
}
const POLL_MS = 2000, MAX_POLLS = 150, NOT_STARTED_POLLS = 15 // about 5 minutes overall; 30 seconds before "never started"
const status = ref<UpdateStatus | null>(null), checkedAt = ref<number | null>(null)
const pending = ref<Pending | null>(null), confirmed = ref(false)
const operation = ref<Operation | null>(null), reconnecting = ref(false), busy = ref(false)
const error = ref(''), notice = ref('')
let timer: ReturnType<typeof setTimeout> | undefined

const install = computed(() => status.value?.install)
const managed = computed(() => !!status.value && status.value.kind === 'release' && status.value.configured && !!install.value)
const blockers = computed(() => status.value?.blockers ?? [])
const inProgress = computed(() => !!install.value?.tx || !!install.value?.needs_recovery || !!operation.value)
const canChange = computed(() => managed.value && !busy.value && !inProgress.value && blockers.value.length === 0)
const previous = computed(() => find(install.value?.previous))
const canRollback = computed(() => canChange.value && !!previous.value?.complete)
const others = computed(() => (install.value?.versions ?? []).filter(v => v.id !== install.value?.current))
const installable = computed(() => others.value.filter(v => !unavailable(v)))
const notOffered = computed(() => others.value.filter(v => unavailable(v)))
const summary = computed(() => {
  const s = status.value
  if (!s) return ''
  if (!managed.value && s.kind === 'release') return 'Managed updates are not set up on this host yet. Details are below.'
  if (!managed.value) return `Managed updates are off: ${s.detail}.`
  const n = installable.value.length
  return `Running ${label(install.value?.current)}. ${n} staged ${n === 1 ? 'update is' : 'updates are'} ready on this host.`
})
const progressText = computed(() => {
  const tx = install.value?.tx
  return tx ? PHASES[tx.phase] ?? 'Working' : 'Waiting for the update helper to start…'
})

function find(id: string | null | undefined) { return install.value?.versions.find(v => v.id === id) }
function label(id: string | null | undefined) { return find(id)?.version ?? id ?? 'none' }
function when(seconds: number | null | undefined) { return seconds ? new Date(seconds * 1000).toLocaleString() : 'an unknown time' }
// Only complete, stable or prerelease application packages are offered. Anything else says why and gets no button.
function unavailable(v: Version): string {
  if (!v.complete || !v.version) return 'It is only partly staged, so it cannot be installed.'
  if (v.channel === 'dev') return 'A development build. It is never offered as an update.'
  if (v.channel !== 'stable' && v.channel !== 'prerelease') return `Channel “${v.channel ?? 'unknown'}” is not an application release, so it is not installable.`
  return ''
}
function denied(e: unknown, fallback: string) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return 'Operator sign-in is required to see or change updates.'
  return e instanceof Error ? e.message : fallback
}
// A 409 carries {message, blockers}; the client flattens it into the message text, so unpack it when it is JSON.
function refusal(e: unknown, fallback: string) {
  if (e instanceof ApiError && e.status === 409) {
    try {
      const body = JSON.parse(e.message) as { message?: string; blockers?: string[] }
      return [body.message, ...(body.blockers ?? [])].filter(Boolean).join(' ')
    } catch { /* plain message */ }
  }
  return denied(e, fallback)
}

async function read(): Promise<boolean> {
  try {
    status.value = await getJson<UpdateStatus>('/api/app-updates')
    checkedAt.value = Date.now(); reconnecting.value = false; error.value = ''
    return true
  } catch (e) {
    // While an operation runs, a network error or 5xx usually means the service is restarting.
    reconnecting.value = !!operation.value && (!(e instanceof ApiError) || e.status >= 500)
    if (!reconnecting.value) error.value = denied(e, 'Updates could not be read right now.')
    return false
  }
}
async function check() {
  notice.value = ''
  await read()
}

function ask(kind: Pending['kind'], version: Version) {
  pending.value = { kind, version }; confirmed.value = false; error.value = ''; notice.value = ''
}
function cancel() { pending.value = null; confirmed.value = false }

async function submit() {
  const p = pending.value
  if (!p || !confirmed.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await postJson('/api/app-updates/apply', { version_id: p.version.id })
    operation.value = { kind: p.kind, target: p.version.id, beforeTx: install.value?.last?.tx ?? null, sawTx: false, polls: 0 }
    pending.value = null; confirmed.value = false
    notice.value = `${p.kind === 'rollback' ? 'Rollback' : 'Install'} started on the host. Progress is shown below.`
    timer = setTimeout(poll, POLL_MS)
  } catch (e) {
    await read() // refreshes blockers; read() clears errors, so set the refusal after it
    error.value = refusal(e, 'The update could not be started.')
  } finally { busy.value = false }
}

async function poll() {
  const op = operation.value
  if (!op) return
  const ok = await read()
  if (!ok && !reconnecting.value) return stop(error.value) // sign-in lapsed or refused: stop polling
  const cur = status.value?.install
  if (ok && cur) {
    if (cur.tx) op.sawTx = true
    // Done once the journal is idle and either a transaction ran (sawTx) or its outcome is new.
    const finished = !cur.tx && (op.sawTx || (cur.last?.tx ?? null) !== op.beforeTx)
    if (finished) return finish(cur.last)
  }
  op.polls++
  if (ok && !cur?.tx && !op.sawTx && op.polls >= NOT_STARTED_POLLS) {
    return stop('The update helper has not started. Nothing was switched as far as the status shows. Check helper.log on the host.')
  }
  if (op.polls >= MAX_POLLS) return stop('Still waiting after about 5 minutes. Check the host with update_recovery.py status; nothing more is started from here.')
  timer = setTimeout(poll, POLL_MS)
}
function finish(last: Last | null | undefined) {
  const op = operation.value
  operation.value = null; reconnecting.value = false
  if (!last) return stop('The update finished, but no outcome was recorded.')
  if (last.outcome === 'committed') {
    notice.value = `${op?.kind === 'rollback' ? 'Rolled back to' : 'Now running'} ${label(last.target)}. Health check: ${last.detail}`
  } else {
    error.value = `Not completed (${last.outcome}): ${last.detail}`
  }
}
function stop(message: string) {
  operation.value = null; reconnecting.value = false
  error.value = message
}

onMounted(check)
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>
<template>
  <section id="updates" class="card update-panel" aria-labelledby="updates-title">
    <h2 id="updates-title">Updates</h2>
    <p class="muted">Installs are never automatic. Checking reads only the packages already verified and staged on this host: nothing is downloaded and no provider is contacted. Install and rollback need operator sign-in and your confirmation.</p>
    <p v-if="error" class="notice-warn" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="reconnecting" class="muted" role="status">Reconnecting to the service. It is restarting, so this can take a minute. Nothing is started again from here.</p>
    <div class="actions">
      <button class="btn" :disabled="busy || !!operation" @click="check">Check for updates</button>
      <span v-if="checkedAt" class="muted small">Checked {{ when(checkedAt / 1000) }} (this host only)</span>
    </div>
    <template v-if="status">
      <p class="status" role="status">{{ summary }}</p>
      <template v-if="!managed">
        <ul v-if="status.manual_instructions.length" class="updates">
          <li v-for="step in status.manual_instructions" :key="step">{{ step }}</li>
        </ul>
        <p v-for="problem in status.problems" :key="problem" class="muted small">{{ problem }}</p>
      </template>
      <template v-else>
        <p>Installed <strong>{{ label(install?.current) }}</strong> · Previous: {{ install?.previous ? label(install.previous) : 'none kept' }}</p>
        <ul v-if="blockers.length" class="updates" aria-label="Work that must finish first">
          <li v-for="b in blockers" :key="b">{{ b }}</li>
        </ul>
        <p v-if="blockers.length" class="muted small">Drain first. Nothing is stopped or cancelled for you.</p>
        <p v-if="install?.needs_recovery" class="notice-warn" role="alert">An earlier update was interrupted. Run recovery on the host before changing versions.</p>

        <h3>Available</h3>
        <ul v-if="installable.length" class="updates">
          <li v-for="v in installable" :key="v.id" class="release">
            <strong>{{ v.version }}</strong> · {{ v.channel }} · {{ v.change ?? 'change unknown' }} · staged {{ when(v.staged_at) }}
            <div class="muted small">Verified: {{ v.authenticity ?? 'not recorded' }} · Source repository: {{ v.repository ?? 'not recorded' }}</div>
            <div class="muted small">Release notes: not included in this package.</div>
            <button class="btn primary" :disabled="!canChange" @click="ask('install', v)">Install {{ v.version }}</button>
          </li>
        </ul>
        <p v-else class="muted">No staged update is waiting on this host. A package can only be added by placing it in the update inbox on the host.</p>
        <ul v-if="notOffered.length" class="updates" aria-label="Staged but not offered">
          <li v-for="v in notOffered" :key="v.id">{{ v.version ?? v.id }}: {{ unavailable(v) }}</li>
        </ul>

        <h3>Rollback</h3>
        <p v-if="previous?.complete">Roll back to <strong>{{ previous.version }}</strong>, the version before the current one.</p>
        <p v-else class="muted">No previous version is kept, so there is nothing to roll back to.</p>
        <button v-if="previous?.complete" class="btn" :disabled="!canRollback" @click="ask('rollback', previous)">Roll back to {{ previous.version }}</button>

        <section v-if="pending" class="confirm" aria-labelledby="confirm-title">
          <h3 id="confirm-title">{{ pending.kind === 'install' ? `Install ${pending.version.version}` : `Roll back to ${pending.version.version}` }}</h3>
          <p v-if="pending.kind === 'install'">Replaces {{ label(install?.current) }}. The service stops briefly, then starts the new version. If it fails its health check, it rolls back automatically.</p>
          <p v-else>Code goes back to {{ pending.version.version }}. This button does not roll data back: anything written while the newer version ran stays in the database. Restoring an older data snapshot is a separate step on the host.</p>
          <p class="small muted">Before anything stops:</p>
          <ul class="preflight">
            <li>Managed updates on this host: yes.</li>
            <li>Update already running: {{ inProgress ? 'yes, wait for it to finish' : 'no' }}.</li>
            <li>Running or waiting work: {{ blockers.length ? blockers.join('; ') : 'none found' }}.</li>
            <li>Database schema: the server checks it compatible before stopping anything.</li>
            <li>Data snapshot: taken automatically before the switch.</li>
          </ul>
          <label class="check"><input v-model="confirmed" type="checkbox" />I have read this and want to continue.</label>
          <div class="actions">
            <button class="btn primary" :disabled="!confirmed || busy || !canChange" @click="submit">{{ pending.kind === 'install' ? `Install ${pending.version.version}` : `Roll back to ${pending.version.version}` }}</button>
            <button class="btn" :disabled="busy" @click="cancel">Cancel</button>
          </div>
        </section>

        <p v-if="operation" class="status" role="status">{{ progressText }}</p>
      </template>
    </template>
  </section>
</template>
<style scoped>
.update-panel { margin: var(--gap-lg) 0; display: grid; gap: var(--gap-sm); }
h2, h3 { margin: 0; }
.status { font-weight: 600; margin: 0; }
.small { font-size: var(--font-size-xs); margin: 0; }
.actions { display: flex; gap: var(--gap); flex-wrap: wrap; align-items: center; }
.updates { display: grid; gap: var(--gap-sm); padding-left: var(--gap); }
.release { display: grid; gap: var(--gap-xs); justify-items: start; }
.confirm { display: grid; gap: var(--gap-sm); border: 1px solid var(--surface-border); border-radius: var(--radius); padding: var(--gap); }
.preflight { margin: 0; padding-left: var(--gap); }
.check { display: flex; align-items: flex-start; gap: var(--gap-sm); }
.check input { flex: none; margin-top: var(--gap-xs); accent-color: var(--accent); }
</style>
