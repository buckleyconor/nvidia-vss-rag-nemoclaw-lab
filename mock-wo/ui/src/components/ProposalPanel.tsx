import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useEvidenceFocus } from '../lib/evidenceFocus'
import { money, range } from '../lib/format'
import type { EtaInfo } from '../lib/incidentModel'
import type { Asset, Evidence, Incident, Part, Proposal, Stage } from '../lib/types'
import { DecisionPanel } from './DecisionPanel'

interface Props {
  incident: Incident
  asset: Asset | null
  proposal: Proposal | null
  evidence: Evidence[]
  stage: Stage | null
  eta: EtaInfo | null
  onChanged: () => void
}

// §8.5–§8.7 — analysis, uncertainty, parts, impact, then the decision. Colour
// --agent marks what the model asserted; identifiers, stock counts and cost
// data from the pack do not carry it (§10).
export function ProposalPanel({ incident, asset, proposal, evidence, stage, eta, onChanged }: Props) {
  const [parts, setParts] = useState<Part[]>([])
  const { focusEvidence } = useEvidenceFocus()

  useEffect(() => {
    api.parts().then(setParts).catch(() => setParts([]))
  }, [])

  const supporting = (ids: string[]) => evidence.filter((row) => ids.includes(row.id))

  return (
    <div className="proposal" data-testid="proposal">
      {!proposal ? (
        <Pending stage={stage} eta={eta} />
      ) : (
        <>
          <section>
            <h3 className="label">Root cause</h3>
            {proposal.alternate_root_cause ? (
              <div className="uncertainty">
                <button type="button" className="claim agent-text candidate" onClick={() => focusEvidence(supporting(proposal.evidence_ids))}>
                  {proposal.root_cause}
                </button>
                <button type="button" className="claim agent-text candidate" onClick={() => focusEvidence(supporting(proposal.evidence_ids))}>
                  {proposal.alternate_root_cause}
                </button>
                <div className="split mono">Confidence {proposal.confidence_split}</div>
                {proposal.discriminating_test && (
                  <div className="discriminating">
                    <span className="label">Discriminating test</span>{' '}
                    <span className="agent-text">{proposal.discriminating_test}</span>
                  </div>
                )}
              </div>
            ) : (
              <button type="button" className="claim agent-text" onClick={() => focusEvidence(supporting(proposal.evidence_ids))}>
                {proposal.root_cause}
              </button>
            )}
            <div className="muted small">
              {proposal.evidence_ids.length} supporting evidence row{proposal.evidence_ids.length === 1 ? '' : 's'} — click to show them
            </div>
          </section>

          {asset && asset.service_history.length > 0 && (
            <section>
              <h3 className="label">History</h3>
              <ul className="history">
                {asset.service_history.map((record) => (
                  <li key={`${record.date}-${record.summary}`}>
                    <span className="mono">{record.date}</span> {record.summary}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {proposal.kind === 'work_order' && (
            <section>
              <h3 className="label">Draft work order</h3>
              <div className="draft">
                <div className="agent-text">{proposal.draft.title}</div>
                <div className="muted small">
                  Priority <span className="mono">{proposal.draft.priority}</span>
                  {proposal.draft.assigned_to ? (
                    <>
                      {' '}
                      · assigned <span className="mono">{proposal.draft.assigned_to}</span>
                    </>
                  ) : null}
                </div>
              </div>
            </section>
          )}

          {proposal.line_items.some((li) => li.part_number) && (
            <section>
              <h3 className="label">Parts</h3>
              {proposal.line_items
                .filter((li) => li.part_number)
                .map((li) => {
                  const part = parts.find((p) => p.part_number === li.part_number)
                  return (
                    <div key={li.id} className="part">
                      <div>
                        <span className="mono">{li.part_number}</span> {part?.description}
                      </div>
                      {part ? (
                        <div className="stock mono">
                          <span className={part.on_hand_local === 0 ? 'state-warn-text' : ''}>local {part.on_hand_local}</span> · regional{' '}
                          {part.on_hand_regional}
                          {part.regional_site ? ` (${part.regional_site}, ${part.regional_transit_days} d)` : ''} · OEM {part.oem_lead_days} d
                        </div>
                      ) : (
                        <div className="muted small">Not in this pack's parts list</div>
                      )}
                    </div>
                  )
                })}
              {proposal.parts_constraint && <p className="agent-text constraint">{proposal.parts_constraint}</p>}
            </section>
          )}

          {(proposal.impact_if_ignored || proposal.impact_if_unnecessary) && (
            <section>
              <h3 className="label">Impact</h3>
              <dl className="impact">
                {proposal.impact_if_ignored && (
                  <>
                    <dt>Cost of not acting</dt>
                    <dd className="mono">{range(proposal.impact_if_ignored.low, proposal.impact_if_ignored.high, proposal.impact_if_ignored.unit)}</dd>
                  </>
                )}
                {proposal.impact_if_unnecessary && (
                  <>
                    <dt>Cost of acting unnecessarily</dt>
                    <dd className="mono">
                      {range(proposal.impact_if_unnecessary.low, proposal.impact_if_unnecessary.high, proposal.impact_if_unnecessary.unit)}
                    </dd>
                  </>
                )}
              </dl>
              {incident.definition && (
                <div className="muted small">
                  Agent estimate. Pack cost data: downtime {money(incident.definition.downtime_cost_per_hour, incident.definition.currency)}/h,
                  callout {money(incident.definition.callout_cost, incident.definition.currency)}.
                </div>
              )}
            </section>
          )}

          {proposal.state === 'pending' && <AskFootage incidentId={incident.id} />}
          <DecisionPanel key={`${proposal.id}-${proposal.state}`} proposal={proposal} onDecided={onChanged} />
        </>
      )}
    </div>
  )
}

function Pending({ stage, eta }: { stage: Stage | null; eta: EtaInfo | null }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  if (stage === 'closed') return <div className="muted">This incident closed without a proposal.</div>
  const elapsed = eta ? Math.max(0, Math.round((now - new Date(eta.since).getTime()) / 1000)) : 0
  return (
    <div className="pending">
      <p className="muted">The agent's proposal appears here when it is ready.</p>
      {eta && (
        <p className="eta" data-testid="eta">
          {eta.chunksTotal ? (
            <>
              Analysed {eta.chunksDone} of {eta.chunksTotal} chunks.
            </>
          ) : (
            <>
              Typically about {Math.round(eta.seconds / 60)} min for this clip. VSS does not report chunk progress here, so this is the pack's
              expected duration, not a measurement.
            </>
          )}{' '}
          <span className="mono">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')} elapsed</span>
        </p>
      )}
    </div>
  )
}

function AskFootage({ incidentId }: { incidentId: string }) {
  const [question, setQuestion] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <form
      className="ask"
      onSubmit={async (event) => {
        event.preventDefault()
        if (question.trim().length < 3) return
        setBusy(true)
        setStatus(null)
        try {
          await api.ask(incidentId, question.trim())
          setStatus('Asked. The answer appears in the activity stream as new evidence.')
          setQuestion('')
        } catch (err) {
          setStatus(err instanceof ApiError ? String(err.detail) : String(err))
        } finally {
          setBusy(false)
        }
      }}
    >
      <label className="label" htmlFor="ask-input">
        Ask a question about this clip before deciding
      </label>
      <div className="ask-row">
        <input
          id="ask-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Is there fluid pooling under the housing?"
          maxLength={500}
        />
        <button type="submit" className="btn" disabled={busy || question.trim().length < 3}>
          Ask
        </button>
      </div>
      {status && <div className="muted small">{status}</div>}
    </form>
  )
}
