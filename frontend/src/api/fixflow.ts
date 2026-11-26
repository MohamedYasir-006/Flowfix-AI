import { request } from './client'

export interface SensorReadings {
  temperature_c: number
  vibration_mm_s: number
  pressure_bar: number
  flow_m3h: number
}

export interface FixFlowEquipment {
  id: string
  name: string
  type: string
  manufacturer: string
  model: string
  location: string
  criticality: string
  details: Record<string, string | number>
  sensor_readings: SensorReadings
  thresholds: Record<string, number>
}

export interface KnowledgeDoc {
  id: string
  title: string
  source: string
  section: string
  content: string
}

export interface FixFlowHypothesis {
  fault: string
  likelihood: number
  evidence: string[]
  recommended_checks: string[]
  source: string
}

export interface FixFlowDiagnosis {
  summary: string
  severity: string
  hypotheses: FixFlowHypothesis[]
  source: string
  model_invoked?: boolean
  model?: string
  llm_error?: string
  artifact_id?: string
}

export interface FixFlowInspection {
  status: string
  simulated: boolean
  model_invoked: boolean
  message: string
  findings: string[]
  image: { name: string; size: number } | null
  notes: string
  artifact_id?: string
}

export interface FixFlowSafetyRule {
  rule: string
  result: string
  detail: string
}

export interface FixFlowSafety {
  decision: string
  deterministic: boolean
  llm_can_override: boolean
  reason_codes: string[]
  rules: FixFlowSafetyRule[]
  inspection_used: boolean
  inputs_used: string[]
  evaluated_at: string
  artifact_id?: string
}

export interface FixFlowTask {
  id: string
  title: string
  priority: string
  tools: string[]
  parts: string[]
  estimated_hours: number
  procedure: string[]
  acceptance: string[]
}

export interface FixFlowPlan {
  tasks: FixFlowTask[]
  required_tools: string[]
  required_parts: string[]
  estimated_downtime_hours: number
  safety_gate: string
  gate_note: string
  evidence_ids: string[]
  artifact_id?: string
}

export interface FixFlowCheck {
  name: string
  value: number
  unit: string
  limit: string
  passed: boolean
}

export interface FixFlowVerification {
  result: string
  checks: FixFlowCheck[]
  notes: string
  verified_at: string
  diagnosis_reopened: boolean
  artifact_id?: string
}

export interface FixFlowAgent {
  id: string
  name: string
  role: string
  status: string
  summary: string
  artifact_id: string | null
  started_at: string
  ended_at: string | null
}

export interface FixFlowRun {
  id: string
  workflow_execution_id: string
  status: string
  equipment: FixFlowEquipment
  readings: SensorReadings
  inspection: FixFlowInspection
  diagnosis: FixFlowDiagnosis
  evidence: Array<KnowledgeDoc & { score: number }>
  safety: FixFlowSafety
  plan: FixFlowPlan
  verification: FixFlowVerification | null
  diagnosis_reopened: boolean
  reopened_diagnosis: (FixFlowDiagnosis & { artifact_id?: string }) | null
  agents: FixFlowAgent[]
  created_at: string
  updated_at: string
}

export interface FixFlowRunRequest {
  equipment_id: string
  readings: SensorReadings
  image_name?: string
  image_size?: number
  notes?: string
}

export const fixflowApi = {
  equipment: () => request<FixFlowEquipment[]>('/fixflow/equipment'),
  knowledge: () => request<KnowledgeDoc[]>('/fixflow/knowledge'),
  runs: () => request<FixFlowRun[]>('/fixflow/runs'),
  run: (input: FixFlowRunRequest) =>
    request<FixFlowRun>('/fixflow/runs', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  verify: (runId: string, readings: SensorReadings, notes?: string) =>
    request<FixFlowRun>(`/fixflow/runs/${runId}/verify`, {
      method: 'POST',
      body: JSON.stringify({ readings, notes }),
    }),
}
