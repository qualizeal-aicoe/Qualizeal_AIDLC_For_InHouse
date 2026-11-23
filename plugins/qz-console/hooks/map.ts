/* What the QualiZeal console knows: which station a call belongs to, what the harness says about the run,
   and how the map is drawn. No I/O here; register.tsx feeds it events and renders what it returns. */
import type { Board, Entry, Run, StationId, Status } from '../types'
import { ICONS } from './icons'

export const STATIONS: { id: StationId; name: string }[] = [
  { id: 'you', name: 'You' },
  { id: 'gates', name: 'Gates' },
  { id: 'guard', name: 'Guard' },
  { id: 'ledger', name: 'Ledger' },
  { id: 'github', name: 'GitHub' },
  { id: 'atlassian', name: 'Jira·Conf' },
  { id: 'knowledge', name: 'Knowledge' },
  { id: 'bid', name: 'Bid' },
  { id: 'demo', name: 'Demo' },
  { id: 'code', name: 'Code' },
  { id: 'agents', name: 'Agents' },
  { id: 'model', name: 'Model' },
]
export const NAME = Object.fromEntries(STATIONS.map(s => [s.id, s.name])) as Record<StationId, string>

export type Setup = { theme: 'auto' | 'dark' | 'light'; showRules: boolean; core: string }

export function setupFrom(o: Readonly<Record<string, unknown>> = {}): Setup {
  const theme = o.theme === 'dark' || o.theme === 'light' ? o.theme : 'auto'
  const core = typeof o.coreName === 'string' && o.coreName.trim() !== '' ? o.coreName.trim().slice(0, 6) : 'QZ'
  return { theme, showRules: o.showRules !== false, core }
}

// ---------- labels: names only, never content ----------
const str = (v: unknown): string => (typeof v === 'string' ? v : '')
const slashes = (p: string): string => p.replace(/\\/g, '/')
const lastTwo = (p: string): string => slashes(p).split('/').filter(Boolean).slice(-2).join('/')

export function clean(label: string, max = 72): string {
  const one = label.replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim()
  return one.length > max ? `${one.slice(0, max - 1)}…` : one
}

function hostOf(url: string): string {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#@]+@)?([^/?#:]+)/i.exec(url)
  return m?.[2] ? m[2].toLowerCase() : 'web'
}

/** The rule id the QZ guard puts at the end of its message: "... (rule QZ-SH-ENV-CREDS)". */
export function ruleOf(message: string | undefined): string | undefined {
  const m = /\(rule ([A-Z][A-Z0-9-]{1,40})\)\s*$/.exec(str(message).trim())
  return m ? m[1] : undefined
}

/** The harness status line: "Run R-1 · lane deliver · stage code-generation · stage tokens 41,000/900,000[ · tests passed 42]." */
export function runFrom(text: string): Run | undefined {
  const m = /Run (\S+) · lane (\S+) · stage (\S+) · stage tokens ([\d,]+)\/([\d,]+)/.exec(text)
  if (!m) return undefined
  const n = (s: string | undefined): number => Number((s ?? '').replace(/,/g, ''))
  const run: Run = { id: m[1] ?? '', lane: m[2] ?? '', stage: m[3] ?? '', used: n(m[4]), limit: n(m[5]) }
  const t = /stage tokens [\d,]+\/[\d,]+ · tests ([^·\n]+?)\.(?:\s|$)/.exec(text)
  if (t?.[1]) run.tests = t[1]
  return run
}

const QZ = /^mcp__(?:plugin_qz-aidlc_qz|qz)__(.+)$/
const BID = new Set(['price_roles', 'price_run', 'price_patch', 'price_parity', 'sow_build', 'deck_build', 'voice_check'])
const LEDGER = new Set(['run_start', 'stage', 'output_seal', 'takeover', 'report_card', 'audit_verify', 'redteam'])

