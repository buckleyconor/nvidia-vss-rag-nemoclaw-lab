import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { navigate, Link } from '../lib/router'
import { useStreamEvents } from '../lib/stream'
import type { Fleet, PackSummary } from '../lib/types'

const STATUS_LABEL = { normal: 'Normal', alarm: 'Fault', attention: 'Action taken' } as const

// §7.2 — landing and resting state. Status is the only coloured element on a
// tile, and it is always paired with a text label.
export function FleetView() {
  const [fleet, setFleet] = useState<Fleet | null>(null)
  const [pack, setPack] = useState<PackSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [injecting, setInjecting] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([api.fleet(), api.packs()])
      .then(([loaded, packs]) => {
        setFleet(loaded)
        setPack(packs.find((p) => p.active) ?? null)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(load, [load])
  useStreamEvents((event) => {
    if (['stage.changed', 'demo.reset', 'pack.activated'].includes(event.type)) load()
  })

  const inject = async (assetId: string, incidentId: string) => {
    setInjecting(true)
    setMessage(null)
    try {
      const incident = await api.inject(assetId, incidentId)
      navigate(`/incidents/${incident.id}`)
    } catch (err) {
      setMessage(err instanceof ApiError ? String(err.detail) : String(err))
    } finally {
      setInjecting(false)
    }
  }

  const reset = async () => {
    setConfirmReset(false)
    const result = await api.reset()
    setMessage(`Demo reset — ${result.incidents_cleared} incident(s) cleared. The audit trail is kept.`)
    load()
  }

  if (error) return <div className="page state-alarm-text">Fleet unavailable: {error}</div>
  if (!fleet) return <div className="page muted">Loading fleet…</div>

  const injectable = fleet.assets.flatMap((asset) => asset.injectable.map((incidentId) => ({ asset, incidentId })))
  const active = fleet.assets.find((asset) => asset.incident && asset.status !== 'normal')
  const allNormal = fleet.assets.every((asset) => asset.status === 'normal')

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{pack?.display_name ?? fleet.pack_id}</h1>
          {pack?.scenario && <p className="muted">{pack.scenario}</p>}
        </div>
        <div className="controls">
          <details className="inject">
            <summary className="btn btn-primary" aria-disabled={injecting || Boolean(active && active.status === 'alarm')}>
              Inject fault
            </summary>
            <div className="menu">
              {injectable.length === 0 && <div className="muted">This pack defines no incidents.</div>}
              {injectable.map(({ asset, incidentId }) => (
                <button
                  key={`${asset.asset_id}-${incidentId}`}
                  type="button"
                  className="menu-item"
                  disabled={injecting || Boolean(active && active.status === 'alarm')}
                  onClick={() => inject(asset.asset_id, incidentId)}
                >
                  <span className="mono">{asset.asset_id}</span> {incidentId}
                </button>
              ))}
            </div>
          </details>
          {confirmReset ? (
            <span className="confirm">
              Clear incidents? The audit trail is kept.{' '}
              <button type="button" className="btn btn-danger" onClick={reset}>
                Reset demo
              </button>{' '}
              <button type="button" className="btn" onClick={() => setConfirmReset(false)}>
                Cancel
              </button>
            </span>
          ) : (
            <button type="button" className="btn" onClick={() => setConfirmReset(true)}>
              Reset demo
            </button>
          )}
        </div>
      </div>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {allNormal ? (
        <p className="muted">All assets nominal. Inject a fault to begin.</p>
      ) : active ? (
        <p>
          <Link href={`/incidents/${active.incident}`}>Open the incident on {active.asset_id}</Link>
        </p>
      ) : null}
      <ul className="fleet-grid">
        {fleet.assets.map((asset) => (
          <li key={asset.asset_id} className={`tile tile-${asset.status}`} data-testid={`tile-${asset.asset_id}`}>
            <div className="tile-thumb" aria-hidden>
              {asset.asset_id.slice(0, 1)}
            </div>
            <div className="tile-body">
              <div className="tile-name">{asset.display_name}</div>
              <div className="muted small">{asset.make_model}</div>
              <div className="muted small">{asset.location}</div>
            </div>
            <div className={`status-band status-${asset.status}`}>
              <span className={`health-dot dot-${asset.status}`} aria-hidden title={STATUS_LABEL[asset.status]} />
              <span>{STATUS_LABEL[asset.status]}</span>
              {asset.incident && asset.status !== 'normal' && (
                <Link href={`/incidents/${asset.incident}`} className="small">
                  Open
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
