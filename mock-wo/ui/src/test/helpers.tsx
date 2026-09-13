import type { ReactNode } from 'react'
import { StreamProvider } from '../lib/stream'
import type { Evidence, Proposal, StreamEvent } from '../lib/types'

export class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  listeners = new Map<string, Set<(event: MessageEvent) => void>>()
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)!.add(listener)
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.get(type)?.delete(listener)
  }

  close() {
    this.closed = true
  }

  emit(event: StreamEvent) {
    const message = { data: JSON.stringify(event) } as MessageEvent
    this.listeners.get(event.type)?.forEach((listener) => listener(message))
  }

  open() {
    this.onopen?.()
  }
}

export function withStream(children: ReactNode) {
  return <StreamProvider>{children}</StreamProvider>
}

type Handler = (url: string, init?: RequestInit) => unknown

export function mockFetch(routes: Record<string, Handler | unknown>) {
  const calls: { url: string; init?: RequestInit }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((pattern) => url.startsWith(pattern) || url === pattern)
    if (!key) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    const route = routes[key]
    const value = typeof route === 'function' ? await (route as Handler)(url, init) : route
    if (value instanceof Response) return value
    return new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

export const event = (seq: number, type: string, extra: Record<string, unknown> = {}, incidentId = 'inc-1'): StreamEvent => ({
  type,
  incident_id: incidentId,
  seq,
  ts: new Date(Date.UTC(2026, 8, 13, 12, 0, seq)).toISOString(),
  ...extra,
})

export const ragEvidence: Evidence = {
  id: 'ev-rag',
  incident_id: 'inc-1',
  source_type: 'rag',
  source_id: 'manual-01#4.2',
  quote: 'Bearing temperature above 75°C: replace per preventive schedule.',
  claim: 'Housing temperature exceeds the replacement threshold',
  t_start: null,
  t_end: null,
  document_anchor: '4.2',
  confidence: 'high',
  created_at: '2026-09-13T12:00:03Z',
}

export const vssEvidence: Evidence = {
  id: 'ev-vss',
  incident_id: 'inc-1',
  source_type: 'vss',
  source_id: 'clip-anomaly-01@00:42',
  quote: 'Heat shimmer over the drive-end housing',
  claim: 'Heat signature on bearing housing',
  t_start: 42,
  t_end: 45,
  document_anchor: null,
  confidence: 'medium',
  created_at: '2026-09-13T12:00:02Z',
}

export const proposal: Proposal = {
  id: 'prop-1',
  incident_id: 'inc-1',
  kind: 'work_order',
  state: 'pending',
  created_at: '2026-09-13T12:04:00Z',
  decided_at: null,
  root_cause: 'Drive-end bearing degradation',
  line_items: [
    { id: 'li-1', action: 'Order bearing', detail: '6312-2RS from Cork', part_number: '6312-2RS', quantity: 1 },
    { id: 'li-2', action: 'De-rate Line 3 to 60%', detail: 'until replacement' },
  ],
  draft: {
    title: 'Bearing replacement — M-3021',
    description: 'Replace the drive-end bearing.',
    equipment: 'M-3021',
    anomaly_ref: 'clip-anomaly-01@00:42',
    priority: 'high',
    assigned_to: 'maintenance-team-b',
  },
  parts_constraint: 'Not held locally; two at Regional DC Cork.',
  impact_if_ignored: { low: 8000, high: 25000, unit: 'EUR' },
  impact_if_unnecessary: { low: 850, high: 2400, unit: 'EUR' },
  evidence_ids: ['ev-vss', 'ev-rag'],
  decision: null,
}