function shellStation(command: string): { station: StationId; word: string } {
  const words = command.trim().split(/\s+/)
  const first = (words[0] ?? '').replace(/^.*\//, '')
  if (first === 'git' && /^(push|pull|fetch|clone|remote)$/.test(words[1] ?? '')) return { station: 'github', word: `git ${words[1]}` }
  if (first === 'gh') return { station: 'github', word: `gh ${words[1] ?? ''}`.trim() }
  if (first === 'aidlc') return { station: 'ledger', word: `aidlc ${words[1] ?? ''} ${words[2] ?? ''}`.trim() }
  if (/qz(\.py)?$/.test(words[1] ?? '') || /qz\.py/.test(command)) return { station: 'ledger', word: 'qz' }
  return { station: 'code', word: first || 'shell' }
}

export type Classified = { station: StationId; label: string }

/** Where a call lands, and the name it goes by. */
export function classify(tool: string, input: Record<string, unknown>): Classified {
  const qz = QZ.exec(tool)
  if (qz) {
    const name = qz[1] ?? ''
    const label = name.replace(/_/g, ' ')
    if (name.startsWith('kf_')) return { station: 'knowledge', label }
    if (name.startsWith('demo_')) return { station: 'demo', label }
    if (BID.has(name)) return { station: 'bid', label }
    if (name === 'review') return { station: 'gates', label: `review ${str(input.decision)}`.trim() }
    if (LEDGER.has(name)) {
      if (name === 'stage') return { station: 'ledger', label: `stage → ${str(input.name)}` }
      if (name === 'run_start') return { station: 'ledger', label: `run ${str(input.lane)} ${str(input.key)}`.trim() }
      return { station: 'ledger', label }
    }
    return { station: 'ledger', label }
  }
  if (/^mcp__[^_]*github/i.test(tool) || /^mcp__plugin_[^_]*github/i.test(tool)) return { station: 'github', label: tool.replace(/^.*__/, '').replace(/_/g, ' ') }
  if (/^mcp__[^_]*atlassian/i.test(tool) || /^mcp__plugin_[^_]*atlassian/i.test(tool)) return { station: 'atlassian', label: tool.replace(/^.*__/, '').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase() }
  if (/^mcp__memory__/.test(tool)) return { station: 'knowledge', label: `memory ${tool.replace(/^.*__memory_?/, '')}`.trim() }
  if (/browser|chrome/i.test(tool)) return { station: 'knowledge', label: 'browser' }
  switch (tool) {
    case 'Read': case 'Edit': case 'Write': case 'MultiEdit': case 'NotebookEdit':
      return { station: 'code', label: lastTwo(str(input.file_path) || str(input.notebook_path)) || tool }
    case 'Glob': case 'Grep': case 'LS':
      return { station: 'code', label: `${tool.toLowerCase()} ${clean(str(input.pattern), 24)}`.trim() }
    case 'Bash': case 'PowerShell': {
      const s = shellStation(str(input.command))
      return { station: s.station, label: clean(str(input.description), 48) || s.word }
    }
    case 'WebFetch': return { station: 'knowledge', label: `web ${hostOf(str(input.url))}` }
    case 'WebSearch': return { station: 'knowledge', label: 'web search' }
    case 'Task': case 'Agent': return { station: 'agents', label: str(input.subagent_type) || clean(str(input.description), 40) || 'sub-agent' }
    case 'AskUserQuestion': return { station: 'gates', label: 'question for you' }
    case 'Skill': return { station: 'model', label: `skill ${str(input.skill)}`.trim() }
    case 'TaskCreate': case 'TaskUpdate': case 'TodoWrite': return { station: 'ledger', label: 'task list' }
  }
  if (tool.startsWith('mcp__')) return { station: 'code', label: tool.replace(/^mcp__/, '').replace(/__/g, ' ') }
  return { station: 'code', label: tool }
}

export const shortModel = (m: string): string => m.replace(/^claude-/, '').replace(/-(\d+)-(\d+)(-\d{8})?$/, ' $1.$2').replace(/-/g, ' ')

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
  return `${Math.floor(ms / 60000)}m${String(Math.round((ms % 60000) / 1000)).padStart(2, '0')}s`
}

export const pct = (r?: Run): number | undefined => (r?.used !== undefined && r.limit ? Math.round((100 * r.used) / r.limit) : undefined)

/** Context growth since the last reading, shared among the stations whose calls ended in between (the idea of
    lot-map's context cost). With no call in between, the growth is the model's own. A drop means a compaction:
    the reading restarts and nothing is charged. Points of the context window, not tokens. */
