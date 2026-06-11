<template>
  <div class="admin-view">
    <AdminPageHeader
      title="项目注册/管理"
      subtitle="统一管理平台内所有项目主数据；点击「进入工作台」弹出项目配置工作台，在弹窗内完成成员、WBS、风险源等全部配置。"
    >
      <template #actions>
        <n-button type="primary" @click="openCreateModal">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          创建项目
        </n-button>
      </template>
    </AdminPageHeader>

    <!-- 项目列表卡片形式 -->
    <div class="admin-panel">
      <table class="ops-table">
        <thead>
          <tr>
            <th>项目名称</th>
            <th>所属单位</th>
            <th>状态</th>
            <th>项目说明</th>
            <th>创建时间</th>
            <th style="text-align: center; width: 280px;">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in store.projects" :key="item.id" :class="{ 'row-active': store.currentProjectId === item.id }">
            <td>
              <div class="project-name-group">
                <span class="p-name">{{ item.name }}</span>
              </div>
            </td>
            <td><span class="cell-primary">{{ item.ownerUnit }}</span></td>
            <td>
              <n-tag :type="getStatusTagType(item.status ?? 'active')" size="small" round>
                {{ getStatusLabel(item.status ?? 'active') }}
              </n-tag>
            </td>
            <td><span class="cell-secondary">{{ item.description || '—' }}</span></td>
            <td><span class="font-mono text-muted">{{ item.createdAt }}</span></td>
            <td>
              <div class="action-cell">
                <button class="tbtn tbtn--primary" @click="openProjectWorkspace(item)">进入工作台</button>
                <button class="tbtn" @click="openEditModal(item)">编辑</button>
                <button class="tbtn tbtn--danger" @click="handleDelete(item.id)" :disabled="store.projects.length <= 1">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <n-modal v-model:show="workspaceVisible" :mask-closable="false">
      <div v-if="workspaceProject" class="project-workspace">
        <header class="workspace-topbar">
          <div class="workspace-topbar-left">
            <span class="workspace-kicker">正在配置</span>
            <h2 class="workspace-title">{{ workspaceProject.name }}</h2>
            <n-tag :type="getStatusTagType(workspaceProject.status)" size="small" round>
              {{ getStatusLabel(workspaceProject.status) }}
            </n-tag>
          </div>
          <div class="workspace-topbar-right">
            <span class="workspace-owner">{{ workspaceProject.ownerUnit }}</span>
            <button class="workspace-close" title="关闭并返回项目列表" @click="workspaceVisible = false">
              <n-icon :size="18"><X /></n-icon>
            </button>
          </div>
        </header>

        <div class="workspace-body">
          <aside class="workspace-nav">
            <button
              v-for="item in workspaceMenus"
              :key="item.key"
              :class="['workspace-nav-item', { active: activeModuleKey === item.key }]"
              @click="activeModuleKey = item.key"
            >
              <n-icon :size="15"><component :is="item.icon" /></n-icon>
              <span>{{ item.title }}</span>
            </button>
          </aside>
          <section class="workspace-main">
            <component :is="activeModule.component" :key="`${workspaceProject.id}-${activeModuleKey}`" />
          </section>
        </div>
      </div>
    </n-modal>

    <!-- 注册或修改 Modal -->
    <n-modal 
      v-model:show="showModal" 
      preset="card" 
      style="width: 650px;" 
      class="custom-modal" 
      :title="isEdit ? '编辑项目' : '创建项目'"
    >
      <n-form :model="form" label-placement="top" size="small" class="grid-form">
        <n-form-item label="工程项目全称" class="col-span-full">
          <n-input v-model:value="form.name" placeholder="请输入项目全称" />
        </n-form-item>
        <n-form-item label="所属单位" class="col-span-1">
          <n-input v-model:value="form.ownerUnit" placeholder="请输入所属单位" />
        </n-form-item>
        <n-form-item label="项目状态" class="col-span-1">
          <n-select v-model:value="form.status" :options="statusOptions" />
        </n-form-item>
        <n-form-item label="项目说明" class="col-span-full">
          <n-input v-model:value="form.description" type="textarea" :rows="3" placeholder="请输入项目说明" />
        </n-form-item>
      </n-form>
      <template #action>
        <div class="modal-footer">
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" @click="submitForm">确认并导入底座</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, markRaw } from 'vue'
import { useAppStore } from '@/stores/app'
import type { Project } from '@/types'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import MemberConfigView from './MemberConfigView.vue'
import WbsImportView from './WbsImportView.vue'
import RiskSourceView from './RiskSourceView.vue'
import WbsRiskLinkView from './WbsRiskLinkView.vue'
import DailyDirConfigView from './DailyDirConfigView.vue'
import RemindRuleView from './RemindRuleView.vue'
import ReportTemplateView from './ReportTemplateView.vue'
import PlatformFieldMappingView from './PlatformFieldMappingView.vue'
import { useMessage, NForm, NFormItem, NInput, NSelect, NButton, NModal, NTag, NIcon } from 'naive-ui'
import { Users, Table, ShieldCheck, Link, Folder, Bell, X } from '@vicons/tabler'

