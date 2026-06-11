<template>
  <div class="page-wrapper">
    <!-- Fluid Pro-SaaS Header -->
    <div class="view-header">
      <div class="vh-title-zone">
        <h2>日报解析确认</h2>
        <p class="vh-subtitle">自动读取日报文件，提取施工进度与风险信息，确认后更新项目进度。</p>
      </div>
    </div>

    <!-- Fluid Pro-SaaS Workbench Tabs -->
    <div class="workbench-tabs">
      <button :class="['w-tab-btn', { active: activeTab === 'pending' }]" @click="activeTab = 'pending'">
        待我确认 <span class="tab-badge-count red-badge" v-if="pendingCount > 0">{{ pendingCount }}</span>
      </button>
      <button :class="['w-tab-btn', { active: activeTab === 'history' }]" @click="activeTab = 'history'">
        历史归档 <span class="tab-badge-count gray-badge">{{ historyCount }}</span>
      </button>
      <button :class="['w-tab-btn', { active: activeTab === 'failed' }]" @click="activeTab = 'failed'">
        异常文件 <span class="tab-badge-count gray-badge">{{ failedCount }}</span>
      </button>
    </div>

    <div class="report-list">
      <template v-if="activeTab === 'failed'">
      <div v-for="file in failedFiles" :key="file.id" class="report-card failed-file-card">
        <div class="card-hd">
          <div class="file-info">
            <div class="file-icon-wrap failed-icon-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <div>
              <div class="file-header-flex">
                <span class="file-name">{{ file.fileName }}</span>
                <span class="parse-badge parse-failed">解析失败</span>
              </div>
              <div class="file-meta font-mono">发现时间：{{ file.detectedAt }} · 文件类型：{{ file.fileType }}</div>
            </div>
          </div>
        </div>
        <div class="failed-file-body">
          <div class="failed-reason" role="alert">
            <strong>异常原因：</strong>{{ file.reason }}
          </div>
          <div class="failed-actions">
            <button class="btn-ghost-full" @click="retryFailedFile(file.fileName)">重新解析</button>
            <button class="btn-success-prominent" @click="message.info('原型演示：已创建人工确认任务')">转人工确认</button>
          </div>
        </div>
      </div>
      </template>

      <template v-if="activeTab !== 'failed'">
      <div v-for="report in filteredReports" :key="report.id" class="report-card">
        <!-- Card Header -->
        <div class="card-hd">
          <div class="file-info">
            <div class="file-icon-wrap">
              <!-- Excel / Docx Solid Minimal Icon -->
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="8" y1="13" x2="16" y2="13"/>
                <line x1="8" y1="17" x2="16" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
            </div>
            <div>
              <div class="file-header-flex">
                <span class="file-name">{{ report.fileName }}</span>
                <span :class="['parse-badge', `parse-${report.parseStatus}`]">{{ parseStatusLabel(report.parseStatus) }}</span>
              </div>
              <div class="file-meta font-mono">抓取日期：{{ report.date }} · 文件类型：{{ report.fileType }}</div>
            </div>
          </div>
          <div class="hd-right">
            <div class="conf-row">
              <span class="conf-label-text">匹配置信度</span>
              <div class="conf-track">
                <div class="conf-fill" :style="{ width: (report.confidence * 100).toFixed(0) + '%', background: confColor(report.confidence) }"></div>
              </div>
              <span class="conf-num font-mono" :style="{ color: confColor(report.confidence) }">{{ (report.confidence * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>

        <!-- Card Body: two columns -->
        <div class="card-body">
          <div class="fields-col">
            <div class="extracted-doc-panel">
              <div class="doc-panel-title">
                <span class="pulse-active-indicator"></span>
                <span>解析结果</span>
                <span class="doc-panel-badge">可编辑</span>
              </div>
              
              <div class="fields-grid">
                <div class="extracted-text-block col-full">
                  <span class="et-label">施工内容</span>
                  <n-input v-model:value="report.constructionContent" type="textarea" :rows="3" class="editable-field" />
                </div>

                <div class="extracted-text-block">
                  <span class="et-label">当日进度</span>
                  <n-input-number v-model:value="report.currentProgress" :min="0" :max="100" class="editable-number" />
                </div>

                <div class="extracted-text-block">
                  <span class="et-label">累计进度</span>
                  <n-input-number v-model:value="report.cumulativeProgress" :min="0" :max="100" class="editable-number" />
                </div>

                <div class="extracted-text-block col-full">
                  <span class="et-label">存在隐患或问题</span>
                  <n-input v-model:value="report.problems" type="textarea" :rows="2" placeholder="未提取到异常隐患" class="editable-field" />
                </div>

                <div class="extracted-text-block col-full">
                  <span class="et-label">风险源控制情况</span>
                  <n-input v-model:value="report.riskContent" type="textarea" :rows="2" placeholder="未提取到风险记录" class="editable-field" />
                </div>

                <div class="extracted-text-block col-full">
                  <span class="et-label">安全巡视/监测记录</span>
                  <n-input v-model:value="report.monitorContent" type="textarea" :rows="2" class="editable-field" />
                </div>

                <div class="extracted-text-block col-full">
                  <span class="et-label">明日计划</span>
                  <n-input v-model:value="report.tomorrowPlan" type="textarea" :rows="2" class="editable-field" />
                </div>
              </div>
            </div>
          </div>

          <div class="side-col">
            <div class="ai-meta-card">
              <div class="side-title">解析详情</div>
              <div class="meta-item">
                <span class="meta-lbl">总体置信度</span>
                <div class="conf-chip-wrap">
                  <span class="conf-text" :style="{ color: confColor(report.confidence) }">{{ (report.confidence * 100).toFixed(0) }}%</span>
                  <div class="conf-track-mini">
                    <div class="conf-fill-mini" :style="{ width: (report.confidence * 100).toFixed(0) + '%', background: confColor(report.confidence) }"></div>
                  </div>
                </div>
              </div>
              <div class="meta-item mt-10">
                <span class="meta-lbl">执行状态</span>
                <span class="badge badge-success font-mono">已入库</span>
              </div>
            </div>
            
            <div class="fgroup wbs-linker">
              <label class="flabel">日报日期</label>
              <n-input v-model:value="report.date" placeholder="YYYY-MM-DD" />
            </div>

            <div class="fgroup wbs-linker">
              <label class="flabel">关联 WBS 节点</label>
              <n-select v-model:value="report.matchedWbsId" :options="wbsOptions" placeholder="选择 WBS 节点" style="width:100%" />
              <p class="wbs-matching-explanation">请确认日报对应的 WBS 节点，确认后将更新实际进度。</p>
            </div>

            <div class="fgroup attachment-marker">
              <label class="flabel">照片和附件标记</label>
              <div class="attachment-list">
                <label v-for="item in attachmentMarks" :key="item.name" class="attachment-mark-row">
                  <input v-model="item.checked" type="checkbox" />
                  <span>{{ item.name }}</span>
                  <em>{{ item.type }}</em>
                </label>
              </div>
            </div>

            <div class="action-bar-box">
              <button v-if="report.status === 'pending_confirm'" class="btn-success-prominent" @click="store.confirmDailyReport(report.id)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> 确认匹配并入库
              </button>
              <div v-else class="archive-status-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> 已归档存底
              </div>
              <button v-if="report.status === 'pending_confirm'" class="btn-ghost-full" @click="reparseReport(report.id)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> 重新提取 Excel
              </button>
            </div>
          </div>
        </div>
      </div>
      </template>

      <div v-if="activeTab !== 'failed' && filteredReports.length === 0" class="empty-card">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" style="color:var(--text-disabled)"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><polyline points="9 15 12 18 15 15"/></svg>
        <div v-if="activeTab === 'pending'">暂无待确认的日报</div>
        <div v-else>暂无已确认的历史日报记录</div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useMessage, NInput, NInputNumber, NSelect } from 'naive-ui'
const store = useAppStore()
const message = useMessage()
const activeTab = ref<'pending' | 'history' | 'failed'>('pending')
const attachmentMarks = reactive([
  { name: '现场照片-0609-001.jpg', type: '现场照片', checked: true },
  { name: '基坑监测数据表-0609.xlsx', type: '监测资料', checked: true },
  { name: '渗水处理记录附图.jpg', type: '待补材料', checked: false },
])
const failedFiles = reactive([
  { id: 'ff1', fileName: '2026-06-10日报扫描件.pdf', fileType: 'PDF', detectedAt: '2026-06-11 07:40', reason: '扫描件清晰度不足，未能稳定识别施工内容和日期。' },
])
const filteredReports = computed(() => {
  if (activeTab.value === 'pending') {
    return store.dailyReports.filter(r => r.status === 'pending_confirm')
  } else if (activeTab.value === 'history') {
    return store.dailyReports.filter(r => r.status === 'confirmed')
  }
  return []
})
const pendingCount = computed(() => store.dailyReports.filter(r => r.status === 'pending_confirm').length)
const historyCount = computed(() => store.dailyReports.filter(r => r.status === 'confirmed').length)
const failedCount = computed(() => failedFiles.length)

const wbsOptions = computed(() => store.wbsItems.map(w => ({ label: `${w.code} ${w.name}`, value: w.id })))
const parseStatusLabel = (s: string) => ({ pending: '待解析', processing: '解析中', done: '已解析', failed: '解析失败' }[s] ?? s)
const confColor = (v: number) => v >= 0.85 ? '#047857' : v >= 0.6 ? '#B45309' : '#DC2626'
const reparseReport = (id: string) => {
  store.addLog({ id: `log-${Date.now()}`, time: new Date().toISOString().slice(0,19).replace('T',' '), operator: '张伟', level: 'info', action: '重新解析', detail: `触发日报重新解析 ID:${id}`, relatedId: id })
  message.info('已触发重新解析，请稍后刷新查看')
}
const retryFailedFile = (fileName: string) => {
  message.info(`已重新投递「${fileName}」解析任务`)
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

/* Archives elements */
.archive-status-badge {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  background: var(--color-success-soft);
  color: var(--color-success);
  border: 1px solid rgba(4,120,87,0.15);
}

.report-list { display: flex; flex-direction: column; gap: 20px; }

.report-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: var(--transition-slow);
}
.report-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-md);
}
.failed-icon-wrap { background: var(--color-danger-soft); color: var(--color-danger); }
.failed-file-body { padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; gap: 14px; }
.failed-reason { flex: 1; min-width: 0; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--color-danger-soft); color: var(--color-danger); font-size: 13px; line-height: 1.5; }
.failed-actions { display: flex; flex-direction: column; gap: 8px; width: 180px; flex-shrink: 0; }

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

