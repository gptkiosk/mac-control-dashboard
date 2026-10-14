import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TaskRetryAction from '@/components/TaskRetryAction.vue'
import { card, run, stubFetch, calls } from './helpers'
import { emptyProject, type Project } from '@/lib/projects'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
const failed = () => card({id:50,column:'failed',agent:'claude',model:'claude-opus-5-5',project:{id:2,node_key:'durable',role:'story'},last_run:run({id:51,card_id:50,stage:'failed',error:"You've hit your session limit"})})
function project(): Project { return {id:2,state:'active',revision:2,approved_revision:2,document:emptyProject(),pipeline:null,error:null,updated_at:1,tasks:[{card_id:50,node_key:'durable',role:'story',revision:2,column:'failed',title:'Durable',run_id:51,run_stage:'failed',retry_routes:[{agent:'claude',model:'claude-opus-5-5'},{agent:'codex',model:'gpt-6.1-sol'}]}],memory:[],workspaces:{},artifacts:{}} }
function setup(p=project()) {
  const f=stubFetch((url,init)=>url==='/api/projects/2' || init?.method==='POST' ? {body:p} : undefined)
  const w=mount(TaskRetryAction,{props:{card:failed()},attachTo:document.body})
  return {w,f}
}
it('queues the same story once without granting approvals or creating a replacement task',async()=>{
  const {w,f}=setup();await flushPromises()
  expect(w.text()).toContain('quota resets')
  await w.findAll('button')[0]!.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/retry')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2})
  expect(w.text()).toContain('Rerun queued')
  expect(w.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  expect(w.emitted('changed')).toHaveLength(1);w.unmount()
})
it('only offers and submits the project’s approved fallback route',async()=>{
  const {w,f}=setup();await flushPromises()
  expect(w.findAll('button')).toHaveLength(3)
  expect(w.findAll('button')[1]!.text()).toContain('Codex · gpt-6.1-sol')
  await w.findAll('button')[1]!.trigger('click');await flushPromises()
  expect(JSON.parse(String(calls(f,'POST','/api/')[0]![1]?.body))).toEqual({revision:2,route:{agent:'codex',model:'gpt-6.1-sol'}})
  w.unmount()
})
it('refuses a stale task state instead of duplicating an active run',async()=>{
  const p=project();const {w,f}=setup(p);await flushPromises()
  p.tasks[0]!.column='running';p.tasks[0]!.run_id=52
  await w.findAll('button')[0]!.trigger('click');await flushPromises()
  expect(calls(f,'POST','/api/')).toHaveLength(0)
  expect(w.text()).toContain('task changed');w.unmount()
})
it('does not offer reruns for human decisions or active jobs and disables paused projects',async()=>{
  const p=project();p.state='paused';const {w,f}=setup(p);await flushPromises()
  expect(w.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('Resume project')
  await w.setProps({card:{...failed(),column:'running'}})
  expect(w.find('button').exists()).toBe(false)
  await w.setProps({card:{...failed(),assignee_type:'human'}})
  expect(w.find('button').exists()).toBe(false)
  expect(calls(f,'POST','/api/')).toHaveLength(0);w.unmount()
})

const freeRoute = {agent:'openclaw' as const,model:'openrouter/example/code:free',agent_target:'mm-developer'}
it('Go Free selects only configured free routes and grants only the current run/story',async()=>{
  const p=project();p.tasks[0]!.free_retry_routes=[freeRoute]
  const {w,f}=setup(p);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Go Free!')!.trigger('click')
  expect(w.text()).toContain('No paid-model or Google BYOK fallback')
  await w.findAll('button').find(b=>b.text()==='Start free retry')!.trigger('click');await flushPromises()
  const writes=calls(f,'POST','/api/');expect(writes).toHaveLength(1)
  expect(writes[0]![0]).toBe('/api/projects/2/stories/50/go-free')
  expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({revision:2,run_id:51,model:freeRoute.model,agent_target:'mm-developer'})
  expect(w.text()).toContain('Free-model retry queued');w.unmount()
})
it('Go Free refuses stale routes before submission and shows missing configuration',async()=>{
  const p=project();p.tasks[0]!.free_retry_routes=[freeRoute]
  const {w,f}=setup(p);await flushPromises()
  await w.findAll('button').find(b=>b.text()==='Go Free!')!.trigger('click')
  p.tasks[0]!.free_retry_routes=[]
  await w.findAll('button').find(b=>b.text()==='Start free retry')!.trigger('click');await flushPromises()
  expect(calls(f,'POST','/api/')).toHaveLength(0)
  expect(w.text()).toContain('no longer configured');w.unmount()
  const missing=setup();await flushPromises()
  expect(missing.w.findAll('button').find(b=>b.text()==='Go Free!')!.attributes('disabled')).toBeDefined()
  expect(missing.w.text()).toContain('configured OpenRouter :free model');missing.w.unmount()
})
it('Go Free stays hidden for failures unrelated to subscription limits',async()=>{
  const {w}=setup();await flushPromises()
  await w.setProps({card:{...failed(),last_run:run({id:51,stage:'failed',error:'test suite failed'})}});await flushPromises()
  expect(w.findAll('button').some(b=>b.text()==='Go Free!')).toBe(false);w.unmount()
})
