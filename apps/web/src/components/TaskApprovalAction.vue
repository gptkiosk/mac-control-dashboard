<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ModalShell from '@/components/ModalShell.vue'
import { getJson, postJson, type Card } from '@/lib/api'
import { awaitsApproval } from '@/lib/cards'
import type { Project } from '@/lib/projects'

const props = defineProps<{ card: Card }>()
const emit = defineEmits<{ changed: [] }>()
const busy = ref(false), error = ref(''), decisionOpen = ref(false), decision = ref('')
const kind = computed(() => {
  const c = props.card
  if (c.project?.role === 'story') {
    if (c.blocked_by.length) return null
    if (c.assignee_type === 'human' && ['backlog','review'].includes(c.column)) return 'decision'
    if (c.column !== 'review') return null
    if (c.last_run?.stage === 'awaiting_approval') return 'output'
    if (c.last_run?.stage === 'succeeded') return 'handoff'
    return null
  }
  return !c.project && awaitsApproval(c) && ['review','backlog'].includes(c.column) ? 'run' : null
})
const label = computed(() => ({ decision:'Record decision', output:'Approve & continue', handoff:'Approve handoff', run:'Approve run' }[kind.value || 'run']))
const explanation = computed(() => {
  if (kind.value === 'handoff') return 'Accept the latest completed result and release ready dependent stories. Open the task to inspect its evidence before approving.'
  if (kind.value === 'output') return 'Continue the same read-only story and allow MCD to save its proposed Markdown document.'
  return props.card.approval_reasons.join('; ') || 'Record your decision before dependent work can start.'
})
async function approve() {
  if (busy.value || !kind.value) return
  if (kind.value === 'decision' && !decisionOpen.value) { decision.value=''; decisionOpen.value=true; return }
  const c = props.card, action = kind.value, runId = c.last_run?.id
  busy.value=true; error.value=''
  try {
    if (action === 'run') await postJson(`/api/cards/${c.id}/approve`, { challenge: c.approval_challenge, pin: c.approval_pin })
    else {
      const base = `/api/projects/${c.project!.id}`
      const p = await getJson<Project>(base)
      const task = p.tasks.find(t => t.card_id === c.id && t.role === 'story')
      if (!task || !['active','paused'].includes(p.state)) throw new Error('This story is no longer available for approval. Refresh the task.')
      if (action === 'decision') {
        if (!decision.value.trim()) throw new Error('Write the operator decision before approving it.')
        await postJson(`${base}/stories/${c.id}/accept`, { revision:p.revision, run_id:null, summary:decision.value.trim(), snapshot:false, files:[] })
      } else {
        if (task.column !== 'review' || task.run_id !== runId) throw new Error('The latest run changed. Review the current result before approving.')
        if (action === 'output') {
          if (!task.output_approval || task.output_approval.run_id !== runId) throw new Error('This run is no longer waiting for output approval.')
          await postJson(`${base}/stories/${c.id}/continue-output`, { revision:p.revision, run_id:runId, approve_output:true })
        } else {
          if (task.run_stage !== 'succeeded') throw new Error('Only a completed successful result can be approved.')
          const artifact = await getJson<{files:string[]; output?:{sha256:string} | null}>(`${base}/stories/${c.id}/artifact`)
          if (artifact.files.length) throw new Error('This handoff has workspace changes. Review and select those files in Projects before approval.')
          const summary = p.memory.find(m => m.kind === 'proposal' && m.run_id === runId)?.text?.trim() || c.last_run?.result_text?.trim()
          if (!summary || summary.length > 12000) throw new Error('Open the project review to write a verified handoff summary.')
          await postJson(`${base}/stories/${c.id}/accept`, { revision:p.revision, run_id:runId, summary, snapshot:false, files:[], ...(artifact.output ? {output_sha256:artifact.output.sha256} : {}) })
        }
      }
    }
    decisionOpen.value=false; emit('changed')
  } catch (e) { error.value=e instanceof Error ? e.message : String(e) }
  finally { busy.value=false }
}
</script>

<template>
  <div v-if="kind" class="task-approval" @click.stop @dragstart.stop.prevent>
    <button type="button" class="btn primary approval-button" :disabled="busy" :title="explanation" @click="approve">
      <AppIcon name="approval" size="sm" />{{ busy ? 'Approving…' : label }}
    </button>
    <p v-if="kind === 'run' && card.approval_reasons.length" class="approval-reason">{{ card.approval_reasons.join('; ') }}</p>
    <p v-if="error && !decisionOpen" class="error-text" role="alert">{{ error }} <RouterLink v-if="card.project" :to="`/projects?project=${card.project.id}&view=work&story=${card.id}&action=review`">Open project review</RouterLink></p>
    <ModalShell class="decision-dialog" v-if="decisionOpen" :labelledby="`decision-title-${card.id}`" @close="decisionOpen=false">
      <form class="decision-form" @submit.prevent="approve">
        <h2 :id="`decision-title-${card.id}`">Record operator decision</h2>
        <p><strong>{{ card.title }}</strong></p>
        <p class="instructions">{{ card.body }}</p>
        <p v-if="card.acceptance" class="instructions muted">Definition of done: {{ card.acceptance }}</p>
        <label :for="`decision-${card.id}`">Your decision</label>
        <textarea :id="`decision-${card.id}`" v-model="decision" class="input" rows="7" required maxlength="12000" data-autofocus placeholder="Record each required choice and any conditions." />
        <p v-if="error" class="error-text" role="alert">{{ error }}</p>
        <div class="decision-actions"><button type="button" class="btn" @click="decisionOpen=false">Keep waiting</button><button class="btn primary" :disabled="busy || !decision.trim()">{{ busy ? 'Approving…' : 'Approve decision' }}</button></div>
      </form>
    </ModalShell>
  </div>
</template>

<style scoped>
.task-approval { width:100%; }
.decision-dialog :deep(.modal-panel) { padding:var(--gap-lg); }
.approval-button { display:inline-flex; align-items:center; justify-content:center; gap:var(--gap-xs); max-width:100%; font-size:var(--font-size-sm); white-space:normal; text-align:center; }
.approval-reason,.error-text { font-size:var(--font-size-xs); margin:var(--gap-xs) 0 0; overflow-wrap:anywhere; }
.decision-form { display:grid; gap:var(--gap); }
.decision-form h2,.decision-form p { margin:0; }
.decision-form h2 { font-size:var(--font-size-xl); font-weight:var(--font-weight-strong); }
.instructions { white-space:pre-wrap; overflow-wrap:anywhere; line-height:var(--line-height); }
.decision-actions { display:flex; justify-content:flex-end; gap:var(--gap-sm); flex-wrap:wrap; margin-top:var(--gap); }
@media (max-width:600px) { .decision-dialog :deep(.modal-panel) { padding:var(--gap); } }
</style>
