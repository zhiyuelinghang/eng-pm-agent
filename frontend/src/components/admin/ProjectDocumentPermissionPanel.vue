<template>
  <section class="document-permission-panel">
    <div v-if="loading" class="permission-loading" aria-label="正在加载岗位资料权限">
      <span></span><span></span><span></span><span></span>
    </div>

    <div v-else-if="loadError" class="permission-state permission-error" role="alert">
      <n-icon :size="30"><AlertTriangle /></n-icon>
      <strong>资料权限加载失败</strong>
      <p>{{ loadError }}</p>
      <button type="button" @click="loadAccessConfiguration(false)">重新加载</button>
    </div>

    <div v-else-if="!positions.length" class="permission-state">
      <n-icon :size="30"><Users /></n-icon>
      <strong>当前项目还没有岗位</strong>
      <p>请先在“项目成员”中为成员添加岗位。</p>
    </div>

    <section v-else class="position-overview">
      <header class="position-overview-head">
        <div>
          <strong>已有岗位</strong>
          <span>{{ positions.length }} 个岗位，共 {{ totalPositionMembers }} 人次</span>
        </div>
        <button type="button" :disabled="loading" @click="loadAccessConfiguration(false)">
          <n-icon :size="16"><Refresh /></n-icon>刷新
        </button>
      </header>

      <div class="position-table-scroll">
        <table class="position-table">
          <thead>
            <tr>
              <th>岗位名称</th>
              <th>岗位人数</th>
              <th>已分配资料</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="position in positions" :key="position.id" class="position-row">
                <td>
                  <span class="position-name">
                    <strong>{{ position.name }}</strong>
                  </span>
                </td>
                <td><strong class="position-count">{{ position.memberCount }}</strong> 人</td>
                <td>
                  <span v-if="position.permissionCount" class="permission-count assigned">
                    {{ position.permissionCount }} 个节点
                  </span>
                  <span v-else class="permission-count">尚未分配</span>
                </td>
                <td>
                  <div class="position-row-actions">
                    <button
                      type="button"
                      class="view-members-button"
                      @click="openMemberViewer(position.id)"
                    >查看人员</button>
                    <button
                      type="button"
                      class="assign-permission-button"
                      :disabled="treeLoading"
                      @click="startPermissionAssignment(position.id)"
                    >{{ treeLoading && loadingPositionId === position.id ? '加载资料…' : '分配权限' }}</button>
                  </div>
                </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <Teleport to="body">
      <div
        v-if="memberViewerPosition"
        class="permission-modal-backdrop"
        @click.self="closeMemberViewer"
      >
        <section
          class="permission-modal permission-standard-modal member-viewer-modal"
          role="dialog"
          aria-modal="true"
          :aria-label="memberViewerPosition.name + '岗位人员'"
        >
          <header class="permission-modal-head">
            <div>
              <span>岗位人员</span>
              <strong>{{ memberViewerPosition.name }}</strong>
              <small>共 {{ memberViewerPosition.memberCount }} 人</small>
            </div>
            <button type="button" @click="closeMemberViewer">关闭</button>
          </header>
          <div v-if="memberViewerPosition.members.length" class="member-list-toolbar">
            <label>
              <n-icon :size="16"><Search /></n-icon>
              <input
                v-model.trim="memberViewerSearch"
                type="search"
                placeholder="搜索姓名、账号或职务"
              >
            </label>
            <span v-if="memberViewerSearch">找到 {{ filteredMemberViewerMembers.length }} 人</span>
          </div>
          <div v-if="filteredMemberViewerMembers.length" class="member-table-wrap">
            <table class="member-table">
              <thead>
                <tr>
                  <th>序号</th>
                  <th>姓名</th>
                  <th>账号</th>
                  <th>职务</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(member, index) in pagedMemberViewerMembers" :key="member.id">
                  <td>{{ memberViewerPageOffset + index + 1 }}</td>
                  <td><strong class="member-plain-name">{{ member.name }}</strong></td>
                  <td>{{ member.username }}</td>
                  <td>{{ member.title || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="member-viewer-empty">
            {{ memberViewerPosition.members.length ? '没有匹配的人员' : '当前没有人员担任该岗位。' }}
          </p>
          <footer class="member-pagination">
            <span>
              <template v-if="memberViewerSearch">共 {{ memberViewerPosition.memberCount }} 人，当前 {{ filteredMemberViewerMembers.length }} 人</template>
              <template v-else>共 {{ memberViewerPosition.memberCount }} 人</template>
            </span>
            <n-pagination
              v-if="memberViewerPageCount > 1"
              v-model:page="memberViewerPage"
              :page-count="memberViewerPageCount"
              :page-slot="7"
              size="small"
            />
          </footer>
        </section>
      </div>

      <div
        v-if="permissionEditorOpen"
        class="permission-modal-backdrop"
        @click.self="requestClosePermissionEditor"
      >
        <section
          class="permission-modal permission-standard-modal permission-assignment-modal"
          role="dialog"
          aria-modal="true"
          :aria-label="'分配' + (selectedPosition?.name || '') + '资料权限'"
        >
    <main class="permission-editor">
      <header class="permission-editor-head">
        <button type="button" class="permission-back" @click="requestClosePermissionEditor">
          <n-icon :size="17"><ArrowLeft /></n-icon>关闭
        </button>
        <div>
          <span>正在分配</span>
          <strong>{{ selectedPosition?.name }}</strong>
          <small>{{ selectedPosition?.memberCount || 0 }} 名岗位成员</small>
        </div>
        <button
          type="button"
          class="save-assignment-button"
          :disabled="treeLoading || Boolean(treeLoadError) || !pendingChangeCount || savingPermission"
          @click="savePermissionAssignment"
        >
          {{ savingPermission ? '正在保存…' : pendingChangeCount ? '保存分配（' + pendingChangeCount + '）' : '保存分配' }}
        </button>
      </header>

      <div v-if="treeLoading" class="permission-editor-loading" role="status">
        <header>
          <strong>正在加载资料目录</strong>
          <span>请稍候</span>
        </header>
        <div class="permission-loading-layout">
          <section>
            <i></i><i></i><i></i><i></i><i></i><i></i>
          </section>
          <aside><i></i><i></i><i></i><i></i></aside>
        </div>
      </div>

      <div v-else-if="treeLoadError" class="permission-editor-error" role="alert">
        <n-icon :size="34"><AlertTriangle /></n-icon>
        <strong>资料目录加载失败</strong>
        <p>{{ treeLoadError }}</p>
        <button
          v-if="selectedPositionId"
          type="button"
          @click="startPermissionAssignment(selectedPositionId)"
        >重新加载</button>
      </div>

      <div v-else class="permission-editor-body">
        <aside class="permission-tree-panel">
          <header>
            <label>
              <n-icon :size="16"><Search /></n-icon>
              <input v-model.trim="nodeSearch" placeholder="搜索目录或文件">
            </label>
            <div>
              <button type="button" @click="expandAll">全部展开</button>
              <button type="button" @click="collapseAll">全部收起</button>
            </div>
          </header>
          <div class="permission-tree-columns">
            <span>资料目录与文件</span>
            <span>当前分配</span>
          </div>
          <div class="permission-tree-scroll">
            <button
              v-for="row in visibleNodeRows"
              :key="row.node.id"
              type="button"
              class="permission-tree-row"
              :class="{ selected: row.node.id === selectedNodeId }"
              :style="{ '--permission-depth': String(row.depth) }"
              @click="selectNode(row.node.id)"
            >
              <span class="permission-tree-name">
                <span
                  v-if="row.hasChildren"
                  class="permission-tree-toggle"
                  :class="{ expanded: expandedNodeIds.has(row.node.id) }"
                  role="button"
                  :aria-label="expandedNodeIds.has(row.node.id) ? '收起下级' : '展开下级'"
                  tabindex="0"
                  @click.stop="toggleNode(row.node.id)"
                  @keydown.enter.stop.prevent="toggleNode(row.node.id)"
                  @keydown.space.stop.prevent="toggleNode(row.node.id)"
                ><n-icon :size="15"><ChevronRight /></n-icon></span>
                <i v-else></i>
                <n-icon :size="17"><component :is="nodeIcon(row.node.node_type)" /></n-icon>
                <span>
                  <strong>{{ row.node.name }}</strong>
                  <small>{{ compactNodePath(row.node) }}</small>
                </span>
              </span>
              <span class="permission-tree-status" :class="permissionStateClass(row.node.id)">
                {{ capabilitySummary(row.node.id) }}
              </span>
            </button>
            <div v-if="!visibleNodeRows.length" class="permission-tree-empty">
              没有匹配的目录或文件
            </div>
          </div>
        </aside>

        <section v-if="selectedNode" class="node-permission-editor">
          <header>
            <div>
              <span>{{ nodeTypeLabel(selectedNode.node_type) }}</span>
              <h3>{{ selectedNode.name }}</h3>
              <p>{{ selectedNodePath }}</p>
            </div>
            <em :class="permissionStateClass(selectedNode.id)">
              {{ permissionStateLabel(selectedNode.id) }}
            </em>
          </header>

          <div class="capability-section">
            <strong>允许该岗位执行</strong>
            <div class="capability-options" role="group" :aria-label="selectedNode.name + '权限'">
              <label
                v-for="item in capabilityOptions"
                :key="item.key"
                :class="{ checked: permissionDraft[item.key] }"
              >
                <input
                  type="checkbox"
                  :checked="permissionDraft[item.key]"
                  @change="handleCapabilityChange(item.key, $event)"
                >
                <span>
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.description }}</small>
                </span>
              </label>
            </div>
          </div>

          <label class="inherit-option" :class="{ disabled: !selectedNodeHasChildren }">
            <input
              type="checkbox"
              :checked="permissionDraft.inherit_to_children"
              :disabled="!selectedNodeHasChildren"
              @change="handleInheritanceChange"
            >
            <span>
              <strong>同时应用到下级</strong>
              <small>下级目录和文件继承当前节点的权限</small>
            </span>
          </label>

          <p v-if="selectedInheritedPermission && !selectedDirectPermission" class="inherited-note">
            当前节点继承了上级目录权限；需要缩小范围时，请调整授予权限的上级节点。
          </p>

          <footer>
            <span>
              <template v-if="pendingChangeCount">已有 {{ pendingChangeCount }} 处修改等待保存</template>
              <template v-else>选择权限后，点击右上角“保存分配”</template>
            </span>
            <button
              v-if="selectedDirectPermission"
              type="button"
              class="clear-node-button"
              @click="clearSelectedNodePermission"
            >取消该节点分配</button>
          </footer>
        </section>

        <section v-else class="node-permission-empty">
          <n-icon :size="30"><Folder /></n-icon>
          <strong>请选择目录或文件</strong>
        </section>
      </div>
    </main>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { NIcon, NPagination, useDialog, useMessage } from 'naive-ui'
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  Database,
  FileText,
  Folder,
  Refresh,
  Search,
  Users,
} from '@vicons/tabler'
import {
  useAppStore,
  type EngineeringDocumentAccessConfiguration,
  type EngineeringDocumentAccessNode,
  type EngineeringDocumentCapabilities,
  type EngineeringDocumentPermissionRecord,
} from '@/stores/app'
import type { Member } from '@/types'

