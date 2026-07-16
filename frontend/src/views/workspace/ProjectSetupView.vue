<template>
  <div class="setup-page">
    <header class="page-heading">
      <div>
        <span>工程基础</span>
        <h1>工程配置</h1>
        <p>先建立工程底图，再让任务、资料、风险和填报流程可追溯地运转。</p>
      </div>
      <button class="refresh" :disabled="store.loading" @click="refresh">刷新数据</button>
    </header>

    <section class="setup-grid first-grid">
      <article class="panel create-project">
        <div class="panel-head"><div><h2>新建工程项目</h2><p>项目是所有资料、任务和风险的归属边界。</p></div></div>
        <form class="form-stack" @submit.prevent="submitProject">
          <label>项目名称<input v-model.trim="projectForm.project_name" required placeholder="例如：真如社区卫生服务中心扩建项目"></label>
          <label>所属单位<input v-model.trim="projectForm.owner_unit" placeholder="建设单位或管理单位"></label>
          <label>工程说明<textarea v-model.trim="projectForm.description" rows="3" placeholder="工程范围、阶段和当前重点"></textarea></label>
          <button type="submit" class="primary" :disabled="submitting">创建并进入配置</button>
        </form>
      </article>
      <article class="panel projects-panel">
        <div class="panel-head"><div><h2>已建项目</h2><p>{{ store.projects.length }} 个可访问项目</p></div></div>
        <button v-for="project in store.projects" :key="project.id" class="project-row" :class="{ active: project.id === store.currentProjectId }" @click="store.selectProject(project.id)">
          <span></span><div><strong>{{ project.name }}</strong><p>{{ project.ownerUnit || '未填写所属单位' }}</p></div><em>{{ project.status === 'active' ? '进行中' : project.status }}</em>
        </button>
        <p v-if="!store.projects.length" class="empty">还没有项目，请先创建一个项目。</p>
      </article>
    </section>

    <template v-if="store.currentProjectId">
      <section class="config-summary">
        <article><span>项目成员</span><strong>{{ store.members.length }}</strong><p>负责人与协作角色</p></article>
        <article><span>WBS 工序</span><strong>{{ store.wbsItems.length }}</strong><p>计划与进度基线</p></article>
        <article><span>风险源</span><strong>{{ store.riskSources.length }}</strong><p>控制要求与责任人</p></article>
        <article><span>风险关联</span><strong>{{ store.wbsRiskLinks.length }}</strong><p>预警触发依据</p></article>
        <article><span>质量指标</span><strong>{{ store.qualityMetrics.length }}</strong><p>工序质量控制点</p></article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>项目成员与责任</h2><p>添加账号后可分派任务和确认事项。</p></div></div>
          <form class="compact-form" @submit.prevent="submitMember">
            <input v-model.trim="memberForm.name" required placeholder="姓名">
            <input v-model.trim="memberForm.username" placeholder="登录账号（可选）">
            <input v-model.trim="memberForm.title" placeholder="岗位，例如安全员">
            <button type="button" class="primary" :disabled="submitting" @click="submitMember">添加</button>
          </form>
          <div class="item-list">
            <div v-for="member in store.members" :key="member.id"><strong>{{ member.name }}</strong><span>{{ member.title }}</span><small>{{ member.role.join('、') || '未设置责任标签' }}</small></div>
            <p v-if="!store.members.length" class="empty">暂无成员。</p>
          </div>
        </article>

        <article class="panel">
          <div class="panel-head"><div><h2>WBS 工序基线</h2><p>工序是进度、预警和日报匹配的基准。</p></div></div>
          <form class="compact-form wbs-form" @submit.prevent="submitWbs">
            <input v-model.trim="wbsForm.code" required placeholder="编码，例如 1.1">
            <input v-model.trim="wbsForm.name" required placeholder="工序名称">
            <input v-model="wbsForm.planned_start" type="date">
            <input v-model="wbsForm.planned_finish" type="date">
            <button type="submit" class="primary" :disabled="submitting">添加工序</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.wbsItems" :key="item.id"><strong>{{ item.code }} · {{ item.name }}</strong><span>{{ item.planStart || '未排期' }} 至 {{ item.planEnd || '未排期' }}</span><small>{{ item.progress }}% · {{ item.status }}</small></div>
            <p v-if="!store.wbsItems.length" class="empty">暂无 WBS 工序。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>质量指标与工序</h2><p>把验收项、控制要求、检查频次和资料要求挂接到 WBS。</p></div></div>
          <form class="compact-form quality-form" @submit.prevent="submitQualityMetric">
            <select v-model="qualityForm.wbs_item_id"><option value="">关联 WBS（可选）</option><option v-for="item in store.wbsItems" :key="item.id" :value="item.id">{{ item.code }} · {{ item.name }}</option></select>
            <input v-model.trim="qualityForm.name" required placeholder="质量验收项">
            <input v-model.trim="qualityForm.requirement" required placeholder="控制指标或验收要求">
            <input v-model.trim="qualityForm.inspection_frequency" placeholder="检查频次">
            <button type="submit" class="primary" :disabled="submitting">添加指标</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.qualityMetrics" :key="item.id"><strong>{{ item.name }}</strong><span>{{ store.getWbsName(item.wbsId || '') }} · {{ item.inspectionFrequency || '频次待定' }}</span><small>{{ item.requirement }}</small></div>
            <p v-if="!store.qualityMetrics.length" class="empty">暂无质量指标。</p>
          </div>
        </article>
        <article class="panel">
          <div class="panel-head"><div><h2>外部平台字段映射</h2><p>生成填报包时会自动按已启用映射写入目标字段。</p></div></div>
          <form class="compact-form mapping-form" @submit.prevent="submitPlatformMapping">
            <input v-model.trim="mappingForm.platformName" required placeholder="平台名称，例如监管填报平台">
            <select v-model="mappingForm.sourceField"><option value="draft_title">草稿标题</option><option value="draft_content">草稿内容</option><option value="source_refs">来源资料</option></select>
            <input v-model.trim="mappingForm.targetField" required placeholder="平台目标字段">
            <label class="check-label"><input v-model="mappingForm.required" type="checkbox"> 必填</label>
            <button class="primary" :disabled="submitting">添加映射</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.platformMappings" :key="item.id"><strong>{{ item.platformName }} · {{ item.targetField }}</strong><span>{{ sourceFieldLabel(item.sourceField) }}{{ item.required ? ' · 必填' : '' }}</span><small><button class="link-button" type="button" @click="store.removePlatformMapping(item.id)">删除</button></small></div>
            <p v-if="!store.platformMappings.length" class="empty">暂无字段映射；未配置时可手工填写填报字段。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>风险源与资料要求</h2><p>风险源定义后可关联工序，形成预警和上报闭环。</p></div></div>
          <form class="compact-form risk-form" @submit.prevent="submitRisk">
            <input v-model.trim="riskForm.name" required placeholder="风险源名称">
            <select v-model="riskForm.level"><option value="critical">重大</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select>
            <input v-model.trim="riskForm.risk_type" placeholder="风险类型">
            <input v-model.trim="riskForm.materials" placeholder="资料要求，使用顿号或逗号分隔">
            <button class="primary" :disabled="submitting">添加风险</button>
          </form>
          <div class="item-list">
            <div v-for="risk in store.riskSources" :key="risk.id"><strong>{{ risk.name }}</strong><span>{{ risk.type }} · {{ riskLabel(risk.level) }}</span><small>{{ risk.materials.join('、') || '未配置资料要求' }}</small></div>
            <p v-if="!store.riskSources.length" class="empty">暂无风险源。</p>
          </div>
        </article>
        <article class="panel audit-panel">
          <div class="panel-head"><div><h2>操作留痕</h2><p>项目基础数据的关键写操作自动记录。</p></div></div>
          <div class="item-list">
            <div v-for="log in store.logs.slice(0, 8)" :key="log.id"><strong>{{ log.action }}</strong><span>{{ log.detail }}</span><small>{{ formatTime(log.time) }}</small></div>
            <p v-if="!store.logs.length" class="empty">还没有操作记录。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>资料目录监控</h2><p>保存资料来源与扫描频率；开启后工作台会按此配置显示监控状态。</p></div></div>
          <form class="form-stack monitor-form" @submit.prevent="saveMonitoring">
            <label>资料接收目录<input v-model.trim="monitorForm.mainDir" placeholder="例如：\\\\server\\project\\incoming"></label>
            <div class="directory-pair"><label>归档目录<input v-model.trim="monitorForm.archiveDir" placeholder="已确认资料归档位置"></label><label>失败目录<input v-model.trim="monitorForm.failedDir" placeholder="解析失败资料位置"></label></div>
            <div class="directory-pair"><label>临时目录<input v-model.trim="monitorForm.tempDir" placeholder="处理中资料位置"></label><label>备份目录<input v-model.trim="monitorForm.backupDir" placeholder="备份位置"></label></div>
            <div class="monitor-controls"><label>扫描间隔（分钟）<input v-model.number="monitorForm.scanInterval" type="number" min="1" max="1440"></label><label class="check-label"><input v-model="monitorForm.enabled" type="checkbox"> 启用目录监控</label><button class="primary" :disabled="submitting">保存配置</button></div>
          </form>
        </article>
        <article class="panel">
          <div class="panel-head"><div><h2>风险预警规则</h2><p>配置预警提前量，作为风险关联和任务生成的统一规则来源。</p></div></div>
          <form class="compact-form reminder-form" @submit.prevent="addReminderRule">
            <select v-model="reminderForm.level"><option value="critical">重大风险</option><option value="high">高风险</option><option value="medium">中风险</option><option value="low">低风险</option></select>
            <input v-model.number="reminderForm.days" type="number" min="0" max="365" placeholder="提前天数">
            <button class="primary" type="submit">添加规则</button>
          </form>
          <div class="item-list">
            <div v-for="rule in monitorRules" :key="rule.id"><strong>{{ riskLabel(rule.level) }}</strong><span>提前 {{ rule.days }} 天预警</span><small><button type="button" class="link-button" @click="removeReminderRule(rule.id)">移除</button></small></div>
            <p v-if="!monitorRules.length" class="empty">暂无规则，可按风险等级添加预警提前量。</p>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useAppStore } from '@/stores/app'
