<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { getJson, postJson, type Card } from '@/lib/api'
import { agentLabel } from '@/lib/cards'
import type { Project, ProjectNode } from '@/lib/projects'

const props = defineProps<{ card: Card }>()
const emit = defineEmits<{ changed: [] }>()
const project = ref<Project | null>(null)
const busy = ref(false), error = ref(''), notice = ref('')
const visible = computed(() => props.card.project?.role === 'story' && props.card.assignee_type !== 'human' && props.card.column === 'failed')
const task = computed(() => project.value?.tasks.find(t => t.card_id === props.card.id && t.role === 'story'))
const ready = computed(() => visible.value && !notice.value && project.value?.state === 'active' && task.value?.column === 'failed' && task.value.run_id === props.card.last_run?.id)
const alternatives = computed(() => (task.value?.retry_routes ?? []).filter(r => r.agent !== props.card.agent || r.model !== (props.card.model ?? '')))
const limited = computed(() => /session limit|usage limit|quota|rate.?limit|limit reached/i.test(props.card.last_run?.error ?? ''))
const freeRoutes = computed(() => task.value?.free_retry_routes ?? [])
const showFree = ref(false), freeModel = ref(''), freeTarget = ref('')
const freeModels = computed(() => [...new Set(freeRoutes.value.map(r => r.model))])
const freeTargets = computed(() => [...new Set(freeRoutes.value.map(r => r.agent_target))])
let generation = 0
watch(() => [props.card.id, props.card.project?.id, props.card.column, props.card.last_run?.id], async () => {
  const mine = ++generation
  project.value = null; error.value = ''; notice.value = ''; showFree.value = false
  if (!visible.value) return
  try {
    const p = await getJson<Project>(`/api/projects/${props.card.project!.id}`)
    if (mine === generation) project.value = p
  } catch (e) { if (mine === generation) error.value = e instanceof Error ? e.message : String(e) }
}, { immediate: true })

function chooseFree() {
  freeModel.value = freeModels.value[0] ?? ''
  const preferred = props.card.agent_target || (props.card.mode === 'edit' ? 'mm-developer' : 'mm-main')
  freeTarget.value = freeTargets.value.includes(preferred) ? preferred : freeTargets.value[0] ?? ''
  showFree.value = true
}

async function goFree() {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const p = await getJson<Project>(base)
    const current = p.tasks.find(t => t.card_id === props.card.id && t.role === 'story')
    if (p.state !== 'active' || current?.column !== 'failed' || current.run_id !== props.card.last_run?.id)
      throw new Error('The task changed. Refresh before rerunning it.')
    if (!current.free_retry_routes?.some(r => r.model === freeModel.value && r.agent_target === freeTarget.value))
      throw new Error('This free route is no longer configured. Refresh before selecting a model.')
    await postJson(`${base}/stories/${props.card.id}/go-free`, { revision: p.revision, run_id: current.run_id, model: freeModel.value, agent_target: freeTarget.value })
    showFree.value = false
    notice.value = 'Free-model retry queued for this task. Google BYOK and paid-model fallback are excluded.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function retry(route?: ProjectNode['routes'][number]) {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const base = `/api/projects/${props.card.project!.id}`
    const p = await getJson<Project>(base)
    const current = p.tasks.find(t => t.card_id === props.card.id && t.role === 'story')
    if (p.state !== 'active' || current?.column !== 'failed' || current.run_id !== props.card.last_run?.id)
      throw new Error('The task changed. Refresh before rerunning it.')
    if (route && !current.retry_routes?.some(r => r.agent === route.agent && r.model === route.model))
      throw new Error('This route is no longer approved. Review the project.')
    await postJson(`${base}/stories/${props.card.id}/retry`, { revision: p.revision, ...(route ? { route } : {}) })
    notice.value = 'Rerun queued. It will start when its dependencies and execution slot are ready.'
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="visible" class="task-retry" aria-label="Rerun failed task">
    <div class="retry-actions">
      <button type="button" class="btn primary" :disabled="busy || !ready" @click="retry()"><AppIcon name="run" size="sm" />{{ busy ? 'Queueing…' : 'Rerun task' }}</button>
      <button v-for="route in alternatives" :key="`${route.agent}:${route.model}`" type="button" class="btn" :disabled="busy || !ready" @click="retry(route)">Rerun with {{ agentLabel(route.agent) }} · {{ route.model || 'Agent default' }}</button>
      <button v-if="limited && (card.agent === 'claude' || card.agent === 'codex')" type="button" class="btn" :disabled="busy || !ready || !freeRoutes.length" @click="chooseFree">Go Free!</button>
    </div>
    <div v-if="showFree" class="free-choice" aria-label="Choose free retry">
      <p><strong>Continue this task with OpenClaw</strong></p>
      <label>Free model<select v-model="freeModel" :disabled="busy"><option v-for="model in freeModels" :key="model" :value="model">{{ model }}</option></select></label>
      <label>OpenClaw agent<select v-model="freeTarget" :disabled="busy"><option v-for="target in freeTargets" :key="target" :value="target">{{ target }}</option></select></label>
      <p class="muted small">Approves this model for this task only. No paid-model or Google BYOK fallback. If the free model is unavailable, the task stops for review.</p>
      <div class="retry-actions"><button type="button" class="btn primary" :disabled="busy || !ready || !freeModel || !freeTarget" @click="goFree">{{ busy ? 'Queueing…' : 'Start free retry' }}</button><button type="button" class="btn" :disabled="busy" @click="showFree = false">Cancel</button></div>
    </div>
    <p class="muted small">Keeps this task’s scope, workspace and dependency order. Earlier runs remain in history.</p>
    <p v-if="limited" class="muted small">The same agent may remain limited until its quota resets. Use an approved alternative above when available.</p>
    <p v-if="limited && (card.agent === 'claude' || card.agent === 'codex') && project && !freeRoutes.length" class="muted small">Go Free needs an installed OpenClaw agent with a configured OpenRouter :free model.</p>
    <p v-if="project?.state === 'paused'" class="muted small">Resume project dispatch before rerunning this task.</p>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.task-retry { display:grid; gap:var(--gap-sm); padding:var(--gap); border:1px solid var(--panel-border); border-radius:var(--radius); background:var(--panel-raised); }
.task-retry p { margin:0; overflow-wrap:anywhere; }
.retry-actions { display:flex; flex-wrap:wrap; gap:var(--gap-sm); }
.retry-actions .btn { display:inline-flex; gap:var(--gap-xs); align-items:center; white-space:normal; overflow-wrap:anywhere; max-width:100%; }
.free-choice { display:grid; gap:var(--gap-sm); border-top:1px solid var(--panel-border); padding-top:var(--gap); }
.free-choice label { display:grid; gap:var(--gap-xs); min-width:0; }
.free-choice select { width:100%; min-width:0; }
</style>