type CapabilityKey = keyof EngineeringDocumentCapabilities
type PermissionDraft = EngineeringDocumentCapabilities & { inherit_to_children: boolean }
type PermissionTreeRow = { node: EngineeringDocumentAccessNode; depth: number; hasChildren: boolean }
type PositionRow = {
  id: number
  name: string
  members: Member[]
  memberCount: number
  permissionCount: number
}

const props = defineProps<{
  projectId: string
  members: Member[]
}>()

const store = useAppStore()
const message = useMessage()
const dialog = useDialog()
const accessConfiguration = shallowRef<EngineeringDocumentAccessConfiguration | null>(null)
const loading = ref(false)
const loadError = ref('')
const nodesLoaded = ref(false)
const treeLoading = ref(false)
const loadingPositionId = ref<number | null>(null)
const savingPermission = ref(false)
const memberViewerPositionId = ref<number | null>(null)
const memberViewerPage = ref(1)
const memberViewerPageSize = 10
const memberViewerSearch = ref('')
const permissionEditorOpen = ref(false)
const treeLoadError = ref('')
const selectedPositionId = ref<number | null>(null)
const selectedNodeId = ref<number | null>(null)
const expandedNodeIds = ref<Set<number>>(new Set())
const nodeSearch = ref('')
const pendingChanges = shallowRef<Map<number, PermissionDraft | null>>(new Map())
const permissionDraft = reactive<PermissionDraft>(emptyPermissionDraft())

