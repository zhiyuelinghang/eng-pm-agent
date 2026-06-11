<template>
  <div class="page-wrapper">
    <!-- Fluid Pro-SaaS Header -->
    <div class="view-header">
      <div class="vh-title-zone">
        <h2>填报助手</h2>
        <p class="vh-subtitle">协助填写监管平台表单，登录后辅助填充字段和上传附件，提交须手动操作。</p>
      </div>
    </div>

    <!-- Fluid Pro-SaaS Workbench Tabs -->
    <div class="workbench-tabs">
      <button :class="['w-tab-btn', { active: activeTab === 'pending' }]" @click="activeTab = 'pending'">
        待处理 <span class="tab-badge-count red-badge" v-if="pendingCount > 0">{{ pendingCount }}</span>
      </button>
      <button :class="['w-tab-btn', { active: activeTab === 'history' }]" @click="activeTab = 'history'">
        历史填报 <span class="tab-badge-count gray-badge">{{ historyCount }}</span>
      </button>
    </div>

    <!-- Security Banner -->
    <div class="security-banner">
      <div class="banner-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      </div>
      <span><strong>安全声明：</strong>账号、密码和验证码请只在目标平台页面输入。系统不保存密码，不绕过验证码，不自动最终提交。登录和最终提交须由您手动完成。</span>
    </div>

    <div class="fill-list">
      <div v-for="pkg in filteredPackages" :key="pkg.id" class="fill-card">
        <!-- Header -->
        <div class="card-hd">
          <div class="platform-info">
            <div class="platform-icon-wrap">
              <!-- Robot Vector Icon -->
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="10" rx="2"/>
                <circle cx="12" cy="5" r="2"/>
                <path d="M12 7v4"/>
                <line x1="8" y1="16" x2="8" y2="16"/>
                <line x1="16" y1="16" x2="16" y2="16"/>
              </svg>
            </div>
            <div>
              <div class="platform-name">{{ pkg.platformName }}</div>
              <div class="process-name">目标表单：{{ pkg.processName }}</div>
            </div>
          </div>
          <div class="hd-right">
            <span :class="['status-badge', `fs-${pkg.status}`]">{{ fillStatusLabel(pkg.status) }}</span>
              <span class="deadline-text font-mono">截止时间：{{ pkg.deadline }}</span>
          </div>
        </div>

        <!-- Body -->
        <div class="card-body">
          <div class="left-col">
            <div class="col-title">
              <span>待填字段</span>
              <span class="badge badge-accent">已锁定 · 只读</span>
            </div>
            
            <table class="fields-table">
              <thead>
                <tr>
                  <th>外部平台字段</th>
                  <th>提取値</th>
                  <th>填写状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(field, i) in pkg.fields" :key="i">
                  <td class="fn-cell">
                    <span class="field-binding-icon" aria-hidden="true">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                    </span>
                    {{ field.name }}
                    <span v-if="field.required" class="req-star">*</span>
                  </td>
                  <td>
                    <!-- Lock and pre-filled read-only styles -->
                    <div class="immutable-value-token" title="已从审核草稿读取，不可修改">
                      {{ field.value || field.placeholder || '—' }}
                    </div>
                  </td>
                  <td class="fs-cell">
                    <span :class="['field-dot', (field.value || pkg.status === 'submitted') ? 'dot-filled' : 'dot-empty']"></span>
                    <span :class="['field-status-text', (field.value || pkg.status === 'submitted') ? 'st-filled' : 'st-empty']">
                      {{ (field.value || pkg.status === 'submitted') ? '已就绪' : '待填写' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="right-col">
            <div class="side-block">
              <div class="col-title">待上传附件 <span class="col-count">{{ pkg.attachments?.length ?? 0 }} 项</span></div>
              <div v-if="pkg.attachments?.length" class="attach-list">
                <div v-for="(att, i) in pkg.attachments" :key="i" class="attach-row">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                  <span class="attach-name">{{ att.name }}</span>
                  <span :class="['attach-tag-status', att.ready ? 'att-ready' : 'att-missing']">{{ att.ready ? '已准备' : '缺失' }}</span>
                </div>
              </div>
            </div>

            <div class="side-block">
              <div class="col-title">填报步骤</div>
              <div class="steps-list">
                <div v-for="(step, i) in steps" :key="i" :class="['step-row', i < stepIndex(pkg) ? 'step-done' : i === stepIndex(pkg) ? 'step-active' : 'step-idle']">
                  <div class="step-num">{{ i < stepIndex(pkg) ? '✓' : i + 1 }}</div>
                  <div>
                    <div class="step-title">{{ step.title }}</div>
                    <div class="step-desc">{{ step.desc }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="side-block">
              <div class="col-title">自动录入进度</div>
              <div class="progress-track-large">
                <div class="progress-fill-large" :style="{ width: fillProgress(pkg) + '%' }"></div>
              </div>
              <div class="progress-meta">
                <span>{{ fillProgress(pkg) }}%</span>
                <span>{{ progressText(pkg) }}</span>
              </div>
              <div v-if="failedFields(pkg).length" class="failed-fields" role="alert">
                <div class="failed-title">需人工处理字段</div>
                <div v-for="field in failedFields(pkg)" :key="field.name" class="failed-row">
                  <span>{{ field.name }}</span>
                  <em>{{ field.placeholder || '平台登录后手动补齐' }}</em>
                </div>
              </div>
            </div>

            <div class="side-block login-check-block">
              <div class="col-title">登录确认</div>
              <button v-if="!loginConfirmed[pkg.id]" class="confirm-login-btn" @click="confirmLogin(pkg)">
                已在目标平台完成登录
              </button>
              <div v-else class="login-confirmed-state">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="20 6 9 17 4 12" /></svg>
                用户已确认登录，允许启动辅助填报
              </div>
            </div>

            <div class="action-bar">
              <button class="btn-primary" @click="openPlatform(pkg)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg> 打开目标平台
              </button>
              <button v-if="pkg.status === 'pending'" class="btn-warning-new" :disabled="!loginConfirmed[pkg.id]" @click="store.startFilling(pkg.id)">
                启动辅助填报
              </button>
              <button v-if="pkg.status === 'filling' && !savedDraft[pkg.id]" class="btn-success-prominent" @click="markSaved(pkg)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="20 6 9 17 4 12"/></svg> 标记平台草稿已保存
              </button>
              <button v-if="pkg.status === 'filling' && savedDraft[pkg.id]" class="btn-success-prominent" @click="store.markFillDone(pkg.id)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="20 6 9 17 4 12"/></svg> 标记用户已最终提交
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="filteredPackages.length === 0" class="empty-card">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" style="color:var(--text-disabled)"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
        <span>{{ activeTab === 'pending' ? '暂无待填报表单' : '暂无历史填报记录' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useMessage } from 'naive-ui'
import type { FillPackage } from '@/types'

const store = useAppStore()
const message = useMessage()
const activeTab = ref<'pending' | 'history'>('pending')
const loginConfirmed = reactive<Record<string, boolean>>({})
const savedDraft = reactive<Record<string, boolean>>({})

const filteredPackages = computed(() => {
  if (activeTab.value === 'pending') {
    return store.fillPackages.filter(p => p.status === 'pending' || p.status === 'filling')
  } else {
    return store.fillPackages.filter(p => p.status === 'submitted' || p.status === 'failed')
  }
})

const pendingCount = computed(() => store.fillPackages.filter(p => p.status === 'pending' || p.status === 'filling').length)
const historyCount = computed(() => store.fillPackages.filter(p => p.status === 'submitted' || p.status === 'failed').length)

const steps = [
  { title: '打开目标平台', desc: '在新标签页打开对应监管平台网页' },
  { title: '手动登录平台', desc: '请在平台网页手动输入账号密码完成登录' },
  { title: '启动辅助填报', desc: '定位表单字段，开始自动填充' },
  { title: '填充表单字段', desc: '逐项填入已确认的字段数据' },
  { title: '上传附件', desc: '上传已准备好的附件文件' },
  { title: '保存平台草稿', desc: '保存后停留在提交前由用户复核' },
  { title: '用户最终提交', desc: '最终提交由用户本人完成' },
]
const fillStatusLabel = (s: string) => ({ pending: '待处理', filling: '填报中', submitted: '已提交', failed: '填报失败' }[s] ?? s)
const stepIndex = (pkg: FillPackage) => {
  if (pkg.status === 'submitted') return 7
  if (pkg.status === 'filling' && savedDraft[pkg.id]) return 6
  if (pkg.status === 'filling') return 4
  if (loginConfirmed[pkg.id]) return 2
  return { pending: 0, failed: 2 }[pkg.status] ?? 0
}
const fillProgress = (pkg: FillPackage) => {
  if (pkg.status === 'submitted') return 100
  if (pkg.status === 'filling' && savedDraft[pkg.id]) return 92
  if (pkg.status === 'filling') return 68
  if (loginConfirmed[pkg.id]) return 28
  return 0
}
const progressText = (pkg: FillPackage) => {
  if (pkg.status === 'submitted') return '用户已完成最终提交'
  if (pkg.status === 'filling' && savedDraft[pkg.id]) return '平台草稿已保存，等待用户提交'
  if (pkg.status === 'filling') return '正在填字段并上传附件'
  if (loginConfirmed[pkg.id]) return '已确认登录，可启动录入'
  return '等待打开平台并手动登录'
}
const failedFields = (pkg: FillPackage) => pkg.fields.filter(field => field.required && !field.value)
const confirmLogin = (pkg: FillPackage) => {
  loginConfirmed[pkg.id] = true
  message.success('已确认目标平台登录状态')
}
const markSaved = (pkg: FillPackage) => {
  savedDraft[pkg.id] = true
  message.success('平台草稿已保存，停留在最终提交前')
}
const openPlatform = (pkg: FillPackage) => {
  message.info(`请在弹出的新沙箱网页中登录「${pkg.platformName}」`)
}
</script>

<style scoped>
.page-wrapper { padding: 20px 24px; }

/* Workbench Tabs Style */
.workbench-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-default);
  margin-bottom: 20px;
  padding-bottom: 2px;
}
.w-tab-btn {
  background: transparent;
  border: none;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-muted);
  padding: 10px 16px;
  cursor: pointer;
  position: relative;
  transition: var(--transition);
}
.w-tab-btn:hover {
  color: var(--text-secondary);
}
.w-tab-btn.active {
  color: var(--color-primary);
  font-weight: 700;
}
.w-tab-btn.active::after {
  content: '';
  position: absolute;
  bottom: -3px;
  left: 0;
  width: 100%;
  height: 2px;
  background: var(--color-primary);
  border-radius: 2px;
}
.tab-badge-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 20px;
  margin-left: 4px;
}
.red-badge {
  background: var(--color-danger);
  color: #fff;
}
.gray-badge {
  background: var(--bg-hover);
  color: var(--text-muted);
  border: 1px solid var(--border-default);
}

