import type { DailyReport, FillPackage, PlatformFieldMapping, QualityMetric, RemindRule, Task, WbsItem } from '@/types'

export type ApiProject = {
  id: number
  name: string
  engineering_type_description?: string
  contract_start_date?: string
  contract_end_date?: string
  contract_duration_days?: number
  contract_amount_wan_yuan?: number
  construction_unit_name?: string
  general_contractor_unit_name?: string
  supervision_unit_name?: string
  design_unit_name?: string
  survey_unit_name?: string
  created_at: string
  updated_at?: string
}
export type ProjectBaseInfoInput = {
  name: string
  engineeringTypeDescription?: string
  contractStartDate?: string
  contractEndDate?: string
  contractDurationDays?: number
  contractAmountWanYuan?: number
  constructionUnitName?: string
  generalContractorUnitName?: string
  supervisionUnitName?: string
  designUnitName?: string
  surveyUnitName?: string
}
export type ApiMember = {
  id: number
  project_id: number
  user_id: number
  user: {
    id: number
    username: string
    real_name: string
    identity_card_no: string
    role: 'admin' | 'user'
  }
  positions: Array<{
    id: number
    position_id: number
    serial_no: number
    position_name: string
    certificate_no: string
    responsibility_description: string
  }>
}
export type MemberWriteInput = {
  name: string
  identityCardNo: string
  positionName: string
  certificateNo?: string
  responsibilityDescription?: string
  username?: string
  password?: string
}
export type ApiWbs = {
  id: number
  project_id: number
  parent_id?: number | null
  sort_order?: number
  color_value?: string | null
  wbs_code?: string
  code?: string
  name: string
  level: number
  assigned_to_text?: string | null
  planned_start_at?: string | null
  planned_finish_at?: string | null
  deadline_at?: string | null
  planned_start?: string | null
  planned_finish?: string | null
  progress_percent?: number | string | null
  progress?: number | string | null
  status_text?: string | null
  status?: string | null
  priority_text?: string | null
  duration_hours?: number | string | null
  estimated_hours?: number | string | null
  time_log_minutes?: number | null
  description?: string | null
  budget?: number | string | null
  actual_cost?: number | string | null
  item_type?: string | null
  responsible_user_id?: number | null
  predecessor_ids?: number[]
  predecessor_codes?: string[]
  msp_uid?: string | null
  msp_id?: string | null
  source_created_at?: string | null
  source_creator?: string | null
  source_project_path?: string | null
  raw_data?: { supervision?: WbsItem['supervision'] }
}
export type ApiRisk = {
  id: number
  project_id: number
  serial_no?: number
  related_process_name?: string
  risk_part?: string
  risk_level?: string
  evaluation_condition?: string
  risk_window_start_date?: string | null
  risk_window_end_date?: string | null
  summary?: string | null
  name?: string
  level?: string
  risk_type?: string
  planned_start?: string | null
  planned_finish?: string | null
  responsible_user_id?: number | null
  confirmer_user_id?: number | null
  material_requirements?: string[]
  control_requirements?: string
}
export type ApiQualityMetric = {
  id: number
  project_id: number
  wbs_item_id?: number | null
  wbs_code?: string
  wbs_name?: string | null
  quality_acceptance_item?: string
  control_indicator?: string
  inspection_frequency?: string
  related_documents?: string
  name?: string
  requirement?: string
  required_materials?: string[]
  owner_user_id?: number | null
  status?: QualityMetric['status']
}
export type ApiPlatformMapping = { id: number; project_id: number; platform_name: string; source_field: PlatformFieldMapping['sourceField']; target_field: string; transform_rule?: string; required: boolean; enabled: boolean }
export type ApiLink = { id: number; project_id: number; wbs_item_id: number; risk_source_id: number; alert_days: number; notify_methods: string[]; basis?: string }
export type ApiTask = { id: number; project_id: number; title: string; task_type: Task['type']; risk_level: Task['riskLevel']; assignee_user_id?: number; confirmer_user_id?: number; due_at?: string; wbs_item_id?: number; risk_source_id?: number; trigger_reason?: string; required_materials: string[]; workflow_steps?: Task['workflowSteps']; status: string; created_at: string; updated_at?: string; closed_at?: string }
export type ApiDaily = { id: number; project_id: number; file_name: string; report_date?: string; content?: string; matched_wbs_id?: number; confidence: number; parse_status: string; status: DailyReport['status']; created_at: string }
export type ApiDraft = { id: number; project_id: number; risk_source_id: number; title: string; content: string; status: string; source_refs: string[]; missing_items: string[]; review_note?: string; created_at: string; updated_at: string }
export type ApiFill = { id: number; project_id: number; draft_id: number; platform_name: string; process_name: string; status: FillPackage['status']; fields: FillPackage['fields']; attachments: FillPackage['attachments']; created_at: string }
export type ApiLog = { id: number; created_at: string; action: string; detail: string; operator_id?: number }
export type ApiProjectSettings = { project_id: number; main_dir?: string; archive_dir?: string; temp_dir?: string; failed_dir?: string; backup_dir?: string; scan_interval?: number; enabled?: boolean; reminder_rules?: Array<{ id?: string; level: RemindRule['level']; days: number; enabled: boolean; frequency?: string }>; weknora_agent_id?: string | null }