const capabilityOptions: Array<{ key: CapabilityKey; label: string; description: string }> = [
  { key: 'can_read', label: '查看', description: '浏览目录与文件' },
  { key: 'can_create', label: '上传', description: '新建目录和上传资料' },
  { key: 'can_update', label: '修改', description: '移动或重命名资料' },
  { key: 'can_delete', label: '删除', description: '删除目录和文件' },
  { key: 'can_manage', label: '管理', description: '具备全部资料权限' },
]

const nodes = computed(() => accessConfiguration.value?.nodes || [])
const permissions = computed(() => accessConfiguration.value?.permissions || [])
const nodeById = computed(() => new Map(nodes.value.map(node => [node.id, node])))
const childrenByParent = computed(() => {
  const result = new Map<number | null, EngineeringDocumentAccessNode[]>()
  for (const node of nodes.value) {
    const parentId = node.parent_id && nodeById.value.has(node.parent_id) ? node.parent_id : null
    const children = result.get(parentId) || []
    children.push(node)
    result.set(parentId, children)
  }
  return result
})

const positions = computed<PositionRow[]>(() => (
  (accessConfiguration.value?.subjects.positions || []).map(position => {
    const members = props.members.filter(member => (
      member.positions.some(item => Number(item.positionId) === position.id)
    ))
    return {
      ...position,
      members,
      memberCount: members.length,
      permissionCount: permissions.value.filter(permission => (
        permission.subject_type === 'position' && permission.subject_id === position.id
      )).length,
    }
  })
))
const totalPositionMembers = computed(() => (
  positions.value.reduce((total, position) => total + position.memberCount, 0)
))
const selectedPosition = computed(() => (
  positions.value.find(position => position.id === selectedPositionId.value) || null
))
const memberViewerPosition = computed(() => (
  positions.value.find(position => position.id === memberViewerPositionId.value) || null
))
const filteredMemberViewerMembers = computed(() => {
  const keyword = memberViewerSearch.value.trim().toLowerCase()
  const members = memberViewerPosition.value?.members || []
  if (!keyword) return members
  return members.filter(member => (
    [member.name, member.username, member.title]
      .filter(Boolean)
      .some(value => String(value).toLowerCase().includes(keyword))
  ))
})
const memberViewerPageCount = computed(() => Math.max(
  1,
  Math.ceil(filteredMemberViewerMembers.value.length / memberViewerPageSize),
))
const memberViewerPageOffset = computed(() => (
  (memberViewerPage.value - 1) * memberViewerPageSize
))
const pagedMemberViewerMembers = computed(() => (
  filteredMemberViewerMembers.value.slice(
    memberViewerPageOffset.value,
    memberViewerPageOffset.value + memberViewerPageSize,
  )
))
const originalPermissionByNode = computed(() => new Map(
  permissions.value
    .filter(permission => (
      permission.subject_type === 'position' && permission.subject_id === selectedPositionId.value
    ))
    .map(permission => [permission.node_id, permission]),
))
const workingPermissionByNode = computed<Map<number, PermissionDraft>>(() => {
  const result = new Map<number, PermissionDraft>()
  for (const [nodeId, permission] of originalPermissionByNode.value) {
    result.set(nodeId, permissionValue(permission))
  }
  for (const [nodeId, draft] of pendingChanges.value) {
    if (draft) result.set(nodeId, { ...draft })
    else result.delete(nodeId)
  }
  return result
})
const pendingChangeCount = computed(() => pendingChanges.value.size)
const selectedNode = computed(() => (
  selectedNodeId.value === null ? null : nodeById.value.get(selectedNodeId.value) || null
))
const selectedDirectPermission = computed(() => (
  selectedNodeId.value === null ? null : workingPermissionByNode.value.get(selectedNodeId.value) || null
))
const selectedNodeHasChildren = computed(() => (
  selectedNodeId.value !== null && Boolean(childrenByParent.value.get(selectedNodeId.value)?.length)
))
const selectedInheritedPermission = computed(() => (
  selectedNodeId.value === null ? false : effectivePermission(selectedNodeId.value).inherited
))

const selectedNodePath = computed(() => {
  if (!selectedNode.value) return ''
  const names: string[] = []
  let cursor: EngineeringDocumentAccessNode | undefined = selectedNode.value
  while (cursor) {
    names.unshift(cursor.name)
    cursor = cursor.parent_id ? nodeById.value.get(cursor.parent_id) : undefined
  }
  return names.join(' / ')
})

const visibleNodeRows = computed<PermissionTreeRow[]>(() => {
  const keyword = nodeSearch.value.trim().toLowerCase()
  const included = new Set<number>()
  if (keyword) {
    for (const node of nodes.value) {
      if ((node.name + ' ' + (node.folder_path || '')).toLowerCase().includes(keyword)) {
        let cursor: EngineeringDocumentAccessNode | undefined = node
        while (cursor) {
          included.add(cursor.id)
          cursor = cursor.parent_id ? nodeById.value.get(cursor.parent_id) : undefined
        }
      }
    }
  }
  const rows: PermissionTreeRow[] = []
  const visit = (parentId: number | null, depth: number) => {
    for (const node of childrenByParent.value.get(parentId) || []) {
      if (keyword && !included.has(node.id)) continue
      const children = childrenByParent.value.get(node.id) || []
      rows.push({ node, depth, hasChildren: children.length > 0 })
      if (keyword || expandedNodeIds.value.has(node.id)) visit(node.id, depth + 1)
    }
  }
  visit(null, 0)
  return rows
})

const normalizedDraft = computed<PermissionDraft>(() => {
  const inherit = selectedNodeHasChildren.value && permissionDraft.inherit_to_children
  if (permissionDraft.can_manage) {
    return {
      can_read: true,
      can_create: true,
      can_update: true,
      can_delete: true,
      can_manage: true,
      inherit_to_children: inherit,
    }
  }
  return {
    can_read: permissionDraft.can_read,
    can_create: permissionDraft.can_create,
    can_update: permissionDraft.can_update,
    can_delete: permissionDraft.can_delete,
    can_manage: false,
    inherit_to_children: inherit,
  }
})

function emptyPermissionDraft(): PermissionDraft {
  return {
    can_read: false,
    can_create: false,
    can_update: false,
    can_delete: false,
    can_manage: false,
    inherit_to_children: true,
  }
}

