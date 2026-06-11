<template>
  <div class="admin-view">
    <AdminPageHeader
      title="上报模板配置"
      subtitle="维护风险进展上报的结构化模板，明确草稿生成时需要填充的章节、字段和资料来源。"
    >
      <template #actions>
        <button class="tbtn" @click="previewMode = previewMode === 'form' ? 'document' : 'form'">
          {{ previewMode === 'form' ? '查看文书预览' : '查看字段配置' }}
        </button>
        <button class="tbtn tbtn--primary" @click="saveTemplate">保存模板</button>
      </template>
    </AdminPageHeader>

    <div class="template-layout">
      <section class="admin-panel template-main">
        <div class="template-toolbar">
          <div>
            <div class="template-name">重大风险动态管控月报</div>
            <div class="template-meta">适用场景：风险进展上报 · 当前版本：V1.3 · 状态：试点启用</div>
          </div>
          <span class="status-chip">已绑定填报助手</span>
        </div>

        <div v-if="previewMode === 'form'" class="section-list">
          <article v-for="section in sections" :key="section.key" class="section-row">
            <div class="section-sort">{{ section.order }}</div>
            <div class="section-body">
              <div class="section-head">
                <div>
                  <div class="section-title">{{ section.title }}</div>
                  <div class="section-desc">{{ section.desc }}</div>
                </div>
                <span :class="['section-tag', section.required ? 'tag-required' : 'tag-optional']">
                  {{ section.required ? '必填章节' : '可选章节' }}
                </span>
              </div>
              <div class="field-grid">
                <label v-for="field in section.fields" :key="field.key" class="field-card">
                  <span class="field-label">{{ field.label }}</span>
                  <span class="field-source">来源：{{ field.source }}</span>
                  <textarea v-if="field.long" v-model="field.demoValue" rows="3" class="field-textarea" />
                  <input v-else v-model="field.demoValue" class="field-input" />
                </label>
              </div>
            </div>
          </article>
        </div>

        <div v-else class="document-preview">
          <div class="doc-kicker">工程智管家 · 风险动态管控文书</div>
          <h2>重大风险动态管控月报</h2>
          <div class="doc-subline">模板编号：TPL-RISK-MONTHLY · 自动草稿生成后需人工审核确认</div>
          <div v-for="section in sections" :key="section.key" class="doc-section">
            <h3>{{ section.order }}. {{ section.title }}</h3>
            <p v-for="field in section.fields" :key="field.key">
              <strong>{{ field.label }}：</strong>{{ field.demoValue || '待系统生成后补全' }}
            </p>
          </div>
        </div>
      </section>

      <aside class="template-side">
        <section class="admin-panel side-card">
          <div class="side-title">模板规则</div>
          <div class="rule-list">
            <div v-for="rule in rules" :key="rule" class="rule-item">
              <span class="rule-dot"></span>
              <span>{{ rule }}</span>
            </div>
          </div>
        </section>

        <section class="admin-panel side-card">
          <div class="side-title">缺项触发</div>
          <div class="missing-list">
            <div v-for="item in missingRules" :key="item.name" class="missing-row">
              <div>
                <div class="missing-name">{{ item.name }}</div>
                <div class="missing-desc">{{ item.desc }}</div>
              </div>
              <span :class="['missing-level', `missing-${item.level}`]">{{ item.label }}</span>
            </div>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'

const message = useMessage()
const previewMode = ref<'form' | 'document'>('form')

const sections = reactive([
  {
    key: 'base', order: '01', title: '风险基本信息', desc: '从风险源库、项目底座和责任配置中自动带出。', required: true,
    fields: [
      { key: 'project', label: '项目名称', source: '项目配置', demoValue: '合流污水一期复线工程（总管部分）', long: false },
      { key: 'riskName', label: '风险源名称', source: '风险源清单', demoValue: '深基坑坍塌风险', long: false },
      { key: 'level', label: '风险等级', source: '风险源清单', demoValue: '重大风险', long: false },
      { key: 'owner', label: '责任人/确认人', source: '成员责任配置', demoValue: '李明 / 张伟', long: false },
    ],
  },
  {
    key: 'progress', order: '02', title: '当前施工进展', desc: '汇总已确认日报和关联 WBS 工序状态。', required: true,
    fields: [
      { key: 'wbs', label: '关联工序', source: 'WBS-风险关联', demoValue: '1.2.2 基坑开挖', long: false },
      { key: 'progressText', label: '进展描述', source: '日报解析确认', demoValue: '基坑开挖累计深度 8.6m，完成率约 80%，第三道钢支撑已安装。', long: true },
    ],
  },
  {
    key: 'measure', order: '03', title: '监测与管控措施', desc: '引用监测资料、风险控制要求和现场整改记录。', required: true,
    fields: [
      { key: 'monitor', label: '监测情况', source: '日报/附件', demoValue: '围护桩顶位移最大值 18mm，地表沉降 S-03 点 12mm，处于安全范围。', long: true },
      { key: 'measureText', label: '管控措施', source: '风险源控制要求', demoValue: '持续开展基坑监测，局部渗水点安排排水泵抽排并补强支撑端头。', long: true },
    ],
  },
  {
    key: 'attachment', order: '04', title: '附件与缺项说明', desc: '根据材料要求检查附件是否就绪，缺项可生成补充任务。', required: true,
    fields: [
      { key: 'readyFiles', label: '已就绪附件', source: '附件清单', demoValue: '现场照片、基坑监测数据表、施工日报', long: false },
      { key: 'missingFiles', label: '缺项说明', source: '材料要求配置', demoValue: '地表沉降监测报告（本周）待补充。', long: true },
    ],
  },
])

