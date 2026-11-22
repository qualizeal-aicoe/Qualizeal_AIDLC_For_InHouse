/* QualiZeal console: a live map of the AI-DLC harness at work, in a pane beside the chat.
   Event wiring follows the pattern of lot-map by Aleksei Volodin (MIT licence, see NOTICE). It reads no files,
   makes no requests, calls no model and adds nothing to the conversation. Labels hold names only. */
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board, Entry, Run, StationId, Status } from '../types'
import { NAME, classify, clean, describeNow, drawMap, foldRows, formatMs, ruleOf, runFrom, setupFrom, shareContext, shortModel, topCost } from './map'

const PANE = 'qz-console'
const KEEP = 80
const CREW = 8

// Change the shape tag when a field of Entry or Board changes: it declines what an earlier version stored.
const board = atom({ plugin: 'qz-console', key: 'board' } as const, { entries: [], counts: {} } as Board, { shape: 'qz-board-2' })

const newId = (now: number): string => `${now.toString(36)}${Math.random().toString(36).slice(2, 7)}`

/** Nothing that goes wrong on the map may reach the tool, the turn or the conversation. */
async function quietly<T>(work: () => Promise<T>): Promise<T | undefined> {
  try {
    return await work()
  } catch {
    return undefined
  }
}

const isFault = (s: Status): boolean => s === 'err' || s === 'block'
const kept = (entries: Entry[]): Entry[] => (entries.length <= KEEP ? entries : entries.filter((e, i) => i >= entries.length - KEEP || e.status === 'run' || e.status === 'ask'))
const plusOne = <K extends string>(m: Partial<Record<K, number>> | undefined, k: K): Partial<Record<K, number>> => ({ ...(m ?? {}), [k]: ((m as Partial<Record<K, number>> | undefined)?.[k] ?? 0) + 1 }) as Partial<Record<K, number>>

type Start = { station: StationId; label: string; from?: Entry['from']; status?: Status; agentId?: string; mark?: Entry['mark']; rule?: string; uncounted?: boolean; patch?: Partial<Board> }

async function begin($: EngineInterface, s: Start): Promise<string | undefined> {
  return quietly(async () => {
    const now = await $.clock.now()
    const done = s.status !== undefined && s.status !== 'run' && s.status !== 'ask'
    const entry: Entry = {
      id: newId(now), station: s.station, label: clean(s.label), from: s.from ?? 'core', startedAt: now,
      status: s.status ?? 'run', ...(done ? { endedAt: now } : {}),
      ...(s.agentId !== undefined ? { agentId: s.agentId } : {}), ...(s.mark !== undefined ? { mark: s.mark } : {}),
    }
    await update($, board, b => ({
      ...b, ...s.patch,
      entries: kept([...b.entries, entry]),
      counts: s.uncounted ? b.counts : plusOne(b.counts, entry.station),
      ...(isFault(entry.status) && entry.station !== 'you' ? { faults: plusOne(b.faults, entry.station) } : {}),
      ...(s.rule ? { rules: plusOne(b.rules, s.rule) as Record<string, number> } : {}),
      ...(entry.agentId !== undefined && !(b.agents ?? []).includes(entry.agentId) ? { agents: [...(b.agents ?? []), entry.agentId].slice(-CREW) } : {}),
    }))
    return entry.id
  })
}

async function finish($: EngineInterface, id: string | undefined, status: Status, patch?: Partial<Board>): Promise<void> {
  if (id === undefined) return
  await quietly(async () => {
    const now = await $.clock.now()
    await update($, board, b => {
      const open = b.entries.find(e => e.id === id && (e.status === 'run' || e.status === 'ask'))
      return {
        ...b, ...patch,
        entries: b.entries.map(e => (e === open ? { ...e, status, endedAt: now } : e)),
        ...(open !== undefined && isFault(status) ? { faults: plusOne(b.faults, open.station) } : {}),
      }
    })
  })
}

/** A person answered: every open ask on the gates station closes, approved or not. */
async function answerAsks($: EngineInterface, status: Status): Promise<void> {
  await quietly(async () => {
    const now = await $.clock.now()
    await update($, board, b => ({ ...b, entries: b.entries.map(e => (e.status === 'ask' ? { ...e, status, endedAt: now } : e)) }))
  })
}

