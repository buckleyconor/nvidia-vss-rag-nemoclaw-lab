import { useEffect, useState } from 'react'
import { ActivityStream } from '../components/ActivityStream'
import { DocumentViewer } from '../components/DocumentViewer'
import { ProposalPanel } from '../components/ProposalPanel'
import { SkillTrace } from '../components/SkillTrace'
import { StageRail } from '../components/StageRail'
import { VideoPlayer } from '../components/VideoPlayer'
import { api, clipUrl } from '../lib/api'
import { EvidenceFocusProvider } from '../lib/evidenceFocus'
import { Link } from '../lib/router'
import { useIncident } from '../lib/useIncident'
import type { Asset } from '../lib/types'

// §7.3 — three fixed columns: evidence, agent activity, proposal.
export function IncidentWorkspace({ incidentId }: { incidentId: string }) {
  const { incident, model, proposal, error, refreshProposal } = useIncident(incidentId)
  const [asset, setAsset] = useState<Asset | null>(null)

  useEffect(() => {
    if (!incident) return
    api
      .fleet()
      .then((fleet) => setAsset(fleet.assets.find((a) => a.asset_id === incident.asset_id) ?? null))
      .catch(() => setAsset(null))
  }, [incident?.asset_id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !incident) {
    return (
      <div className="page">
        <p className="state-alarm-text">This incident could not be loaded: {error}</p>
        <Link href="/fleet">Back to fleet</Link>
      </div>
    )
  }
  if (!incident) return <div className="page muted">Loading incident…</div>

  const stage = model.stage ?? incident.stage
  return (
    <EvidenceFocusProvider>
      <div className="workspace">
        <header className="workspace-head">
          <div>
            <span className="mono">{incident.asset_id}</span> · {asset?.display_name ?? incident.definition?.title}
            {asset?.location ? <span className="muted"> · {asset.location}</span> : null}
            {incident.definition ? <div className="muted small">{incident.definition.title}</div> : null}
          </div>
          <Link className="btn" href="/fleet">
            Back to fleet
          </Link>
        </header>
        <StageRail model={{ stage, previousStage: model.previousStage, decideNotRequired: model.decideNotRequired }} />
        <SkillTrace skills={model.skills} />
        <div className="columns">
          <section className="column" aria-label="Evidence">
            <h2 className="column-title">Evidence</h2>
            <VideoPlayer src={clipUrl(incident.pack_id, incident.clip)} evidence={model.evidence} />
            <DocumentViewer packId={incident.pack_id} evidence={model.evidence} />
          </section>
          <section className="column" aria-label="Agent activity">
            <h2 className="column-title">Agent activity</h2>
            <ActivityStream
              events={model.events}
              evidence={model.evidence}
              stage={stage}
              lastEventAt={model.lastEventAt}
              onRetry={() => void api.retry(incident.id)}
            />
          </section>
          <section className="column" aria-label="Proposal">
            <h2 className="column-title">Proposal</h2>
            <ProposalPanel
              incident={incident}
              asset={asset}
              proposal={proposal}
              evidence={model.evidence}
              stage={stage}
              eta={model.eta}
              onChanged={() => void refreshProposal()}
            />
          </section>
        </div>
      </div>
    </EvidenceFocusProvider>
  )
}
