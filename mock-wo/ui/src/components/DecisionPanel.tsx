import { useState } from 'react'
import { api, ApiError, type DecisionBody } from '../lib/api'
import { Link } from '../lib/router'
import type { Proposal, WorkOrderDraft } from '../lib/types'
import { decisionWord } from './ActivityStream'

const COMMON_REASONS = ['Already addressed', 'Wrong root cause', 'Not urgent', 'Insufficient evidence']
const PRIORITIES: WorkOrderDraft['priority'][] = ['low', 'medium', 'high', 'critical']

type Mode = 'idle' | 'modify' | 'deny'

// §8.6 — Approve / Modify / Deny, always visible. Buttons name their outcome
// and keep the name. The work order is created server-side; this panel only
// records the operator's decision (ADR-V04).
export function DecisionPanel({ proposal, onDecided }: { proposal: Proposal; onDecided: () => void }) {
  const [mode, setMode] = useState<Mode>('idle')
  const [selected, setSelected] = useState<string[]>(proposal.line_items.map((li) => li.id))
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [edits, setEdits] = useState({
    title: proposal.draft.title,
    description: proposal.draft.description,
    priority: proposal.draft.priority,
    assigned_to: proposal.draft.assigned_to ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (proposal.state === 'auto_filed') {
    return (
      <div className="decision decided">
        <strong>Filed as a monitoring note.</strong> No approval required — only work orders are gated.
      </div>
    )
  }
  if (proposal.state !== 'pending') {
    const decision = proposal.decision
    return (
      <div className="decision decided" data-testid="decided">
        <strong>{decision ? decisionWord(decision.action) : proposal.state}</strong>
        {decision?.reason ? <span className="muted"> — {decision.reason}</span> : null}
        {decision?.work_order_id ? (
          <div>
            Work order{' '}
            <Link className="mono" href={`/work-orders/${decision.work_order_id}`}>
              WO-{decision.work_order_id.slice(0, 8)}
            </Link>{' '}
            created.
          </div>
        ) : null}
      </div>
    )
  }

  const hasItems = proposal.line_items.length > 0
  const submit = async (body: DecisionBody) => {
    setBusy(true)
    setError(null)
    try {
      await api.decide(proposal.id, body)
      onDecided()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('This proposal has already been decided.')
        onDecided()
      } else {
        setError(err instanceof ApiError ? describe(err.detail) : String(err))
      }
    } finally {
      setBusy(false)
    }
  }

  const modifications = () => {
    const out: Record<string, unknown> = {}
    if (edits.title !== proposal.draft.title) out.title = edits.title
    if (edits.description !== proposal.draft.description) out.description = edits.description
    if (edits.priority !== proposal.draft.priority) out.priority = edits.priority
    if ((edits.assigned_to || null) !== (proposal.draft.assigned_to ?? null)) out.assigned_to = edits.assigned_to || null
    return out
  }

  return (
    <div className="decision" data-testid="decision">
      {hasItems && (
        <fieldset className="line-items">
          <legend className="label">Actions</legend>
          {proposal.line_items.map((item) => (
            <label key={item.id} className="line-item">
              <input
                type="checkbox"
                checked={selected.includes(item.id)}
                onChange={(event) =>
                  setSelected(event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))
                }
              />
              <span className="agent-text">{item.action}</span>
              {item.detail ? <span className="muted"> — {item.detail}</span> : null}
            </label>
          ))}
          {selected.length < proposal.line_items.length && (
            <button type="button" className="link-button" onClick={() => setSelected(proposal.line_items.map((li) => li.id))}>
              Select all
            </button>
          )}
        </fieldset>
      )}

      {mode === 'modify' && (
        <div className="decision-form">
          <label>
            Title
            <input value={edits.title} onChange={(e) => setEdits({ ...edits, title: e.target.value })} />
          </label>
          <label>
            Priority
            <select value={edits.priority} onChange={(e) => setEdits({ ...edits, priority: e.target.value as WorkOrderDraft['priority'] })}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label>
            Assigned to
            <input value={edits.assigned_to} onChange={(e) => setEdits({ ...edits, assigned_to: e.target.value })} />
          </label>
          <label>
            Description
            <textarea rows={4} value={edits.description} onChange={(e) => setEdits({ ...edits, description: e.target.value })} />
          </label>
          <label>
            What changed and why (required)
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Scheduled for the planned window" />
          </label>
        </div>
      )}

      {mode === 'deny' && (
        <div className="decision-form">
          <div className="reason-chips">
            {COMMON_REASONS.map((r) => (
              <button key={r} type="button" className={`chip ${reason === r ? 'chip-on' : ''}`} onClick={() => setReason(r)}>
                {r}
              </button>
            ))}
          </div>
          <label>
            Reason (required)
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>
      )}

      {error && (
        <div className="state-alarm-text" role="alert">
          {error}
        </div>
      )}

      <div className="decision-buttons">
        {mode === 'idle' && (
          <>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || (hasItems && selected.length === 0)}
              onClick={() => submit({ action: 'approve', line_items_approved: hasItems ? selected : undefined })}
            >
              Approve
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setMode('modify')}>
              Modify
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setMode('deny')}>
              Deny
            </button>
          </>
        )}
        {mode === 'modify' && (
          <>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !note.trim() || Object.keys(modifications()).length === 0 || (hasItems && selected.length === 0)}
              onClick={() =>
                submit({
                  action: 'modify',
                  reason: note.trim(),
                  modifications: modifications(),
                  line_items_approved: hasItems ? selected : undefined,
                })
              }
            >
              Approve with changes
            </button>
            <button type="button" className="btn" onClick={() => setMode('idle')}>
              Cancel
            </button>
          </>
        )}
        {mode === 'deny' && (
          <>
            <button type="button" className="btn btn-danger" disabled={busy || !reason.trim()} onClick={() => submit({ action: 'deny', reason: reason.trim() })}>
              Deny
            </button>
            <button type="button" className="btn" onClick={() => setMode('idle')}>
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : String(d))).join('; ')
  return 'The decision could not be recorded.'
}
