import type {
  Ask,
  AuditRow,
  DocumentBody,
  Evidence,
  Fleet,
  Incident,
  Note,
  NotificationItem,
  PackSummary,
  Part,
  Proposal,
  StreamEvent,
  WorkOrder,
  WorkOrderDraft,
} from './types'

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  const text = await response.text()
  const body = text ? safeJson(text) : null
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : text
    throw new ApiError(response.status, detail)
  }
  return body as T
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export type DecisionBody =
  | { action: 'approve'; line_items_approved?: string[] }
  | {
      action: 'modify'
      reason: string
      modifications: Partial<Pick<WorkOrderDraft, 'title' | 'description' | 'priority' | 'assigned_to'>>
      line_items_approved?: string[]
    }
  | { action: 'deny'; reason: string }

export const api = {
  packs: () => request<PackSummary[]>('/api/v1/packs'),
  activatePack: (packId: string) => post<PackSummary>(`/api/v1/packs/${encodeURIComponent(packId)}/activate`),
  fleet: () => request<Fleet>('/api/v1/fleet'),
  parts: () => request<Part[]>('/api/v1/parts'),
  incidents: () => request<Incident[]>('/api/v1/incidents'),
  incident: (id: string) => request<Incident>(`/api/v1/incidents/${encodeURIComponent(id)}`),
  inject: (assetId: string, incidentId: string) =>
    post<Incident>('/api/v1/incidents/inject', { asset_id: assetId, incident_id: incidentId }),
  retry: (id: string) => post<{ status: string }>(`/api/v1/incidents/${encodeURIComponent(id)}/retry`),
  evidence: (id: string) => request<Evidence[]>(`/api/v1/incidents/${encodeURIComponent(id)}/evidence`),
  events: (id: string, afterSeq: number) =>
    request<StreamEvent[]>(`/api/v1/incidents/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`),
  asks: (id: string) => request<Ask[]>(`/api/v1/incidents/${encodeURIComponent(id)}/asks`),
  ask: (id: string, question: string) =>
    post<Ask>(`/api/v1/incidents/${encodeURIComponent(id)}/ask`, { question }),
  proposal: (id: string) => request<Proposal>(`/api/v1/proposals/${encodeURIComponent(id)}`),
  decide: (id: string, body: DecisionBody) =>
    post<Proposal>(`/api/v1/proposals/${encodeURIComponent(id)}/decision`, body),
  document: (packId: string, docId: string) =>
    request<DocumentBody>(`/api/v1/packs/${encodeURIComponent(packId)}/documents/${encodeURIComponent(docId)}`),
  workOrders: () => request<WorkOrder[]>('/api/v1/work-orders'),
  workOrder: (id: string) => request<WorkOrder>(`/api/v1/work-orders/${encodeURIComponent(id)}`),
  notes: () => request<Note[]>('/api/v1/notes'),
  notifications: () => request<NotificationItem[]>('/api/v1/notifications'),
  audit: () => request<AuditRow[]>('/api/v1/audit'),
  reset: () => post<{ incidents_cleared: number }>('/api/v1/demo/reset'),
}

export const clipUrl = (packId: string, clip: string) =>
  `/media/clips/${encodeURIComponent(packId)}/${encodeURIComponent(clip)}`