/* Header */
.view-header {
  margin-bottom: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 14px 18px;
}
.vh-title-zone h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}
.vh-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.4;
  margin: 0;
}

.security-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 18px;
  background: var(--color-danger-soft);
  border: 1px solid rgba(220,38,38,0.2);
  border-radius: var(--radius-sm);
  margin-bottom: 20px;
  font-size: 12px;
  color: var(--color-danger);
  line-height: 1.5;
}
.banner-icon { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.security-banner strong { font-weight: 700; }

.fill-list { display: flex; flex-direction: column; gap: 20px; }
.fill-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: var(--transition-slow);
}
.fill-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-md);
}

.card-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border-default);
  background: var(--bg-surface); flex-wrap: wrap; gap: 12px;
}
.platform-info { display: flex; align-items: center; gap: 12px; }
.platform-icon-wrap {
  width: 32px; height: 32px;
  background: rgba(232,89,12,0.06);
  border-radius: var(--radius-sm);
  display: flex; align-items: center; justify-content: center;
  color: var(--color-primary); font-size: 16px;
}
.platform-name { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.process-name { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.hd-right { display: flex; align-items: center; gap: 14px; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.fs-pending   { background: var(--color-info-soft);    color: var(--color-info); }
.fs-filling   { background: var(--color-warning-soft); color: var(--color-warning); }
.fs-submitted { background: var(--color-success-soft); color: var(--color-success); }
.fs-failed    { background: var(--color-danger-soft);  color: var(--color-danger); }
.deadline-text { font-size: 12px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }

.card-body { display: grid; grid-template-columns: 1fr 340px; }
.left-col { padding: 12px 14px; border-right: 1px solid var(--border-default); }
.right-col { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; background: rgba(244,245,247,0.4); }

.col-title { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.col-count { font-size: 11px; font-weight: 400; color: var(--text-secondary); background: var(--bg-hover); padding: 1px 4px; border-radius: 8px; }

.fields-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 4px; }
.fields-table th { text-align: left; padding: 6px 8px; font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; border-bottom: 1px solid var(--border-default); background: var(--bg-hover); }
.fields-table td { padding: 8px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
.fields-table tr:hover td { background: var(--bg-hover); }

.fn-cell { color: var(--text-primary); width: 150px; white-space: nowrap; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 4px; }
.field-binding-icon { width: 14px; height: 14px; color: var(--text-muted); display: inline-flex; align-items: center; justify-content: center; }
.req-star { color: var(--color-danger); margin-left: 2px; }

/* Locked Pre-filled Token values styling */
.immutable-value-token {
  font-size: 14px;
  color: var(--text-secondary);
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 6px 10px;
  max-width: 480px;
  width: 100%;
  font-family: inherit;
  white-space: normal;
  word-break: break-all;
}

.fs-cell { width: 70px; }
.fields-table .fs-cell { display: table-cell; }
.field-dot { display: inline-block; width: 5px; height: 5px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
.dot-filled { background: var(--color-success); }
.dot-empty  { background: var(--color-danger); }
.field-status-text { font-size: 12px; font-weight: 500; margin-left: 4px; vertical-align: middle; }
.st-filled { color: var(--color-success); }
.st-empty  { color: var(--color-danger); }

.side-block {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}
.attach-list { display: flex; flex-direction: column; gap: 5px; }
.attach-row { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); }
.attach-row svg { color: var(--text-muted); flex-shrink: 0; }
.attach-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attach-tag-status { font-size: 11px; padding: 1px 4px; border-radius: 3px; flex-shrink: 0; font-weight: 600; }
.att-ready   { background: var(--color-success-soft); color: var(--color-success); }
.att-missing { background: var(--color-danger-soft);  color: var(--color-danger); }

.steps-list { display: flex; flex-direction: column; gap: 10px; position: relative; }
.step-row { display: flex; align-items: flex-start; gap: 12px; font-size: 13px; position: relative; }
.step-num {
  width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; flex-shrink: 0; margin-top: 1px;
}
.step-done .step-num { background: var(--color-success); color: #fff; }
.step-active .step-num { background: var(--color-primary); color: #fff; box-shadow: 0 0 0 3px var(--color-primary-dim); }
.step-idle .step-num { background: var(--bg-hover); color: var(--text-muted); border: 1px solid var(--border-default); }
.step-title { font-weight: 600; color: var(--text-primary); line-height: 1.4; }
.step-desc { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.step-done .step-title { color: var(--color-success); }
.step-active .step-title { color: var(--color-primary); }
.progress-track-large { height: 8px; border-radius: 4px; background: var(--bg-hover); overflow: hidden; }
.progress-fill-large { height: 100%; border-radius: 4px; background: var(--color-primary); transition: width .25s ease; }
.progress-meta { display: flex; justify-content: space-between; gap: 8px; margin-top: 6px; font-size: 12px; color: var(--text-secondary); }
.progress-meta span:first-child { color: var(--color-primary); font-weight: 800; font-family: 'JetBrains Mono', monospace; }
.failed-fields { margin-top: 10px; padding: 9px 10px; border-radius: var(--radius-xs); background: var(--color-warning-soft); color: var(--color-warning); }
.failed-title { font-size: 12px; font-weight: 800; margin-bottom: 6px; }
.failed-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; line-height: 1.4; }
.failed-row em { font-style: normal; color: var(--text-secondary); }
.confirm-login-btn { width: 100%; padding: 8px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-primary); background: var(--color-primary-soft); color: var(--color-primary); font-size: 13px; font-weight: 700; cursor: pointer; }
.confirm-login-btn:hover { background: var(--color-primary); color: #fff; }
.login-confirmed-state { display: flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--color-success-soft); color: var(--color-success); font-size: 12px; font-weight: 700; line-height: 1.4; }

.action-bar { display: flex; flex-direction: column; gap: 8px; padding-top: 14px; border-top: 1px solid var(--border-default); margin-top: auto; }
.action-bar button { width: 100%; display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 14px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; transition: var(--transition); border: none; }
.action-bar button:disabled { opacity: .45; cursor: not-allowed; transform: none; }
.btn-primary { background: var(--color-primary-soft); color: var(--color-primary); border: 1px solid var(--border-primary) !important; }
.btn-primary:hover { background: var(--color-primary); color: #fff; transform: translateY(-1px); }
.btn-warning-new { background: var(--color-primary); color: #fff; font-weight: 600; box-shadow: 0 1px 2px rgba(232,89,12,0.1); }
.btn-warning-new:hover { background: var(--color-primary-dark); transform: translateY(-1px); }
.btn-success-prominent { background: var(--color-success); color: #fff; font-weight: 600; }
.btn-success-prominent:hover { background: #035e45; transform: translateY(-1px); }

.empty-card { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 80px 20px; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); color: var(--text-muted); font-size: 13px; }

@media (max-width: 1200px) {
  .card-body { grid-template-columns: 1fr; }
  .left-col { border-right: none; border-bottom: 1px solid var(--border-default); }
  .right-col { background: var(--bg-card); }
}
@media (max-width: 768px) {
  .page-wrapper { padding: 12px 16px; }
}
</style>
