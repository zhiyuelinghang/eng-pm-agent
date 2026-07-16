import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import api, { type ApiEnvelope } from '@/api/client'
import type { DailyReport, DirConfig, FillPackage, Member, OperationLog, Project, RemindRule, RiskDraft, RiskSource, Task, WbsItem, WbsRiskLink } from '@/types'

type ApiProject = { id: number; project_name: string; owner_unit?: string; description?: string; status: Project['status']; created_at: string }
type ApiMember = { id: number; project_id: number; user_id: number; member_role: string; display_name?: string; phone?: string; responsibilities: string[]; user: { real_name: string; title?: string; email?: string; phone?: string } }
type ApiWbs = { id: number; project_id: number; parent_id?: number; code: string; name: string; level: number; planned_start?: string; planned_finish?: string; progress: number; status: WbsItem['status']; responsible_user_id?: number }
type ApiRisk = { id: number; project_id: number; name: string; level: RiskSource['level']; risk_type: string; planned_start?: string; planned_finish?: string; responsible_user_id?: number; confirmer_user_id?: number; material_requirements: string[]; control_requirements?: string }
type ApiLink = { id: number; project_id: number; wbs_item_id: number; risk_source_id: number; alert_days: number; notify_methods: string[]; basis?: string }
type ApiTask = { id: number; project_id: number; title: string; task_type: Task['type']; risk_level: Task['riskLevel']; assignee_user_id?: number; confirmer_user_id?: number; due_at?: string; wbs_item_id?: number; risk_source_id?: number; trigger_reason?: string; required_materials: string[]; status: string; created_at: string }
type ApiDaily = { id: number; project_id: number; file_name: string; report_date?: string; content?: string; matched_wbs_id?: number; confidence: number; parse_status: string; status: DailyReport['status']; created_at: string }
type ApiDraft = { id: number; project_id: number; risk_source_id: number; title: string; content: string; status: string; source_refs: string[]; missing_items: string[]; review_note?: string; created_at: string; updated_at: string }
type ApiFill = { id: number; project_id: number; draft_id: number; platform_name: string; process_name: string; status: FillPackage['status']; fields: FillPackage['fields']; attachments: FillPackage['attachments']; created_at: string }
type ApiLog = { id: number; created_at: string; action: string; detail: string; operator_id?: number }
type ApiProjectSettings = { project_id: number; main_dir?: string; archive_dir?: string; temp_dir?: string; failed_dir?: string; backup_dir?: string; scan_interval?: number; enabled?: boolean; reminder_rules?: Array<{ id?: string; level: RemindRule['level']; days: number; enabled: boolean; frequency?: string }> }
export type AttachmentRecord = { id: string; projectId: string; fileName: string; category: string; version: number; fileSize: number; contentType: string; createdAt: string }
type ApiAttachment = { id: number; project_id: number; file_name: string; category: string; version: number; file_size: number; content_type?: string; created_at: string }

const uiTaskStatus = (status: string): Task['status'] => ({ completed: 'done', pending_confirm: 'waiting_confirm' }[status] ?? status) as Task['status']
const apiTaskStatus = (status: Task['status']) => ({ done: 'completed', waiting_confirm: 'pending_confirm' } as Partial<Record<Task['status'], string>>)[status] ?? status
const id = (value?: number | string | null) => value == null ? '' : String(value)
const emptyDirConfig: DirConfig = { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 0, enabled: false }

