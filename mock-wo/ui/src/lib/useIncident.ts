import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { applyEvents, emptyModel, type IncidentModel } from './incidentModel'
import { useStream } from './stream'
import type { Incident, Proposal } from './types'

export interface IncidentState {
  incident: Incident | null
  model: IncidentModel
  proposal: Proposal | null
  error: string | null
  refreshProposal: () => Promise<void>
}

// Loads an incident, folds its event log, and keeps it live. A seq gap or a
// reconnect re-fetches from the last seq seen; proposal and decision events
// re-read the proposal so the panel always shows the stored record.
export function useIncident(incidentId: string): IncidentState {
  const { subscribe, onReconnect } = useStream()
  const [incident, setIncident] = useState<Incident | null>(null)
  const [model, setModel] = useState<IncidentModel>(emptyModel)
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [error, setError] = useState<string | null>(null)
  const modelRef = useRef(model)
  modelRef.current = model
  const fetching = useRef(false)

  const refreshProposal = useCallback(async () => {
    try {
      const fresh = await api.incident(incidentId)
      setIncident(fresh)
      if (fresh.proposal_id) setProposal(await api.proposal(fresh.proposal_id))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [incidentId])

  const backfill = useCallback(async () => {
    if (fetching.current) return
    fetching.current = true
    try {
      const events = await api.events(incidentId, modelRef.current.lastSeq)
      const { model: next } = applyEvents(modelRef.current, events)
      modelRef.current = next
      setModel(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      fetching.current = false
    }
  }, [incidentId])

  useEffect(() => {
    let cancelled = false
    modelRef.current = emptyModel()
    setModel(modelRef.current)
    setProposal(null)
    setError(null)
    api
      .incident(incidentId)
      .then(async (loaded) => {
        if (cancelled) return
        setIncident(loaded)
        await backfill()
        if (loaded.proposal_id && !cancelled) setProposal(await api.proposal(loaded.proposal_id))
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [incidentId, backfill])

  useEffect(
    () =>
      subscribe((event) => {
        if (event.incident_id !== incidentId) return
        const { model: next, gap } = applyEvents(modelRef.current, [event])
        if (gap) {
          void backfill()
          return
        }
        if (next !== modelRef.current) {
          modelRef.current = next
          setModel(next)
        }
        if (['proposal.ready', 'decision.recorded', 'workorder.created', 'stage.changed'].includes(event.type)) {
          void refreshProposal()
        }
      }),
    [subscribe, incidentId, backfill, refreshProposal],
  )

  useEffect(() => onReconnect(() => void backfill()), [onReconnect, backfill])

  return { incident, model, proposal: proposal ?? model.proposal, error, refreshProposal }
}
