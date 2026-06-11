<template>
  <div class="page-wrapper">
    <!-- Fluid Pro-SaaS Header -->
    <div class="view-header">
      <div class="vh-title-zone">
        <h2>草稿审核</h2>
        <p class="vh-subtitle">审核系统生成的风险管控草稿，确认后生成填报包提交上报。</p>
      </div>
    </div>

    <!-- Fluid Pro-SaaS Workbench Tabs -->
    <div class="workbench-tabs">
      <button :class="['w-tab-btn', { active: activeTab === 'pending' }]" @click="activeTab = 'pending'">
        待我审核 <span class="tab-badge-count red-badge" v-if="pendingCount > 0">{{ pendingCount }}</span>
      </button>
      <button :class="['w-tab-btn', { active: activeTab === 'history' }]" @click="activeTab = 'history'">
        已审核 <span class="tab-badge-count gray-badge">{{ historyCount }}</span>
      </button>
    </div>

    <div class="draft-list">
      <div v-for="draft in filteredDrafts" :key="draft.id" class="draft-card">
        <!-- Header -->
        <div class="draft-hd">
          <div class="draft-hd-left">
            <span :class="['level-badge', `level-${draft.riskLevel}`]">{{ levelLabel(draft.riskLevel) }}</span>
            <span class="draft-title">{{ draft.title }}</span>
          </div>
          <span :class="['status-badge', `ds-${draft.status}`]">{{ draftStatusLabel(draft.status) }}</span>
        </div>
        <div v-if="draft.missingItems?.length" class="missing-alert">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          提醒：以下佐证附件由于现场未扫描捕获，处于「缺失」预警状态：{{ draft.missingItems.join('、') }}
        </div>

        <!-- Body -->
        <div class="draft-body">
          <div class="left-col">
            <!-- Simulated Official Memorandum Document Layout -->
            <div class="official-doc-container">
              <div class="doc-badge-floating">草稿预览</div>
              
              <div class="doc-header">
                <div class="doc-org-title">合流污水总管标 · 风险动态管控文书</div>
                <div class="doc-sub-num font-mono">编号：DRAFT-{{ draft.id.toUpperCase() }}</div>
              </div>

              <div class="doc-content-area">
                <div class="doc-title-input-layer">
                  <span class="d-label">报告标题：</span>
                  <input v-model="draft.title" class="doc-inline-input" :disabled="draft.status !== 'reviewing'" />
                </div>

                <div class="doc-body-textarea-layer">
                  <span class="d-label">公文正文：</span>
                  <textarea v-model="draft.content" rows="8" class="doc-inline-textarea" :disabled="draft.status !== 'reviewing'"></textarea>
                </div>

                <div class="meta-inline-grid">
                  <div class="meta-inline-cell">
                    <span class="meta-ic-label">隐患/风险类型：</span>
                    <span class="meta-ic-val">{{ draft.hazardType }}</span>
                  </div>
                  <div class="meta-inline-cell">
                    <span class="meta-ic-label">责任人：</span>
                    <span class="meta-ic-val">{{ store.getMemberName(draft.responsibleId) }}</span>
                  </div>
                  <div class="meta-inline-cell">
                    <span class="meta-ic-label">整改期限：</span>
                    <span class="meta-ic-val font-mono text-danger">{{ draft.deadline }}</span>
                  </div>
                  <div class="meta-inline-cell col-full-cell">
                    <span class="meta-ic-label">建议管控整改措施：</span>
                    <span class="meta-ic-val">{{ draft.measures }}</span>
                  </div>
                </div>
              </div>

              <div class="doc-footer-sign font-mono">
                                工程智管家  ·  日期：{{ new Date().toLocaleDateString() }}
              </div>
            </div>
          </div>

          <div class="right-col">
            <div class="side-block">
              <div class="side-title">参考来源</div>
              <div class="ref-list">
                <div v-for="(ref, i) in draft.sourceRefs" :key="i" class="ref-item">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> 
                  <span class="ref-text">{{ ref }}</span>
                </div>
              </div>
            </div>

            <div class="side-block">
              <div class="side-title">配套附件 <span class="side-count">{{ draft.attachments?.length ?? 0 }} 个</span></div>
              <div v-if="draft.attachments?.length" class="attach-list">
                <div v-for="(att, i) in draft.attachments" :key="i" class="attach-row">
                  <!-- Attachment Type Minimal Icon -->
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                  </svg>
                  <span class="attach-name">{{ att.name }}</span>
                  <span :class="['attach-tag-new', att.ready ? 'ready-new' : 'missing-new']">{{ att.ready ? '已就绪' : '缺失(待补)' }}</span>
                </div>
              </div>
              <div v-else class="no-attach"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> 尚未绑定文件</div>
            </div>

            <div v-if="draft.status === 'reviewing'" class="review-block">
              <div class="fgroup">
                <label class="flabel font-semibold">审核/签批意见（选填）</label>
                <n-input v-model:value="reviewNote[draft.id]" type="textarea" :rows="2" placeholder="填写签批说明，退回修改意见将回流至前置工序" />
              </div>
              <div class="review-btns">
                <button class="btn-ok-prominent" @click="approveAndPackage(draft.id)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> 审核通过并生成填报包
                </button>
                <button class="btn-reject-prominent" @click="store.rejectDraft(draft.id, reviewNote[draft.id] ?? '')">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> 驳回修改
                </button>
              </div>
            </div>
            <div v-else class="review-result">
              <span v-if="draft.status === 'confirmed'" class="result-pass"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> 已审核通过</span>
              <div v-if="draft.status === 'confirmed'" class="package-result">
                <div class="package-title">平台填报包已生成</div>
                <div class="package-desc">包含 {{ draft.attachments.filter(item => item.ready).length }} 个附件、{{ draft.sourceRefs.length }} 条来源引用，待填报助手预览。</div>
                <router-link to="/filling" class="package-link">进入填报助手</router-link>
              </div>
              <span v-if="draft.status === 'rejected'" class="result-reject"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> 已驳回：{{ draft.reviewNote }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="filteredDrafts.length === 0" class="empty-card">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" style="color:var(--text-disabled)"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        <span>{{ activeTab === 'pending' ? '暂无待审核草稿' : '暂无历史签批记录' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useMessage, NInput } from 'naive-ui'

const store = useAppStore()
const message = useMessage()
const activeTab = ref<'pending' | 'history'>('pending')
const reviewNote = ref<Record<string, string>>({})

const filteredDrafts = computed(() => {
  if (activeTab.value === 'pending') {
    return store.riskDrafts.filter(d => d.status === 'reviewing')
  } else {
    return store.riskDrafts.filter(d => d.status !== 'reviewing')
  }
})

const pendingCount = computed(() => store.riskDrafts.filter(d => d.status === 'reviewing').length)
const historyCount = computed(() => store.riskDrafts.filter(d => d.status !== 'reviewing').length)

const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const draftStatusLabel = (s: string) => ({ reviewing: '待审核', confirmed: '已通过', rejected: '已驳回', draft: '草稿', packaged: '已打包' }[s] ?? s)
const approveAndPackage = (draftId: string) => {
  store.confirmDraft(draftId)
  message.success('草稿已审核通过，平台填报包已生成')
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

.draft-list { display: flex; flex-direction: column; gap: 20px; }

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

.draft-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: var(--transition-slow);
}
.draft-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-md);
}