export const useAppStore = defineStore('app', () => {
  const projects = ref<Project[]>([])
  const currentProjectId = ref('')
  const allMembers = ref<Member[]>([])
  const allWbsItems = ref<WbsItem[]>([])
  const allRiskSources = ref<RiskSource[]>([])
  const allWbsRiskLinks = ref<WbsRiskLink[]>([])
  const allTasks = ref<Task[]>([])
  const allDailyReports = ref<DailyReport[]>([])
  const allRiskDrafts = ref<RiskDraft[]>([])
  const allFillPackages = ref<FillPackage[]>([])
  const attachments = ref<AttachmentRecord[]>([])
  const logs = ref<OperationLog[]>([])
  const projectSettings = ref<ApiProjectSettings | null>(null)
  const loading = ref(false)
  const loadError = ref('')

  const currentProject = computed(() => projects.value.find(p => p.id === currentProjectId.value))
  const members = computed(() => allMembers.value.filter(m => m.projectId === currentProjectId.value))
  const wbsItems = computed(() => allWbsItems.value.filter(w => w.projectId === currentProjectId.value))
  const riskSources = computed(() => allRiskSources.value.filter(r => r.projectId === currentProjectId.value))
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
  function mapProject(row: ApiProject): Project { return { id: id(row.id), name: row.project_name, ownerUnit: row.owner_unit ?? '', description: row.description, status: row.status, createdAt: row.created_at } }
  function mapMember(row: ApiMember): Member { return { id: id(row.user_id), name: row.display_name || row.user.real_name, title: row.user.title || row.member_role, phone: row.phone || row.user.phone || '', email: row.user.email || '', role: row.responsibilities || [], projectId: id(row.project_id) } }
  function mapWbs(row: ApiWbs): WbsItem { return { id: id(row.id), projectId: id(row.project_id), parentId: row.parent_id ? id(row.parent_id) : null, code: row.code, name: row.name, level: row.level, planStart: row.planned_start || '', planEnd: row.planned_finish || '', progress: row.progress, status: row.status, responsibleId: id(row.responsible_user_id) } }
  function mapRisk(row: ApiRisk): RiskSource { return { id: id(row.id), projectId: id(row.project_id), name: row.name, level: row.level, type: row.risk_type, controlStart: row.planned_start || '', controlEnd: row.planned_finish || '', responsibleId: id(row.responsible_user_id), confirmatorId: id(row.confirmer_user_id), materials: row.material_requirements || [], controlMeasures: row.control_requirements } }
  function mapTask(row: ApiTask): Task { return { id: id(row.id), projectId: id(row.project_id), title: row.title, type: row.task_type, riskLevel: row.risk_level, responsibleId: id(row.assignee_user_id), confirmatorId: id(row.confirmer_user_id), deadline: row.due_at || '', linkedWbsIds: row.wbs_item_id ? [id(row.wbs_item_id)] : [], linkedRiskId: row.risk_source_id ? id(row.risk_source_id) : undefined, triggerReason: row.trigger_reason || '', missingCount: row.required_materials?.length || 0, status: uiTaskStatus(row.status), createdAt: row.created_at } }
  function mapDaily(row: ApiDaily): DailyReport { return { id: id(row.id), projectId: id(row.project_id), fileName: row.file_name, fileType: '文件', date: row.report_date || '', constructionContent: row.content || '', currentProgress: 0, cumulativeProgress: 0, problems: '', tomorrowPlan: '', riskContent: '', monitorContent: '', matchedWbsId: row.matched_wbs_id ? id(row.matched_wbs_id) : undefined, confidence: row.confidence, parseStatus: (row.parse_status === 'parsed' ? 'done' : row.parse_status) as DailyReport['parseStatus'], status: row.status, createdAt: row.created_at } }
  function mapDraft(row: ApiDraft): RiskDraft { const risk = allRiskSources.value.find(item => item.id === id(row.risk_source_id)); const draftStatus = row.status === 'pending_review' ? 'reviewing' : row.status; return { id: id(row.id), projectId: id(row.project_id), riskId: id(row.risk_source_id), riskLevel: risk?.level || 'medium', title: row.title, content: row.content, hazardType: risk?.type || '风险上报', deadline: '', measures: '', responsibleId: risk?.responsibleId || '', missingItems: row.missing_items || [], sourceRefs: row.source_refs || [], attachments: [], status: draftStatus as RiskDraft['status'], reviewNote: row.review_note, createdAt: row.created_at, updatedAt: row.updated_at } }
  function mapFill(row: ApiFill): FillPackage { return { id: id(row.id), projectId: id(row.project_id), draftId: id(row.draft_id), platformName: row.platform_name, processName: row.process_name, status: row.status, deadline: '', fields: row.fields || [], attachments: row.attachments || [], createdAt: row.created_at } }
  function mapLog(row: ApiLog): OperationLog { return { id: id(row.id), time: row.created_at, operator: row.operator_id ? getMemberName(id(row.operator_id)) : '系统', action: row.action, detail: row.detail, level: 'info' } }
  function mapAttachment(row: ApiAttachment): AttachmentRecord { return { id: id(row.id), projectId: id(row.project_id), fileName: row.file_name, category: row.category, version: row.version, fileSize: row.file_size, contentType: row.content_type || '', createdAt: row.created_at } }

  async function loadProjectData(projectId = currentProjectId.value) {
    if (!projectId) return
    const [memberResult, wbsResult, riskResult, linkResult, taskResult, dailyResult, draftResult, fillResult, attachmentResult, logResult, settingsResult] = await Promise.all([
      api.get<ApiEnvelope<ApiMember[]>>(`/projects/${projectId}/members`), api.get<ApiEnvelope<ApiWbs[]>>(`/projects/${projectId}/wbs`), api.get<ApiEnvelope<ApiRisk[]>>(`/projects/${projectId}/risks`), api.get<ApiEnvelope<ApiLink[]>>(`/projects/${projectId}/wbs-risk-links`), api.get<ApiEnvelope<ApiTask[]>>(`/projects/${projectId}/tasks`), api.get<ApiEnvelope<ApiDaily[]>>(`/projects/${projectId}/daily-reports`), api.get<ApiEnvelope<ApiDraft[]>>(`/projects/${projectId}/risk-drafts`), api.get<ApiEnvelope<ApiFill[]>>(`/projects/${projectId}/fill-packages`), api.get<ApiEnvelope<ApiAttachment[]>>(`/projects/${projectId}/attachments`), api.get<ApiEnvelope<ApiLog[]>>(`/projects/${projectId}/operation-logs`), api.get<ApiEnvelope<ApiProjectSettings>>(`/projects/${projectId}/settings`),
    ])
    allMembers.value = memberResult.data.data.map(mapMember); allWbsItems.value = wbsResult.data.data.map(mapWbs); allRiskSources.value = riskResult.data.data.map(mapRisk)
    allWbsRiskLinks.value = linkResult.data.data.map(link => ({ id: id(link.id), wbsId: id(link.wbs_item_id), riskId: id(link.risk_source_id), alertDays: link.alert_days, notifyMethods: link.notify_methods, basis: link.basis }))
    allTasks.value = taskResult.data.data.map(mapTask); allDailyReports.value = dailyResult.data.data.map(mapDaily); allRiskDrafts.value = draftResult.data.data.map(mapDraft); allFillPackages.value = fillResult.data.data.map(mapFill); attachments.value = attachmentResult.data.data.map(mapAttachment); logs.value = logResult.data.data.map(mapLog); projectSettings.value = settingsResult.data.data
  }

  async function initialize() {
    if (!sessionStorage.getItem('access_token')) return
    loading.value = true; loadError.value = ''
    try { const response = await api.get<ApiEnvelope<ApiProject[]>>('/projects'); projects.value = response.data.data.map(mapProject); currentProjectId.value = currentProjectId.value || projects.value[0]?.id || ''; await loadProjectData() } catch { loadError.value = '无法连接工程管理服务，请确认后端已启动。' } finally { loading.value = false }
  }
  async function selectProject(projectId: string) { currentProjectId.value = projectId; await loadProjectData(projectId) }
  async function createProject(payload: { project_name: string; owner_unit?: string; description?: string }) { const response = await api.post<ApiEnvelope<ApiProject>>('/projects', payload); const project = mapProject(response.data.data); projects.value.unshift(project); currentProjectId.value = project.id; await loadProjectData(project.id); return project }
  async function saveProjectSettings(payload: DirConfig & { reminderRules: RemindRule[] }) { await api.put(`/projects/${currentProjectId.value}/settings`, { main_dir: payload.mainDir, archive_dir: payload.archiveDir, temp_dir: payload.tempDir, failed_dir: payload.failedDir, backup_dir: payload.backupDir, scan_interval: payload.scanInterval, enabled: payload.enabled, reminder_rules: payload.reminderRules }); await loadProjectData() }
  async function createWbs(payload: { code: string; name: string; planned_start?: string; planned_finish?: string }) { await api.post(`/projects/${currentProjectId.value}/wbs`, payload); await loadProjectData() }
  async function createRisk(payload: { name: string; level: RiskSource['level']; risk_type?: string; material_requirements?: string[] }) { await api.post(`/projects/${currentProjectId.value}/risks`, payload); await loadProjectData() }
  async function createTask(payload: { title: string; task_type: Task['type']; risk_level?: Task['riskLevel']; assignee_user_id?: string; confirmer_user_id?: string; due_at?: string; risk_source_id?: string; wbs_item_id?: string; trigger_reason?: string; required_materials?: string[] }) { await api.post(`/projects/${currentProjectId.value}/tasks`, { ...payload, assignee_user_id: payload.assignee_user_id ? Number(payload.assignee_user_id) : null, confirmer_user_id: payload.confirmer_user_id ? Number(payload.confirmer_user_id) : null, risk_source_id: payload.risk_source_id ? Number(payload.risk_source_id) : null, wbs_item_id: payload.wbs_item_id ? Number(payload.wbs_item_id) : null }); await loadProjectData() }
  async function uploadAttachment(file: File, category = '自动归类') { const body = new FormData(); body.append('file', file); body.append('category', category); await api.post(`/projects/${currentProjectId.value}/attachments`, body); await loadProjectData() }
  async function parseDailyAttachment(attachmentId: string) { await api.post(`/attachments/${attachmentId}/parse-daily`); await loadProjectData() }
  async function createRiskDraft(payload: { risk_source_id: string; title: string; content: string; source_refs?: string[]; missing_items?: string[] }) { await api.post(`/projects/${currentProjectId.value}/risk-drafts`, { ...payload, risk_source_id: Number(payload.risk_source_id) }); await loadProjectData() }
  async function submitDraftReview(draftId: string) { await api.post(`/risk-drafts/${draftId}/submit-review`); await loadProjectData() }
  async function updateTaskStatus(taskId: string, taskStatus: Task['status']) { await api.post(`/tasks/${taskId}/transition`, { status: apiTaskStatus(taskStatus) }); await loadProjectData() }
  async function saveMember(member: Partial<Member> & { username?: string }) { await api.post(`/projects/${currentProjectId.value}/members`, { username: member.username || undefined, real_name: member.name || '未命名成员', phone: member.phone, email: member.email, title: member.title, responsibilities: member.role || [] }); await loadProjectData() }
  async function saveRiskSource(risk: Partial<RiskSource>) { await api.post(`/projects/${currentProjectId.value}/risks`, { name: risk.name || '未命名风险源', level: risk.level || 'medium', risk_type: risk.type || '综合风险', material_requirements: risk.materials || [], control_requirements: risk.controlMeasures }); await loadProjectData() }
  async function addWbsRiskLink(link: Omit<WbsRiskLink, 'id'>) { await api.post(`/projects/${currentProjectId.value}/wbs-risk-links`, { wbs_item_id: Number(link.wbsId), risk_source_id: Number(link.riskId), alert_days: link.alertDays, notify_methods: link.notifyMethods, basis: link.basis }); await loadProjectData() }
  async function confirmDailyReport(reportId: string) { await api.post(`/daily-reports/${reportId}/confirm`); await loadProjectData() }
  async function confirmDraft(draftId: string, note?: string) { await api.post(`/risk-drafts/${draftId}/confirm`, { note }); await loadProjectData() }
  async function rejectDraft(draftId: string, note: string) { await api.post(`/risk-drafts/${draftId}/return`, { note }); await loadProjectData() }
  async function createFillPackage(draftId: string, payload: { platform_name: string; process_name: string; fields?: Array<{ name: string; value: string }>; attachments?: Array<{ name: string; ready: boolean }> }) { await api.post(`/risk-drafts/${draftId}/fill-package`, payload); await loadProjectData() }
  async function startFilling(packageId: string) { await api.post(`/fill-packages/${packageId}/transition`, { status: 'filling' }); await loadProjectData() }
  async function markFillDone(packageId: string) { await api.post(`/fill-packages/${packageId}/transition`, { status: 'submitted' }); await loadProjectData() }
  async function removeWbsRiskLink(linkId: string) { await api.delete(`/wbs-risk-links/${linkId}`); await loadProjectData() }
  function addLog(log: OperationLog) { if (!currentProjectId.value) return; void api.post(`/projects/${currentProjectId.value}/operation-logs`, { action: log.action, detail: log.detail }).then(() => loadProjectData()) }

  return { projects, currentProjectId, currentProject, members, memberMap, wbsItems, riskSources, wbsRiskLinks, tasks, dailyReports, riskDrafts, fillPackages, attachments, remindRules, dirConfig, logs, loading, loadError, overdueTasks, pendingTasks, processingTasks, waitingConfirmTasks, pendingDailyReports, pendingDrafts, pendingFills, getMemberName, getWbsName, getRiskName, initialize, selectProject, createProject, saveProjectSettings, createWbs, createRisk, createTask, uploadAttachment, parseDailyAttachment, createRiskDraft, submitDraftReview, loadProjectData, saveMember, saveRiskSource, addWbsRiskLink, updateTaskStatus, confirmDailyReport, confirmDraft, rejectDraft, createFillPackage, startFilling, markFillDone, removeWbsRiskLink, addLog }
})
