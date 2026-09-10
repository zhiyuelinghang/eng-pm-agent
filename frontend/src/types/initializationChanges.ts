export type InitializationSection = 'project' | 'personnel' | 'wbs' | 'risks' | 'quality_requirements'
export type InitializationOperation = 'add' | 'update' | 'unchanged' | 'conflict' | 'applied'
export type InitializationDraftReference = { id: number; revision: number; status: string }

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

export type InitializationChangePreview = {
  preview_id: string
  draft_id: number
  draft_revision: number
  baseline_hash: string
  changes: InitializationChange[]
  selected_keys: string[]
  issues: InitializationChangeIssue[]
  can_apply: boolean
  required_personnel_credentials: InitializationRequiredCredential[]
  existing_personnel_accounts?: Array<{ identity_card_no: string; username: string; real_name: string | null }>
  validation: { status: 'completed' | 'failed'; package_version?: string | null; error?: string | null }
  summary: Record<InitializationOperation | 'selected', number>
}

export type InitializationPreviewInput = {
  selected_keys?: string[]
  resolutions?: Record<string, number | null>
}
export type InitializationApplyInput = {
  preview_id: string
  allow_warnings: boolean
  personnel_credentials: Array<Pick<InitializationChangeCredential, 'identity_card_no' | 'username' | 'initial_password'>>
}
export type InitializationApplyResult = { result: { status: string; counts: Record<string, number> } }
