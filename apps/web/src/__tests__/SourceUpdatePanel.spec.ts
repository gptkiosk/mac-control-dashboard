import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import UpdatePanel from '@/components/UpdatePanel.vue'
import { stubFetch, calls } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

const REPO = 'gptkiosk/mac-control-dashboard'
const COMMIT = 'c'.repeat(40)
const inspection = (over: Record<string, unknown> = {}) => ({
  eligible: true, problems: [], checkout: '/Users/me/mcd-driver', version: '0.3.1', commit: 'a'.repeat(40), short: 'aaaaaaa', tag: 'v0.3.1',
  branch: null, remote: `https://github.com/${REPO}.git`, ...over,
})
const dev = (source: Record<string, unknown> = inspection()) => ({
  kind: 'dev', detail: 'this is a source checkout', configured: false, problems: [], manual_instructions: [], source,
})
const checkBody = (over: Record<string, unknown> = {}) => ({
  inspection: inspection(), available: true, blockers: [],
  candidate: { tag: 'v0.4.0', version: '0.4.0', notes: 'Adds <b>things</b>', html_url: `https://github.com/${REPO}/releases/tag/v0.4.0`, published_at: '2026-10-20T00:00:00Z', change: 'upgrade', repository: REPO },
  verified: { commit: COMMIT, signer: 'ssh-signature (dashboard-release)', version: '0.4.0' },
  ...over,
})
const operation = (state: string, over: Record<string, unknown> = {}) => ({
  operation: { id: '20261020T000000Z-abc123', state, tag: 'v0.4.0', commit: COMMIT, version: '0.4.0', from: { version: '0.3.1', commit: 'a'.repeat(40) },
    steps: [{ name: 'preflight', state: 'ok', detail: 'idle' }], message: 'Working.', ...over },
  active: state === 'running', log: ['10:00:00  checkout aaaaaaa v0.3.1'],
})
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find(b => b.text() === text)

