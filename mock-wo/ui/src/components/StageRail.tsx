import { railStates, STAGE_LABEL, type IncidentModel, type RailState } from '../lib/incidentModel'
import { RAIL_STAGES } from '../lib/types'

const GLYPH: Record<RailState, string> = {
  done: '●',
  current: '◐',
  pending: '○',
  not_required: '◌',
  not_taken: '◌',
}

const NOTE: Partial<Record<RailState, string>> = {
  not_required: 'not required',
  not_taken: 'not taken',
}

// The single source of progress truth (§7.3): lights on state-machine
// transitions only, never on UI guesswork.
export function StageRail({ model }: { model: Pick<IncidentModel, 'stage' | 'previousStage' | 'decideNotRequired'> }) {
  const states = railStates(model)
  return (
    <ol className="rail" aria-label="Incident stage">
      {RAIL_STAGES.map((stage, index) => {
        const state = states[stage]
        return (
          <li key={stage} className={`rail-step rail-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            {index > 0 && <span className="rail-line" aria-hidden />}
            <span className="rail-glyph" aria-hidden>
              {GLYPH[state]}
            </span>
            <span className="rail-label">{STAGE_LABEL[stage]}</span>
            {NOTE[state] && <span className="rail-note">{NOTE[state]}</span>}
            <span className="sr-only">{` (${state.replace('_', ' ')})`}</span>
          </li>
        )
      })}
    </ol>
  )
}
