import { useEffect, useState } from 'react'
import { decisionWord } from '../components/ActivityStream'
import { api, ApiError } from '../lib/api'
import { dateTime, shortId } from '../lib/format'
import { navigate, Link } from '../lib/router'
import type { AuditRow, Note, NotificationItem, PackSummary, WorkOrder } from '../lib/types'

function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    loader()
      .then((value) => !cancelled && setData(value))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error }
}

// §7.1 — one card per installed pack.
export function PackSelector() {
  const { data, error } = useLoad(api.packs)
  const [message, setMessage] = useState<string | null>(null)
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading packs…</div>
  const activate = async (pack: PackSummary) => {
    try {
      await api.activatePack(pack.pack_id)
      navigate('/fleet')
    } catch (err) {
      setMessage(err instanceof ApiError ? String(err.detail) : String(err))
    }
  }
  return (
    <div className="page">
      <h1>Choose a vertical</h1>
      {message && <p className="notice">{message}</p>}
      <ul className="pack-grid">
        {data.map((pack) => (
          <li key={pack.pack_id} className="card">
            <h2>{pack.display_name}</h2>
            <div className="muted">{pack.asset_class}</div>
            <p>{pack.scenario}</p>
            <button type="button" className="btn btn-primary" onClick={() => activate(pack)}>
              {pack.active ? 'Continue' : 'Activate'}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

// §8.8 — one row per decision; rows expand to the full incident record.
export function AuditView() {
  const { data, error } = useLoad(api.audit)
  const [open, setOpen] = useState<string | null>(null)
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading audit trail…</div>
  return (
    <div className="page">
      <h1>Audit trail</h1>
      <p className="muted">Kept across demo resets and restarts.</p>
      {data.length === 0 ? (
        <p className="muted">No decisions yet. Inject a fault and decide on the proposal to create the first entry.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Kind</th>
              <th>Asset</th>
              <th>Proposed</th>
              <th>Decision</th>
              <th>Reason</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <AuditLine key={row.id} row={row} open={open === row.id} onToggle={() => setOpen(open === row.id ? null : row.id)} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function AuditLine({ row, open, onToggle }: { row: AuditRow; open: boolean; onToggle: () => void }) {
  const record = row.record
  const proposal = record.proposal
  const decision = record.decision
  return (
    <>
      <tr className={record.incident ? 'clickable' : undefined} onClick={record.incident ? onToggle : undefined}>
        <td className="mono">{dateTime(row.ts)}</td>
        <td>{row.kind.replace('_', ' ')}</td>
        <td className="mono">{row.asset_id ?? '—'}</td>
        <td>{proposal ? (proposal.kind === 'work_order' ? proposal.draft.title : 'Monitoring note') : record.title ?? '—'}</td>
        <td>{decision ? decisionWord(decision.action) : row.kind === 'auto_filed' ? 'Auto-filed' : '—'}</td>
        <td>{decision?.reason ?? (row.kind === 'reset' ? `${record.incidents_cleared ?? 0} incident(s) cleared` : '—')}</td>
        <td>{record.evidence ? record.evidence.length : '—'}</td>
      </tr>
      {open && (
        <tr className="expanded">
          <td colSpan={7}>
            {proposal && (
              <div>
                <span className="label">Root cause</span> <span className="agent-text">{proposal.root_cause}</span>
              </div>
            )}
            {decision?.modifications && (
              <div>
                <span className="label">Modifications</span> <code className="mono">{JSON.stringify(decision.modifications)}</code>
              </div>
            )}
            {record.asks && record.asks.length > 0 && (
              <div>
                <span className="label">Operator questions</span>
                <ul>
                  {record.asks.map((ask) => (
                    <li key={ask.id}>
                      {ask.question} — <span className="agent-text">{ask.answer ?? ask.error}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {record.evidence && (
              <ul className="evidence-list">
                {record.evidence.map((e) => (
                  <li key={e.id}>
                    <span className="mono">{e.source_type}</span> <span className="agent-text">{e.claim}</span>{' '}
                    <span className="muted mono">{e.source_id}</span>
                  </li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export function WorkOrdersView() {
  const { data, error } = useLoad(api.workOrders)
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading work orders…</div>
  return (
    <div className="page">
      <h1>Work orders</h1>
      {data.length === 0 ? (
        <p className="muted">No work orders yet. A work order exists only after an operator approves a proposal.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Equipment</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {data.map((wo) => (
              <tr key={wo.id}>
                <td className="mono">
                  <Link href={`/work-orders/${wo.id}`}>WO-{shortId(wo.id)}</Link>
                </td>
                <td>{wo.title}</td>
                <td className="mono">{wo.equipment}</td>
                <td>{wo.priority}</td>
                <td>{wo.status}</td>
                <td className="mono">{dateTime(wo.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function WorkOrderDetail({ id }: { id: string }) {
  const { data, error } = useLoad<WorkOrder>(() => api.workOrder(id), [id])
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading work order…</div>
  const grouped = data.citations.reduce<Record<string, WorkOrder['citations']>>((acc, c) => {
    ;(acc[c.source_type] ||= []).push(c)
    return acc
  }, {})
  return (
    <div className="page">
      <Link href="/work-orders">All work orders</Link>
      <h1>{data.title}</h1>
      <dl className="facts">
        <dt>ID</dt>
        <dd className="mono">WO-{data.id}</dd>
        <dt>Equipment</dt>
        <dd className="mono">{data.equipment}</dd>
        <dt>Priority</dt>
        <dd>{data.priority}</dd>
        <dt>Status</dt>
        <dd>{data.status}</dd>
        <dt>Assigned</dt>
        <dd>{data.assigned_to ?? 'Unassigned'}</dd>
        <dt>Anomaly</dt>
        <dd className="mono">{data.anomaly_ref}</dd>
      </dl>
      <p className="prewrap">{data.description}</p>
      <h2>Evidence</h2>
      {Object.entries(grouped).map(([source, citations]) => (
        <section key={source}>
          <h3 className="label">{source}</h3>
          <ul className="evidence-list">
            {citations.map((c, i) => (
              <li key={i}>
                <span className="mono">{c.source_id}</span> — {c.quote}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

export function NotesView() {
  const { data, error } = useLoad<Note[]>(api.notes)
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading notes…</div>
  return (
    <div className="page">
      <h1>Monitoring notes</h1>
      {data.length === 0 ? (
        <p className="muted">No monitoring notes yet. Notes are filed without approval — only work orders are gated.</p>
      ) : (
        <ul className="evidence-list">
          {data.map((note) => (
            <li key={note.id}>
              <span className="mono">{dateTime(note.created_at)}</span> <span className="mono">{note.equipment}</span> — {note.description}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function NotificationsView() {
  const { data, error } = useLoad<NotificationItem[]>(api.notifications)
  if (error) return <div className="page state-alarm-text">{error}</div>
  if (!data) return <div className="page muted">Loading notifications…</div>
  return (
    <div className="page">
      <h1>Notifications</h1>
      {data.length === 0 ? (
        <p className="muted">No notifications. The maintenance team is notified when a work order is created.</p>
      ) : (
        <ul className="evidence-list">
          {data.map((n) => (
            <li key={n.id}>
              <Link href={`/work-orders/${n.work_order_id}`}>{n.message}</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