.card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-default);
  background: var(--bg-surface);
  flex-wrap: wrap;
  gap: 12px;
}
.file-info { display: flex; align-items: center; gap: 12px; }
.file-icon-wrap {
  width: 32px; height: 32px;
  background: rgba(232,89,12,0.06);
  border-radius: var(--radius-sm);
  display: flex; align-items: center; justify-content: center;
  color: var(--color-primary); font-size: 16px;
}
.file-header-flex {
  display: flex;
  align-items: center;
  gap: 8px;
}
.file-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.file-meta { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.hd-right { display: flex; align-items: center; gap: 16px; }
.parse-badge { padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.parse-pending    { background: var(--color-info-soft);    color: var(--color-info); }
.parse-processing { background: var(--color-warning-soft); color: var(--color-warning); }
.parse-done       { background: var(--color-success-soft); color: var(--color-success); }
.parse-failed     { background: var(--color-danger-soft);  color: var(--color-danger); }

.conf-row { display: flex; align-items: center; gap: 8px; }
.conf-label-text { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.conf-track { width: 72px; height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.conf-fill { height: 100%; border-radius: 2px; transition: width 0.5s; }
.conf-num { font-size: 13px; font-weight: 700; width: 32px; text-align: right; }

/* Body */
.card-body { display: grid; grid-template-columns: 1fr 340px; }
.fields-col { padding: 12px 14px; border-right: 1px solid var(--border-default); }

/* Extracted Doc Panel style replacing Inputs */
.extracted-doc-panel {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.doc-panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 8px;
}
.pulse-active-indicator {
  width: 5px; height: 5px;
  background: var(--color-success);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--color-success);
}
.doc-panel-badge {
  margin-left: auto;
  font-size: 11px;
  background: var(--border-emphasis);
  color: var(--text-secondary);
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 500;
}
.editable-field, .editable-number { width: 100%; }
.attachment-marker { margin-top: 0; }
.attachment-list { display: flex; flex-direction: column; gap: 6px; }
.attachment-mark-row { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 7px 8px; border-radius: var(--radius-xs); background: var(--bg-card); border: 1px solid var(--border-subtle); cursor: pointer; }
.attachment-mark-row span { font-size: 12px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-mark-row em { font-style: normal; font-size: 11px; color: var(--text-muted); }
.fields-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 8px; }
.col-full { grid-column: span 2; }

.extracted-text-block {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.et-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}
.et-value-box {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 8px 10px;
  font-size: 14px;
  line-height: 1.45;
  color: var(--text-primary);
  min-height: 32px;
}
.text-filled {
  border-left: 2px solid var(--border-emphasis);
}
.number-filled {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: var(--color-primary);
  border-left: 2px solid var(--color-primary-light);
  background: var(--color-primary-soft);
}
.warn-filled {
  border-left: 2px solid var(--color-danger);
  background: rgba(220,38,38,0.02);
  color: var(--color-danger);
}
.info-filled {
  border-left: 2px solid var(--color-info);
  background: rgba(2,132,199,0.02);
  color: var(--color-info);
}
.empty-filled {
  color: var(--text-muted);
  font-style: italic;
  background: rgba(23,32,46,0.01);
}

.side-col { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; background: rgba(244,245,247,0.4); }

.fgroup { display: flex; flex-direction: column; gap: 4px; }
.flabel { font-size: 13px; color: var(--text-secondary); font-weight: 600; display: flex; align-items: center; justify-content: space-between; }
.ai-parsed-badge { font-size: 11px; color: var(--color-primary); background: var(--color-primary-soft); padding: 1px 4px; border-radius: 3px; font-weight: 500; }

.ai-meta-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}
.side-title { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.03em; }
.meta-item { display: flex; align-items: center; justify-content: space-between; }
.mt-10 { margin-top: 6px; }
.meta-lbl { font-size: 12px; color: var(--text-muted); }
.conf-chip-wrap { display: flex; align-items: center; gap: 6px; }
.conf-text { font-size: 13px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.conf-track-mini { width: 44px; height: 3px; background: var(--bg-base); border-radius: 2px; overflow: hidden; }
.conf-fill-mini { height: 100%; border-radius: 2px; }

.wbs-linker { margin-top: 0; }
.wbs-matching-explanation {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  margin: 4px 0 0 0;
}

.action-bar-box { margin-top: auto; padding-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.btn-success-prominent {
  width: 100%;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 14px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 600; font-family: inherit;
  border: none; cursor: pointer; transition: var(--transition);
  background: var(--color-success); color: #fff;
  box-shadow: 0 1px 2px rgba(4,120,87,0.1);
}
.btn-success-prominent:hover {
  background: #035e45;
  box-shadow: 0 3px 6px rgba(4,120,87,0.2);
  transform: translateY(-1px);
}
.btn-ghost-full {
  width: 100%;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 7px 14px; border-radius: var(--radius-sm);
  font-size: 12px; font-weight: 500; font-family: inherit;
  cursor: pointer; transition: var(--transition);
  background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border-emphasis);
}
.btn-ghost-full:hover {
  background: var(--bg-hover); color: var(--text-primary); border-color: var(--text-secondary);
}

.empty-card {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 60px 20px; background: var(--bg-card);
  border: 1px solid var(--border-default); border-radius: var(--radius-md);
  color: var(--text-muted); font-size: 13px;
}

@media (max-width: 1200px) {
  .card-body { grid-template-columns: 1fr; }
  .fields-col { border-right: none; border-bottom: 1px solid var(--border-default); }
  .side-col { background: var(--bg-card); }
}

@media (max-width: 768px) {
  .fields-grid { grid-template-columns: 1fr; }
  .col-full { grid-column: auto; }
  .page-wrapper { padding: 12px 16px; }
  .failed-file-body { flex-direction: column; align-items: stretch; }
  .failed-actions { width: 100%; }
}
</style>