import type { DirConfig, RemindRule, RiskLevel } from '@/types'

const store = useAppStore()
const message = useMessage()
const submitting = ref(false)
const projectForm = reactive({ project_name: '', owner_unit: '', description: '' })
const memberForm = reactive({ name: '', username: '', title: '' })
const wbsForm = reactive({ code: '', name: '', planned_start: '', planned_finish: '' })
const riskForm = reactive<{ name: string; level: RiskLevel; risk_type: string; materials: string }>({ name: '', level: 'medium', risk_type: '', materials: '' })
const qualityForm = reactive({ wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' })
const mappingForm = reactive({ platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false })
const monitorForm = reactive<DirConfig>({ mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false })
const monitorRules = ref<RemindRule[]>([])
const reminderForm = reactive<{ level: RiskLevel; days: number }>({ level: 'medium', days: 7 })

watch(() => [store.currentProjectId, store.dirConfig, store.remindRules] as const, () => {
  Object.assign(monitorForm, store.dirConfig)
  monitorRules.value = store.remindRules.map(rule => ({ ...rule }))
}, { immediate: true, deep: true })

async function run(action: () => Promise<unknown>, success: string) {
  submitting.value = true
  try { await action(); message.success(success) } catch (error: any) { message.error(error.response?.data?.detail || '保存失败，请检查权限和服务连接。') } finally { submitting.value = false }
}
function submitProject() { void run(async () => { await store.createProject(projectForm); Object.assign(projectForm, { project_name: '', owner_unit: '', description: '' }) }, '项目已创建') }
function submitMember() { void run(async () => { await store.saveMember({ name: memberForm.name, username: memberForm.username, title: memberForm.title }); Object.assign(memberForm, { name: '', username: '', title: '' }) }, '成员已添加') }
function submitWbs() { void run(async () => { await store.createWbs(wbsForm); Object.assign(wbsForm, { code: '', name: '', planned_start: '', planned_finish: '' }) }, 'WBS 工序已添加') }
function submitRisk() { void run(async () => { const materials = riskForm.materials.split(/[、,，]/).map(item => item.trim()).filter(Boolean); await store.createRisk({ name: riskForm.name, level: riskForm.level, risk_type: riskForm.risk_type || '综合风险', material_requirements: materials }); Object.assign(riskForm, { name: '', level: 'medium', risk_type: '', materials: '' }) }, '风险源已添加') }
function submitQualityMetric() { void run(async () => { await store.createQualityMetric(qualityForm); Object.assign(qualityForm, { wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' }) }, '质量指标已添加') }
function submitPlatformMapping() { void run(async () => { await store.createPlatformMapping({ ...mappingForm, enabled: true }); Object.assign(mappingForm, { platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false }) }, '平台字段映射已添加') }
function saveMonitoring() { void run(() => store.saveProjectSettings({ ...monitorForm, reminderRules: monitorRules.value }), '目录与预警规则已保存') }
function addReminderRule() { const index = monitorRules.value.findIndex(rule => rule.level === reminderForm.level); const next = { id: `rule-${reminderForm.level}`, level: reminderForm.level, days: Number(reminderForm.days) || 0, enabled: true }; if (index >= 0) monitorRules.value[index] = next; else monitorRules.value.push(next); message.info('规则已加入，请点击“保存配置”生效') }
function removeReminderRule(ruleId: string) { monitorRules.value = monitorRules.value.filter(rule => rule.id !== ruleId); message.info('规则已移除，请点击“保存配置”生效') }
function refresh() { void run(() => store.initialize(), '数据已刷新') }
function riskLabel(level: RiskLevel) { return ({ critical: '重大风险', high: '高风险', medium: '中风险', low: '低风险' } as Record<RiskLevel, string>)[level] }
function sourceFieldLabel(value: string) { return ({ draft_title: '草稿标题', draft_content: '草稿内容', source_refs: '来源资料' } as Record<string, string>)[value] || value }
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '刚刚' }
</script>

<style scoped>
.setup-page { max-width: 1440px; margin: 0 auto; padding: 28px; color: var(--text-primary); }
.page-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; padding:6px 0 24px; }
.page-heading span { color:var(--color-primary); font-size:12px; font-weight:700; letter-spacing:.08em; }.page-heading h1 { margin:6px 0; font-size:26px; }.page-heading p,.panel-head p { margin:0; color:var(--text-muted); font-size:13px; }.refresh,.primary { border:0; border-radius:6px; cursor:pointer; font-weight:700; }.refresh { background:#fff; border:1px solid var(--border-emphasis); padding:9px 14px; }.primary { background:var(--color-primary); color:#fff; padding:9px 14px; }.primary:disabled,.refresh:disabled { opacity:.55; cursor:not-allowed; }
.setup-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-top:18px; }.panel { background:#fff; border:1px solid var(--border-default); border-radius:10px; padding:20px; min-width:0; }.panel-head { margin-bottom:16px; }.panel-head h2 { margin:0 0 5px; font-size:16px; }.form-stack { display:grid; gap:12px; }.form-stack label { display:grid; gap:6px; font-size:12px; font-weight:700; color:var(--text-secondary); }.form-stack input,.form-stack textarea,.compact-form input,.compact-form select { border:1px solid var(--border-emphasis); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--text-primary); }.form-stack textarea { resize:vertical; }.compact-form { display:grid; grid-template-columns:1fr 1fr 1fr auto; gap:8px; }.wbs-form { grid-template-columns:.45fr 1.25fr 1fr 1fr auto; }.risk-form { grid-template-columns:1.1fr .55fr .9fr 1.35fr auto; }.quality-form { grid-template-columns:1fr 1fr 1.4fr .8fr auto; }.mapping-form { grid-template-columns:1.2fr .9fr 1fr auto auto; }.reminder-form { grid-template-columns:1fr 1fr auto; }.directory-pair,.monitor-controls { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.monitor-controls { align-items:end; grid-template-columns:1fr 1fr auto; }.check-label { display:flex !important; align-items:center; gap:7px; padding-bottom:9px; }.check-label input { width:15px; height:15px; }.link-button { border:0; padding:0; background:transparent; color:var(--color-primary); cursor:pointer; font:inherit; }.item-list { display:grid; gap:0; margin-top:16px; border-top:1px solid var(--border-default); }.item-list>div { display:grid; grid-template-columns:1.2fr 1fr .8fr; gap:10px; align-items:center; padding:11px 0; border-bottom:1px solid var(--border-default); font-size:12px; }.item-list strong { font-size:13px; }.item-list span,.item-list small { color:var(--text-muted); }.empty { color:var(--text-muted); font-size:13px; padding:14px 0; }.project-row { display:flex; text-align:left; align-items:center; gap:10px; width:100%; padding:12px 4px; border:0; border-bottom:1px solid var(--border-default); background:transparent; cursor:pointer; }.project-row.active { color:var(--color-primary); }.project-row>span { width:8px; height:8px; border-radius:50%; background:var(--color-success); }.project-row div { flex:1; }.project-row strong,.project-row p { display:block; margin:0; }.project-row p,.project-row em { margin-top:3px; color:var(--text-muted); font-size:11px; font-style:normal; }.config-summary { display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-top:18px; }.config-summary article { padding:16px; background:#f8faf9; border:1px solid var(--border-default); border-radius:9px; }.config-summary span,.config-summary p { display:block; color:var(--text-muted); font-size:12px; }.config-summary strong { display:block; margin:8px 0 3px; font-size:28px; }.config-summary p { margin:0; }
@media (max-width:1000px) { .setup-grid,.first-grid { grid-template-columns:1fr; }.config-summary { grid-template-columns:repeat(2,1fr); }.compact-form,.wbs-form,.risk-form { grid-template-columns:1fr 1fr; }.compact-form button { grid-column:span 2; } } @media (max-width:600px) { .setup-page { padding:18px; }.page-heading { display:block; }.refresh { margin-top:12px; }.config-summary { grid-template-columns:1fr 1fr; }.item-list>div { grid-template-columns:1fr; gap:3px; } }
</style>
