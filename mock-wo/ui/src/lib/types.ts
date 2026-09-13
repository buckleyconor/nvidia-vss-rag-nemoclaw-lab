// Shapes returned by mock-wo's operator API (operator-dashboard-spec §5, §6).

export type Stage = 'detect' | 'gather' | 'propose' | 'decide' | 'act' | 'closed'

export const RAIL_STAGES = ['monitor', 'detect', 'gather', 'propose', 'decide', 'act'] as const
export type RailStage = (typeof RAIL_STAGES)[number]

export type SourceType = 'vss' | 'rag' | 'agent'
export type Confidence = 'high' | 'medium' | 'low'

export interface Evidence {
  id: string
  incident_id: string
  source_type: SourceType
  source_id: string
  quote: string
  claim: string
  t_start: number | null
  t_end: number | null
  document_anchor: string | null
  confidence: Confidence
  created_at: string
}

export interface ServiceRecord {
  date: string
  summary: string
  technician: string
}

export interface Asset {
  asset_id: string
  display_name: string
  make_model: string
  commissioned: string
  location: string
  baseline_clips: string[]
  thumbnail: string | null
  service_history: ServiceRecord[]
  status: 'normal' | 'alarm' | 'attention'
  incident: string | null
  injectable: string[]
}

export interface Fleet {
  pack_id: string
  assets: Asset[]
}

export interface PackSummary {
  pack_id: string
  display_name: string
  asset_class: string
  scenario: string
  knowledge_collection: string
  asset_count: number
  incident_count: number
  skills: string[]
  active: boolean
}

export interface IncidentDefinition {
  incident_id: string
  asset_id: string
  title: string
  clip: string
  outcome_class: 'work_order' | 'monitoring_note'
  downtime_cost_per_hour: number
  callout_cost: number
  currency: string
  ambiguous?: boolean
  expected_analysis_seconds: number
}

export interface Incident {
  id: string
  pack_id: string
  asset_id: string
  pack_incident_id: string
  clip: string
  stage: Stage
  opened_at: string
  closed_at: string | null
  definition: IncidentDefinition | null
  proposal_id?: string | null
}

export interface LineItem {
  id: string
  action: string
  detail: string
  part_number?: string | null
  quantity?: number | null
}

export interface ImpactRange {
  low: number
  high: number
  unit: string
}

export interface Decision {
  id: string
  action: 'approve' | 'modify' | 'deny'
  reason: string | null
  modifications: Record<string, unknown> | null
  line_items_approved: string[]
  work_order_id: string | null
  decided_at: string
}

export interface WorkOrderDraft {
  title: string
  description: string
  equipment: string
  anomaly_ref: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  assigned_to?: string | null
}

export interface Proposal {
  id: string
  incident_id: string
  kind: 'work_order' | 'monitoring_note'
  state: 'pending' | 'approved' | 'modified' | 'denied' | 'auto_filed'
  created_at: string
  decided_at: string | null
  root_cause: string
  alternate_root_cause?: string | null
  confidence_split?: string | null
  discriminating_test?: string | null
  line_items: LineItem[]
  draft: WorkOrderDraft & Record<string, unknown>
  parts_constraint?: string | null
  impact_if_ignored?: ImpactRange | null
  impact_if_unnecessary?: ImpactRange | null
  evidence_ids: string[]
  decision?: Decision | null
}

export interface Part {
  part_number: string
  description: string
  on_hand_local: number
  on_hand_regional: number
  regional_site: string
  regional_transit_days: number
  oem_lead_days: number
}

export interface DocumentSection {
  anchor: string
  title: string
  level: number
  line: number
}

export interface DocumentBody {
  id: string
  content_type: string
  text: string
  sections: DocumentSection[]
}

export interface Citation {
  source_type: SourceType
  source_id: string
  quote: string
}

export interface WorkOrder {
  id: string
  title: string
  description: string
  equipment: string
  anomaly_ref: string
  priority: string
  assigned_to: string | null
  status: string
  citations: Citation[]
  proposal_id: string | null
  created_at: string
  updated_at: string
}

export interface Note {
  id: string
  equipment: string
  description: string
  anomaly_ref: string
  proposal_id: string | null
  created_at: string
}

export interface NotificationItem {
  id: string
  work_order_id: string
  channel: string
  message: string
  read_at: string | null
}

export interface Ask {
  id: string
  incident_id: string
  question: string
  status: 'pending' | 'answered' | 'failed'
  answer: string | null
  error: string | null
  evidence_id: string | null
  asked_at: string
  answered_at: string | null
}

export interface AuditRow {
  id: string
  ts: string
  kind: 'inject' | 'decision' | 'auto_filed' | 'reset'
  incident_id: string | null
  pack_id: string | null
  asset_id: string | null
  record: {
    incident?: Incident
    evidence?: Evidence[]
    proposal?: Proposal | null
    decision?: Decision | null
    asks?: Ask[]
    title?: string
    incidents_cleared?: number
    [key: string]: unknown
  }
}

export interface StreamEvent {
  type: string
  incident_id: string | null
  seq: number
  ts: string
  [key: string]: unknown
}

export const EVENT_TYPES = [
  'stage.changed',
  'analysis.progress',
  'analysis.caption',
  'retrieval.query',
  'retrieval.result',
  'skill.invoked',
  'skill.completed',
  'archive.match',
  'agent.token',
  'evidence.added',
  'ask.answer',
  'proposal.ready',
  'decision.recorded',
  'workorder.created',
  'error',
  'demo.reset',
  'pack.activated',
] as const