function permissionValue(permission: EngineeringDocumentPermissionRecord | PermissionDraft): PermissionDraft {
  return {
    can_read: Boolean(permission.can_read),
    can_create: Boolean(permission.can_create),
    can_update: Boolean(permission.can_update),
    can_delete: Boolean(permission.can_delete),
    can_manage: Boolean(permission.can_manage),
    inherit_to_children: Boolean(permission.inherit_to_children),
  }
}

function hasCapability(permission: PermissionDraft) {
  return capabilityOptions.some(item => permission[item.key])
}

function samePermission(left: PermissionDraft, right: PermissionDraft) {
  return capabilityOptions.every(item => left[item.key] === right[item.key])
    && left.inherit_to_children === right.inherit_to_children
}

function syncPermissionDraft() {
  Object.assign(permissionDraft, selectedDirectPermission.value || emptyPermissionDraft())
}

function stageSelectedPermission() {
  if (selectedNodeId.value === null) return
  const nodeId = selectedNodeId.value
  const next = new Map(pendingChanges.value)
  const original = originalPermissionByNode.value.get(nodeId)
  const draft = { ...normalizedDraft.value }
  if (!hasCapability(draft)) {
    if (original) next.set(nodeId, null)
    else next.delete(nodeId)
  } else if (original && samePermission(draft, permissionValue(original))) {
    next.delete(nodeId)
  } else {
    next.set(nodeId, draft)
  }
  pendingChanges.value = next
}

function toggleCapability(key: CapabilityKey, checked: boolean) {
  permissionDraft[key] = checked
  if (key === 'can_read' && !checked) {
    permissionDraft.can_create = false
    permissionDraft.can_update = false
    permissionDraft.can_delete = false
    permissionDraft.can_manage = false
  } else if (key === 'can_manage' && checked) {
    permissionDraft.can_read = true
    permissionDraft.can_create = true
    permissionDraft.can_update = true
    permissionDraft.can_delete = true
  } else if (key !== 'can_read' && checked) {
    permissionDraft.can_read = true
  }
  stageSelectedPermission()
}

function handleCapabilityChange(key: CapabilityKey, event: Event) {
  toggleCapability(key, (event.target as HTMLInputElement).checked)
}

function handleInheritanceChange(event: Event) {
  permissionDraft.inherit_to_children = (event.target as HTMLInputElement).checked
  stageSelectedPermission()
}

function clearSelectedNodePermission() {
  Object.assign(permissionDraft, emptyPermissionDraft())
  stageSelectedPermission()
}

function effectivePermission(nodeId: number): { capabilities: EngineeringDocumentCapabilities; inherited: boolean } {
  const capabilities: EngineeringDocumentCapabilities = {
    can_read: false,
    can_create: false,
    can_update: false,
    can_delete: false,
    can_manage: false,
  }
  let inherited = false
  let cursor = nodeById.value.get(nodeId)
  while (cursor) {
    const direct = workingPermissionByNode.value.get(cursor.id)
    if (direct && (cursor.id === nodeId || direct.inherit_to_children)) {
      if (cursor.id !== nodeId) inherited = true
      for (const item of capabilityOptions) capabilities[item.key] ||= Boolean(direct[item.key])
    }
    cursor = cursor.parent_id ? nodeById.value.get(cursor.parent_id) : undefined
  }
  if (capabilities.can_manage) {
    for (const item of capabilityOptions) capabilities[item.key] = true
  }
  return { capabilities, inherited }
}

function hasGrantedDescendant(nodeId: number) {
  for (const grantedNodeId of workingPermissionByNode.value.keys()) {
    let cursor = nodeById.value.get(grantedNodeId)
    while (cursor?.parent_id) {
      if (cursor.parent_id === nodeId) return true
      cursor = nodeById.value.get(cursor.parent_id)
    }
  }
  return false
}

function permissionStateLabel(nodeId: number) {
  if (workingPermissionByNode.value.has(nodeId)) return '已直接分配'
  if (effectivePermission(nodeId).inherited) return '继承上级权限'
  if (hasGrantedDescendant(nodeId)) return '下级已有分配'
  return '未分配'
}

function permissionStateClass(nodeId: number) {
  if (workingPermissionByNode.value.has(nodeId)) return 'direct'
  if (effectivePermission(nodeId).inherited) return 'inherited'
  if (hasGrantedDescendant(nodeId)) return 'descendant'
  return 'none'
}

function capabilitySummary(nodeId: number) {
  const { capabilities } = effectivePermission(nodeId)
  if (capabilities.can_manage) return '全部权限'
  const labels = capabilityOptions.filter(item => capabilities[item.key]).map(item => item.label)
  if (labels.length) return labels.join('、')
  return hasGrantedDescendant(nodeId) ? '下级已分配' : '未分配'
}

function openMemberViewer(positionId: number) {
  memberViewerPage.value = 1
  memberViewerSearch.value = ''
  memberViewerPositionId.value = positionId
}

function closeMemberViewer() {
  memberViewerPositionId.value = null
  memberViewerSearch.value = ''
}

function openPermissionEditor(positionId: number) {
  selectedPositionId.value = positionId
  pendingChanges.value = new Map()
  permissionEditorOpen.value = true
  treeLoadError.value = ''
  nodeSearch.value = ''
  selectedNodeId.value = null
  expandedNodeIds.value = new Set()
  Object.assign(permissionDraft, emptyPermissionDraft())
}

function initializePermissionEditorTree(positionId: number) {
  selectedPositionId.value = positionId
  const firstAssignedNodeId = permissions.value.find(permission => (
    permission.subject_type === 'position' && permission.subject_id === positionId
  ))?.node_id
  selectedNodeId.value = firstAssignedNodeId || nodes.value[0]?.id || null
  expandedNodeIds.value = new Set(
    nodes.value.filter(node => node.parent_id === null).map(node => node.id),
  )
  expandSelectedNodePath()
  syncPermissionDraft()
}

