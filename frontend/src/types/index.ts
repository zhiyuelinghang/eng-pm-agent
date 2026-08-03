// 风险等级
export type RiskLevel = 'critical' | 'high' | 'medium' | 'low'
// 任务状态
export type TaskStatus = 'pending' | 'processing' | 'need_more_info' | 'waiting_confirm' | 'done' | 'overdue' | 'cancelled'
// 日报解析状态
export type ParseStatus = 'pending_confirm' | 'confirmed' | 'failed' | 'reparse'
// 草稿状态
export type DraftStatus = 'draft' | 'reviewing' | 'confirmed' | 'rejected' | 'packaged'
// 填报状态
export type FillStatus = 'pending' | 'filling' | 'submitted' | 'failed'

export interface Project {
  id: string
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
  createdAt: string
  updatedAt?: string
}

export interface Member {
  id: string
  projectMemberId: string
  username: string
  identityCardNo: string
  systemRole: 'admin' | 'user'
  name: string
  title: string
  phone: string
  email: string
  role: string[]
  positions: MemberPosition[]
  projectId: string
}

export interface MemberPosition {
  id: string
  positionId: string
  name: string
  serialNo: number
  certificateNo: string
  responsibilityDescription: string
}

export interface WbsItem {
  id: string
  code: string
  name: string
  level: number
  parentId: string | null
  sortOrder?: number
  colorValue?: string
  itemType?: string
  assignedToText?: string
  planStart: string
  planEnd: string
  deadline?: string
  actualStart?: string
  progress: number
  status: 'not_started' | 'in_progress' | 'done' | 'delayed'
  statusText?: string
  priorityText?: string
  durationHours?: number
  estimatedHours?: number
  timeLogMinutes?: number
  description?: string
  budget?: number
  actualCost?: number
  predecessorIds?: string[]
  predecessorCodes?: string[]
  mspUid?: string
  mspId?: string
  sourceCreatedAt?: string
  sourceCreator?: string
  sourceProjectPath?: string
  responsibleId: string
  projectId: string
  supervision?: {
    yesterday: string
    today: string
    quality: string
    risk: string
    focus: string
    key: boolean
  }
}

export interface RiskSource {
  id: string
  serialNo?: number
  name: string
  level: RiskLevel
  levelText?: string
  type: string
  relatedProcessName?: string
  riskPart?: string
  controlStart: string
  controlEnd: string
  responsibleId: string
  confirmatorId: string
  materials: string[]
  controlMeasures?: string
  evaluationCondition?: string
  summary?: string
  projectId: string
}

export interface QualityMetric {
  id: string
  projectId: string
  wbsId?: string
  wbsCode?: string
  wbsName?: string
  name: string
  acceptanceItem?: string
  requirement: string
  controlIndicator?: string
  inspectionFrequency: string
  requiredMaterials: string[]
  relatedDocuments?: string
  ownerId?: string
  status: 'pending' | 'processing' | 'passed' | 'failed'
}

export interface PlatformFieldMapping {
  id: string
  projectId: string
  platformName: string
  sourceField: 'draft_title' | 'draft_content' | 'source_refs' | string
  targetField: string
  transformRule?: string
  required: boolean
  enabled: boolean
}

export interface WbsRiskLink {
  id: string
  wbsId: string
  riskId: string
  alertDays: number
  notifyMethods: string[]
  basis?: string
  responsibleId?: string
}

export interface Task {
  id: string
  title: string
  type: 'risk_alert' | 'material_missing' | 'daily_confirm' | 'draft_review' | 'fill_platform'
  riskLevel: RiskLevel
  projectId: string
  linkedWbsIds: string[]
  linkedRiskId?: string
  responsibleId: string
  confirmatorId: string
  deadline: string
  status: TaskStatus
  missingCount: number
  triggerReason: string
  workflowSteps: Array<{ name: string; owner?: string; owner_user_id?: string; due_at?: string; order?: number; next_step?: number; status: 'pending' | 'processing' | 'completed' | 'blocked'; note?: string; material?: string; phase?: string; closure?: string }>
  createdAt: string
}

export interface ProjectInformationRecord {
  id: string
  projectId: string
  sourceType: string
  sourceName: string
  author: string
  recordedAt: string
  status: string
  confidence: string
  content: string
  sourceRefs: string[]
}

export interface DailyReport {
  id: string
  fileName: string
  fileType: string
  date: string
  constructionContent: string
  currentProgress: number
  cumulativeProgress: number
  problems: string
  tomorrowPlan: string
  riskContent: string
  monitorContent: string
  matchedWbsId?: string
  confidence: number
  parseStatus: 'pending' | 'processing' | 'done' | 'failed'
  status: ParseStatus
  projectId: string
  createdAt: string
}

export interface RiskDraft {
  id: string
  title: string
  riskId: string
  riskLevel: RiskLevel
  projectId: string
  content: string
  hazardType: string
  deadline: string
  measures: string
  responsibleId: string
  missingItems: string[]
  sourceRefs: string[]
  attachments: Array<{ name: string; ready: boolean }>
  status: DraftStatus
  reviewNote?: string
  createdAt: string
  updatedAt: string
}

export interface FillPackage {
  id: string
  draftId: string
  platformName: string
  processName: string
  status: FillStatus
  deadline: string
  fields: Array<{ name: string; value: string; placeholder?: string; required?: boolean }>
  attachments: Array<{ name: string; ready: boolean }>
  projectId: string
  createdAt: string
}

export interface RemindRule {
  id: string
  level: RiskLevel
  days: number
  enabled: boolean
  frequency?: string
}

export interface DirConfig {
  mainDir: string
  archiveDir: string
  tempDir: string
  failedDir: string
  backupDir: string
  scanInterval: number
  enabled: boolean
}

export interface OperationLog {
  id: string
  time: string
  operator: string
  level: 'info' | 'success' | 'warning' | 'error'
  action: string
  detail: string
  relatedId?: string
}