.draft-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border-default);
  background: var(--bg-surface); gap: 10px; flex-wrap: wrap;
}
.draft-hd-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.draft-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.level-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.level-critical { background: var(--color-danger-soft);  color: var(--color-danger); }
.level-high     { background: var(--color-warning-soft); color: var(--color-warning); }
.level-medium   { background: var(--color-info-soft);    color: var(--color-info); }
.level-low      { background: var(--color-success-soft); color: var(--color-success); }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; flex-shrink: 0; }
.ds-reviewing { background: var(--color-warning-soft); color: var(--color-warning); }
.ds-confirmed { background: var(--color-success-soft); color: var(--color-success); }
.ds-rejected  { background: var(--color-danger-soft);  color: var(--color-danger); }
.ds-draft     { background: var(--bg-elevated); color: var(--text-muted); }
.ds-packaged  { background: var(--color-primary-soft); color: var(--color-primary); }

.missing-alert {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 16px;
  background: var(--color-danger-soft);
  border-bottom: 1px solid rgba(220,38,38,0.12);
  font-size: 12px; color: var(--color-danger);
  line-height: 1.4;
}

.draft-body { display: grid; grid-template-columns: 1fr 340px; }
.left-col { padding: 12px 14px; border-right: 1px solid var(--border-default); display: flex; flex-direction: column; gap: 12px; }
.right-col { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; background: rgba(244,245,247,0.4); }

