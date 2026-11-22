import { expect, test } from 'claude-code/testing'

import type { Board } from '../types'
import { classify, describeNow, drawMap, foldRows, ruleOf, runFrom, setupFrom, shareContext, topCost } from './map'

const PANE = {
  plugin: 'qz-console',
  component: 'Pane',
  requestId: 'qz-console',
  props: { title: 'QualiZeal console', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const
const SETUP = setupFrom({})
const STEP = { turnId: 't1', index: 0, model: 'claude-opus-5-5', messages: [] } as never

test('every kind of call lands on its station', () => {
  const at = (tool: string, input: Record<string, unknown> = {}) => classify(tool, input).station
  expect(at('mcp__plugin_qz-aidlc_qz__kf_search', { query: 'x' })).toBe('knowledge')
  expect(at('mcp__plugin_qz-aidlc_qz__price_run', { plan: 'p.json' })).toBe('bid')
  expect(at('mcp__plugin_qz-aidlc_qz__deck_build', {})).toBe('bid')
  expect(at('mcp__plugin_qz-aidlc_qz__voice_check', {})).toBe('bid')
  expect(at('mcp__plugin_qz-aidlc_qz__demo_check', {})).toBe('demo')
  expect(at('mcp__plugin_qz-aidlc_qz__stage', { name: 'pricing' })).toBe('ledger')
  expect(at('mcp__plugin_qz-aidlc_qz__review', { decision: 'accept' })).toBe('gates')
  expect(at('mcp__github__create_pull_request', {})).toBe('github')
  expect(at('mcp__atlassian__getJiraIssue', {})).toBe('atlassian')
  expect(at('Bash', { command: 'git push origin feature/x' })).toBe('github')
  expect(at('Bash', { command: 'git status' })).toBe('code')
  expect(at('Bash', { command: 'aidlc engine next' })).toBe('ledger')
  expect(at('Read', { file_path: '/repo/src/main/Customer.java' })).toBe('code')
  expect(at('WebFetch', { url: 'https://docs.example.com/a?b=c' })).toBe('knowledge')
  expect(at('Agent', { subagent_type: 'qz-bid-writer' })).toBe('agents')
  expect(at('AskUserQuestion', {})).toBe('gates')
})

test('labels carry names, never content', () => {
  expect(classify('Read', { file_path: '/Users/a/secret/project/notes.md' }).label).toBe('project/notes.md')
  expect(classify('WebFetch', { url: 'https://user:pw@docs.example.com/x?token=abc' }).label).toBe('web docs.example.com')
  expect(classify('Bash', { command: 'export TOKEN=abc && curl -H x https://a' }).label).toBe('export')
  expect(classify('mcp__plugin_qz-aidlc_qz__stage', { name: 'pricing' }).label).toBe('stage → pricing')
})

test('the guard rule id and the run status line are read from the harness words', () => {
  expect(ruleOf('Credentials are never read by an agent. (rule QZ-SH-ENV-CREDS)')).toBe('QZ-SH-ENV-CREDS')
  expect(ruleOf('no rule here')).toBeUndefined()
  expect(runFrom('[qz-ledger] Run R-7 · lane bid · stage pricing · stage tokens 12,000/60,000.')).toEqual({ id: 'R-7', lane: 'bid', stage: 'pricing', used: 12000, limit: 60000 })
})

test('the map draws on both themes and says where the run is', () => {
  const b: Board = { entries: [{ id: 'a', station: 'guard', label: 'blocked Read · QZ-SH-ENV-CREDS', from: 'core', startedAt: 900, endedAt: 900, status: 'block' }], counts: { guard: 1, code: 4 }, faults: { guard: 1 }, rules: { 'QZ-SH-ENV-CREDS': 1 }, context: 37, run: { lane: 'deliver', key: 'NW-214', stage: 'code-generation', used: 450000, limit: 900000 } }
  for (const theme of ['auto', 'dark', 'light']) {
    const svg = drawMap(b, 1000, setupFrom({ theme }))
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg).toContain('DELIVER · NW-214')
    expect(svg).toContain('STAGE BUDGET 50%')
    expect(svg).toContain('QZ-SH-ENV-CREDS ×1')
  }
  expect(describeNow(b)).toBe('DELIVER · NW-214 · stage code-generation · 50% of stage budget · context 37%')
  expect(drawMap(b, 1000, setupFrom({ showRules: false }))).not.toContain('QZ-SH-ENV-CREDS ×1')
})

test('repeated calls fold into one feed row', () => {
  const e = (id: string) => ({ id, station: 'code' as const, label: 'src/A.java', from: 'core' as const, startedAt: 0, endedAt: 5, status: 'ok' as const })
  const rows = foldRows([e('1'), e('2'), e('3')])
  expect(rows.length).toBe(1)
  expect(rows[0]?.times).toBe(3)
})

test('a call shows on the pane, on every surface', async ($, on) => {
  on('clock.now', () => ({ value: 1_000_000 }))
  on('command.register', () => ({ value: { command: 'qz-console' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('tool.call', () => ({ result: {} }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.tool.call({ tool: 'mcp__plugin_qz-aidlc_qz__kf_search', query: 'cold chain excursion' })
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /kf search/ }))?.text).toContain('Knowledge')
    expect(await ui.find({ type: 'Text', text: /cold chain/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('a guard refusal reads as blocked, by rule only, and the guard counts it', async ($, on) => {
  on('clock.now', () => ({ value: 1_000_000 }))
  on('classic.PreToolUse', () => ({ deny: 'Credentials are never read: found AKIA1234 in .env (rule QZ-SH-ENV-CREDS)' }))
  on('tool.call', () => ({ result: {} }))
  await $.tool.call({ tool: 'Read', file_path: '/repo/.env', tool_use_id: 'u1' })
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /blocked Read · QZ-SH-ENV-CREDS/ }))?.text).toContain('Guard')
  expect((await ui.find({ type: 'Text', text: /repo\/\.env/ }))?.text).toContain('✕')
  expect(await ui.find({ type: 'Text', text: /AKIA1234/ })).toBeUndefined()
  await ui.unmount()
})

test('a guard ask waits on the gates station until the call goes ahead', async ($, on) => {
  on('clock.now', () => ({ value: 1_000_000 }))
  on('classic.PreToolUse', () => ({ ask: "Pushing a branch is a person's step (rule QZ-ASK-GIT-PUSH)" }))
  on('tool.call', () => ({ result: {} }))
  await $.tool.call({ tool: 'Bash', command: 'git push origin feature/x', description: 'Push the branch', tool_use_id: 'u2' })
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /asked about Bash · QZ-ASK-GIT-PUSH/ }))?.text).toContain('Guard')
  const gate = await ui.find({ type: 'Text', text: /your yes for Bash/ })
  expect(gate?.text).toContain('Gates')
  expect(gate?.text).not.toContain('waiting for you')
  expect((await ui.find({ type: 'Text', text: /Push the branch/ }))?.text).toContain('GitHub')
  await ui.unmount()
})

