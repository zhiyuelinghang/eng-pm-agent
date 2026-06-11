import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  mockProjects, mockMembers, mockWbs, mockRisks, mockLinks,
  mockTasks, mockDailyReports, mockDrafts, mockFillPackages,
  mockRemindRulesByProject, mockDirConfigsByProject, mockLogs,
} from '@/mock/data'
import type { Task, DailyReport, RiskDraft, FillPackage, OperationLog, Member, RiskSource, WbsRiskLink } from '@/types'

export const useAppStore = defineStore('app', () => {
  const projects = ref([...mockProjects])
  const currentProjectId = ref('p1')
  const allMembers = ref([...mockMembers])
  const allWbsItems = ref([...mockWbs])
  const allRiskSources = ref([...mockRisks])
  const allWbsRiskLinks = ref([...mockLinks])
  const allTasks = ref<Task[]>([...mockTasks])
  const allDailyReports = ref<DailyReport[]>([...mockDailyReports])
  const allRiskDrafts = ref<RiskDraft[]>([...mockDrafts])
  const allFillPackages = ref<FillPackage[]>([...mockFillPackages])
  const remindRuleSets = ref(mockRemindRulesByProject)
  const dirConfigSets = ref(mockDirConfigsByProject)
  const logs = ref<OperationLog[]>([...mockLogs])

  const currentProject = computed(() => projects.value.find(p => p.id === currentProjectId.value))
  const members = computed(() => allMembers.value.filter(m => m.projectId === currentProjectId.value))
  const wbsItems = computed(() => allWbsItems.value.filter(w => w.projectId === currentProjectId.value))
  const riskSources = computed(() => allRiskSources.value.filter(r => r.projectId === currentProjectId.value))
  const wbsRiskLinks = computed(() => {
    const currentWbsIds = new Set(wbsItems.value.map(w => w.id))
    const currentRiskIds = new Set(riskSources.value.map(r => r.id))
    return allWbsRiskLinks.value.filter(l => currentWbsIds.has(l.wbsId) && currentRiskIds.has(l.riskId))
  })
  const tasks = computed(() => allTasks.value.filter(t => t.projectId === currentProjectId.value))
  const dailyReports = computed(() => allDailyReports.value.filter(r => r.projectId === currentProjectId.value))
  const riskDrafts = computed(() => allRiskDrafts.value.filter(d => d.projectId === currentProjectId.value))
  const fillPackages = computed(() => allFillPackages.value.filter(f => f.projectId === currentProjectId.value))
  const remindRules = computed(() => remindRuleSets.value[currentProjectId.value] ?? [])
  const dirConfig = computed(() => dirConfigSets.value[currentProjectId.value] ?? dirConfigSets.value.p1)
  const overdueTasks = computed(() => tasks.value.filter(t => t.status === 'overdue'))
  const pendingTasks = computed(() => tasks.value.filter(t => t.status === 'pending'))
  const processingTasks = computed(() => tasks.value.filter(t => t.status === 'processing'))
  const waitingConfirmTasks = computed(() => tasks.value.filter(t => t.status === 'waiting_confirm'))
  const pendingDailyReports = computed(() => dailyReports.value.filter(r => r.status === 'pending_confirm'))
  const pendingDrafts = computed(() => riskDrafts.value.filter(d => d.status === 'reviewing'))
  const pendingFills = computed(() => fillPackages.value.filter(f => f.status === 'pending'))
  const memberMap = computed(() => Object.fromEntries(allMembers.value.map(m => [m.id, m])))

  function getMemberName(id: string) { return memberMap.value[id]?.name ?? id }
  function getWbsName(id: string) { return allWbsItems.value.find(w => w.id === id)?.name ?? id }
  function getRiskName(id: string) { return allRiskSources.value.find(r => r.id === id)?.name ?? id }

  function updateTaskStatus(taskId: string, status: Task['status']) {
    const t = allTasks.value.find(t => t.id === taskId)
    if (t) t.status = status
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '更新任务状态', detail: `任务「${t?.title}」状态变更为 ${status}`, level: 'info' })
  }

  function saveMember(member: Partial<Member>) {
    const payload: Member = {
      id: member.id || `m${Date.now()}`,
      name: member.name || '未命名成员',
      title: member.title || '项目成员',
      phone: member.phone || '',
      email: member.email || '',
      role: member.role || [],
      projectId: member.projectId || currentProjectId.value,
    }
    const idx = allMembers.value.findIndex(item => item.id === payload.id)
    if (idx >= 0) allMembers.value[idx] = payload
    else allMembers.value.push(payload)
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '李明', action: idx >= 0 ? '更新成员责任' : '添加项目成员', detail: `成员「${payload.name}」已保存`, level: 'success', relatedId: payload.id })
  }

  function saveRiskSource(risk: Partial<RiskSource>) {
    const payload: RiskSource = {
      id: risk.id || `r${Date.now()}`,
      name: risk.name || '未命名风险源',
      level: (risk.level || 'medium') as RiskSource['level'],
      type: risk.type || '综合风险',
      controlStart: risk.controlStart || '2026-06-01',
      controlEnd: risk.controlEnd || '2026-06-30',
      responsibleId: risk.responsibleId || members.value[0]?.id || 'm1',
      confirmatorId: risk.confirmatorId || members.value[0]?.id || 'm1',
      materials: risk.materials?.length ? risk.materials : ['现场照片', '监测资料'],
      controlMeasures: risk.controlMeasures || '',
      projectId: risk.projectId || currentProjectId.value,
    }
    const idx = allRiskSources.value.findIndex(item => item.id === payload.id)
    if (idx >= 0) allRiskSources.value[idx] = payload
    else allRiskSources.value.push(payload)
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '李明', action: idx >= 0 ? '更新风险源' : '添加风险源', detail: `风险源「${payload.name}」已保存`, level: 'success', relatedId: payload.id })
  }

  function addWbsRiskLink(link: Omit<WbsRiskLink, 'id'>) {
    const payload: WbsRiskLink = { id: `l${Date.now()}`, ...link }
    allWbsRiskLinks.value.push(payload)
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '李明', action: '添加 WBS-风险关联', detail: `${getWbsName(payload.wbsId)} 关联 ${getRiskName(payload.riskId)}`, level: 'success', relatedId: payload.id })
  }

  function confirmDailyReport(reportId: string) {
    const r = allDailyReports.value.find(r => r.id === reportId)
    if (r) r.status = 'confirmed'
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '确认日报解析', detail: `日报「${r?.fileName}」已确认`, level: 'success' })
  }

  function confirmDraft(draftId: string) {
    const d = allRiskDrafts.value.find(d => d.id === draftId)
    if (d) d.status = 'confirmed'
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '审核确认草稿', detail: `草稿「${d?.title}」审核通过`, level: 'success' })
  }

  function rejectDraft(draftId: string, note: string) {
    const d = allRiskDrafts.value.find(d => d.id === draftId)
    if (d) { d.status = 'rejected'; d.reviewNote = note }
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '退回草稿', detail: `草稿「${d?.title}」已退回，原因：${note}`, level: 'warning' })
  }

  function startFilling(packageId: string) {
    const f = allFillPackages.value.find(f => f.id === packageId)
    if (f) f.status = 'filling'
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '启动填报助手', detail: `填报包「${packageId}」开始填报`, level: 'info' })
  }

  function markFillDone(packageId: string) {
    const f = allFillPackages.value.find(f => f.id === packageId)
    if (f) f.status = 'submitted'
    addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '张伟', action: '标记填报完成', detail: `填报包「${packageId}」已标记为已提交`, level: 'success' })
  }

  function removeWbsRiskLink(linkId: string) {
    const idx = allWbsRiskLinks.value.findIndex(l => l.id === linkId)
    if (idx > -1) allWbsRiskLinks.value.splice(idx, 1)
  }

  function addLog(log: OperationLog) {
    logs.value.unshift(log)
  }

  function nowStr() {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`
  }

  return {
    projects, currentProjectId, currentProject,
    members, memberMap, wbsItems, riskSources, wbsRiskLinks,
    tasks, dailyReports, riskDrafts, fillPackages, remindRules, dirConfig, logs,
    overdueTasks, pendingTasks, processingTasks, waitingConfirmTasks,
    pendingDailyReports, pendingDrafts, pendingFills,
    getMemberName, getWbsName, getRiskName,
    saveMember, saveRiskSource, addWbsRiskLink,
    updateTaskStatus, confirmDailyReport, confirmDraft, rejectDraft,
    startFilling, markFillDone, removeWbsRiskLink, addLog,
  }
})