async function startPermissionAssignment(positionId: number) {
  if (treeLoading.value) return
  openPermissionEditor(positionId)
  if (!nodesLoaded.value) {
    treeLoading.value = true
    loadingPositionId.value = positionId
    try {
      const result = await store.loadEngineeringDocumentAccess(props.projectId, true)
      applyAccessConfiguration(result, true)
    } catch (error: any) {
      treeLoadError.value = error.response?.data?.detail || error.message || '无法读取当前项目的资料目录。'
      return
    } finally {
      treeLoading.value = false
      loadingPositionId.value = null
    }
  }
  if (!permissionEditorOpen.value || selectedPositionId.value !== positionId) return
  if (!nodes.value.length) {
    treeLoadError.value = '当前项目还没有可分配的资料目录。'
    return
  }
  initializePermissionEditorTree(positionId)
}

function closePermissionEditor() {
  permissionEditorOpen.value = false
  treeLoadError.value = ''
  pendingChanges.value = new Map()
  nodeSearch.value = ''
  selectedPositionId.value = null
  selectedNodeId.value = null
}

function requestClosePermissionEditor() {
  if (!pendingChangeCount.value) {
    closePermissionEditor()
    return
  }
  dialog.warning({
    title: '放弃未保存的分配',
    content: '当前岗位的资料权限尚未保存。',
    positiveText: '放弃修改',
    negativeText: '继续分配',
    onPositiveClick: closePermissionEditor,
  })
}

function selectNode(nodeId: number) {
  selectedNodeId.value = nodeId
}

function toggleNode(nodeId: number) {
  const next = new Set(expandedNodeIds.value)
  if (next.has(nodeId)) next.delete(nodeId)
  else next.add(nodeId)
  expandedNodeIds.value = next
}

function expandSelectedNodePath() {
  let cursor = selectedNodeId.value === null ? undefined : nodeById.value.get(selectedNodeId.value)
  const next = new Set(expandedNodeIds.value)
  while (cursor?.parent_id) {
    next.add(cursor.parent_id)
    cursor = nodeById.value.get(cursor.parent_id)
  }
  expandedNodeIds.value = next
}

function expandAll() {
  expandedNodeIds.value = new Set(
    nodes.value.filter(node => childrenByParent.value.get(node.id)?.length).map(node => node.id),
  )
}

function collapseAll() {
  expandedNodeIds.value = new Set(
    nodes.value.filter(node => node.parent_id === null && childrenByParent.value.get(node.id)?.length).map(node => node.id),
  )
}

function nodeIcon(nodeType: EngineeringDocumentAccessNode['node_type']) {
  if (nodeType === 'knowledge_base') return Database
  if (nodeType === 'folder') return Folder
  return FileText
}

function nodeTypeLabel(nodeType: EngineeringDocumentAccessNode['node_type']) {
  if (nodeType === 'knowledge_base') return '知识库'
  if (nodeType === 'folder') return '目录'
  return '文件'
}

function compactNodePath(node: EngineeringDocumentAccessNode) {
  if (node.node_type === 'knowledge_base') return '资料库根目录'
  return node.folder_path || (node.node_type === 'folder' ? '一级目录' : '根目录文件')
}

function applyAccessConfiguration(
  result: EngineeringDocumentAccessConfiguration,
  includeNodes: boolean,
) {
  const retainedNodes = includeNodes
    ? result.nodes
    : accessConfiguration.value?.nodes || []
  accessConfiguration.value = { ...result, nodes: retainedNodes }
  if (includeNodes) nodesLoaded.value = true
  const positionIds = new Set(result.subjects.positions.map(item => item.id))
  selectedPositionId.value = selectedPositionId.value && positionIds.has(selectedPositionId.value)
    ? selectedPositionId.value
    : result.subjects.positions[0]?.id || null
  memberViewerPositionId.value = memberViewerPositionId.value && positionIds.has(memberViewerPositionId.value)
    ? memberViewerPositionId.value
    : null
}

async function loadAccessConfiguration(includeNodes = false) {
  if (!props.projectId) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await store.loadEngineeringDocumentAccess(props.projectId, includeNodes)
    applyAccessConfiguration(result, includeNodes)
  } catch (error: any) {
    accessConfiguration.value = null
    nodesLoaded.value = false
    loadError.value = error.response?.data?.detail || error.message || '无法读取当前项目的资料权限。'
  } finally {
    loading.value = false
  }
}

async function synchronizeAccessMode() {
  if (!accessConfiguration.value) return
  const hasAssignedPermission = accessConfiguration.value.permissions.some(permission => (
    permission.subject_type === 'position'
    && capabilityOptions.some(option => permission[option.key])
  ))
  const targetMode: 'project' | 'restricted' = hasAssignedPermission ? 'restricted' : 'project'
  if (accessConfiguration.value.access_mode === targetMode) return
  await store.updateEngineeringDocumentAccessMode(targetMode, props.projectId)
  accessConfiguration.value.access_mode = targetMode
}

async function savePermissionAssignment() {
  if (!selectedPositionId.value || !pendingChangeCount.value) return
  savingPermission.value = true
  const changes = Array.from(pendingChanges.value.entries())
  try {
    const results = await Promise.allSettled(changes.map(async ([nodeId, draft]) => {
      const original = originalPermissionByNode.value.get(nodeId)
      if (!draft) {
        if (original) await store.deleteEngineeringDocumentPermission(original.id, props.projectId)
        return
      }
      await store.saveEngineeringDocumentPermission({
        node_id: nodeId,
        subject_type: 'position',
        subject_id: selectedPositionId.value as number,
        ...draft,
      }, props.projectId)
    }))
    await loadAccessConfiguration(false)
    await synchronizeAccessMode()
    const failed = new Map<number, PermissionDraft | null>()
    results.forEach((result, index) => {
      if (result.status === 'rejected') failed.set(changes[index][0], changes[index][1])
    })
    pendingChanges.value = failed
    syncPermissionDraft()
    if (failed.size) {
      message.error('有 ' + failed.size + ' 处分配未能保存，请检查后重试。')
      return
    }
    const positionName = selectedPosition.value?.name || '岗位'
    closePermissionEditor()
    message.success(positionName + '的资料权限已保存')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '岗位资料权限保存失败。')
  } finally {
    savingPermission.value = false
  }
}

watch(() => props.projectId, () => {
  accessConfiguration.value = null
  nodesLoaded.value = false
  treeLoading.value = false
  loadingPositionId.value = null
  memberViewerPositionId.value = null
  memberViewerPage.value = 1
  memberViewerSearch.value = ''
  permissionEditorOpen.value = false
  treeLoadError.value = ''
  selectedPositionId.value = null
  selectedNodeId.value = null
  pendingChanges.value = new Map()
  nodeSearch.value = ''
  void loadAccessConfiguration()
}, { immediate: true })