it('shows nothing extra on a packaged install and no update button on an unmanaged host without a source report', async () => {
  stubFetch(url => url === '/api/app-updates' ? { body: { ...dev(), source: undefined } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).not.toContain('Update this checkout')
  w.unmount()
})

it('offers the manual steps only as a fallback when the one-click update is available', async () => {
  stubFetch(url => {
    if (url === '/api/app-updates') return { body: { ...dev(inspection({ remote: null })), manual_instructions: ['Back up the data folder.'] } }
    if (url === '/api/app-updates/source/operation') return { body: { operation: null, active: false, log: [] } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('the official repository')
  expect(w.get('details.manual summary').text()).toBe('Update by hand instead')
  w.unmount()
})

it('explains why a checkout cannot be updated and offers no button', async () => {
  stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev(inspection({ eligible: false, problems: ['origin is a fork, not the official repository.'] })) }
    if (url === '/api/app-updates/source/operation') return { body: { operation: null, active: false, log: [] } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('One-click update is not available here.')
  expect(w.text()).toContain('origin is a fork')
  expect(button(w, 'Check for updates')).toBeUndefined()
  w.unmount()
})

it('reads the release only when asked, shows the exact tag, commit and plain-text notes, and starts nothing', async () => {
  const f = stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') return { body: { operation: null, active: false, log: [] } }
    if (url === '/api/app-updates/source/check') return { body: checkBody() }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  expect(calls(f, 'GET', '/api/app-updates/source/check')).toHaveLength(0)
  await button(w, 'Check for updates')!.trigger('click'); await flushPromises()
  expect(w.text()).toContain('Update available: 0.4.0')
  expect(w.get('[data-test="dashboard"] [data-test="version"]').text()).toContain('→ 0.4.0')     // the same Running release card the packaged updater uses
  expect(w.get('[data-test="dashboard"] [data-test="word"]').text()).toBe('update available')
  expect(w.text()).toContain(COMMIT.slice(0, 12))
  expect(w.find('pre.notes').text()).toBe('Adds <b>things</b>')
  expect(w.find('b').exists()).toBe(false)
  expect(w.find(`a[href^="https://github.com/${REPO}/"]`).exists()).toBe(true)
  expect(calls(f, 'POST', '/api/app-updates/source')).toHaveLength(0)
  w.unmount()
})

it('needs a separate confirmation and then sends exactly the tag and commit the check showed', async () => {
  vi.useFakeTimers()
  let state = 'starting'
  const f = stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') return { body: state === 'none' ? { operation: null, active: false, log: [] } : operation(state) }
    if (url === '/api/app-updates/source/check') return { body: checkBody() }
    if (url === '/api/app-updates/source/start') { state = 'starting'; return { status: 202, body: { operation_id: 'x', poll: '/api/app-updates/source/operation' } } }
    return undefined
  })
  state = 'none'
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates')!.trigger('click'); await flushPromises()
  await button(w, 'Update to 0.4.0')!.trigger('click'); await flushPromises()
  const go = w.findAll('button').filter(b => b.text() === 'Update to 0.4.0').at(-1)!
  expect(go.attributes('disabled')).toBeDefined()                      // not until the box is ticked
  expect(calls(f, 'POST', '/api/app-updates/source/start')).toHaveLength(0)
  await w.get('input[type="checkbox"]').setValue(true)
  await go.trigger('click'); await flushPromises()
  const post = calls(f, 'POST', '/api/app-updates/source/start')
  expect(post).toHaveLength(1)
  expect(JSON.parse(String(post[0]![1]!.body))).toEqual({ tag: 'v0.4.0', commit: COMMIT, confirm: true })
  expect(w.text()).toContain('Updating to v0.4.0')
  w.unmount()
})

it('keeps polling through the restart and reports success with a reload hint', async () => {
  vi.useFakeTimers()
  let phase = 0
  stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') {
      phase++
      if (phase === 1) return { body: operation('running') }
      if (phase === 2) return { status: 503, body: { detail: 'restarting' } }          // the service is restarting
      return { body: operation('succeeded', { message: 'Updated to 0.4.0 (ccccccc). Health check passed.' }) }
    }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()                                   // page opened mid-update
  expect(w.text()).toContain('Updating to v0.4.0')
  await vi.advanceTimersByTimeAsync(2000); await flushPromises()
  expect(w.text()).toContain('Reconnecting to the service')
  await vi.advanceTimersByTimeAsync(2000); await flushPromises()
  expect(w.text()).toContain('Updated to 0.4.0 (ccccccc). Health check passed.')
  expect(w.text()).toContain('Reload this page')
  expect(w.text()).toContain('succeeded')
  w.unmount()
})

it('shows a rollback as a failure the operator must read, not as success', async () => {
  stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') return { body: operation('rolled_back', { message: 'The update failed and the previous version was restored.' }) }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('rolled back')
  expect(w.find('[role="alert"]').text()).toContain('previous version was restored')
  w.unmount()
})

it('does not offer the button while work is running and says what to drain', async () => {
  stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') return { body: { operation: null, active: false, log: [] } }
    if (url === '/api/app-updates/source/check') return { body: checkBody({ blockers: ['1 agent or chat run(s) still running: let them finish or cancel them'] }) }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates')!.trigger('click'); await flushPromises()
  expect(w.text()).toContain('still running')
  expect(w.text()).toContain('Finish or pause this work first')
  expect(button(w, 'Update to 0.4.0')).toBeUndefined()
  w.unmount()
})

it('shows the server refusal when the release moved on after the check', async () => {
  const f = stubFetch(url => {
    if (url === '/api/app-updates') return { body: dev() }
    if (url === '/api/app-updates/source/operation') return { body: { operation: null, active: false, log: [] } }
    if (url === '/api/app-updates/source/check') return { body: checkBody() }
    if (url === '/api/app-updates/source/start') return { status: 409, body: { detail: { message: 'The newest verified release is no longer the one you confirmed. Check again.', problems: [], blockers: [] } } }
    return undefined
  })
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates')!.trigger('click'); await flushPromises()
  await button(w, 'Update to 0.4.0')!.trigger('click'); await flushPromises()
  await w.get('input[type="checkbox"]').setValue(true)
  await w.findAll('button').filter(b => b.text() === 'Update to 0.4.0').at(-1)!.trigger('click'); await flushPromises()
  expect(w.find('[role="alert"]').text()).toContain('no longer the one you confirmed')
  expect(calls(f, 'POST', '/api/app-updates/source/start')).toHaveLength(1)
  w.unmount()
})
