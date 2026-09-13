import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from '../App'
import { matchRoute, navigate } from '../lib/router'
import { event, FakeEventSource, mockFetch, proposal, ragEvidence, withStream } from '../test/helpers'
import { FleetView } from './FleetView'
import { IncidentWorkspace } from './IncidentWorkspace'

const FLEET = {
  pack_id: 'manufacturing-motor-drive',
  assets: [
    {
      asset_id: 'M-3021',
      display_name: 'Motor drive M-3021',
      make_model: 'ABB M3BP 200',
      commissioned: '2019-04',
      location: 'Line 3, Hall B',
      baseline_clips: [],
      thumbnail: null,
      service_history: [{ date: '2025-07-14', summary: 'Bearing inspected', technician: 'J. Moore' }],
      status: 'normal',
      incident: null,
      injectable: ['M3021-BEARING-THERMAL'],
    },
  ],
}
const PACKS = [
  {
    pack_id: 'manufacturing-motor-drive',
    display_name: 'Manufacturing — Motor Drive',
    asset_class: 'Line motor drives',
    scenario: 'A bearing runs hot.',
    knowledge_collection: 'demo_corpus',
    asset_count: 1,
    incident_count: 1,
    skills: [],
    active: true,
  },
]
const INCIDENT = {
  id: 'inc-1',
  pack_id: 'manufacturing-motor-drive',
  asset_id: 'M-3021',
  pack_incident_id: 'M3021-BEARING-THERMAL',
  clip: 'clip-anomaly-01.mp4',
  stage: 'gather',
  opened_at: '2026-09-13T12:00:00Z',
  closed_at: null,
  definition: {
    incident_id: 'M3021-BEARING-THERMAL',
    asset_id: 'M-3021',
    title: 'Drive-end bearing thermal anomaly',
    clip: 'clip-anomaly-01.mp4',
    outcome_class: 'work_order',
    downtime_cost_per_hour: 4200,
    callout_cost: 850,
    currency: 'EUR',
    expected_analysis_seconds: 240,
  },
  proposal_id: null,
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  window.history.replaceState(null, '', '/')
})

describe('router', () => {
  it('matches every screen', () => {
    expect(matchRoute('/')).toEqual({ name: 'fleet' })
    expect(matchRoute('/incidents/abc')).toEqual({ name: 'incident', id: 'abc' })
    expect(matchRoute('/work-orders/x')).toEqual({ name: 'work-order', id: 'x' })
    expect(matchRoute('/audit/extra')).toEqual({ name: 'not-found' })
    expect(matchRoute('/incidents')).toEqual({ name: 'not-found' })
    expect(matchRoute('/nope')).toEqual({ name: 'not-found' })
  })
})

describe('FleetView (§7.2)', () => {
  it('shows the resting state and injects a fault into the workspace', async () => {
    const calls = mockFetch({ '/api/v1/fleet': FLEET, '/api/v1/packs': PACKS, '/api/v1/incidents/inject': INCIDENT })
    render(withStream(<FleetView />))
    expect(await screen.findByText('All assets nominal. Inject a fault to begin.')).toBeInTheDocument()
    expect(screen.getByTestId('tile-M-3021')).toHaveTextContent('Normal')
    // The health dot mirrors the band label: nominal assets show green.
    expect(screen.getByTestId('tile-M-3021')).toContainElement(document.querySelector('.dot-normal')!)
    await userEvent.click(screen.getByText('Inject fault'))
    await userEvent.click(screen.getByRole('button', { name: /M3021-BEARING-THERMAL/ }))
    await waitFor(() => expect(window.location.pathname).toBe('/incidents/inc-1'))
    const injected = calls.find((c) => c.url === '/api/v1/incidents/inject')!
    expect(JSON.parse(String(injected.init?.body))).toEqual({ asset_id: 'M-3021', incident_id: 'M3021-BEARING-THERMAL' })
  })

  it('confirms before resetting and says the audit trail is kept', async () => {
    const calls = mockFetch({ '/api/v1/fleet': FLEET, '/api/v1/packs': PACKS, '/api/v1/demo/reset': { incidents_cleared: 2 } })
    render(withStream(<FleetView />))
    await userEvent.click(await screen.findByRole('button', { name: 'Reset demo' }))
    expect(screen.getByText(/The audit trail is kept/)).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Reset demo' })[0])
    expect(await screen.findByRole('status')).toHaveTextContent('2 incident(s) cleared')
    expect(calls.some((c) => c.url === '/api/v1/demo/reset')).toBe(true)
  })
})