/** Read the context once and share what it grew by among the stations that worked since the last reading. */
async function measure($: EngineInterface): Promise<void> {
  await quietly(async () => {
    const percent = (await $.session.usage()).context.percent
    if (typeof percent !== 'number') return
    const now = await $.clock.now()
    await update($, board, b => ({ ...b, ...shareContext(b, percent, now) }))
  })
}

async function noteRun($: EngineInterface, texts: readonly string[] | undefined): Promise<void> {
  const run = runFrom((texts ?? []).join('\n'))
  if (run === undefined) return
  await quietly(() => update($, board, b => ({ ...b, run: { ...b.run, ...run } })))
}

export const register: Register = (on, options) => {
  const setup = setupFrom(options)
  // Calls the guard refused or asked about, so the tool's own row reads right.
  const refused = new Set<string>()
  const asked = new Map<string, string>()

  on('session.start', async ($, e, next) => {
    await quietly(() => $.command.register({ name: 'qz-console', description: 'Open the QualiZeal console beside the chat' }))
    void quietly(() => $.ui.open({ id: PANE, title: 'QualiZeal console' }))
    return next(e)
  })

  on('command.run', { command: 'qz-console' }, async $ => {
    const opened = await $.ui.open({ id: PANE, title: 'QualiZeal console' })
    return { text: opened.isPlaced ? 'QualiZeal console is open beside the chat.' : `The console could not open here (${String(opened.reason)}).` }
  })

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && e.text !== '') {
      await quietly(() => update($, board, b => (b.faults === undefined ? b : { ...b, faults: {} })))
      await begin($, { station: 'you', label: 'new message', from: 'inbound', status: 'ok' })
    }
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    const main = e.agentId === undefined
    const id = await begin($, {
      station: 'model', label: `${shortModel(e.model)} · step ${e.index + 1}${main ? '' : ' · sub-agent'}`,
      from: main ? 'core' : 'agents', ...(main ? { patch: { model: e.model, step: e.index + 1 } } : { agentId: e.agentId }),
    })
    try {
      return yield* next(e)
    } finally {
      await finish($, id, 'ok')
      if (main) await measure($)
    }
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) {
      const agentId = e.agentId
      await quietly(async () => {
        const now = await $.clock.now()
        await update($, board, b => ({
          ...b, agents: (b.agents ?? []).filter(x => x !== agentId),
          entries: b.entries.map(x => (x.status === 'run' && x.agentId === agentId ? { ...x, status: 'ok' as const, endedAt: now } : x)),
        }))
      })
    } else {
      await begin($, { station: 'you', label: e.isAborted ? 'turn stopped' : 'answer ready', status: e.isAborted ? 'err' : 'ok', ...(e.isAborted ? {} : { mark: 'done' as const }) })
      await quietly(async () => {
        const now = await $.clock.now()
        await update($, board, b => ({ ...b, entries: b.entries.map(x => (x.status === 'run' && x.from === 'core' ? { ...x, status: 'ok' as const, endedAt: now } : x)) }))
      })
    }
    return next(e)
  })

  // The QualiZeal guard runs as a settings hook: its refusals and asks show here, by rule id only.
  on('classic.PreToolUse', async ($, e, next) => {
    const decided = await next(e)
    await quietly(async () => {
      if (decided.deny !== undefined) {
        const rule = ruleOf(decided.deny)
        if (e.tool_use_id !== undefined) refused.add(e.tool_use_id)
        await begin($, { station: 'guard', label: `blocked ${e.tool}${setup.showRules && rule ? ` · ${rule}` : ''}`, status: 'block', ...(rule ? { rule } : {}) })
      } else if (decided.ask !== undefined) {
        const rule = ruleOf(decided.ask) ?? 'ask'
        if (e.tool_use_id !== undefined) asked.set(e.tool_use_id, rule)
        await begin($, { station: 'guard', label: `asked about ${e.tool}${setup.showRules ? ` · ${rule}` : ''}`, status: 'ok', rule })
        await begin($, { station: 'gates', label: `your yes for ${e.tool}${setup.showRules ? ` · ${rule}` : ''}`, status: 'ask', uncounted: false })
      }
    })
    return decided
  })

  on('tool.call', async ($, e, next) => {
    const input = e as unknown as Record<string, unknown>
    const seen = classify(e.tool, input)
    const id = await begin($, { ...seen, ...(e.tool === 'AskUserQuestion' ? { status: 'ask' as const } : {}), ...(e.agentId === undefined ? { from: 'core' as const } : { from: 'agents' as const, agentId: e.agentId }) })
    try {
      const ran = await next(e)
      const wasRefused = ran.deny !== undefined || (e.tool_use_id !== undefined && refused.delete(e.tool_use_id))
      if (e.tool_use_id !== undefined && asked.has(e.tool_use_id)) {
        asked.delete(e.tool_use_id)
        await answerAsks($, wasRefused ? 'block' : 'ok')
      }
      const status: Status = wasRefused ? 'block' : ran.isError === true ? 'err' : 'ok'
      let patch: Partial<Board> | undefined
      if (status === 'ok' && /__(run_start|stage)$/.test(e.tool)) {
        await quietly(async () => {
          const cur = (await read($, board)).run ?? {}
          const next_: Run = /__run_start$/.test(e.tool)
            ? { ...cur, lane: String(input.lane ?? cur.lane ?? ''), ...(input.key ? { key: String(input.key) } : {}), stage: 'start', used: 0 }
            : { ...cur, stage: String(input.name ?? cur.stage ?? '') }
          patch = { run: next_ }
        })
      }
      await finish($, id, status, patch)
      return ran
    } catch (failure) {
      await finish($, id, 'err')
      throw failure
    }
  })

  on('classic.SessionStart', async ($, e, next) => {
    const result = await next(e)
    await noteRun($, result.additionalContext)
    return result
  })

  on('classic.UserPromptSubmit', async ($, e, next) => {
    const result = await next(e)
    await noteRun($, result.additionalContext)
    return result
  })

  on('session.compact', async ($, e, next) => {
    const id = await begin($, { station: 'model', label: 'compacting the conversation' })
    try {
      return await next(e)
    } finally {
      await finish($, id, 'ok')
      await measure($)
    }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const state = await read($, board)
    const now = await $.clock.now()
    const { Box, Text } = $.ui.resolve(e)
    const width = Math.max(...Object.values(NAME).map(n => n.length))
    const rows = foldRows(state.entries).map(({ entry, times, tookMs }) => {
      const mark = entry.status === 'run' ? '●' : entry.status === 'ask' ? '◆' : entry.status === 'ok' ? '·' : '✕'
      const took = entry.status === 'run' ? 'running' : entry.status === 'ask' ? 'waiting for you' : tookMs > 0 ? formatMs(tookMs) : ''
      const color = entry.status === 'run' ? 'claude' : entry.status === 'ok' ? undefined : entry.status === 'ask' ? 'claude' : 'error'
      const line = `${mark} ${NAME[entry.station].padEnd(width)} ${entry.label}${times > 1 ? `  ×${times}` : ''}${took ? `  ${took}` : ''}`
      return (
        <Text mono size="footnote" color={color} dimColor={entry.status === 'ok'}>
          {line}
        </Text>
      )
    })
    const feed = rows.length > 0 ? rows : [<Text dimColor>Nothing yet. Start a run with /qz-aidlc:qz.</Text>]
    const current = <Text mono size="footnote">{describeNow(state)}</Text>
    if (e.surface === 'terminal') {
      const tally = Object.entries(state.counts).filter(([, n]) => (n ?? 0) > 0).map(([k, n]) => `${NAME[k as StationId]} ${n}`).join(' · ')
      const filled = topCost(state, 4).map(([k, v]) => `${NAME[k]} +${Math.round(v)}%`).join(' · ')
      return (
        <Box flexDirection="column">
          {current}
          <Text dimColor>{tally === '' ? 'no calls yet' : tally}</Text>
          {filled === '' ? null : <Text dimColor>{`context from: ${filled}`}</Text>}
          {feed}
        </Box>
      )
    }
    const { Svg } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Svg source={drawMap(state, now, setup)} alt={`QualiZeal console. ${describeNow(state)}`} />
        {current}
        {feed}
      </Box>
    )
  })
}
