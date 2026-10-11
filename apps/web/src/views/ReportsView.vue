<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import AppSelect from '@/components/AppSelect.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { bytesLabel, dateLabel, type Reports, type ReportContent } from '@/lib/operations'
import { renderReport } from '@/lib/reportMarkdown'

const { data, error, loaded, refresh } = usePolledJson<Reports>('/api/reports', 60000)
const selected = ref('')
const reports = computed(() => data.value?.reports ?? [])
watch(reports, list => { if (!list.some(r => r.id === selected.value)) selected.value = list[0]?.id ?? '' })
const current = computed(() => reports.value.find(r => r.id === selected.value))
const path = computed(() => selected.value ? `/api/reports/${selected.value}` : '/api/reports')
const { data: rawContent, error: contentError, loaded: contentLoaded, refresh: refreshContent } = usePolledJson<ReportContent | Reports>(path, 60000)
const content = computed(() => rawContent.value && 'content' in rawContent.value ? rawContent.value : null)
const historical = computed(() => !!current.value && Date.now() / 1000 - current.value.modified_at > 86400)
const html = computed(() => content.value?.format === 'markdown' ? renderReport(content.value.content) : '')
function refreshAll() { refresh(); if (selected.value) refreshContent() }
</script>
<template>
  <section aria-labelledby="reports-title">
    <div class="page-header"><h1 id="reports-title" class="page-title has-icon"><AppIcon name="logs" size="lg" />Ops reports</h1><button class="btn" @click="refreshAll">Refresh</button></div>
    <p class="muted">Hermes reports and configured local report folders. Latest first, checked every minute.</p>
    <p v-if="error || data?.error" role="status" class="notice-warn">{{ error || data?.error }}</p>
    <p v-if="!loaded" role="status" class="muted">Loading reports…</p>
    <div v-else-if="!reports.length" class="card empty"><h2>No reports yet</h2><p class="muted">Markdown and UTF-8 text reports will appear here when Hermes writes them to the report folder.</p><code>{{ data?.root }}</code><p v-if="data && !data.available" class="muted">The report folder is not available yet.</p></div>
    <template v-else>
      <div class="report-controls card"><label>Report<AppSelect v-model="selected" aria-label="Report"><option v-for="r in reports" :key="r.id" :value="r.id" :data-description="`${r.source || 'Ops report folder'} · ${dateLabel(r.modified_at)} · ${bytesLabel(r.size)}`">{{ r.title || r.name }}</option></AppSelect></label><p class="muted">{{ reports.length }} reports<span v-if="data?.limited"> · Showing a capped list of up to 200 reports</span> · Preview limit 512 KiB</p></div>
      <div class="reports-layout">
        <nav class="report-list" aria-label="Reports"><button v-for="r in reports" :key="r.id" class="card report-row" :class="{ selected: r.id === selected }" :aria-pressed="r.id === selected" @click="selected = r.id"><strong>{{ r.title || r.name }}</strong><small class="muted">{{ r.source }} · {{ dateLabel(r.modified_at) }} · {{ bytesLabel(r.size) }}</small><small v-if="!r.readable" class="muted">Too large to preview</small></button></nav>
        <article class="card report-content" :aria-label="current?.title || current?.name || 'Report content'">
          <header v-if="current"><h2>{{ current.title || current.name }}</h2><p class="muted">{{ current.source }} · Captured {{ dateLabel(content?.modified_at ?? current.modified_at) }} · {{ bytesLabel(content?.size ?? current.size) }}</p></header>
          <p v-if="historical" role="status" class="notice-warn">Historical report, more than 24 hours old. These findings describe its captured run, not current health.</p>
          <p v-if="content?.response_only" class="muted small">Showing the recorded Hermes response. The original job prompt is omitted.</p>
          <p v-if="contentError" role="status" class="notice-warn">{{ contentError }}<span v-if="content"> Showing the last successfully read version.</span></p>
          <p v-if="!contentLoaded" role="status" class="muted">Loading report…</p>
          <div v-if="content?.format === 'markdown'" class="markdown-report" v-html="html" />
          <pre v-else-if="content" class="text-report">{{ content.content }}</pre>
        </article>
      </div>
    </template>
  </section>
</template>
<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--gap); }
.empty code { overflow-wrap: anywhere; }
.report-controls { margin: var(--gap-lg) 0; }
label { display: grid; gap: var(--gap-sm); color: var(--text-muted); }
.report-controls p { margin-bottom: 0; font-size: var(--font-size-xs); }
.reports-layout { display: grid; grid-template-columns: minmax(200px, 300px) minmax(0, 1fr); gap: var(--gap-lg); align-items: start; }
.report-list { display: grid; gap: var(--gap-sm); max-height: 70vh; overflow-y: auto; }
.report-row { text-align: left; display: grid; gap: var(--gap-sm); cursor: pointer; color: var(--text); font: inherit; overflow-wrap: anywhere; }
.report-row.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.report-content { min-width: 0; overflow-wrap: anywhere; }
h2 { font-size: var(--font-size-lg); margin-top: 0; }
header { border-bottom: 1px solid var(--surface-border); margin-bottom: 0; }
header p { font-size: var(--font-size-xs); }
.text-report { white-space: pre-wrap; overflow-wrap: anywhere; }
.markdown-report { line-height: 1.7; }
.markdown-report :deep(> :first-child) { margin-top: 0; }
.markdown-report :deep(p) { margin: .8em 0; }
.markdown-report :deep(ul), .markdown-report :deep(ol) { padding-left: 1.5em; margin: .8em 0; }
.markdown-report :deep(ul) { list-style: disc; }
.markdown-report :deep(ol) { list-style: decimal; }
.markdown-report :deep(li) { margin: .25em 0; }
.markdown-report :deep(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.markdown-report :deep(hr) { border-color: var(--surface-border); margin: 1.2em 0; }
.markdown-report :deep(h1), .markdown-report :deep(h2), .markdown-report :deep(h3) { line-height: 1.3; margin: 1.5em 0 .6em; }
.markdown-report :deep(h1) { font-size: 1.6rem; }
.markdown-report :deep(h2) { font-size: 1.3rem; }
.markdown-report :deep(h3) { font-size: 1.1rem; }
.markdown-report :deep(pre) { overflow: auto; padding: var(--gap); background: var(--bg); border: 1px solid var(--surface-border); border-radius: var(--radius-sm); }
.markdown-report :deep(pre code) { white-space: pre; }
.markdown-report :deep(code) { color: var(--accent); font-size: .9em; }
.markdown-report :deep(blockquote) { margin-left: 0; padding-left: var(--gap); border-left: 3px solid var(--accent); color: var(--text-muted); }
.markdown-report :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.markdown-report :deep(th), .markdown-report :deep(td) { padding: var(--gap-sm); border: 1px solid var(--surface-border); }
@media (max-width: 760px) { .reports-layout { grid-template-columns: 1fr; } .report-list { display: none; } }
</style>