export function shareContext(b: Board, percent: number, now: number): Partial<Board> {
  const last = b.context
  if (last === undefined || percent <= last) return { context: percent, measuredAt: now }
  const since = b.measuredAt ?? -Infinity
  const ended = b.entries.filter(e => e.endedAt !== undefined && e.endedAt > since && e.endedAt <= now && e.station !== 'you' && e.station !== 'model')
  const who: StationId[] = ended.length ? ended.map(e => e.station) : ['model']
  const cost = { ...(b.cost ?? {}) }
  for (const s of who) cost[s] = Math.round(((cost[s] ?? 0) + (percent - last) / who.length) * 10) / 10
  return { context: percent, measuredAt: now, cost }
}

/** The stations that filled the context most, biggest first. */
export function topCost(b: Board, n = 3): [StationId, number][] {
  return (Object.entries(b.cost ?? {}) as [StationId, number][]).filter(([, v]) => v >= 0.5).sort((x, y) => y[1] - x[1]).slice(0, n)
}

/** The line under the map: where the run is and what is happening now. */
export function describeNow(b: Board): string {
  const r = b.run ?? {}
  const parts = [r.lane ? r.lane.toUpperCase() : 'no run', r.key, r.stage ? `stage ${r.stage}` : undefined]
  const p = pct(r)
  if (p !== undefined) parts.push(`${p}% of stage budget`)
  if (r.tests) parts.push(`tests ${r.tests}`)
  if (b.context !== undefined) {
    const top = topCost(b, 2)
    parts.push(`context ${Math.round(b.context)}%${top.length ? ` (most from ${top.map(([k]) => NAME[k]).join(', ')})` : ''}`)
  }
  const running = b.entries.filter(e => e.status === 'run').length
  const waiting = b.entries.filter(e => e.status === 'ask').length
  if (waiting) parts.push(`${waiting} waiting on you`)
  else if (running) parts.push(`${running} running`)
  return parts.filter(Boolean).join(' · ')
}

/** Feed rows, newest first; a call repeated back to back folds into one row with a count. */
export function foldRows(entries: Entry[], max = 16): { entry: Entry; times: number; tookMs: number }[] {
  const out: { entry: Entry; times: number; tookMs: number }[] = []
  for (const e of [...entries].reverse()) {
    const prev = out[out.length - 1]
    const took = e.endedAt !== undefined ? e.endedAt - e.startedAt : 0
    if (prev && prev.entry.station === e.station && prev.entry.label === e.label && prev.entry.status === e.status && e.status !== 'run') {
      prev.times += 1; prev.tookMs += took
      continue
    }
    out.push({ entry: e, times: 1, tookMs: took })
    if (out.length >= max) break
  }
  return out
}

// ---------- the map ----------
type Palette = { ground: string; raised: string; line: string; spoke: string; text: string; dim: string; accent: string; hot: string; red: string; amber: string; violet: string; green: string }
const DARK: Palette = { ground: '#0B1830', raised: '#122650', line: '#2A3F78', spoke: '#1E2E5C', text: '#EAF0FA', dim: '#8C9AC0', accent: '#0096FF', hot: '#6CC4FF', red: '#F43D59', amber: '#F5B53D', violet: '#8B6CFF', green: '#34D399' }
const LIGHT: Palette = { ground: '#F7F9FC', raised: '#FFFFFF', line: '#CCD5E3', spoke: '#DCE3EE', text: '#16243A', dim: '#5B6B82', accent: '#0A6FD6', hot: '#0096FF', red: '#D2334C', amber: '#B7791F', violet: '#6A4FE0', green: '#1F8F5F' }
const KEYS = Object.keys(DARK) as (keyof Palette)[]

const W = 480, H = 500, CX = 240, CY = 250, RX = 182, RY = 172, NODE = 21, CORE = 44, HUB = CORE + 10
const PULSE_MS = 900, GLOW_MS = 3000
const n1 = (v: number): string => (Math.round(v * 10) / 10).toString()
const clock = (ms: number): string => `${(ms / 1000).toFixed(2)}s`
const esc = (s: string): string => s.replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] as string)
type P = { x: number; y: number }
const place = (i: number): P => { const a = (i * 2 * Math.PI) / STATIONS.length; return { x: CX + RX * Math.sin(a), y: CY - RY * Math.cos(a) } }
const idx = (id: StationId): number => STATIONS.findIndex(s => s.id === id)
const edge = (from: P, to: P, r: number): P => { const dx = to.x - from.x, dy = to.y - from.y, d = Math.hypot(dx, dy) || 1; return { x: from.x + (dx / d) * r, y: from.y + (dy / d) * r } }

