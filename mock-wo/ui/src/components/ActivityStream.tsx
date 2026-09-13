import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useEvidenceFocus } from '../lib/evidenceFocus'
import { clock, duration, timecode } from '../lib/format'
import { STAGE_LABEL, waitingOn } from '../lib/incidentModel'
import { Link } from '../lib/router'
import type { Evidence, Stage, StreamEvent } from '../lib/types'

export const QUIET_MS = 8000

interface Props {
  events: StreamEvent[]
  evidence: Evidence[]
  stage: Stage | null
  lastEventAt: string | null
  onRetry?: () => void
  now?: () => number
}

// §8.4 — append-only, newest at the bottom, auto-scrolls until the operator
// scrolls away. Five classes render distinctly. Never a spinner: after eight
// quiet seconds the stream says what it is waiting on and for how long.
export function ActivityStream({ events, evidence, stage, lastEventAt, onRetry, now = Date.now }: Props) {
  const list = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useLayoutEffect(() => {
    const element = list.current
    if (element && pinned.current) element.scrollTop = element.scrollHeight
  }, [events.length, tick])

  const quietFor = lastEventAt ? now() - new Date(lastEventAt).getTime() : 0
  const waiting = waitingOn(stage)
  const visible = events.filter((event) => RENDERED.has(event.type))

  return (
    <div
      className="activity"
      ref={list}
      data-testid="activity"
      onScroll={(event) => {
        const el = event.currentTarget
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      }}
    >
      {visible.length === 0 && <div className="muted empty">The agent's work appears here as it happens.</div>}
      {visible.map((event) => (
        <ActivityRow key={`${event.incident_id}:${event.seq}`} event={event} evidence={evidence} onRetry={onRetry} stage={stage} />
      ))}
      {waiting && quietFor > QUIET_MS && (
        <div className="activity-waiting" role="status" data-testid="waiting">
          Waiting on {waiting} — {Math.round(quietFor / 1000)} s since the last update.
        </div>
      )}
      {stage === 'decide' && <div className="activity-waiting">Waiting on your decision.</div>}
    </div>
  )
}

const RENDERED = new Set([
  'stage.changed',
  'analysis.caption',
  'retrieval.query',
  'retrieval.result',
  'skill.invoked',
  'skill.completed',
  'agent.token',
  'evidence.added',
  'ask.answer',
  'archive.match',
  'decision.recorded',
  'workorder.created',
  'error',
])

function ActivityRow({
  event,
  evidence,
  onRetry,
  stage,
}: {
  event: StreamEvent
  evidence: Evidence[]
  onRetry?: () => void
  stage: Stage | null
}) {
  const { focusEvidence } = useEvidenceFocus()
  const time = <span className="ts mono">{clock(event.ts)}</span>
  switch (event.type) {
    case 'stage.changed':
      return (
        <div className="row row-stage">
          {time}
          <span className="stage-rule">{STAGE_LABEL[String(event.stage)] ?? String(event.stage)}</span>
          {event.decide === 'not_required' && <span className="muted"> — decision not required for a monitoring note</span>}
        </div>
      )
    case 'skill.invoked':
      return (
        <div className="row row-skill">
          {time}
          <span className="chip mono">{String(event.skill_name)}</span>
          {event.rationale ? <span className="agent-text"> {String(event.rationale)}</span> : null}
        </div>
      )
    case 'skill.completed':
      return (
        <div className={`row row-skill ${event.outcome === 'failed' ? 'row-failed' : ''}`}>
          {time}
          <span className="chip mono">{String(event.skill_name)}</span>
          <span className="muted">
            {' '}
            {event.outcome === 'failed' ? `failed — ${String(event.error ?? 'no detail')}` : `done in ${duration(Number(event.duration_ms))}`}
          </span>
        </div>
      )
    case 'analysis.caption':
      return (
        <div className="row row-video">
          {time}
          <span className="mono">{timecode(Number(event.t_start))}</span> <q>{String(event.text)}</q>
        </div>
      )
    case 'retrieval.query':
      return (
        <div className="row row-retrieval">
          {time}
          <span className="label">Retrieving</span> {event.query ? String(event.query) : <span className="muted">(query not readable)</span>}
        </div>
      )
    case 'retrieval.result': {
      const documents = (event.documents as { document_name: string }[]) ?? []
      return (
        <div className="row row-retrieval">
          {time}
          {event.error ? (
            <span className="state-alarm-text">Retrieval failed: {String(event.error)}</span>
          ) : (
            <>
              <span className="label">Returned</span>{' '}
              {documents.length ? documents.map((d) => d.document_name).join(', ') : <span className="muted">no documents</span>}
              <span className="muted"> · {Number(event.latency_ms)} ms</span>
            </>
          )}
        </div>
      )
    }
    case 'agent.token':
      return <Reasoning time={time} text={String(event.text ?? '')} />
    case 'evidence.added': {
      const row = event.evidence as Evidence
      const full = evidence.find((e) => e.id === row.id) ?? row
      return (
        <div className="row row-evidence">
          {time}
          <button type="button" className="claim agent-text" onClick={() => focusEvidence([full])}>
            {full.claim}
          </button>
          <span className="muted mono"> → {full.source_id}</span>
        </div>
      )
    }
    case 'ask.answer': {
      const row = evidence.find((e) => e.id === event.evidence_id)
      return (
        <div className="row row-ask">
          {time}
          <span className="label">You asked</span> {String(event.question)}
          <div className="agent-text answer">
            {row ? (
              <button type="button" className="claim agent-text" onClick={() => focusEvidence([row])}>
                {String(event.answer)}
              </button>
            ) : (
              String(event.answer)
            )}
          </div>
        </div>
      )
    }
    case 'archive.match':
      return (
        <div className="row row-video">
          {time}
          <span className="label">Precedent</span> {String(event.clip)} on {String(event.date)}
          <span className="muted"> · similarity {Number(event.similarity).toFixed(2)}</span>
        </div>
      )
    case 'decision.recorded':
      return (
        <div className="row row-stage">
          {time}
          <span className="label">Decision</span> {decisionWord(String(event.action))}
          {event.reason ? <span className="muted"> — {String(event.reason)}</span> : null}
        </div>
      )
    case 'workorder.created':
      return (
        <div className="row row-stage">
          {time}
          <span className="label">Work order created</span>{' '}
          <Link className="mono" href={`/work-orders/${String(event.work_order_id)}`}>
            WO-{String(event.work_order_id).slice(0, 8)}
          </Link>
        </div>
      )
    case 'error':
      return (
        <div className="row row-error" role="alert">
          {time}
          <span className="state-alarm-text">{String(event.message)}</span>
          {event.recoverable && event.stage === 'detect' && stage === 'detect' && onRetry ? (
            <button type="button" className="btn btn-small" onClick={onRetry}>
              Retry
            </button>
          ) : null}
        </div>
      )
    default:
      return null
  }
}

function Reasoning({ time, text }: { time: ReactNode; text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 180 || text.split('\n').length > 2
  return (
    <div className="row row-reasoning">
      {time}
      <div className={`agent-text reasoning ${open || !long ? 'open' : 'clamped'}`}>{text}</div>
      {long && (
        <button type="button" className="link-button" onClick={() => setOpen(!open)}>
          {open ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}

export function decisionWord(action: string) {
  return action === 'approve' ? 'Approved' : action === 'modify' ? 'Modified' : action === 'deny' ? 'Denied' : action
}
