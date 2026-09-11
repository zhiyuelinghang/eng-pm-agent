export type InitializationSection = 'project' | 'personnel' | 'wbs' | 'risks' | 'quality_requirements'
export type InitializationOperation = 'add' | 'update' | 'unchanged' | 'conflict' | 'applied'
export type InitializationValidationInfo = { status: string; source?: string; reused?: boolean; validated_at?: string; package_id?: string | null; package_version?: string | null; ruleset_version?: string | null; duration_ms?: number | null; error?: string | null }
export type InitializationDraftReference = {
  id: number; revision: number; status: string;
  validation_issues?: InitializationChangeIssue[];
  validation?: InitializationValidationInfo | null;
  extraction_notes?: Array<{ section: InitializationSection; notes: string[] }>;
}

export type InitializationChange = {
  key: string
  record_id: number
  section: InitializationSection
  title: string
  operation: InitializationOperation
  target_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown>
  fields: Array<{ name: string; before: unknown; after: unknown }>
  selected: boolean
  candidates: Array<{ id: number; title: string }>
}

export type InitializationChangeIssue = {
  details?: Record<string, unknown>
  rule_id?: string
  target_record_id?: number | null
  level: 'error' | 'warning'
  section: InitializationSection
  change_key?: string | null
  field_name?: string | null
  title: string
  message: string
  suggestion?: string | null
}

export type InitializationRequiredCredential = {
  identity_card_no: string
  real_name: string
  position_name: string
  suggested_username: string
}
export type InitializationChangeCredential = InitializationRequiredCredential & {
  username: string
  initial_password: string
}
export type InitializationCredentialField = 'username' | 'initial_password'

export type InitializationChangePreview = {
  mode?: 'initialization' | 'update'
  preview_id: string
  draft_id: number
  draft_revision: number
  baseline_hash: string
  changes: InitializationChange[]
  selected_keys: string[]
  issues: InitializationChangeIssue[]
  operation_issues?: InitializationChangeIssue[]
  can_apply: boolean
  required_personnel_credentials: InitializationRequiredCredential[]
  existing_personnel_accounts?: Array<{ identity_card_no: string; username: string; real_name: string | null }>
  validation: InitializationValidationInfo
  summary: Record<InitializationOperation | 'selected', number>
}

export type InitializationPreviewInput = {
  force_validation?: boolean
  selected_keys?: string[]
  resolutions?: Record<string, number | null>
}
export type InitializationApplyInput = {
  preview_id: string
  allow_warnings: boolean
  personnel_credentials: Array<Pick<InitializationChangeCredential, 'identity_card_no' | 'username' | 'initial_password'>>
}
export type InitializationApplyResult = { result: { status: string; counts: Record<string, number> } }