/** In auto, the map is drawn dark and repaints itself on a light surface through CSS variables. */
function paint(theme: Setup['theme']): { c: Record<keyof Palette, string>; style: string } {
  if (theme !== 'auto') { const p = theme === 'light' ? LIGHT : DARK; return { c: p, style: '' } }
  const c = Object.fromEntries(KEYS.map(k => [k, `var(--qz-${k})`])) as Record<keyof Palette, string>
  const vars = (p: Palette): string => KEYS.map(k => `--qz-${k}:${p[k]}`).join(';')
  return { c, style: `<style>svg{${vars(DARK)}}@media (prefers-color-scheme: light){svg{${vars(LIGHT)}}}</style>` }
}

const statusColor = (s: Status, c: Record<keyof Palette, string>): string => (s === 'block' || s === 'err' ? c.red : s === 'ask' ? c.amber : c.hot)

export function drawMap(b: Board, now: number, setup: Setup): string {
  const { c, style } = paint(setup.theme)
  const core: P = { x: CX, y: CY }
  const recent = b.entries.slice(-48)
  let out = `<rect width="${W}" height="${H}" rx="14" fill="${c.ground}"/>`

  // Header: the run, in the harness's own words.
  const r = b.run ?? {}
  const p = pct(r)
  out += `<text x="18" y="26" font-family="JetBrains Mono, ui-monospace, Menlo, monospace" font-size="11" letter-spacing="1.6" fill="${c.red}">${esc((r.lane ?? 'no run').toUpperCase())}${r.key ? ` · ${esc(r.key)}` : ''}</text>`
  out += `<text x="18" y="44" font-family="Inter, system-ui, sans-serif" font-size="13" fill="${c.text}">${r.stage ? `stage ${esc(r.stage)}` : 'waiting for a run'}</text>`
  if (p !== undefined) {
    const w = 120, x = W - 18 - w, full = Math.min(100, p)
    out += `<text x="${W - 18}" y="26" text-anchor="end" font-family="JetBrains Mono, ui-monospace, monospace" font-size="10" fill="${c.dim}">STAGE BUDGET ${p}%</text>`
    out += `<rect x="${x}" y="34" width="${w}" height="6" rx="3" fill="${c.spoke}"/><rect x="${x}" y="34" width="${n1((w * full) / 100)}" height="6" rx="3" fill="${p >= 100 ? c.red : p >= 80 ? c.amber : c.accent}"/>`
  }

  // Contours, then spokes worn by use.
  for (const [rx, ry] of [[74, 70], [116, 109], [154, 145]]) out += `<ellipse cx="${CX}" cy="${CY}" rx="${rx}" ry="${ry}" fill="none" stroke="${c.line}" stroke-width=".7" opacity=".4" stroke-dasharray="2 5"/>`
  STATIONS.forEach((s, i) => {
    const pt = place(i), a = edge(core, pt, HUB), z = edge(pt, core, NODE)
    const worn = Math.min(1, Math.log2(1 + (b.counts[s.id] ?? 0)) / 6)
    const line = `<line x1="${n1(a.x)}" y1="${n1(a.y)}" x2="${n1(z.x)}" y2="${n1(z.y)}" stroke-linecap="round" stroke-width="${n1(1 + 2.8 * worn)}"`
    out += `${line} stroke="${c.spoke}"/>`
    if (worn > 0) out += `${line} stroke="${s.id === 'guard' ? c.red : s.id === 'gates' ? c.amber : c.accent}" opacity="${n1(0.25 + worn * 0.4)}"/>`
  })

  // Pulses out on start and back on finish: the direction of the work is the point of the map.
  const agentsAt = place(idx('agents'))
  const ends = (e: Entry): [P, P] => { const to = place(idx(e.station)), from = e.from === 'agents' ? agentsAt : core; return [edge(from, to, e.from === 'agents' ? NODE : HUB), edge(to, from, NODE)] }
  for (const e of recent.filter(x => now - x.startedAt < PULSE_MS * 1.6).slice(-16)) {
    const [a, z] = ends(e), [s0, s1] = e.from === 'inbound' ? [z, a] : [a, z]
    const col = statusColor(e.status, c), begin = clock(e.startedAt - now)
    out += `<line x1="${n1(a.x)}" y1="${n1(a.y)}" x2="${n1(z.x)}" y2="${n1(z.y)}" stroke="${col}" stroke-width="2.4" stroke-linecap="round" opacity="0"><animate attributeName="opacity" values=".8;0" begin="${begin}" dur="${clock(GLOW_MS)}" fill="freeze"/></line>`
    out += `<circle r="4" fill="${col}" opacity="0"><animate attributeName="opacity" values="1;1;0" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/><animate attributeName="cx" from="${n1(s0.x)}" to="${n1(s1.x)}" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/><animate attributeName="cy" from="${n1(s0.y)}" to="${n1(s1.y)}" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/></circle>`
  }
  for (const e of recent.filter(x => x.endedAt !== undefined && x.from !== 'inbound' && now - (x.endedAt as number) < PULSE_MS * 1.6).slice(-16)) {
    const [a, z] = ends(e), begin = clock((e.endedAt as number) - now)
    const col = e.status === 'ok' ? c.dim : statusColor(e.status, c)
    out += `<circle r="2.8" fill="${col}" opacity="0"><animate attributeName="opacity" values=".9;.9;0" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/><animate attributeName="cx" from="${n1(z.x)}" to="${n1(a.x)}" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/><animate attributeName="cy" from="${n1(z.y)}" to="${n1(a.y)}" begin="${begin}" dur="${clock(PULSE_MS)}" fill="freeze"/></circle>`
  }

  // Stations: lit while busy, a red count for what went wrong, an amber count for what waits on a person.
  STATIONS.forEach((s, i) => {
    const pt = place(i)
    const mine = recent.filter(e => e.station === s.id)
    const busy = mine.some(e => e.status === 'run')
    const asking = mine.filter(e => e.status === 'ask').length
    const lastAt = mine.length ? Math.max(...mine.map(e => e.endedAt ?? e.startedAt)) : -Infinity
    const warm = busy || now - lastAt < GLOW_MS
    const ring = s.id === 'guard' && (b.faults?.guard ?? 0) > 0 ? c.red : busy ? c.accent : warm ? c.hot : c.line
    if (busy) out += `<circle cx="${n1(pt.x)}" cy="${n1(pt.y)}" r="${NODE + 6}" fill="${c.accent}" opacity=".14"><animate attributeName="r" values="${NODE + 3};${NODE + 10};${NODE + 3}" dur="1.4s" begin="${clock(-(now % 1400))}" repeatCount="indefinite"/></circle>`
    out += `<circle cx="${n1(pt.x)}" cy="${n1(pt.y)}" r="${NODE}" fill="${c.raised}" stroke="${ring}" stroke-width="${busy || warm ? 1.8 : 1.1}"/>`
    out += `<svg x="${n1(pt.x - 10)}" y="${n1(pt.y - 10)}" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${warm ? c.text : c.dim}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[s.id]}</svg>`
    const below = pt.y >= CY - 4
    out += `<text x="${n1(pt.x)}" y="${n1(below ? pt.y + NODE + 14 : pt.y - NODE - 7)}" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="10.5" fill="${warm ? c.text : c.dim}">${esc(s.name)}${b.counts[s.id] ? ` ${b.counts[s.id]}` : ''}</text>`
    const share = b.cost?.[s.id] ?? 0
    if (share >= 0.5) out += `<text x="${n1(pt.x)}" y="${n1(below ? pt.y + NODE + 26 : pt.y - NODE - 19)}" text-anchor="middle" font-family="JetBrains Mono, ui-monospace, monospace" font-size="8.5" fill="${c.dim}">ctx +${Math.round(share)}%</text>`
    const bad = b.faults?.[s.id] ?? 0
    if (bad > 0) out += `<circle cx="${n1(pt.x + NODE - 3)}" cy="${n1(pt.y - NODE + 3)}" r="8" fill="${c.red}"/><text x="${n1(pt.x + NODE - 3)}" y="${n1(pt.y - NODE + 6.5)}" text-anchor="middle" font-family="Inter, sans-serif" font-size="9.5" font-weight="700" fill="#fff">${bad}</text>`
    if (asking > 0) out += `<circle cx="${n1(pt.x - NODE + 3)}" cy="${n1(pt.y - NODE + 3)}" r="8" fill="${c.amber}"/><text x="${n1(pt.x - NODE + 3)}" y="${n1(pt.y - NODE + 6.5)}" text-anchor="middle" font-family="Inter, sans-serif" font-size="9.5" font-weight="700" fill="#1a1a1a">${asking}</text>`
  })

  // Sub-agents still working circle the agents station.
  ;(b.agents ?? []).slice(0, 6).forEach((_, k, all) => {
    const lap = 6000, at = `${n1(agentsAt.x)} ${n1(agentsAt.y)}`
    out += `<g><animateTransform attributeName="transform" type="rotate" from="0 ${at}" to="360 ${at}" begin="${clock(-((now + (k * lap) / all.length) % lap))}" dur="${clock(lap)}" repeatCount="indefinite"/><circle cx="${n1(agentsAt.x)}" cy="${n1(agentsAt.y - NODE - 6)}" r="3" fill="${c.violet}"/></g>`
  })

  // The core: the harness. Outer ring = stage budget, inner ring = context window.
  const anyRunning = recent.some(e => e.status === 'run')
  const period = anyRunning ? 1500 : 4600
  out += `<circle cx="${CX}" cy="${CY}" r="${CORE + 6}" fill="${c.accent}" opacity=".08"><animate attributeName="r" values="${CORE + 2};${CORE + 13};${CORE + 2}" begin="${clock(-(now % period))}" dur="${clock(period)}" repeatCount="indefinite"/></circle>`
  out += `<circle cx="${CX}" cy="${CY}" r="${CORE}" fill="${c.raised}" stroke="${anyRunning ? c.accent : c.line}" stroke-width="1.4"/>`
  const arc = (rad: number, value: number, col: string): string =>
    `<circle cx="${CX}" cy="${CY}" r="${rad}" fill="none" stroke="${c.spoke}" stroke-width="2.6"/><circle cx="${CX}" cy="${CY}" r="${rad}" fill="none" stroke="${col}" stroke-width="2.6" stroke-linecap="round" pathLength="100" stroke-dasharray="${Math.max(0, Math.min(100, value))} 100" transform="rotate(-90 ${CX} ${CY})"/>`
  if (p !== undefined) out += arc(CORE + 9, p, p >= 100 ? c.red : p >= 80 ? c.amber : c.accent)
  if (b.context !== undefined) out += arc(CORE - 5, b.context, b.context >= 90 ? c.red : b.context >= 70 ? c.amber : c.green)
  const size = Math.min(20, 64 / (0.72 * Math.max(2, setup.core.length)))
  out += `<text x="${CX}" y="${CY + 2}" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-weight="700" font-size="${n1(size)}" letter-spacing="1.5" fill="${c.text}">${esc(setup.core)}</text>`
  if (b.model) out += `<text x="${CX}" y="${CY + 18}" text-anchor="middle" font-family="JetBrains Mono, ui-monospace, monospace" font-size="9" fill="${c.dim}">${esc(shortModel(b.model))}</text>`
  const done = recent.filter(e => e.mark === 'done').pop()
  if (done && now - done.startedAt < 1200) {
    out += `<circle cx="${CX}" cy="${CY}" r="${CORE}" fill="none" stroke="${c.text}" stroke-width="1.6" opacity="0"><animate attributeName="r" values="${CORE};${CORE + 40}" begin="${clock(done.startedAt - now)}" dur="1.2s" fill="freeze"/><animate attributeName="opacity" values=".6;0" begin="${clock(done.startedAt - now)}" dur="1.2s" fill="freeze"/></circle>`
  }

  // Footer: guard rules seen this session.
  const rules = Object.entries(b.rules ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 4)
  if (setup.showRules && rules.length) {
    out += `<text x="18" y="${H - 14}" font-family="JetBrains Mono, ui-monospace, monospace" font-size="9.5" fill="${c.dim}">GUARD  ${esc(rules.map(([k, v]) => `${k} ×${v}`).join('  '))}</text>`
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W * 2}" height="${H * 2}">${style}${out}</svg>`
}
