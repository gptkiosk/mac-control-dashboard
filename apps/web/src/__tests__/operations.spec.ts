import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import GithubView from '@/views/GithubView.vue'
import ReportsView from '@/views/ReportsView.vue'
import { renderReport } from '@/lib/reportMarkdown'
import { stubFetch } from './helpers'

const fresh = { checked_at: 1000, stale: false, error: null }
const repos = ['example-repo', 'another-repo'].map(name => ({ name: `example-user/${name}`, url: `https://github.com/example-user/${name}`, private: true, archived: false, branch: 'main', description: 'Operations', updated_at: '2026-10-09T00:00:00Z' }))
const report = { id: 'a'.repeat(64), name: 'weekly/status.md', modified_at: 1000, size: 90, readable: true }
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('operations pages', () => {
  it('shows repositories, switches details, filters and retains stale work', async () => {
    stubFetch(url => url === '/api/github/repos' ? { body: { ...fresh, repos, limited: false } } : { body: { name: url, pulls: { ...fresh, items: [] }, issues: { ...fresh, stale: true, error: 'GitHub unavailable', items: [{ number: 7, title: 'Investigate', user: 'example-user', url: 'https://github.com/example-user/example-repo/issues/7', labels: ['ops'], updated_at: '2026-10-09T00:00:00Z', draft: false }] } } })
    const w = mount(GithubView); await flushPromises()
    expect(w.text()).toContain('2 repositories')
    expect(w.text()).toContain('No open pull requests')
    expect(w.text()).toContain('Showing the last successful result')
    await w.findAll('.repo-card')[1]!.trigger('click'); await flushPromises()
    expect(w.get('.detail-heading').text()).toContain('another-repo')
    await w.get('input[type="search"]').setValue('another')
    expect(w.findAll('.repo-card')).toHaveLength(1)
    expect(w.get('a[href$="/issues/7"]').attributes('rel')).toBe('noopener noreferrer')
    w.unmount()
  })
  it('shows missing reports without trying a file request', async () => {
    const fetch = stubFetch(() => ({ body: { reports: [], available: false, error: null, limited: false, root: '/ops-reports' } }))
    const w = mount(ReportsView); await flushPromises()
    expect(w.text()).toContain('No reports yet')
    expect(w.text()).toContain('/ops-reports')
    expect(fetch.mock.calls.every(([url]) => url === '/api/reports')).toBe(true)
    w.unmount()
  })
  it('renders the latest report and reports a deleted file without stale content from another report', async () => {
    const next = { ...report, id: 'b'.repeat(64), name: 'deleted.md' }
    stubFetch(url => url === '/api/reports' ? { body: { reports: [report, next], available: true, error: null, limited: false, root: '/reports' } } : url.endsWith(report.id) ? { body: { ...report, content: '# Healthy\n\n| Agent | Status |\n| --- | --- |\n| Hermes | Idle |', format: 'markdown' } } : { status: 404, body: { detail: 'Report is unavailable.' } })
    const w = mount(ReportsView); await flushPromises()
    expect(w.get('.markdown-report h1').text()).toBe('Healthy')
    expect(w.find('.markdown-report table').exists()).toBe(true)
    await w.findAll('.report-row')[1]!.trigger('click'); await flushPromises()
    expect(w.text()).toContain('Report is unavailable.')
    expect(w.find('.markdown-report').exists()).toBe(false)
    w.unmount()
  })
  it('labels historical Hermes findings and shows readable source titles', async () => {
    const archived = { ...report, title: 'Morning Fleet Health Check', source: 'Hermes cron archive', source_id: 'hermes' }
    stubFetch(url => url === '/api/reports' ? { body: { reports: [archived], available: true, error: null, limited: false, root: '/reports' } } : { body: { ...archived, response_only: true, content: '# Recorded findings', format: 'markdown' } })
    const w=mount(ReportsView);await flushPromises()
    expect(w.get('article h2').text()).toBe('Morning Fleet Health Check')
    expect(w.text()).toContain('Hermes cron archive')
    expect(w.text()).toContain('not current health')
    expect(w.text()).toContain('original job prompt is omitted')
    w.unmount()
  })
})
describe('untrusted report Markdown', () => {
  it('escapes HTML, rejects unsafe/relative links and prevents remote images', () => {
    const html = renderReport('<script>alert(1)</script>\n\n[bad](javascript:alert%281%29) [relative](/auth/logout) ![remote](https://example.com/tracker) [good](https://github.com/example-user/example-repo)')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('href="/auth/')
    expect(html).toContain('href="https://github.com/example-user/example-repo"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('[Image: remote]')
  })
})