const rules = [
  '草稿生成后必须进入人工审核，不直接生成正式填报包。',
  '每个字段保留数据来源，便于用户解释 AI 生成依据。',
  '缺少必填附件时，草稿可审核但生成填报包前必须提示。',
  '模板章节允许调整顺序，但演示原型保持项目试点默认结构。',
]

const missingRules = [
  { name: '监测日报', desc: '重大/较大风险默认必填', level: 'high', label: '强提醒' },
  { name: '现场照片', desc: '用于填报助手附件上传', level: 'high', label: '强提醒' },
  { name: '审批资料', desc: '按风险类型条件触发', level: 'medium', label: '条件' },
]

const saveTemplate = () => {
  message.success('模板配置已保存到原型状态')
}
</script>

<style scoped>
.template-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.template-main { padding: 20px 22px; }
.template-toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); }
.template-name { font-size: 16px; font-weight: 750; color: var(--text-primary); }
.template-meta { margin-top: 4px; font-size: 12px; color: var(--text-secondary); }
.status-chip { flex-shrink: 0; padding: 3px 9px; border-radius: 12px; background: var(--color-success-soft); color: var(--color-success); font-size: 12px; font-weight: 700; }
.section-list { display: flex; flex-direction: column; gap: 14px; }
.section-row { display: grid; grid-template-columns: 46px 1fr; gap: 12px; }
.section-sort { height: 34px; border-radius: var(--radius-sm); background: var(--bg-inverse); color: #fff; display: flex; align-items: center; justify-content: center; font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; }
.section-body { border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--bg-card); padding: 14px; }
.section-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.section-title { font-size: 14px; font-weight: 750; color: var(--text-primary); }
.section-desc { margin-top: 3px; font-size: 12px; color: var(--text-muted); }
.section-tag { height: 22px; display: inline-flex; align-items: center; padding: 0 8px; border-radius: 11px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.tag-required { background: var(--color-primary-soft); color: var(--color-primary); }
.tag-optional { background: var(--bg-elevated); color: var(--text-secondary); }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.field-card { display: flex; flex-direction: column; gap: 5px; padding: 10px; border-radius: var(--radius-sm); background: var(--bg-elevated); border: 1px solid var(--border-subtle); }
.field-label { font-size: 12px; font-weight: 700; color: var(--text-secondary); }
.field-source { font-size: 11px; color: var(--text-muted); }
.field-input, .field-textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-xs); background: var(--bg-card); color: var(--text-primary); font: inherit; font-size: 13px; padding: 7px 9px; outline: none; }
.field-textarea { resize: vertical; line-height: 1.55; }
.field-input:focus, .field-textarea:focus { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--color-primary-dim); }
.document-preview { max-width: 760px; margin: 0 auto; padding: 30px 34px; background: #fff; border: 1px solid var(--border-emphasis); border-radius: var(--radius-sm); box-shadow: var(--shadow-sm); }
.doc-kicker { text-align: center; font-size: 12px; color: var(--color-danger); font-weight: 800; letter-spacing: 0.12em; }
.document-preview h2 { margin: 8px 0 4px; text-align: center; font-size: 24px; color: var(--text-primary); }
.doc-subline { text-align: center; font-size: 12px; color: var(--text-muted); padding-bottom: 16px; border-bottom: 2px double var(--color-danger); }
.doc-section { padding: 14px 0; border-bottom: 1px solid var(--border-subtle); }
.doc-section h3 { margin: 0 0 8px; font-size: 15px; color: var(--text-primary); }
.doc-section p { margin: 5px 0; font-size: 13px; line-height: 1.7; color: var(--text-secondary); }
.template-side { display: flex; flex-direction: column; gap: 14px; }
.side-card { padding: 16px 18px; }
.side-title { font-size: 13px; font-weight: 750; color: var(--text-primary); margin-bottom: 10px; }
.rule-list { display: flex; flex-direction: column; gap: 9px; }
.rule-item { display: flex; gap: 8px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.rule-dot { width: 6px; height: 6px; margin-top: 6px; border-radius: 50%; background: var(--color-primary); flex-shrink: 0; }
.missing-list { display: flex; flex-direction: column; gap: 8px; }
.missing-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 10px; border-radius: var(--radius-sm); background: var(--bg-elevated); }
.missing-name { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.missing-desc { margin-top: 2px; font-size: 11px; color: var(--text-muted); }
.missing-level { flex-shrink: 0; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.missing-high { background: var(--color-danger-soft); color: var(--color-danger); }
.missing-medium { background: var(--color-warning-soft); color: var(--color-warning); }
@media (max-width: 1100px) { .template-layout { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .field-grid, .section-row { grid-template-columns: 1fr; } .section-sort { width: 46px; } .template-toolbar { flex-direction: column; } }
</style>