import { useEffect, useRef, useState } from 'react'
import { useEvidenceFocus } from '../lib/evidenceFocus'
import { timecode } from '../lib/format'
import type { Evidence } from '../lib/types'

const FALLBACK_DURATION = 90

// §8.1 — standard controls plus a marker track of `vss` evidence. Fully
// usable during analysis. Linking (§8.3) seeks to t_start and pauses.
export function VideoPlayer({ src, evidence }: { src: string; evidence: Evidence[] }) {
  const video = useRef<HTMLVideoElement>(null)
  const pane = useRef<HTMLDivElement>(null)
  const { target, focusEvidence } = useEvidenceFocus()
  const [duration, setDuration] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const [linked, setLinked] = useState(false)

  const markers = evidence.filter((row) => row.source_type === 'vss' && row.t_start !== null)
  const span = duration ?? Math.max(FALLBACK_DURATION, ...markers.map((m) => m.t_end ?? m.t_start ?? 0))

  useEffect(() => {
    if (!target.video || target.nonce === 0) return
    const element = video.current
    if (element) {
      try {
        element.currentTime = target.video.t_start ?? 0
      } catch {
        // Seeking a clip that failed to load is a no-op.
      }
      element.pause()
    }
    setLinked(true)
    const timer = window.setTimeout(() => setLinked(false), 900)
    return () => window.clearTimeout(timer)
  }, [target])

  return (
    <div ref={pane} className={`pane video-pane ${linked ? 'linked' : ''}`} data-testid="video-pane">
      <div className="pane-well">
        {failed ? (
          <div className="clip-unavailable" role="status">
            This clip could not be played here. The committed fixtures are provisional placeholders (ADR-004); the
            curated clip is swapped in at environment prep.
          </div>
        ) : null}
        <video
          ref={video}
          src={src}
          controls
          preload="metadata"
          hidden={failed}
          onLoadedMetadata={(event) => {
            const value = event.currentTarget.duration
            if (Number.isFinite(value) && value > 0) setDuration(value)
          }}
          onError={() => setFailed(true)}
          data-testid="clip"
        />
      </div>
      <div className="marker-track" aria-label="Evidence markers">
        {markers.map((row) => (
          <button
            key={row.id}
            type="button"
            className="marker"
            style={{ left: `${Math.min(100, ((row.t_start ?? 0) / span) * 100)}%` }}
            title={`${timecode(row.t_start)} — ${row.claim}`}
            aria-label={`Evidence at ${timecode(row.t_start)}: ${row.claim}`}
            onClick={() => focusEvidence([row])}
          />
        ))}
      </div>
      <div className="pane-caption muted">
        {markers.length ? `${markers.length} video evidence marker${markers.length === 1 ? '' : 's'}` : 'Evidence markers appear as the agent cites the video'}
      </div>
    </div>
  )
}
