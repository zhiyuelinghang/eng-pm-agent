import type { AgentRuntimeTrace } from '@/types/agentRuntime'
import type { Member, WbsItem } from '@/types'

export type ProjectConnectorKey = 'wecom' | 'feishu' | 'dingtalk'
export type WorkspaceTab = 'agent' | 'manual'
export type ManualSection =
  | 'overview'
  | 'members'
  | 'documentPermissions'
  | 'wbs'
  | 'quality'
  | 'risks'
  | 'mappings'
  | 'monitor'
  | ProjectConnectorKey

export type ProjectBaseInfoForm = {
  name: string
  engineeringTypeDescription: string
  contractStartDate: string
  contractEndDate: string
  contractDurationDays: number | ''
  contractAmountWanYuan: number | ''
  constructionUnitName: string
  generalContractorUnitName: string
  supervisionUnitName: string
  designUnitName: string
  surveyUnitName: string
}

export type ManualWbsTreeRow = {
  item: WbsItem
  depth: number
  hasChildren: boolean
}

export type InitializationAttachment = {
  id: string
  name: string
  size: number
}

export type MaterialAgentMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  attachments?: InitializationAttachment[]
  runtimeTrace?: AgentRuntimeTrace | null
}

export type MaterialAgentPreparation = {
  stage: 'creating_conversation' | 'uploading' | 'starting_agent'
  completed: number
  total: number
  currentFile: string
}

export type ApiAgentConversation = {
  id: number
  project_id: number
  user_id: number
  agent_id: string
  agent_name: string
  conversation_type: 'initialization'
  title: string
  agentscope_session_id?: string | null
  status: string
}

export type ApiInitializationFile = {
  id: number
  project_id: number
  conversation_id: number
  file_name: string
  file_size: number
}

export type InitializationDraftIssue = {
  id: number
  rule_id: string
  level: 'error' | 'warning'
  section: 'project' | 'personnel' | 'wbs' | 'risks' | 'quality_requirements'
  target_record_id: number | null
  field_name: string | null
  label: string
  title: string
  message: string
  suggestion?: string | null
  related_record_ids: number[]
  details: Record<string, unknown>
}

export type InitializationReviewSectionKey = InitializationDraftIssue['section']

export type InitializationDraftPersonnel = {
  record_id: number
  serial_no: number
  real_name: string
  identity_card_no: string
  position_name: string
  certificate_no: string
  responsibility_description: string
}

export type InitializationDraftWbs = {
  record_id: number
  wbs_code: string
  parent_wbs_code?: string | null
  predecessor_wbs_codes?: string[]
  name: string
  planned_start_at?: string | null
  planned_finish_at?: string | null
  progress_percent?: number | string | null
  status_text?: string | null
  priority_text?: string | null
  duration_hours?: number | string | null
  level?: number | null
  item_type?: string | null
}

export type InitializationWbsTreeRow = {
  item: InitializationDraftWbs
  depth: number
  ancestorCodes: string[]
  hasChildren: boolean
}

export type InitializationDraftRisk = {
  record_id: number
  serial_no: number
  related_process_name: string
  risk_part: string
  risk_level: string
  evaluation_condition: string
  risk_window_start_date?: string | null
  risk_window_end_date?: string | null
  summary?: string | null
}

export type InitializationDraftQuality = {
  record_id: number
  wbs_code: string
  quality_acceptance_item: string
  control_indicator: string
  inspection_frequency: string
  related_documents: string
}

export type InitializationDraftSourceFile = {
  file_id?: number | string | null
  file_name?: string | null
  name?: string | null
  original_name?: string | null
  content_type?: string | null
  file_size?: number | null
  chunk_ids?: Array<number | string>
}

export type ApiInitializationDraft = {
  id: number
  project_id: number
  conversation_id: number
  status: 'collecting' | 'reviewing' | 'invalid' | 'ready' | 'applied' | 'rejected'
  revision: number
  payload: {
    project: Record<string, string | number | null> & { record_id: number | null }
    personnel: InitializationDraftPersonnel[]
    wbs: InitializationDraftWbs[]
    risks: InitializationDraftRisk[]
    quality_requirements: InitializationDraftQuality[]
  }
  validation_issues: InitializationDraftIssue[]
  validation?: {
    id: number
    status: 'running' | 'completed' | 'failed'
    draft_revision: number
    result_status?: 'ready' | 'invalid' | null
    package_id?: string | null
    package_version?: string | null
    ruleset_version?: string | null
    duration_ms?: number | null
    error?: string | null
    started_at?: string | null
    finished_at?: string | null
  } | null
  source_files: Array<string | InitializationDraftSourceFile>
  workflow?: {
    stage: 'collecting' | 'reviewing' | 'completed'
    run_revision: number
    expected_sections: string[]
    completed_sections: string[]
    pending_sections: string[]
    reviewer_agent_id?: string | null
    semantic_issues: InitializationDraftIssue[]
    review_summary?: string | null
  } | null
  required_personnel_credentials: Array<{
    identity_card_no: string
    real_name: string
    position_name: string
    suggested_username: string
  }>
  existing_personnel_accounts: Array<{
    identity_card_no: string
    user_id: number
    username: string
    real_name: string
  }>
  summary: {
    project_fields: number
    personnel: number
    position_assignments: number
    wbs: number
    risks: number
    quality_requirements: number
  }
}

export type InitializationCredentialForm = {
  identity_card_no: string
  real_name: string
  position_name: string
  suggested_username: string
  username: string
  initial_password: string
}

export type InitializationPersonnelReviewGroup = {
  key: string
  serial_no: number
  real_name: string
  identity_card_no: string
  positions: InitializationDraftPersonnel[]
  record_ids: number[]
  existingAccount: ApiInitializationDraft['existing_personnel_accounts'][number] | null
  credential: InitializationCredentialForm | null
  issues: InitializationDraftIssue[]
}

export type ProjectConnectorConfig = {
  key: ProjectConnectorKey
  label: string
  description: string
  connectionLabel: string
  connectionPlaceholder: string
  secretLabel: string
  secretPlaceholder: string
  connectionId: string
  secret: string
  configured: boolean
  hasSecret: boolean
  updatedAt: string
  icon: any
}

export type ApiProjectConnectorConfig = {
  connector_type: ProjectConnectorKey
  connection_id: string
  configured: boolean
  has_secret: boolean
  updated_at: string | null
}