test('the harness status line sets lane, stage and budget; a stage call moves the stage', async ($, on) => {
  on('clock.now', () => ({ value: 1_000_000 }))
  on('classic.UserPromptSubmit', () => ({ additionalContext: ['[qz-ledger] Run R-9 · lane bid · stage solution · stage tokens 30,000/150,000.'] }))
  on('tool.call', () => ({ result: {} }))
  await $.classic.UserPromptSubmit({ prompt: 'price it' } as never)
  await $.tool.call({ tool: 'mcp__plugin_qz-aidlc_qz__stage', name: 'pricing' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /BID/ }))?.text).toContain('stage pricing')
  expect((await ui.find({ type: 'Text', text: /BID/ }))?.text).toContain('20% of stage budget')
  await ui.unmount()
})

test('a model step streams through untouched and shows on the map', async ($, on) => {
  on('clock.now', () => ({ value: 1_000_000 }))
  on('turn.step', async function* () {
    yield { kind: 'text', index: 0, text: 'one' } as never
    yield { kind: 'text', index: 0, text: 'two' } as never
    return { turnId: 't1', index: 0, answer: '', toolUses: [] } as never
  })
  const seen: unknown[] = []
  for await (const chunk of $.turn.step(STEP)) seen.push(chunk)
  expect(seen).toEqual([{ kind: 'text', index: 0, text: 'one' }, { kind: 'text', index: 0, text: 'two' }])
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /step 1/ }))?.text).toContain('Model')
  await ui.unmount()
})

test('a broken board never stops a call', async ($, on) => {
  on('state.get', () => { throw new Error('no state') })
  on('state.set', () => { throw new Error('no state') })
  on('clock.now', () => { throw new Error('no clock') })
  on('tool.call', () => ({ result: { ok: true } }))
  const ran = await $.tool.call({ tool: 'Read', file_path: '/a/b.txt' })
  expect(ran.result).toEqual({ ok: true })
})

test('the core name is short and set', () => {
  expect(setupFrom({ coreName: 'QualiZeal' }).core).toBe('QualiZ')
  expect(SETUP.core).toBe('QZ')
})

test('context growth is shared among the stations that worked since the last reading', () => {
  const e = (id: string, station: 'code' | 'knowledge', endedAt: number) => ({ id, station, label: id, from: 'core' as const, startedAt: endedAt - 5, endedAt, status: 'ok' as const })
  let b: Board = { entries: [], counts: {} }
  b = { ...b, ...shareContext(b, 10, 100) }
  expect(b.cost).toBeUndefined()
  b = { ...b, entries: [e('a', 'code', 150), e('b', 'code', 160), e('c', 'knowledge', 170)] }
  b = { ...b, ...shareContext(b, 16, 200) }
  expect(b.cost).toEqual({ code: 4, knowledge: 2 })
  b = { ...b, ...shareContext(b, 19, 300) }
  expect(b.cost?.model).toBe(3)
  b = { ...b, ...shareContext(b, 5, 400) }
  expect(b.context).toBe(5)
  expect(b.cost).toEqual({ code: 4, knowledge: 2, model: 3 })
  expect(topCost(b, 2)).toEqual([['code', 4], ['model', 3]])
  expect(describeNow(b)).toContain('context 5% (most from Code, Model)')
  expect(drawMap(b, 1000, setupFrom({}))).toContain('ctx +4%')
})