watch(selectedNodeId, () => {
  syncPermissionDraft()
  expandSelectedNodePath()
})

watch(memberViewerSearch, () => {
  memberViewerPage.value = 1
})

watch(memberViewerPageCount, pageCount => {
  if (memberViewerPage.value > pageCount) memberViewerPage.value = pageCount
})
</script>

<style scoped>
.document-permission-panel {
  height: 100%;
  width: 100%;
  min-height: 520px;
  color: #173d3b;
  background: #fff;
  display: flex;
  flex-direction: column;
}

.permission-loading {
  min-height: 420px;
  padding: 20px;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 10px;
}
.permission-loading span {
  height: 58px;
  border-radius: 6px;
  background: linear-gradient(90deg, #edf3f1, #f8fbfa, #edf3f1);
  background-size: 200% 100%;
  animation: permission-skeleton 1.2s ease-in-out infinite;
}
@keyframes permission-skeleton { from { background-position: 100% 0; } to { background-position: -100% 0; } }

.permission-state {
  min-height: 430px;
  padding: 60px 24px;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #718783;
  text-align: center;
}
.permission-state :deep(svg) { color: #799c97; }
.permission-state strong { margin-top: 12px; color: #204d49; font-size: 15px; }
.permission-state p { max-width: 440px; margin: 6px 0 0; font-size: 13px; line-height: 1.65; }
.permission-state button {
  min-height: 34px;
  margin-top: 16px;
  padding: 0 14px;
  border: 1px solid #b9d0cc;
  border-radius: 6px;
  color: #0b625b;
  background: #fff;
  font-weight: 650;
  cursor: pointer;
}
.permission-error :deep(svg) { color: #c55d3e; }

.position-overview {
  min-height: 0;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
}
.position-overview-head {
  min-height: 52px;
  padding: 9px 14px;
  border-bottom: 1px solid #e1eae8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.position-overview-head > div { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.position-overview-head strong { color: #244b47; font-size: 13px; }
.position-overview-head span { color: #78908c; font-size: 11px; font-variant-numeric: tabular-nums; }
.position-overview-head button {
  min-height: 31px;
  padding: 0 9px;
  border: 1px solid #cadbd7;
  border-radius: 6px;
  color: #426863;
  background: #fff;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  cursor: pointer;
}
.position-table-scroll { min-height: 360px; overflow: auto; display: block; flex: 1 1 0; }
.position-table { width: 100%; min-width: 560px; border-collapse: collapse; table-layout: fixed; }
.position-table th {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 10px 14px;
  border-bottom: 1px solid #dce7e4;
  color: #687f7b;
  background: #f5f8f7;
  font-size: 11px;
  font-weight: 700;
  text-align: left;
}
.position-table th:nth-child(1) { width: 29%; }
.position-table th:nth-child(2) { width: 16%; }
.position-table th:nth-child(3) { width: 21%; }
.position-table th:nth-child(4) { width: 34%; text-align: right; }
.position-row {
  border-bottom: 1px solid #e8efed;
  cursor: default;
  transition: background .16s ease;
}
.position-row:hover { background: #f8fbfa; }
.position-row td { padding: 13px 14px; color: #4e6965; font-size: 12px; vertical-align: middle; }
.position-row td:last-child { text-align: right; }
.position-name { min-width: 0; display: block; }
.position-name strong {
  min-width: 0;
  overflow: hidden;
  color: #254b47;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.position-count { color: #0d7167; font-size: 14px; font-variant-numeric: tabular-nums; }
.permission-count {
  display: inline-block;
  padding: 3px 7px;
  border-radius: 5px;
  color: #738783;
  background: #eef3f2;
  font-size: 10px;
}
.permission-count.assigned { color: #0c675e; background: #dff0ec; }
.position-row-actions { display: flex; align-items: center; justify-content: flex-end; gap: 6px; white-space: nowrap; }
.view-members-button,
.assign-permission-button {
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid #a9ccc6;
  border-radius: 6px;
  color: #0b675e;
  background: #fff;
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
  transition: color .16s ease, background .16s ease, border-color .16s ease;
}
.assign-permission-button:disabled { opacity: .58; cursor: wait; }
.view-members-button { color: #536f6b; border-color: #c8d8d5; background: #f8fbfa; }
.view-members-button:hover { color: #0b675e; border-color: #91bab3; background: #edf6f3; }
.assign-permission-button:hover { color: #fff; border-color: #0d756b; background: #0d756b; }
.view-members-button:active,
.assign-permission-button:active { transform: translateY(1px); }
.permission-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  padding: 24px;
  background: rgba(20, 45, 42, .34);
  display: grid;
  place-items: center;
  backdrop-filter: blur(2px);
}
.permission-modal {
  max-width: calc(100vw - 48px);
  max-height: calc(100dvh - 48px);
  border: 1px solid #cfddda;
  border-radius: 10px;
  color: #173d3b;
  background: #fff;
  box-shadow: 0 20px 60px rgba(24, 54, 50, .2);
  overflow: hidden;
}
.permission-standard-modal {
  width: min(980px, calc(100vw - 48px));
  height: min(660px, calc(100dvh - 48px));
  display: flex;
  flex-direction: column;
}
.permission-modal-head {
  min-height: 62px;
  padding: 11px 14px 11px 17px;
  border-bottom: 1px solid #dfe8e6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.permission-modal-head > div { min-width: 0; display: flex; align-items: baseline; gap: 8px; }
.permission-modal-head span { color: #0d756b; font-size: 12px; font-weight: 700; }
.permission-modal-head strong { overflow: hidden; color: #214944; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.permission-modal-head small { color: #7b8f8b; font-size: 12px; }
.permission-modal-head button {
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid #c7d8d5;
  border-radius: 6px;
  color: #516e69;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.member-list-toolbar {
  min-height: 50px;
  padding: 8px 16px 8px 18px;
  border-bottom: 1px solid #e1eae8;
  background: #fbfdfc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.member-list-toolbar label {
  width: min(360px, 100%);
  height: 34px;
  padding: 0 10px;
  border: 1px solid #c9dad7;
  border-radius: 6px;
  color: #78908c;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 7px;
}
.member-list-toolbar input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  color: #284b47;
  background: transparent;
  font: inherit;
  font-size: 12px;
}
.member-list-toolbar > span { color: #718783; font-size: 12px; font-variant-numeric: tabular-nums; }
.member-table-wrap { min-height: 0; flex: 1 1 auto; overflow: auto; }
.member-table { width: 100%; min-width: 680px; border-collapse: collapse; table-layout: fixed; }
.member-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  height: 36px;
  padding: 0 18px;
  border-bottom: 1px solid #dce7e4;
  color: #657d78;
  background: #f5f8f7;
  font-size: 12px;
  font-weight: 700;
  text-align: left;
}
.member-table th:nth-child(1) { width: 90px; }
.member-table th:nth-child(2) { width: 26%; }
.member-table th:nth-child(3) { width: 32%; }
.member-table th:nth-child(4) { width: auto; }
.member-table td {
  height: 42px;
  padding: 0 18px;
  border-bottom: 1px solid #e8efed;
  overflow: hidden;
  color: #536d68;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.member-table tbody tr:hover { background: #f8fbfa; }
.member-plain-name { color: #294f4a; font-size: 12px; font-weight: 700; }
.member-viewer-empty {
  min-height: 0;
  margin: 0;
  padding: 70px 20px;
  color: #748985;
  display: grid;
  flex: 1 1 auto;
  place-items: center;
  text-align: center;
  font-size: 12px;
}
.member-pagination {
  min-height: 56px;
  padding: 0 16px 0 18px;
  border-top: 1px solid #dfe8e6;
  background: #fbfdfc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.member-pagination > span { color: #718783; font-size: 12px; font-variant-numeric: tabular-nums; }
.permission-assignment-modal {
  width: min(1240px, calc(100vw - 48px));
  height: min(760px, calc(100dvh - 48px));
}
.permission-editor {
  height: 100%;
  min-height: 0;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
}
.permission-editor-head {
  min-height: 58px;
  padding: 8px 12px;
  border-bottom: 1px solid #dce7e4;
  background: #f8fbfa;
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}
.permission-back {
  min-height: 32px;
  padding: 0 8px;
  border: 0;
  color: #4f706b;
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  cursor: pointer;
}
.permission-back:hover { color: #0d6f66; }
.permission-editor-head > div { min-width: 0; display: flex; align-items: baseline; gap: 8px; }
.permission-editor-head > div span { color: #79908c; font-size: 12px; }
.permission-editor-head > div strong { overflow: hidden; color: #1f4a46; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.permission-editor-head > div small { color: #78908c; font-size: 12px; }
.save-assignment-button {
  min-height: 34px;
  padding: 0 13px;
  border: 1px solid #0d756b;
  border-radius: 6px;
  color: #fff;
  background: #0d756b;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.save-assignment-button:disabled { cursor: not-allowed; opacity: .45; }
.permission-editor-loading {
  min-height: 0;
  padding: 20px;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
}
.permission-editor-loading > header {
  min-height: 42px;
  display: flex;
  align-items: baseline;
  gap: 9px;
}
.permission-editor-loading > header strong { color: #31544f; font-size: 13px; }
.permission-editor-loading > header span { color: #7d918d; font-size: 12px; }
.permission-loading-layout {
  min-height: 0;
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr);
  gap: 18px;
}
.permission-loading-layout section,
.permission-loading-layout aside {
  min-height: 0;
  padding: 14px;
  border: 1px solid #e0e9e7;
  border-radius: 7px;
  background: #fbfdfc;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.permission-loading-layout i {
  height: 42px;
  border-radius: 5px;
  background: linear-gradient(90deg, #e8f0ee 20%, #f5f9f8 45%, #e8f0ee 70%);
  background-size: 240% 100%;
  animation: permission-skeleton 1.2s ease-in-out infinite;
}
.permission-loading-layout aside i:first-child { width: 55%; height: 24px; }
.permission-loading-layout aside i:nth-child(2) { height: 88px; }
.permission-loading-layout aside i:nth-child(3) { height: 88px; }
.permission-loading-layout aside i:last-child { width: 42%; height: 34px; margin-top: auto; align-self: flex-end; }
.permission-editor-error {
  min-height: 0;
  padding: 48px 24px;
  color: #768b87;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.permission-editor-error :deep(svg) { color: #bd644c; }
.permission-editor-error strong { margin-top: 12px; color: #31524e; font-size: 14px; }
.permission-editor-error p { max-width: 480px; margin: 6px 0 0; font-size: 12px; line-height: 1.6; }
.permission-editor-error button {
  min-height: 34px;
  margin-top: 16px;
  padding: 0 13px;
  border: 1px solid #a8cac4;
  border-radius: 6px;
  color: #0c675e;
  background: #fff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.permission-editor-body {
  min-height: 0;
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: minmax(330px, 1.15fr) minmax(300px, .85fr);
  overflow: hidden;
}
.permission-tree-panel {
  min-width: 0;
  min-height: 0;
  border-right: 1px solid #dfe9e7;
  display: flex;
  flex-direction: column;
}
.permission-tree-panel > header {
  min-height: 51px;
  padding: 8px 10px;
  border-bottom: 1px solid #e2ebe9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.permission-tree-panel > header label {
  min-width: 150px;
  max-width: 290px;
  height: 33px;
  flex: 1 1 auto;
  padding: 0 9px;
  border: 1px solid #cadbd7;
  border-radius: 6px;
  color: #78908d;
  display: flex;
  align-items: center;
  gap: 6px;
}
.permission-tree-panel > header input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  color: #234a46;
  background: transparent;
  font-size: 12px;
}
.permission-tree-panel > header > div { flex: 0 0 auto; display: flex; gap: 4px; }
.permission-tree-panel > header button {
  min-height: 30px;
  padding: 0 7px;
  border: 1px solid #d1dfdc;
  border-radius: 5px;
  color: #5e7672;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.permission-tree-columns {
  min-height: 32px;
  padding: 0 10px;
  border-bottom: 1px solid #e4ecea;
  color: #718681;
  background: #f5f8f7;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 650;
}
.permission-tree-columns span:last-child { text-align: right; }
.permission-tree-scroll { min-height: 0; overflow: auto; }
.permission-tree-row {
  width: 100%;
  min-height: 43px;
  padding: 5px 10px 5px calc(8px + (var(--permission-depth) * 15px));
  border: 0;
  border-bottom: 1px solid #edf2f1;
  color: inherit;
  background: #fff;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px;
  align-items: center;
  gap: 8px;
  text-align: left;
  cursor: pointer;
  transition: background .15s ease, box-shadow .15s ease;
}
.permission-tree-row:hover { background: #f7faf9; }
.permission-tree-row.selected { background: #eaf5f2; box-shadow: inset 3px 0 #0d756b; }
.permission-tree-name { min-width: 0; display: flex; align-items: center; gap: 6px; }
.permission-tree-name > i { flex: 0 0 18px; }
.permission-tree-toggle {
  flex: 0 0 18px;
  height: 22px;
  border-radius: 4px;
  color: #79908d;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform .15s ease, background .15s ease;
}
.permission-tree-toggle:hover { background: #dceae7; }
.permission-tree-toggle.expanded { transform: rotate(90deg); }
.permission-tree-name > :deep(.n-icon) { flex: 0 0 auto; color: #4f817b; }
.permission-tree-name > span:last-child { min-width: 0; }
.permission-tree-name strong,
.permission-tree-name small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.permission-tree-name strong { color: #244b47; font-size: 12px; }
.permission-tree-name small { margin-top: 2px; color: #849592; font-size: 12px; }
.permission-tree-status {
  justify-self: end;
  max-width: 110px;
  overflow: hidden;
  padding: 3px 6px;
  border-radius: 5px;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.permission-tree-status.direct { color: #0b675e; background: #dff0ec; }
.permission-tree-status.inherited { color: #75622b; background: #f4edcf; }
.permission-tree-status.descendant { color: #426d7a; background: #e6f0f3; }
.permission-tree-status.none { color: #7d8d8a; background: #eef2f1; }
.permission-tree-empty { padding: 50px 20px; color: #7c908d; text-align: center; font-size: 12px; }

.node-permission-editor {
  min-width: 0;
  min-height: 0;
  padding: 17px;
  background: #fbfdfc;
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.node-permission-editor > header {
  padding-bottom: 13px;
  border-bottom: 1px solid #dfe9e7;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.node-permission-editor > header > div { min-width: 0; }
.node-permission-editor > header span { color: #0d756b; font-size: 12px; font-weight: 650; }
.node-permission-editor h3 {
  margin: 3px 0 0;
  overflow: hidden;
  color: #173f3b;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-permission-editor header p {
  margin: 4px 0 0;
  color: #78908d;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.node-permission-editor header em {
  flex: 0 0 auto;
  padding: 3px 7px;
  border-radius: 5px;
  font-size: 12px;
  font-style: normal;
}
.node-permission-editor header em.direct { color: #0b675e; background: #dff0ec; }
.node-permission-editor header em.inherited { color: #75622b; background: #f4edcf; }
.node-permission-editor header em.descendant { color: #426d7a; background: #e6f0f3; }
.node-permission-editor header em.none { color: #758582; background: #e9efed; }
.capability-section { padding: 15px 0; border-bottom: 1px solid #e1eae8; }
.capability-section > strong { color: #3d5d58; font-size: 12px; }
.capability-options { margin-top: 9px; display: grid; grid-template-columns: repeat(2, minmax(100px, 1fr)); gap: 6px; }
.capability-options label {
  min-width: 0;
  min-height: 49px;
  padding: 7px;
  border: 1px solid #d5e2df;
  border-radius: 6px;
  background: #fff;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease;
}
.capability-options label:hover { border-color: #a8cdc7; }
.capability-options label.checked { border-color: #81bbb2; background: #eaf5f2; }
.capability-options input { flex: 0 0 auto; margin: 2px 0 0; accent-color: #0d756b; }
.capability-options span { min-width: 0; }
.capability-options strong { display: block; color: #315552; font-size: 12px; }
.capability-options small { display: block; margin-top: 1px; color: #829490; font-size: 12px; line-height: 1.35; }
.inherit-option {
  margin-top: 14px;
  padding: 10px;
  border: 1px solid #d7e3e0;
  border-radius: 6px;
  background: #fff;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
}
.inherit-option.disabled { opacity: .5; cursor: not-allowed; }
.inherit-option input { margin-top: 2px; accent-color: #0d756b; }
.inherit-option span { min-width: 0; }
.inherit-option strong,
.inherit-option small { display: block; }
.inherit-option strong { color: #315550; font-size: 12px; }
.inherit-option small { margin-top: 2px; color: #7b8f8b; font-size: 12px; }
.inherited-note {
  margin: 10px 0 0;
  padding: 8px 9px;
  border-left: 2px solid #c3a958;
  color: #73632f;
  background: #f7f2df;
  font-size: 12px;
  line-height: 1.55;
}
.node-permission-editor > footer {
  margin-top: auto;
  padding-top: 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.node-permission-editor > footer span { color: #778d89; font-size: 12px; }
.clear-node-button {
  min-height: 31px;
  padding: 0 9px;
  border: 1px solid #dfb3a7;
  border-radius: 6px;
  color: #a34b36;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.node-permission-empty {
  min-height: 0;
  padding: 40px 20px;
  color: #7b908c;
  background: #fbfdfc;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.node-permission-empty strong { margin-top: 10px; color: #3a5b56; font-size: 13px; }

button:focus-visible,
input:focus-visible {
  outline: 2px solid rgba(15, 118, 110, .25);
  outline-offset: 1px;
}

@media (max-width: 1100px) {
  .permission-editor-body { grid-template-columns: minmax(300px, 1fr) minmax(280px, .85fr); }
}

@media (max-width: 760px) {
  .permission-modal-backdrop { padding: 12px; }
  .permission-modal { max-width: calc(100vw - 24px); max-height: calc(100dvh - 24px); }
  .permission-standard-modal { width: calc(100vw - 24px); height: calc(100dvh - 24px); }
  .permission-editor-head { grid-template-columns: 1fr auto; }
  .permission-editor-head > div { grid-column: 1 / -1; grid-row: 1; }
  .permission-back { grid-column: 1; grid-row: 2; }
  .save-assignment-button { grid-column: 2; grid-row: 2; }
  .permission-loading-layout { grid-template-columns: 1fr; overflow: auto; }
  .permission-loading-layout section { min-height: 340px; }
  .permission-loading-layout aside { min-height: 300px; }
  .permission-editor-body { grid-template-columns: 1fr; overflow: auto; }
  .permission-tree-panel { min-height: 420px; border-right: 0; border-bottom: 1px solid #dfe9e7; }
  .node-permission-editor { min-height: 380px; }
}
</style>