describe('IncidentWorkspace', () => {
  it('backfills the log, stays live, and re-fetches when a seq gap appears', async () => {
    let backfillCalls = 0
    mockFetch({
      '/api/v1/incidents/inc-1/events': (url: string) => {
        backfillCalls += 1
        const after = Number(new URL(url, 'http://x').searchParams.get('after_seq'))
        const log = [
          event(1, 'stage.changed', { stage: 'detect', previous: null }),
          event(2, 'stage.changed', { stage: 'gather', previous: 'detect' }),
          event(3, 'evidence.added', { evidence: ragEvidence }),
          event(4, 'retrieval.query', { query: 'bearing limits' }),
          event(5, 'retrieval.result', { documents: [], latency_ms: 12 }),
        ]
        return backfillCalls === 1 ? log.slice(0, 2) : log.filter((e) => e.seq > after)
      },
      '/api/v1/incidents/inc-1': INCIDENT,
      '/api/v1/fleet': FLEET,
      '/api/v1/parts': [],
      '/api/v1/packs/manufacturing-motor-drive/documents/manual-01': { id: 'manual-01', content_type: 'manual', text: '', sections: [] },
    })
    render(withStream(<IncidentWorkspace incidentId="inc-1" />))
    expect(await screen.findByText('Gather context', { selector: '.stage-rule' })).toBeInTheDocument()
    const source = FakeEventSource.instances[0]
    // Live event in sequence.
    act(() => source.emit(event(3, 'evidence.added', { evidence: ragEvidence })))
    expect(await screen.findByRole('button', { name: ragEvidence.claim })).toBeInTheDocument()
    // Seq 5 arrives while 4 was missed: the workspace re-fetches instead of skipping.
    act(() => source.emit(event(5, 'retrieval.result', { documents: [], latency_ms: 12 })))
    expect(await screen.findByText('bearing limits')).toBeInTheDocument()
    expect(backfillCalls).toBe(2)
    // Another incident's events are ignored.
    act(() => source.emit(event(6, 'stage.changed', { stage: 'closed', previous: 'gather' }, 'other')))
    expect(screen.getByText('Gather context', { selector: '.rail-label' }).closest('li')).toHaveAttribute('aria-current', 'step')
  })

  it('shows the proposal and decision panel when the proposal is ready', async () => {
    mockFetch({
      '/api/v1/incidents/inc-1/events': [
        event(1, 'stage.changed', { stage: 'detect', previous: null }),
        event(2, 'stage.changed', { stage: 'gather', previous: 'detect' }),
        event(3, 'stage.changed', { stage: 'propose', previous: 'gather' }),
        event(4, 'proposal.ready', { proposal }),
        event(5, 'stage.changed', { stage: 'decide', previous: 'propose' }),
      ],
      '/api/v1/incidents/inc-1': { ...INCIDENT, stage: 'decide', proposal_id: 'prop-1' },
      '/api/v1/proposals/prop-1': proposal,
      '/api/v1/fleet': FLEET,
      '/api/v1/parts': [
        { part_number: '6312-2RS', description: 'Deep-groove bearing', on_hand_local: 0, on_hand_regional: 2, regional_site: 'Regional DC Cork', regional_transit_days: 1, oem_lead_days: 6 },
      ],
    })
    render(withStream(<IncidentWorkspace incidentId="inc-1" />))
    expect(await screen.findByRole('button', { name: 'Drive-end bearing degradation' })).toBeInTheDocument()
    expect(await screen.findByText(/local 0/)).toHaveClass('state-warn-text')
    expect(screen.getByText('€8,000 – €25,000')).toBeInTheDocument()
    expect(screen.getByText(/Pack cost data: downtime €4,200\/h/)).toBeInTheDocument()
    expect(screen.getByLabelText('Ask a question about this clip before deciding')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
    expect(screen.getByText('Waiting on your decision.')).toBeInTheDocument()
  })
})

describe('App shell', () => {
  it('routes through the nav without a page load', async () => {
    mockFetch({
      '/api/v1/fleet': FLEET,
      '/api/v1/packs': PACKS,
      '/api/v1/audit': [],
      '/api/v1/work-orders': [],
    })
    render(<App />)
    expect(await screen.findByText('Manufacturing — Motor Drive')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Audit trail' }))
    expect(await screen.findByText(/No decisions yet/)).toBeInTheDocument()
    act(() => navigate('/work-orders'))
    expect(await screen.findByText(/A work order exists only after an operator approves/)).toBeInTheDocument()
    expect(screen.getByText(/Technical demonstration, not a product/)).toBeInTheDocument()
  })
})
