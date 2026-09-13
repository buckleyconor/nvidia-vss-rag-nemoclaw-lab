import type { Evidence, Proposal, Stage, StreamEvent } from './types'

// The incident workspace is a pure fold over the incident's event log
// (operator-dashboard-spec §6.3). The same function serves the initial
// backfill and live events, so what the rail shows after a reload is exactly
// what it showed live. Events carry a per-incident `seq`; an event that skips
// ahead means something was missed and the caller re-fetches from the log
// rather than rendering an incomplete stream.

export interface SkillTraceEntry {
  name: string
  state: 'running' | 'done' | 'failed'
  startedAt: string
  durationMs?: number
  rationale?: string | null
  error?: string
}

export interface EtaInfo {
  seconds: number
  basis: string
  since: string
  chunksDone: number | null
  chunksTotal: number | null
}

export interface IncidentModel {
  lastSeq: number
  stage: Stage | null
  previousStage: Stage | null
  decideNotRequired: boolean
  events: StreamEvent[]
  skills: SkillTraceEntry[]
  evidence: Evidence[]
  proposal: Proposal | null
  errors: StreamEvent[]
  eta: EtaInfo | null
  lastEventAt: string | null
  workOrderId: string | null
}

export const emptyModel = (): IncidentModel => ({
  lastSeq: 0,
  stage: null,
  previousStage: null,
  decideNotRequired: false,
  events: [],
  skills: [],
  evidence: [],
  proposal: null,
  errors: [],
  eta: null,
  lastEventAt: null,
  workOrderId: null,
})

export interface FoldResult {
  model: IncidentModel
  gap: boolean
}

export function applyEvents(model: IncidentModel, incoming: StreamEvent[]): FoldResult {
  const sorted = [...incoming].sort((a, b) => a.seq - b.seq)
  let next = model
  for (const event of sorted) {
    if (event.seq <= next.lastSeq) continue // duplicate (live + backfill overlap)
    if (event.seq !== next.lastSeq + 1) return { model: next, gap: true }
    next = applyOne(next, event)
  }
  return { model: next, gap: false }
}

function applyOne(model: IncidentModel, event: StreamEvent): IncidentModel {
  const next: IncidentModel = {
    ...model,
    lastSeq: event.seq,
    events: [...model.events, event],
    lastEventAt: event.ts,
  }
  switch (event.type) {
    case 'stage.changed': {
      next.previousStage = (event.previous as Stage | null) ?? null
      next.stage = event.stage as Stage
      if (event.decide === 'not_required') next.decideNotRequired = true
      break
    }
    case 'analysis.progress': {
      next.eta = {
        seconds: Number(event.eta_seconds ?? 0),
        basis: String(event.basis ?? 'vss'),
        since: event.ts,
        chunksDone: (event.chunks_done as number | null) ?? null,
        chunksTotal: (event.chunks_total as number | null) ?? null,
      }
      break
    }
    case 'skill.invoked': {
      next.skills = [
        ...model.skills,
        {
          name: String(event.skill_name),
          state: 'running',
          startedAt: event.ts,
          rationale: (event.rationale as string | null) ?? null,
        },
      ]
      break
    }
    case 'skill.completed': {
      const skills = [...model.skills]
      for (let i = skills.length - 1; i >= 0; i--) {
        if (skills[i].name === event.skill_name && skills[i].state === 'running') {
          skills[i] = {
            ...skills[i],
            state: event.outcome === 'failed' ? 'failed' : 'done',
            durationMs: Number(event.duration_ms ?? 0),
            error: event.error as string | undefined,
          }
          break
        }
      }
      next.skills = skills
      break
    }
    case 'evidence.added': {
      const row = event.evidence as Evidence
      if (!model.evidence.some((e) => e.id === row.id)) next.evidence = [...model.evidence, row]
      break
    }
    case 'proposal.ready':
      next.proposal = event.proposal as Proposal
      break
    case 'workorder.created':
      next.workOrderId = String(event.work_order_id)
      break
    case 'error':
      next.errors = [...model.errors, event]
      break
    default:
      break
  }
  return next
}

export type RailState = 'done' | 'current' | 'pending' | 'not_required' | 'not_taken'

// Stage rail truth table (§3). Monitor is a fleet state: lit before the
// incident exists. Decide is "not required" for an auto-filed monitoring
// note; Act is "not taken" when a proposal was denied.
export function railStates(model: Pick<IncidentModel, 'stage' | 'previousStage' | 'decideNotRequired'>) {
  const order: Stage[] = ['detect', 'gather', 'propose', 'decide', 'act']
  const states: Record<string, RailState> = { monitor: 'done' }
  const stage = model.stage
  if (stage === null) {
    order.forEach((s) => (states[s] = 'pending'))
    states.monitor = 'current'
    return states
  }
  if (stage === 'closed') {
    const deniedAt = model.previousStage === 'decide'
    order.forEach((s) => (states[s] = 'done'))
    if (deniedAt) states.act = 'not_taken'
    if (model.decideNotRequired) states.decide = 'not_required'
    if (model.previousStage && model.previousStage !== 'act' && !deniedAt) {
      // Closed early (reset or failure before a proposal).
      const reached = order.indexOf(model.previousStage)
      order.forEach((s, i) => (states[s] = i <= reached ? 'done' : 'not_taken'))
    }
    return states
  }
  const index = order.indexOf(stage)
  order.forEach((s, i) => {
    states[s] = i < index ? 'done' : i === index ? (s === 'act' ? 'done' : 'current') : 'pending'
  })
  if (model.decideNotRequired) states.decide = 'not_required'
  return states
}

export const STAGE_LABEL: Record<string, string> = {
  monitor: 'Monitor',
  detect: 'Detect',
  gather: 'Gather context',
  propose: 'Propose',
  decide: 'Decide',
  act: 'Act',
  closed: 'Closed',
}

// What the system is waiting on while quiet (§8.4 "never a spinner").
export function waitingOn(stage: Stage | null): string | null {
  switch (stage) {
    case 'detect':
      return 'clip submission to VSS and the agent wake-up'
    case 'gather':
      return 'VSS video analysis and the agent'
    case 'propose':
      return "the agent's proposal"
    default:
      return null
  }
}