type ProjectStatus = Project['status']

interface ProjectForm {
  name: string
  ownerUnit: string
  status: ProjectStatus
  description: string
}

const store = useAppStore()
const message = useMessage()

const workspaceVisible = ref(false)
const workspaceProject = ref<Project | null>(null)
const activeModuleKey = ref('members')

const workspaceMenus = [
  { key: 'members',       title: '成员与责任',  icon: Users,       component: markRaw(MemberConfigView) },
  { key: 'wbs',           title: 'WBS 导入中心', icon: Table,       component: markRaw(WbsImportView) },
  { key: 'risk-sources',  title: '风险源管理',  icon: ShieldCheck, component: markRaw(RiskSourceView) },
  { key: 'wbs-risk-link', title: 'WBS-风险映射', icon: Link,        component: markRaw(WbsRiskLinkView) },
  { key: 'daily-dir',     title: '日报目录规则', icon: Folder,      component: markRaw(DailyDirConfigView) },
  { key: 'rules',         title: '提醒预警规则', icon: Bell,        component: markRaw(RemindRuleView) },
  { key: 'templates',     title: '上报模板配置', icon: Table,       component: markRaw(ReportTemplateView) },
  { key: 'field-mapping', title: '平台字段映射', icon: Link,        component: markRaw(PlatformFieldMappingView) },
]

const activeModule = computed(() =>
  workspaceMenus.find(m => m.key === activeModuleKey.value) ?? workspaceMenus[0]
)

const statusOptions: Array<{ label: string; value: ProjectStatus }> = [
  { label: '启用', value: 'active' },
  { label: '停用', value: 'inactive' },
  { label: '归档', value: 'archived' },
]

const showModal = ref(false)
const isEdit = ref(false)
const editId = ref('')

const form = reactive<ProjectForm>({
  name: '',
  ownerUnit: '',
  status: 'active',
  description: ''
})

const getStatusTagType = (status: ProjectStatus) => {
  switch (status) {
    case 'active': return 'success'
    case 'inactive': return 'warning'
    case 'archived': return 'info'
    default: return 'info'
  }
}

const getStatusLabel = (status: ProjectStatus) => {
  switch (status) {
    case 'active': return '启用'
    case 'inactive': return '停用'
    case 'archived': return '归档'
    default: return status
  }
}

const openCreateModal = () => {
  isEdit.value = false
  editId.value = ''
  Object.assign(form, {
    name: '',
    ownerUnit: '',
    status: 'active',
    description: ''
  })
  showModal.value = true
}

const openEditModal = (item: Project) => {
  isEdit.value = true
  editId.value = item.id
  Object.assign(form, {
    name: item.name,
    ownerUnit: item.ownerUnit,
    status: item.status || 'active',
    description: item.description || ''
  })
  showModal.value = true
}

const openProjectWorkspace = (project: Project) => {
  const previousProjectId = store.currentProjectId
  store.currentProjectId = project.id
  workspaceProject.value = project
  activeModuleKey.value = 'members'
  workspaceVisible.value = true
  if (previousProjectId === project.id) return
  store.addLog({
    id: `log-${Date.now()}`,
    time: nowStr(),
    operator: '李明',
    level: 'info',
    action: '进入项目管理',
    detail: `运维人员进入项目进行单独管理: ${project.name}`,
    relatedId: project.id
  })
}

