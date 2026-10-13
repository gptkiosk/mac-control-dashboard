import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import UpdatePanel from '@/components/UpdatePanel.vue'
import { stubFetch, calls, headerOf } from './helpers'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

const names: Record<string, string> = { v0: '0.9', v1: '1.0', v2: '1.1', v3: '1.2', v4: '1.3', v5: '1.4' }
const version = (id: string, over: Record<string, unknown> = {}) => ({ id, complete: true, version: names[id], channel: 'stable', change: 'upgrade', repository: 'example-owner/example-app', authenticity: 'ssh-signature', staged_at: 1700000000, ...over })
const managed = (over: Record<string, unknown> = {}, install: Record<string, unknown> = {}) => ({
  kind: 'release', detail: 'packaged version 1.0', configured: true, problems: [], manual_instructions: [], blockers: [],
  install: {
    current: 'v1', previous: null, tx: null, last: null, needs_recovery: false,
    versions: [version('v1', { change: 'install' }), version('v2'), version('v3', { channel: 'dev' }), version('v4', { complete: false })],
    ...install,
  },
  ...over,
})
const tick = async (ms = 0) => { await vi.advanceTimersByTimeAsync(ms); await nextTick() }
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find(b => b.text() === text)!

it('says what is available on an unmanaged host and offers no install, rollback or network check', async () => {
  const f = stubFetch(url => url === '/api/app-updates' ? { body: { kind: 'dev', detail: 'this is a source checkout', configured: false, problems: [], manual_instructions: ['Automatic updates are off for this install.'] } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Managed updates are off: this is a source checkout.')
  expect(w.text()).toContain('Automatic updates are off for this install.')
  expect(w.findAll('button').map(b => b.text())).toEqual(['Check for updates'])
  expect(w.find('a').exists()).toBe(false)
  expect(calls(f, 'POST', '/api/app-updates')).toHaveLength(0)
  w.unmount()
})

it('checks only this host: one GET to the local status route, no other request', async () => {
  const f = stubFetch(url => url === '/api/app-updates' ? { body: managed() } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Check for updates').trigger('click'); await flushPromises()
  expect(f.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)).toEqual(['GET /api/app-updates', 'GET /api/app-updates'])
  expect(w.text()).toContain('Checked')
  w.unmount()
})

it('offers only complete stable or prerelease packages and never a link, archive or docs download', async () => {
  stubFetch(url => url === '/api/app-updates' ? { body: managed({}, { versions: [version('v1', { change: 'install' }), version('v2'), version('v3', { channel: 'dev' }), version('v4', { complete: false }), version('v5', { channel: 'docs' })] }) } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Running 1.0. 1 staged update is ready on this host.')
  expect(w.findAll('button').map(b => b.text())).toContain('Install 1.1')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Install 1.2')
  expect(w.findAll('button').map(b => b.text())).not.toContain('Install 1.3')
  expect(w.text()).toContain('A development build. It is never offered as an update.')
  expect(w.text()).toContain('only partly staged')
  expect(w.text()).toContain('Channel “docs” is not an application release')
  expect(w.text()).toContain('Release notes: not included in this package.')
  expect(w.find('a').exists()).toBe(false)
  expect(w.text()).not.toMatch(/\.zip|\.tar|archive|\bdownload\b/i)
  w.unmount()
})

it('requires an explicit confirmation before posting the operator-only install', async () => {
  const f = stubFetch((url, init) => url === '/api/app-updates' ? { body: managed() } : url === '/api/app-updates/apply' && init?.method === 'POST' ? { status: 202, body: { started: 'apply' } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Install 1.1').trigger('click'); await flushPromises()
  const confirm = w.get('.confirm')
  expect(confirm.text()).toContain('Replaces 1.0')
  const go = confirm.findAll('button')[0]!
  expect(go.attributes('disabled')).toBeDefined()
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  expect(confirm.findAll('button')[0]!.attributes('disabled')).toBeUndefined()
  await confirm.findAll('button')[0]!.trigger('click'); await flushPromises()
  const [, init] = calls(f, 'POST', '/api/app-updates/apply')[0]!
  expect(JSON.parse(init!.body as string)).toEqual({ version_id: 'v2' })
  expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  expect(w.text()).toContain('Install started on the host')
  w.unmount()
})

it('disables install and rollback while work is running and says to drain first', async () => {
  stubFetch(url => url === '/api/app-updates' ? { body: managed({ blockers: ['1 live agent run'] }, { previous: 'v0', versions: [version('v0', { change: 'upgrade' }), version('v1', { change: 'install' }), version('v2')] }) } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  expect(w.text()).toContain('Drain first. Nothing is stopped or cancelled for you.')
  expect(button(w, 'Install 1.1').attributes('disabled')).toBeDefined()
  expect(button(w, 'Roll back to 0.9').attributes('disabled')).toBeDefined()
  w.unmount()
})

it('shows the server refusal and the blockers it names, unpacked from the 409 body', async () => {
  stubFetch((url, init) => url === '/api/app-updates' ? { body: managed() } : url === '/api/app-updates/apply' && init?.method === 'POST' ? { status: 409, body: { detail: { message: 'Drain first. Nothing was stopped.', blockers: ['1 queued task'] } } } : undefined)
  const w = mount(UpdatePanel); await flushPromises()
  await button(w, 'Install 1.1').trigger('click'); await flushPromises()
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toBe('Drain first. Nothing was stopped. 1 queued task')
  w.unmount()
})

it('follows progress through a service restart and reports the health result', async () => {
  vi.useFakeTimers()
  const idle = managed()
  const switching = managed({}, { tx: { id: 't2', kind: 'switch', phase: 'switching', target: 'v2' } })
  const committed = managed({ kind: 'release' }, { current: 'v2', previous: 'v1', last: { tx: 't2', kind: 'switch', outcome: 'committed', detail: 'ready', target: 'v2', from: 'v1', at: 1700000100 } })
  const replies = [{ body: idle }, { body: switching }, { status: 503, body: { detail: 'restarting' } }, { body: committed }]
  let reads = 0
  const f = stubFetch((url, init) => {
    if (url === '/api/app-updates/apply' && init?.method === 'POST') return { status: 202, body: { started: 'apply' } }
    if (url === '/api/app-updates') return replies[Math.min(reads++, replies.length - 1)]
    return undefined
  })
  const w = mount(UpdatePanel); await tick(0)
  await button(w, 'Install 1.1').trigger('click'); await tick(0)
  await w.get('.confirm input[type="checkbox"]').setValue(true)
  await w.get('.confirm').findAll('button')[0]!.trigger('click'); await tick(0)
  expect(calls(f, 'POST', '/api/app-updates/apply')).toHaveLength(1)
  await tick(2000); expect(w.text()).toContain('Switching versions')
  await tick(2000); expect(w.text()).toContain('Reconnecting to the service')
  await tick(2000)
  expect(w.text()).toContain('Now running 1.1. Health check: ready')
  expect(w.text()).not.toContain('Reconnecting')
  w.unmount()
})