/* Official Memorandum Container styles */
.official-doc-container {
  background: #FCFCFD;
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  padding: 24px;
  box-shadow: inset 0 1px 4px rgba(0,0,0,0.02);
  position: relative;
}
.doc-badge-floating {
  position: absolute;
  top: 10px;
  right: 12px;
  font-size: 11px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border: 1px solid rgba(232,89,12,0.2);
  padding: 1px 6px;
  border-radius: 20px;
}
.doc-header {
  border-bottom: 2px double var(--color-danger);
  padding-bottom: 8px;
  margin-bottom: 16px;
  text-align: center;
}
.doc-org-title {
  font-size: 18px;
  font-weight: 800;
  color: var(--color-danger);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.doc-sub-num {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
.doc-content-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.doc-title-input-layer {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px dashed var(--border-default);
  padding-bottom: 6px;
}
.d-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  white-space: nowrap;
}
.doc-inline-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  outline: none;
  padding: 1px 4px;
}
.doc-inline-input:focus {
  background: var(--bg-surface);
  border-radius: 2px;
  box-shadow: 0 0 0 1px var(--color-primary);
}
.doc-body-textarea-layer {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.doc-inline-textarea {
  flex: 1;
  width: 100%;
  border: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary);
  resize: vertical;
  outline: none;
  padding: 4px;
  box-sizing: border-box;
}
.doc-inline-textarea:focus {
  background: var(--bg-surface);
  border: 1px dashed var(--border-emphasis);
  border-radius: var(--radius-xs);
}
.meta-inline-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 10px;
  margin-top: 8px;
}
.meta-inline-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.col-full-cell {
  grid-column: span 3;
  border-top: 1px solid var(--border-subtle);
  padding-top: 6px;
  margin-top: 2px;
}
.meta-ic-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}
.meta-ic-val {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 600;
}
.doc-footer-sign {
  margin-top: 20px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 10px;
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  justify-content: space-between;
}

.ref-list { display: flex; flex-direction: column; gap: 5px; }
.ref-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); }
.ref-item svg { color: var(--color-success); flex-shrink: 0; }
.ref-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attach-list { display: flex; flex-direction: column; gap: 5px; }
.attach-row { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); }
.attach-row svg { color: var(--text-muted); flex-shrink: 0; }
.attach-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attach-tag-new {
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  flex-shrink: 0;
  font-weight: 700;
}
.ready-new {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.missing-new {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.review-block { margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border-default); display: flex; flex-direction: column; gap: 10px; }
.review-btns { display: flex; flex-direction: column; gap: 8px; }
.btn-ok-prominent {
  width: 100%;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 10px 14px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 600; font-family: inherit;
  border: none; cursor: pointer; transition: var(--transition);
  background: var(--color-success); color: #fff;
  box-shadow: 0 1px 2px rgba(4,120,87,0.1);
}
.btn-ok-prominent:hover {
  background: #035e45;
  box-shadow: 0 3px 6px rgba(4,120,87,0.2);
  transform: translateY(-1px);
}
.btn-reject-prominent {
  width: 100%;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 14px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 600; font-family: inherit;
  border: 1px solid transparent; cursor: pointer; transition: var(--transition);
  background: var(--color-danger-soft); color: var(--color-danger); border-color: rgba(220,38,38,0.2);
}
.btn-reject-prominent:hover {
  background: var(--color-danger); color: #fff;
  box-shadow: 0 3px 6px rgba(220,38,38,0.2);
  transform: translateY(-1px);
}

.review-result { margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border-default); }
.result-pass { display: flex; align-items: center; gap: 5px; font-size: 13px; color: var(--color-success); font-weight: 600; }
.result-reject { display: flex; align-items: center; gap: 5px; font-size: 13px; color: var(--color-danger); font-weight: 600; line-height: 1.4; }
.package-result { margin-top: 10px; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--color-primary-soft); border: 1px solid var(--border-primary); }
.package-title { font-size: 13px; font-weight: 750; color: var(--color-primary); }
.package-desc { margin-top: 4px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.package-link { margin-top: 8px; display: inline-flex; align-items: center; color: var(--color-primary); font-size: 12px; font-weight: 700; text-decoration: none; }
.package-link:hover { color: var(--color-primary-dark); }

.empty-card { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 60px 20px; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); color: var(--text-muted); font-size: 13px; }

@media (max-width: 1200px) {
  .draft-body { grid-template-columns: 1fr; }
  .left-col { border-right: none; border-bottom: 1px solid var(--border-default); }
  .right-col { background: var(--bg-card); }
}
@media (max-width: 768px) {
  .page-wrapper { padding: 12px 16px; }
}
</style>
