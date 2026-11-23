export type StationId =
  | 'you' | 'model' | 'agents' | 'guard' | 'gates' | 'ledger'
  | 'knowledge' | 'code' | 'github' | 'atlassian' | 'bid' | 'demo'

/** run: going · ok: done · err: failed · block: the guard refused it · ask: waiting on a person */
export type Status = 'run' | 'ok' | 'err' | 'block' | 'ask'

/** One action on the map. Labels carry names only: a file's last two path parts, a tool, a rule id. Never content. */
export type Entry = {
  id: string
  station: StationId
  label: string
  from: 'core' | 'agents' | 'inbound'
  startedAt: number
  endedAt?: number
  status: Status
  agentId?: string
  mark?: 'done' | 'switch'
}

/** What the harness last announced about the run (from its status line or from run_start / stage calls). */
export type Run = { id?: string; lane?: string; key?: string; stage?: string; used?: number; limit?: number; tests?: string }

export type Board = {
  entries: Entry[]
  counts: Partial<Record<StationId, number>>
  /** Refusals and errors per station since the person's last message. */
  faults?: Partial<Record<StationId, number>>
  /** Guard refusals and asks this session, by rule id. */
  rules?: Record<string, number>
  agents?: string[]
  model?: string
  step?: number
  context?: number
  /** When the context was last read (clock ms), and the context percentage points each station added since the session began. */
  measuredAt?: number
  cost?: Partial<Record<StationId, number>>
  run?: Run
}

declare module 'claude-code' {
  interface PluginState {
    'qz-console': { board: Shaped<Board> }
  }
}
