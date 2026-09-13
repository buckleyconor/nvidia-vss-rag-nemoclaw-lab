import { event, ragEvidence } from '../test/helpers'
import { applyEvents, emptyModel, railStates, waitingOn } from './incidentModel'

describe('applyEvents', () => {
  it('folds stages, skills, evidence and proposal in seq order', () => {
    const { model, gap } = applyEvents(emptyModel(), [
      event(3, 'skill.invoked', { skill_name: 'vss-ask-video', rationale: 'Need a closer look' }),
      event(1, 'stage.changed', { stage: 'detect', previous: null }),
      event(2, 'stage.changed', { stage: 'gather', previous: 'detect' }),
      event(4, 'skill.completed', { skill_name: 'vss-ask-video', duration_ms: 1500, outcome: 'ok' }),
      event(5, 'evidence.added', { evidence: ragEvidence }),
      event(6, 'analysis.progress', { eta_seconds: 240, basis: 'pack_expected_duration', chunks_done: null, chunks_total: null }),
    ])
    expect(gap).toBe(false)
    expect(model.lastSeq).toBe(6)
    expect(model.stage).toBe('gather')
    expect(model.skills).toEqual([
      expect.objectContaining({ name: 'vss-ask-video', state: 'done', durationMs: 1500, rationale: 'Need a closer look' }),
    ])
    expect(model.evidence.map((e) => e.id)).toEqual(['ev-rag'])
    expect(model.eta).toMatchObject({ seconds: 240, basis: 'pack_expected_duration' })
  })

  it('ignores duplicates and reports a gap instead of skipping ahead', () => {
    const first = applyEvents(emptyModel(), [event(1, 'stage.changed', { stage: 'detect', previous: null })]).model
    expect(applyEvents(first, [event(1, 'stage.changed', { stage: 'detect', previous: null })]).model).toBe(first)
    const skipped = applyEvents(first, [event(3, 'stage.changed', { stage: 'propose', previous: 'gather' })])
    expect(skipped.gap).toBe(true)
    expect(skipped.model.stage).toBe('detect')
  })

  it('marks failed skills and records errors and the work order', () => {
    const { model } = applyEvents(emptyModel(), [
      event(1, 'skill.invoked', { skill_name: 'vss-generate-video-report-rag' }),
      event(2, 'skill.completed', { skill_name: 'vss-generate-video-report-rag', duration_ms: 10, outcome: 'failed', error: 'timeout' }),
      event(3, 'error', { stage: 'detect', message: 'VST unreachable', recoverable: true }),
      event(4, 'workorder.created', { work_order_id: 'wo-1', notification_id: 'n-1' }),
    ])
    expect(model.skills[0]).toMatchObject({ state: 'failed', error: 'timeout' })
    expect(model.errors).toHaveLength(1)
    expect(model.workOrderId).toBe('wo-1')
  })
})

describe('railStates', () => {
  it('lights monitor only before an incident exists', () => {
    expect(railStates({ stage: null, previousStage: null, decideNotRequired: false })).toMatchObject({
      monitor: 'current',
      detect: 'pending',
    })
  })

  it('tracks the current stage', () => {
    expect(railStates({ stage: 'gather', previousStage: 'detect', decideNotRequired: false })).toMatchObject({
      monitor: 'done',
      detect: 'done',
      gather: 'current',
      propose: 'pending',
      act: 'pending',
    })
  })

  it('shows decide as not required for an auto-filed monitoring note', () => {
    expect(railStates({ stage: 'act', previousStage: 'propose', decideNotRequired: true })).toMatchObject({
      propose: 'done',
      decide: 'not_required',
      act: 'done',
    })
  })

  it('shows act as not taken after a denial', () => {
    expect(railStates({ stage: 'closed', previousStage: 'decide', decideNotRequired: false })).toMatchObject({
      decide: 'done',
      act: 'not_taken',
    })
  })

  it('shows everything done when an acted incident closes', () => {
    const states = railStates({ stage: 'closed', previousStage: 'act', decideNotRequired: false })
    expect(Object.values(states).every((s) => s === 'done')).toBe(true)
  })

  it('marks unreached stages not taken when closed early', () => {
    expect(railStates({ stage: 'closed', previousStage: 'gather', decideNotRequired: false })).toMatchObject({
      gather: 'done',
      propose: 'not_taken',
      act: 'not_taken',
    })
  })
})

it('says what it is waiting on', () => {
  expect(waitingOn('gather')).toContain('VSS')
  expect(waitingOn('decide')).toBeNull()
})