const submitForm = () => {
  if (!form.name) {
    message.warning('请输入项目全称')
    return
  }

  if (isEdit.value) {
    const idx = store.projects.findIndex(x => x.id === editId.value)
    if (idx !== -1) {
      store.projects[idx] = {
        ...store.projects[idx],
        ...form
      }
      store.addLog({
        id: `log-${Date.now()}`,
        time: nowStr(),
        operator: '李明',
        level: 'success',
        action: '编辑项目配置',
        detail: `系统运维员更新了项目明细: ${form.name}`,
        relatedId: editId.value
      })
      message.success('项目信息更新成功')
    }
  } else {
    const newId = `p${Date.now()}`
    store.projects.push({
      id: newId,
      createdAt: new Date().toISOString(),
      ...form
    })
    store.addLog({
      id: `log-${Date.now()}`,
      time: nowStr(),
      operator: '李明',
      level: 'success',
      action: '创建项目',
      detail: `系统运维员创建了新项目: ${form.name}`,
      relatedId: newId
    })
    message.success('项目创建成功，配置底座已初始化')
  }
  showModal.value = false
}

const handleDelete = (id: string) => {
  if (store.projects.length <= 1) {
    message.error('系统中须至少保留一个活跃的工程项目底座')
    return
  }
  const confirmDelete = confirm('确定要删除该项目吗？此操作将使关联的 WBS 及配置数据暂时隐藏')
  if (confirmDelete) {
    const deletedProj = store.projects.find(x => x.id === id)
    store.projects = store.projects.filter(x => x.id !== id)
    if (store.currentProjectId === id) {
      store.currentProjectId = store.projects[0].id
    }
    store.addLog({
      id: `log-${Date.now()}`,
      time: nowStr(),
      operator: '李明',
      level: 'warning',
      action: '注销删除项目',
      detail: `系统运维员注销从底座卸载了工程项目: ${deletedProj?.name}`
    })
    message.success('项目底座已被物理注销')
  }
}

const nowStr = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')} ${String(now.getMinutes()).padStart(2,'0')}`
}
</script>

<style scoped>
.ops-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
.ops-table th {
  background: var(--bg-subtle, #f8fafc);
  padding: 14px 18px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-default);
}
.ops-table td {
  padding: 16px 18px;
  font-size: 13px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-default);
  vertical-align: middle;
}

.ops-table tbody tr {
  transition: var(--transition);
}
.ops-table tbody tr:hover {
  background: var(--bg-hover, #f1f5f9);
}

.ops-table tbody tr.row-active {
  background: var(--color-primary-soft);
}
.ops-table tbody tr.row-active td {
  border-bottom-color: var(--color-primary-light);
}

.project-name-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.p-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.cell-primary {
  color: var(--text-primary);
  font-weight: 500;
}
.cell-secondary {
  color: var(--text-secondary);
}

.action-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: nowrap;
}

.active-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  border-radius: 12px;
  white-space: nowrap;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(232, 89, 12, 0.25);
}

.project-workspace {
  width: 95vw;
  height: 95vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-page, #f5f6f8);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.workspace-topbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
}
.workspace-topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.workspace-kicker {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 12px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.workspace-title {
  margin: 0;
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.workspace-topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}
.workspace-owner {
  color: var(--text-secondary);
  font-size: 13px;
  white-space: nowrap;
}
.workspace-close {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
}
.workspace-close:hover { color: var(--text-primary); border-color: var(--border-emphasis); background: var(--bg-hover); }
.workspace-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.workspace-nav {
  flex-shrink: 0;
  width: 210px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 10px;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
  overflow-y: auto;
}
.workspace-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  transition: var(--transition);
}
.workspace-nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.workspace-nav-item.active {
  background: var(--color-primary);
  color: #fff;
  font-weight: 650;
}
.workspace-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

@media (max-width: 640px) {
  .workspace-nav { width: 56px; padding: 14px 8px; }
  .workspace-nav-item span { display: none; }
  .workspace-owner { display: none; }
}

.pulse-dot {
  width: 6px;
  height: 6px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 0 rgba(255,255,255, 0.7);
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255,255,255, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(255,255,255, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255,255,255, 0); }
}

/* Modal form style */
.grid-form {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 16px;
}
.col-span-1 { grid-column: span 1; }
.col-span-full { grid-column: 1 / -1; }
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
