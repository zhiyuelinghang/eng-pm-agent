import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import api, { type ApiEnvelope } from '@/api/client'
import type { DailyReport, DirConfig, FillPackage, Member, OperationLog, PlatformFieldMapping, Project, ProjectInformationRecord, QualityMetric, RemindRule, RiskDraft, RiskSource, Task, WbsItem, WbsRiskLink } from '@/types'

type ApiProject = {
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
type ApiMember = {
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
type MemberWriteInput = {
  name: string
  identityCardNo: string
  positionName: string
  certificateNo?: string
  responsibilityDescription?: string
  username?: string
  password?: string
  systemRole?: 'admin' | 'user'
}
type ApiWbs = {
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
type ApiRisk = {
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
type ApiQualityMetric = {
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
type ApiPlatformMapping = { id: number; project_id: number; platform_name: string; source_field: PlatformFieldMapping['sourceField']; target_field: string; transform_rule?: string; required: boolean; enabled: boolean }
type ApiLink = { id: number; project_id: number; wbs_item_id: number; risk_source_id: number; alert_days: number; notify_methods: string[]; basis?: string }
type ApiTask = { id: number; project_id: number; title: string; task_type: Task['type']; risk_level: Task['riskLevel']; assignee_user_id?: number; confirmer_user_id?: number; due_at?: string; wbs_item_id?: number; risk_source_id?: number; trigger_reason?: string; required_materials: string[]; workflow_steps?: Task['workflowSteps']; status: string; created_at: string }
type ApiDaily = { id: number; project_id: number; file_name: string; report_date?: string; content?: string; matched_wbs_id?: number; confidence: number; parse_status: string; status: DailyReport['status']; created_at: string }
type ApiDraft = { id: number; project_id: number; risk_source_id: number; title: string; content: string; status: string; source_refs: string[]; missing_items: string[]; review_note?: string; created_at: string; updated_at: string }
type ApiFill = { id: number; project_id: number; draft_id: number; platform_name: string; process_name: string; status: FillPackage['status']; fields: FillPackage['fields']; attachments: FillPackage['attachments']; created_at: string }
type ApiLog = { id: number; created_at: string; action: string; detail: string; operator_id?: number }
type ApiProjectSettings = { project_id: number; main_dir?: string; archive_dir?: string; temp_dir?: string; failed_dir?: string; backup_dir?: string; scan_interval?: number; enabled?: boolean; reminder_rules?: Array<{ id?: string; level: RemindRule['level']; days: number; enabled: boolean; frequency?: string }> }
type ProjectDashboard = { progress_rate: number; progress_status?: string; planned_delta?: string; risk_warnings: number; safety_issues: number; quality_issues: number; task_completion_rate: number; open_changes: number; unread_notifications: number; main_risk: string; main_safety?: string; main_quality: string; overall?: string }
type ProjectChangeRecord = { id: number; category: string; title: string; content: string; status: string; source_refs: string[]; created_at: string }
type ApiInformationRecord = { id: number; project_id: number; source_type: string; source_name: string; author?: string; recorded_at: string; status: string; confidence: string; content: string; source_refs: string[] }
type NotificationRecord = { id: number; notification_type: string; title: string; content: string; priority: string; is_read: boolean; created_at: string }
export type AttachmentRecord = { id: string; projectId: string; fileName: string; category: string; version: number; fileSize: number; contentType: string; createdAt: string; folderId?: string; snippet?: string }
export type DocumentFolderRecord = { id: string; projectId: string; parentId?: string; name: string; createdAt: string }
export type ProjectConfigScope = { members: Member[]; wbsItems: WbsItem[]; riskSources: RiskSource[]; qualityMetrics: QualityMetric[]; platformMappings: PlatformFieldMapping[]; dirConfig: DirConfig; remindRules: RemindRule[] }
type WbsWriteInput = {
  code: string
  name: string
  level?: number
  parent_id?: string | null
  sort_order?: number
  color_value?: string | null
  assigned_to_text?: string | null
  planned_start?: string | null
  planned_finish?: string | null
  deadline?: string | null
  progress?: number | null
  duration_hours?: number | null
  estimated_hours?: number | null
  time_log_minutes?: number | null
  status?: string | null
  priority_text?: string | null
  description?: string | null
  budget?: number | null
  actual_cost?: number | null
  item_type?: string | null
  predecessor_ids?: string[]
  responsible_user_id?: string | null
}
type RiskWriteInput = {
  serial_no?: number
  name: string
  level: string
  risk_type?: string
  planned_start?: string | null
  planned_finish?: string | null
  control_requirements?: string | null
  summary?: string | null
  material_requirements?: string[]
}
type QualityMetricWriteInput = {
  name: string
  requirement: string
  wbs_item_id?: string | null
  inspection_frequency?: string | null
  related_documents?: string | null
}
type ApiAttachment = { id: number; project_id: number; file_name: string; category: string; version: number; file_size: number; content_type?: string; created_at: string; folder_id?: number | null; snippet?: string }
type ApiDocumentFolder = { id: number; project_id: number; parent_id?: number | null; name: string; created_at: string }

const uiTaskStatus = (status: string): Task['status'] => ({ completed: 'done', pending_confirm: 'waiting_confirm' }[status] ?? status) as Task['status']
const apiTaskStatus = (status: Task['status']) => ({ done: 'completed', waiting_confirm: 'pending_confirm' } as Partial<Record<Task['status'], string>>)[status] ?? status
const id = (value?: number | string | null) => value == null ? '' : String(value)
const numeric = (value?: number | string | null) => value == null || value === '' ? undefined : Number(value)
const normalizeWbsStatus = (value: string | null | undefined): WbsItem['status'] => {
  const text = (value || '').toLowerCase()
  if (/完成|完工|done|complete/.test(text)) return 'done'
  if (/延期|延误|滞后|delayed|overdue/.test(text)) return 'delayed'
  if (/进行|打开|执行|active|open|in_progress/.test(text)) return 'in_progress'
  return 'not_started'
}
const normalizeRiskLevel = (value: string | null | undefined): RiskSource['level'] => {
  const text = (value || '').toLowerCase()
  if (/重大|一级|critical/.test(text)) return 'critical'
  if (/较大|二级|high/.test(text)) return 'high'
  if (/一般|三级|中|medium/.test(text)) return 'medium'
  return 'low'
}
const emptyDirConfig: DirConfig = { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 0, enabled: false }

export const useAppStore = defineStore('app', () => {
  const projects = ref<Project[]>([])
  const currentProjectId = ref('')
  const allMembers = ref<Member[]>([])
  const allWbsItems = ref<WbsItem[]>([])
  const allRiskSources = ref<RiskSource[]>([])
  const allQualityMetrics = ref<QualityMetric[]>([])
  const allPlatformMappings = ref<PlatformFieldMapping[]>([])
  const allWbsRiskLinks = ref<WbsRiskLink[]>([])
  const allTasks = ref<Task[]>([])
  const allDailyReports = ref<DailyReport[]>([])
  const informationRecords = ref<ProjectInformationRecord[]>([])
  const allRiskDrafts = ref<RiskDraft[]>([])
  const allFillPackages = ref<FillPackage[]>([])
  const attachments = ref<AttachmentRecord[]>([])
  const documentFolders = ref<DocumentFolderRecord[]>([])
  const logs = ref<OperationLog[]>([])
  const projectSettings = ref<ApiProjectSettings | null>(null)
  const dashboard = ref<ProjectDashboard | null>(null)
  const projectChanges = ref<ProjectChangeRecord[]>([])
  const notifications = ref<NotificationRecord[]>([])
  const loading = ref(false)
  const loadError = ref('')
  const projectSetupRefreshVersion = ref(0)
  const projectCatalogLoaded = ref(false)
  let projectCatalogToken = ''
  let projectCatalogPromise: Promise<void> | null = null

  const currentProject = computed(() => projects.value.find(p => p.id === currentProjectId.value))
  const members = computed(() => allMembers.value.filter(m => m.projectId === currentProjectId.value))
  const wbsItems = computed(() => allWbsItems.value.filter(w => w.projectId === currentProjectId.value))
  const riskSources = computed(() => allRiskSources.value.filter(r => r.projectId === currentProjectId.value))
  const qualityMetrics = computed(() => allQualityMetrics.value.filter(item => item.projectId === currentProjectId.value))
  const platformMappings = computed(() => allPlatformMappings.value.filter(item => item.projectId === currentProjectId.value))
  const wbsRiskLinks = computed(() => allWbsRiskLinks.value.filter(l => wbsItems.value.some(w => w.id === l.wbsId) && riskSources.value.some(r => r.id === l.riskId)))
  const tasks = computed(() => allTasks.value.filter(t => t.projectId === currentProjectId.value))
  const dailyReports = computed(() => allDailyReports.value.filter(r => r.projectId === currentProjectId.value))
  const riskDrafts = computed(() => allRiskDrafts.value.filter(d => d.projectId === currentProjectId.value))
  const fillPackages = computed(() => allFillPackages.value.filter(f => f.projectId === currentProjectId.value))
  const remindRules = computed<RemindRule[]>(() => (projectSettings.value?.reminder_rules || []).map((rule, index) => ({ ...rule, id: rule.id || `rule-${index + 1}` })))
  const dirConfig = computed<DirConfig>(() => projectSettings.value ? { mainDir: projectSettings.value.main_dir || '', archiveDir: projectSettings.value.archive_dir || '', tempDir: projectSettings.value.temp_dir || '', failedDir: projectSettings.value.failed_dir || '', backupDir: projectSettings.value.backup_dir || '', scanInterval: projectSettings.value.scan_interval || 30, enabled: Boolean(projectSettings.value.enabled) } : emptyDirConfig)
  const overdueTasks = computed(() => tasks.value.filter(t => t.status === 'overdue'))
  const pendingTasks = computed(() => tasks.value.filter(t => t.status === 'pending'))
  const processingTasks = computed(() => tasks.value.filter(t => t.status === 'processing'))
  const waitingConfirmTasks = computed(() => tasks.value.filter(t => t.status === 'waiting_confirm'))
  const pendingDailyReports = computed(() => dailyReports.value.filter(r => r.status === 'pending_confirm'))
  const pendingDrafts = computed(() => riskDrafts.value.filter(d => d.status === 'reviewing'))
  const pendingFills = computed(() => fillPackages.value.filter(f => f.status === 'pending'))
  const memberMap = computed(() => Object.fromEntries(allMembers.value.map(member => [member.id, member])))

  function getMemberName(memberId: string) { return memberMap.value[memberId]?.name ?? (memberId || '未指派') }
  function getWbsName(wbsId: string) { return allWbsItems.value.find(w => w.id === wbsId)?.name ?? wbsId }
  function getRiskName(riskId: string) { return allRiskSources.value.find(r => r.id === riskId)?.name ?? riskId }
  function mapProject(row: ApiProject): Project {
    return {
      id: id(row.id),
      name: row.name,
      engineeringTypeDescription: row.engineering_type_description,
      contractStartDate: row.contract_start_date,
      contractEndDate: row.contract_end_date,
      contractDurationDays: row.contract_duration_days,
      contractAmountWanYuan: row.contract_amount_wan_yuan,
      constructionUnitName: row.construction_unit_name,
      generalContractorUnitName: row.general_contractor_unit_name,
      supervisionUnitName: row.supervision_unit_name,
      designUnitName: row.design_unit_name,
      surveyUnitName: row.survey_unit_name,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    }
  }
  function mapMember(row: ApiMember): Member {
    const positions = (row.positions || []).map(position => ({
      id: id(position.id),
      positionId: id(position.position_id),
      name: position.position_name,
      serialNo: position.serial_no,
      certificateNo: position.certificate_no || '',
      responsibilityDescription: position.responsibility_description || '',
    }))
    return {
      id: id(row.user_id),
      projectMemberId: id(row.id),
      username: row.user.username,
      identityCardNo: row.user.identity_card_no,
      systemRole: row.user.role,
      name: row.user.real_name,
      title: positions.map(position => position.name).join('、'),
      phone: '',
      email: '',
      role: positions
        .map(position => position.responsibilityDescription)
        .filter(Boolean),
      positions,
      projectId: id(row.project_id),
    }
  }
  function mapWbs(row: ApiWbs): WbsItem {
    const progress = numeric(row.progress_percent ?? row.progress) || 0
    const statusText = Object.prototype.hasOwnProperty.call(row, 'status_text')
      ? row.status_text || ''
      : row.status || ''
    const normalizedStatusSource = statusText || row.status || ''
    return {
      id: id(row.id), projectId: id(row.project_id), parentId: row.parent_id ? id(row.parent_id) : null,
      code: row.wbs_code || row.code || '', name: row.name, level: row.level, sortOrder: row.sort_order || 0,
      colorValue: row.color_value || undefined, itemType: row.item_type || undefined,
      assignedToText: row.assigned_to_text || undefined,
      planStart: row.planned_start_at || row.planned_start || '', planEnd: row.planned_finish_at || row.planned_finish || '',
      deadline: row.deadline_at || undefined, progress, status: normalizeWbsStatus(normalizedStatusSource), statusText,
      priorityText: row.priority_text || undefined, durationHours: numeric(row.duration_hours),
      estimatedHours: numeric(row.estimated_hours), timeLogMinutes: row.time_log_minutes ?? undefined,
      description: row.description || undefined, budget: numeric(row.budget), actualCost: numeric(row.actual_cost),
      predecessorIds: (row.predecessor_ids || []).map(id), predecessorCodes: row.predecessor_codes || [],
      mspUid: row.msp_uid || undefined, mspId: row.msp_id || undefined,
      sourceCreatedAt: row.source_created_at || undefined, sourceCreator: row.source_creator || undefined,
      sourceProjectPath: row.source_project_path || undefined,
      responsibleId: id(row.responsible_user_id), supervision: row.raw_data?.supervision,
    }
  }
  function mapRisk(row: ApiRisk): RiskSource {
    const levelText = row.risk_level || row.level || '未分级'
    const riskPart = row.risk_part || row.name || '未命名风险源'
    const relatedProcessName = row.related_process_name || row.risk_type || ''
    const evaluationCondition = row.evaluation_condition || row.control_requirements || ''
    return {
      id: id(row.id), projectId: id(row.project_id), serialNo: row.serial_no || 0,
      name: riskPart, riskPart, level: normalizeRiskLevel(levelText), levelText,
      type: relatedProcessName, relatedProcessName,
      controlStart: row.risk_window_start_date || row.planned_start || '',
      controlEnd: row.risk_window_end_date || row.planned_finish || '',
      responsibleId: id(row.responsible_user_id), confirmatorId: id(row.confirmer_user_id),
      materials: row.material_requirements || [], controlMeasures: evaluationCondition,
      evaluationCondition, summary: row.summary || undefined,
    }
  }
  function mapQualityMetric(row: ApiQualityMetric, wbsItems: WbsItem[] = []): QualityMetric {
    const acceptanceItem = row.quality_acceptance_item || row.name || ''
    const controlIndicator = row.control_indicator || row.requirement || ''
    const apiWbsId = id(row.wbs_item_id) || undefined
    const wbsCode = (row.wbs_code || '').trim()
    const matchedWbs = wbsItems.find(item => apiWbsId && item.id === apiWbsId)
      || wbsItems.find(item => wbsCode && item.code.trim() === wbsCode)
    return {
      id: id(row.id), projectId: id(row.project_id), wbsId: matchedWbs?.id || apiWbsId,
      wbsCode: wbsCode || matchedWbs?.code || '', wbsName: row.wbs_name || matchedWbs?.name || undefined,
      name: acceptanceItem, acceptanceItem, requirement: controlIndicator, controlIndicator,
      inspectionFrequency: row.inspection_frequency || '', requiredMaterials: row.required_materials || [],
      relatedDocuments: row.related_documents || '', ownerId: id(row.owner_user_id) || undefined,
      status: row.status || 'pending',
    }
  }
  function mapPlatformMapping(row: ApiPlatformMapping): PlatformFieldMapping { return { id: id(row.id), projectId: id(row.project_id), platformName: row.platform_name, sourceField: row.source_field, targetField: row.target_field, transformRule: row.transform_rule, required: row.required, enabled: row.enabled } }
  function mapTask(row: ApiTask): Task { return { id: id(row.id), projectId: id(row.project_id), title: row.title, type: row.task_type, riskLevel: row.risk_level, responsibleId: id(row.assignee_user_id), confirmatorId: id(row.confirmer_user_id), deadline: row.due_at || '', linkedWbsIds: row.wbs_item_id ? [id(row.wbs_item_id)] : [], linkedRiskId: row.risk_source_id ? id(row.risk_source_id) : undefined, triggerReason: row.trigger_reason || '', missingCount: row.required_materials?.length || 0, workflowSteps: (row.workflow_steps || []).map(step => ({ ...step, status: step.status || 'pending' })), status: uiTaskStatus(row.status), createdAt: row.created_at } }
  function mapDaily(row: ApiDaily): DailyReport { return { id: id(row.id), projectId: id(row.project_id), fileName: row.file_name, fileType: '文件', date: row.report_date || '', constructionContent: row.content || '', currentProgress: 0, cumulativeProgress: 0, problems: '', tomorrowPlan: '', riskContent: '', monitorContent: '', matchedWbsId: row.matched_wbs_id ? id(row.matched_wbs_id) : undefined, confidence: row.confidence, parseStatus: (row.parse_status === 'parsed' ? 'done' : row.parse_status) as DailyReport['parseStatus'], status: row.status, createdAt: row.created_at } }
  function mapDraft(row: ApiDraft): RiskDraft { const risk = allRiskSources.value.find(item => item.id === id(row.risk_source_id)); const draftStatus = row.status === 'pending_review' ? 'reviewing' : row.status; return { id: id(row.id), projectId: id(row.project_id), riskId: id(row.risk_source_id), riskLevel: risk?.level || 'medium', title: row.title, content: row.content, hazardType: risk?.type || '风险上报', deadline: '', measures: '', responsibleId: risk?.responsibleId || '', missingItems: row.missing_items || [], sourceRefs: row.source_refs || [], attachments: [], status: draftStatus as RiskDraft['status'], reviewNote: row.review_note, createdAt: row.created_at, updatedAt: row.updated_at } }
  function mapFill(row: ApiFill): FillPackage { return { id: id(row.id), projectId: id(row.project_id), draftId: id(row.draft_id), platformName: row.platform_name, processName: row.process_name, status: row.status, deadline: '', fields: row.fields || [], attachments: row.attachments || [], createdAt: row.created_at } }
  function mapLog(row: ApiLog): OperationLog { return { id: id(row.id), time: row.created_at, operator: row.operator_id ? getMemberName(id(row.operator_id)) : '系统', action: row.action, detail: row.detail, level: 'info' } }
  function mapAttachment(row: ApiAttachment): AttachmentRecord { return { id: id(row.id), projectId: id(row.project_id), fileName: row.file_name, category: row.category, version: row.version, fileSize: row.file_size, contentType: row.content_type || '', createdAt: row.created_at, folderId: id(row.folder_id) || undefined, snippet: row.snippet } }
  function mapDocumentFolder(row: ApiDocumentFolder): DocumentFolderRecord { return { id: id(row.id), projectId: id(row.project_id), parentId: id(row.parent_id) || undefined, name: row.name, createdAt: row.created_at } }
  function mapInformationRecord(row: ApiInformationRecord): ProjectInformationRecord { return { id: id(row.id), projectId: id(row.project_id), sourceType: row.source_type, sourceName: row.source_name, author: row.author || '', recordedAt: row.recorded_at, status: row.status, confidence: row.confidence, content: row.content, sourceRefs: row.source_refs || [] } }

  async function fetchProjectConfigScope(projectId: string): Promise<ProjectConfigScope> {
    const [memberResult, wbsResult, riskResult, qualityResult, mappingResult, settingsResult] = await Promise.all([
      api.get<ApiEnvelope<ApiMember[]>>(`/projects/${projectId}/members`),
      api.get<ApiEnvelope<ApiWbs[]>>(`/projects/${projectId}/wbs`),
      api.get<ApiEnvelope<ApiRisk[]>>(`/projects/${projectId}/risks`),
      api.get<ApiEnvelope<ApiQualityMetric[]>>(`/projects/${projectId}/quality-metrics`),
      api.get<ApiEnvelope<ApiPlatformMapping[]>>(`/projects/${projectId}/platform-field-mappings`),
      api.get<ApiEnvelope<ApiProjectSettings>>(`/projects/${projectId}/settings`),
    ])
    const settings = settingsResult.data.data
    const wbsItems = wbsResult.data.data.map(mapWbs)
    return {
      members: memberResult.data.data.map(mapMember),
      wbsItems,
      riskSources: riskResult.data.data.map(mapRisk),
      qualityMetrics: qualityResult.data.data.map(row => mapQualityMetric(row, wbsItems)),
      platformMappings: mappingResult.data.data.map(mapPlatformMapping),
      dirConfig: { mainDir: settings.main_dir || '', archiveDir: settings.archive_dir || '', tempDir: settings.temp_dir || '', failedDir: settings.failed_dir || '', backupDir: settings.backup_dir || '', scanInterval: settings.scan_interval || 30, enabled: Boolean(settings.enabled) },
      remindRules: (settings.reminder_rules || []).map((rule, index) => ({ ...rule, id: rule.id || `rule-${index + 1}` })),
    }
  }

  async function loadProjectData(projectId = currentProjectId.value) {
    if (!projectId) return
    const [memberResult, wbsResult, riskResult, qualityResult, mappingResult, linkResult, taskResult, dailyResult, informationResult, draftResult, fillResult, attachmentResult, folderResult, logResult, settingsResult, dashboardResult, changesResult, notificationsResult] = await Promise.all([
      api.get<ApiEnvelope<ApiMember[]>>(`/projects/${projectId}/members`), api.get<ApiEnvelope<ApiWbs[]>>(`/projects/${projectId}/wbs`), api.get<ApiEnvelope<ApiRisk[]>>(`/projects/${projectId}/risks`), api.get<ApiEnvelope<ApiQualityMetric[]>>(`/projects/${projectId}/quality-metrics`), api.get<ApiEnvelope<ApiPlatformMapping[]>>(`/projects/${projectId}/platform-field-mappings`), api.get<ApiEnvelope<ApiLink[]>>(`/projects/${projectId}/wbs-risk-links`), api.get<ApiEnvelope<ApiTask[]>>(`/projects/${projectId}/tasks`), api.get<ApiEnvelope<ApiDaily[]>>(`/projects/${projectId}/daily-reports`), api.get<ApiEnvelope<ApiInformationRecord[]>>(`/projects/${projectId}/information-records`), api.get<ApiEnvelope<ApiDraft[]>>(`/projects/${projectId}/risk-drafts`), api.get<ApiEnvelope<ApiFill[]>>(`/projects/${projectId}/fill-packages`), api.get<ApiEnvelope<ApiAttachment[]>>(`/projects/${projectId}/attachments`), api.get<ApiEnvelope<ApiDocumentFolder[]>>(`/projects/${projectId}/document-folders`), api.get<ApiEnvelope<ApiLog[]>>(`/projects/${projectId}/operation-logs`), api.get<ApiEnvelope<ApiProjectSettings>>(`/projects/${projectId}/settings`), api.get<ApiEnvelope<ProjectDashboard>>(`/projects/${projectId}/dashboard`), api.get<ApiEnvelope<ProjectChangeRecord[]>>(`/projects/${projectId}/changes`), api.get<ApiEnvelope<NotificationRecord[]>>(`/projects/${projectId}/notifications`),
    ])
    allMembers.value = memberResult.data.data.map(mapMember); allWbsItems.value = wbsResult.data.data.map(mapWbs); allRiskSources.value = riskResult.data.data.map(mapRisk); allQualityMetrics.value = qualityResult.data.data.map(row => mapQualityMetric(row, allWbsItems.value)); allPlatformMappings.value = mappingResult.data.data.map(mapPlatformMapping)
    allWbsRiskLinks.value = linkResult.data.data.map(link => ({ id: id(link.id), wbsId: id(link.wbs_item_id), riskId: id(link.risk_source_id), alertDays: link.alert_days, notifyMethods: link.notify_methods, basis: link.basis }))
    allTasks.value = taskResult.data.data.map(mapTask); allDailyReports.value = dailyResult.data.data.map(mapDaily); informationRecords.value = informationResult.data.data.map(mapInformationRecord); allRiskDrafts.value = draftResult.data.data.map(mapDraft); allFillPackages.value = fillResult.data.data.map(mapFill); attachments.value = attachmentResult.data.data.map(mapAttachment); documentFolders.value = folderResult.data.data.map(mapDocumentFolder); logs.value = logResult.data.data.map(mapLog); projectSettings.value = settingsResult.data.data; dashboard.value = dashboardResult.data.data; projectChanges.value = changesResult.data.data; notifications.value = notificationsResult.data.data
  }

  async function loadProjectCatalog(force = false) {
    const token = sessionStorage.getItem('access_token') || ''
    if (!token) {
      projectCatalogLoaded.value = false
      projectCatalogToken = ''
      return
    }
    if (!force && projectCatalogLoaded.value && projectCatalogToken === token) return
    if (!force && projectCatalogPromise) return projectCatalogPromise

    projectCatalogPromise = (async () => {
      const response = await api.get<ApiEnvelope<ApiProject[]>>('/projects')
      projects.value = response.data.data.map(mapProject)
      if (!projects.value.some(project => project.id === currentProjectId.value)) {
        currentProjectId.value = projects.value[0]?.id || ''
      }
      projectCatalogToken = token
      projectCatalogLoaded.value = true
    })()

    try {
      await projectCatalogPromise
    } catch (error) {
      projectCatalogLoaded.value = false
      throw error
    } finally {
      projectCatalogPromise = null
    }
  }

  async function initialize() {
    if (!sessionStorage.getItem('access_token')) return
    loading.value = true
    loadError.value = ''
    try {
      await loadProjectCatalog()
      await loadProjectData()
    } catch {
      loadError.value = '无法连接工程管理服务，请确认后端已启动。'
    } finally {
      loading.value = false
    }
  }
  async function selectProject(projectId: string) { currentProjectId.value = projectId; await loadProjectData(projectId) }
  async function createProject(payload: { name: string }) {
    const response = await api.post<ApiEnvelope<ApiProject>>('/projects', payload)
    const project = mapProject(response.data.data)
    projects.value.unshift(project)
    currentProjectId.value = project.id
    projectCatalogLoaded.value = true
    return project
  }
  function requestProjectSetupRefresh() {
    projectSetupRefreshVersion.value += 1
  }
  function resetSession() {
    projects.value = []
    currentProjectId.value = ''
    projectCatalogLoaded.value = false
    projectCatalogToken = ''
    projectCatalogPromise = null
  }
  async function createProjectChange(payload: { category: string; title: string; content: string }) { await api.post(`/projects/${currentProjectId.value}/changes`, payload); await loadProjectData() }
  async function readNotification(notificationId: number) { await api.post(`/notifications/${notificationId}/read`); await loadProjectData() }
  async function saveProjectSettings(payload: DirConfig & { reminderRules: RemindRule[] }, projectId = currentProjectId.value) { await api.put(`/projects/${projectId}/settings`, { main_dir: payload.mainDir, archive_dir: payload.archiveDir, temp_dir: payload.tempDir, failed_dir: payload.failedDir, backup_dir: payload.backupDir, scan_interval: payload.scanInterval, enabled: payload.enabled, reminder_rules: payload.reminderRules }); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  function wbsWriteRequest(payload: WbsWriteInput) {
    const request: Record<string, unknown> = {
      ...payload,
      parent_id: payload.parent_id ? Number(payload.parent_id) : null,
      predecessor_ids: payload.predecessor_ids?.map(Number),
    }
    if (payload.responsible_user_id !== undefined) {
      request.responsible_user_id = payload.responsible_user_id ? Number(payload.responsible_user_id) : null
    }
    return request
  }
  async function createWbs(payload: WbsWriteInput, projectId = currentProjectId.value) { await api.post(`/projects/${projectId}/wbs`, wbsWriteRequest(payload)); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function updateWbs(itemId: string, payload: WbsWriteInput, projectId = currentProjectId.value) { await api.patch(`/wbs/${itemId}`, wbsWriteRequest(payload)); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function createRisk(payload: RiskWriteInput, projectId = currentProjectId.value) { await api.post(`/projects/${projectId}/risks`, payload); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function updateRisk(riskId: string, payload: RiskWriteInput, projectId = currentProjectId.value) { await api.patch(`/risks/${riskId}`, payload); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  function qualityMetricWriteRequest(payload: QualityMetricWriteInput) {
    return { ...payload, wbs_item_id: payload.wbs_item_id ? Number(payload.wbs_item_id) : null }
  }
  async function createQualityMetric(payload: QualityMetricWriteInput, projectId = currentProjectId.value) { await api.post(`/projects/${projectId}/quality-metrics`, qualityMetricWriteRequest(payload)); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function updateQualityMetric(metricId: string, payload: QualityMetricWriteInput, projectId = currentProjectId.value) { await api.patch(`/quality-metrics/${metricId}`, qualityMetricWriteRequest(payload)); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function createPlatformMapping(payload: Omit<PlatformFieldMapping, 'id' | 'projectId'>, projectId = currentProjectId.value) { await api.post(`/projects/${projectId}/platform-field-mappings`, { platform_name: payload.platformName, source_field: payload.sourceField, target_field: payload.targetField, transform_rule: payload.transformRule, required: payload.required, enabled: payload.enabled }); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function updatePlatformMapping(mappingId: string, payload: Omit<PlatformFieldMapping, 'id' | 'projectId'>, projectId = currentProjectId.value) { await api.patch(`/platform-field-mappings/${mappingId}`, { platform_name: payload.platformName, source_field: payload.sourceField, target_field: payload.targetField, transform_rule: payload.transformRule, required: payload.required, enabled: payload.enabled }); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function removePlatformMapping(mappingId: string, projectId = currentProjectId.value) { await api.delete(`/platform-field-mappings/${mappingId}`); if (projectId === currentProjectId.value) await loadProjectData(projectId) }
  async function createTask(payload: { title: string; task_type: Task['type']; risk_level?: Task['riskLevel']; assignee_user_id?: string; confirmer_user_id?: string; due_at?: string; risk_source_id?: string; wbs_item_id?: string; trigger_reason?: string; required_materials?: string[]; workflow_steps?: Task['workflowSteps'] }) { await api.post(`/projects/${currentProjectId.value}/tasks`, { ...payload, assignee_user_id: payload.assignee_user_id ? Number(payload.assignee_user_id) : null, confirmer_user_id: payload.confirmer_user_id ? Number(payload.confirmer_user_id) : null, risk_source_id: payload.risk_source_id ? Number(payload.risk_source_id) : null, wbs_item_id: payload.wbs_item_id ? Number(payload.wbs_item_id) : null }); await loadProjectData() }
  async function uploadAttachment(file: File, category = '自动归类', folderId?: string) { const body = new FormData(); body.append('file', file); body.append('category', category); if (folderId) body.append('folder_id', folderId); await api.post(`/projects/${currentProjectId.value}/attachments`, body); await loadProjectData() }
  async function updateAttachmentCategory(attachmentId: string, category: string) { await api.patch(`/attachments/${attachmentId}`, { category }); await loadProjectData() }
  async function createDocumentFolder(payload: { name: string; parentId?: string }) { await api.post(`/projects/${currentProjectId.value}/document-folders`, { name: payload.name, parent_id: payload.parentId ? Number(payload.parentId) : null }); await loadProjectData() }
  async function searchDocuments(keyword: string) { if (!keyword.trim()) return [] as AttachmentRecord[]; const response = await api.get<ApiEnvelope<ApiAttachment[]>>(`/projects/${currentProjectId.value}/document-search`, { params: { keyword } }); return response.data.data.map(mapAttachment) }
  async function parseDailyAttachment(attachmentId: string) { await api.post(`/attachments/${attachmentId}/parse-daily`); await loadProjectData() }
  async function createRiskDraft(payload: { risk_source_id: string; title: string; content: string; source_refs?: string[]; missing_items?: string[] }) { await api.post(`/projects/${currentProjectId.value}/risk-drafts`, { ...payload, risk_source_id: Number(payload.risk_source_id) }); await loadProjectData() }
  async function assistRiskDraft(riskId: string) { await api.post(`/projects/${currentProjectId.value}/risk-drafts/assist/${riskId}`); await loadProjectData() }
  async function submitDraftReview(draftId: string) { await api.post(`/risk-drafts/${draftId}/submit-review`); await loadProjectData() }
  async function updateTaskStatus(taskId: string, taskStatus: Task['status'], note?: string) { await api.post(`/tasks/${taskId}/transition`, { status: apiTaskStatus(taskStatus), note }); await loadProjectData() }
  async function updateTaskStep(taskId: string, stepIndex: number, taskStatus: 'pending' | 'processing' | 'completed' | 'blocked') { await api.post(`/tasks/${taskId}/steps/${stepIndex}`, { status: taskStatus }); await loadProjectData() }
  async function reassignTask(taskId: string, assigneeUserId: string, note?: string) { await api.post(`/tasks/${taskId}/reassign`, { assignee_user_id: Number(assigneeUserId), note }); await loadProjectData() }
  async function addTaskNote(taskId: string, note: string) { await api.post(`/tasks/${taskId}/notes`, { note }) }
  async function getTaskHistory(taskId: string) { const response = await api.get<ApiEnvelope<{ history: Array<{ id: number; from_status?: string; to_status: string; note?: string; created_at: string }> }>>(`/tasks/${taskId}`); return response.data.data.history }
  function memberWritePayload(member: MemberWriteInput) {
    return {
      username: member.username || undefined,
      real_name: member.name,
      identity_card_no: member.identityCardNo,
      password: member.password || undefined,
      system_role: member.systemRole || 'user',
      position_name: member.positionName,
      certificate_no: member.certificateNo || '',
      responsibility_description: member.responsibilityDescription || '',
    }
  }
  async function saveMember(member: MemberWriteInput, projectId = currentProjectId.value) {
    await api.post(`/projects/${projectId}/members`, memberWritePayload(member))
    if (projectId === currentProjectId.value) await loadProjectData(projectId)
  }
  async function updateMemberPosition(assignmentId: string, member: MemberWriteInput, projectId = currentProjectId.value) {
    await api.patch(
      `/projects/${projectId}/member-positions/${assignmentId}`,
      memberWritePayload(member),
    )
    if (projectId === currentProjectId.value) await loadProjectData(projectId)
  }
  async function saveRiskSource(risk: Partial<RiskSource>) { await api.post(`/projects/${currentProjectId.value}/risks`, { name: risk.name || '未命名风险源', level: risk.level || 'medium', risk_type: risk.type || '综合风险', material_requirements: risk.materials || [], control_requirements: risk.controlMeasures }); await loadProjectData() }
  async function addWbsRiskLink(link: Omit<WbsRiskLink, 'id'>) { await api.post(`/projects/${currentProjectId.value}/wbs-risk-links`, { wbs_item_id: Number(link.wbsId), risk_source_id: Number(link.riskId), alert_days: link.alertDays, notify_methods: link.notifyMethods, basis: link.basis }); await loadProjectData() }
  async function confirmDailyReport(reportId: string) { await api.post(`/daily-reports/${reportId}/confirm`); await loadProjectData() }
  async function disposeInformationRecord(recordId: string, action: 'confirm' | 'deny' | 'revise', content?: string) { await api.post(`/information-records/${recordId}/dispose`, { action, content }); await loadProjectData() }
  async function confirmDraft(draftId: string, note?: string) { await api.post(`/risk-drafts/${draftId}/confirm`, { note }); await loadProjectData() }
  async function rejectDraft(draftId: string, note: string) { await api.post(`/risk-drafts/${draftId}/return`, { note }); await loadProjectData() }
  async function createFillPackage(draftId: string, payload: { platform_name: string; process_name: string; fields?: Array<{ name: string; value: string }>; attachments?: Array<{ name: string; ready: boolean }> }) { await api.post(`/risk-drafts/${draftId}/fill-package`, payload); await loadProjectData() }
  async function startFilling(packageId: string) { await api.post(`/fill-packages/${packageId}/transition`, { status: 'filling' }); await loadProjectData() }
  async function markFillDone(packageId: string) { await api.post(`/fill-packages/${packageId}/transition`, { status: 'submitted' }); await loadProjectData() }
  async function removeWbsRiskLink(linkId: string) { await api.delete(`/wbs-risk-links/${linkId}`); await loadProjectData() }
  function addLog(log: OperationLog) { if (!currentProjectId.value) return; void api.post(`/projects/${currentProjectId.value}/operation-logs`, { action: log.action, detail: log.detail }).then(() => loadProjectData()) }

  return { projects, currentProjectId, currentProject, members, memberMap, wbsItems, riskSources, qualityMetrics, platformMappings, wbsRiskLinks, tasks, dailyReports, informationRecords, riskDrafts, fillPackages, attachments, documentFolders, remindRules, dirConfig, logs, dashboard, projectChanges, notifications, loading, loadError, projectSetupRefreshVersion, projectCatalogLoaded, overdueTasks, pendingTasks, processingTasks, waitingConfirmTasks, pendingDailyReports, pendingDrafts, pendingFills, getMemberName, getWbsName, getRiskName, initialize, loadProjectCatalog, requestProjectSetupRefresh, resetSession, selectProject, createProject, createProjectChange, readNotification, saveProjectSettings, createWbs, updateWbs, createRisk, updateRisk, createQualityMetric, updateQualityMetric, createPlatformMapping, updatePlatformMapping, removePlatformMapping, createTask, uploadAttachment, updateAttachmentCategory, createDocumentFolder, searchDocuments, parseDailyAttachment, createRiskDraft, assistRiskDraft, submitDraftReview, loadProjectData, fetchProjectConfigScope, saveMember, updateMemberPosition, saveRiskSource, addWbsRiskLink, updateTaskStatus, updateTaskStep, reassignTask, addTaskNote, getTaskHistory, confirmDailyReport, disposeInformationRecord, confirmDraft, rejectDraft, createFillPackage, startFilling, markFillDone, removeWbsRiskLink, addLog }
})
