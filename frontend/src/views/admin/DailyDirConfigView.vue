<template>
  <div class="admin-view">
    <AdminPageHeader
      title="日报目录规则"
      subtitle="配置系统扫描、解析与归档日报文件的各目录路径及触发策略。"
    >
      <template #actions>
        <button class="tbtn" @click="testScan">测试扫描</button>
        <button class="tbtn tbtn--primary" @click="save">保存配置</button>
      </template>
    </AdminPageHeader>

    <!-- ── 状态总览条 ── -->
    <div class="status-strip" :class="form.enabled ? 'is-on' : 'is-off'">
      <div class="status-strip-left">
        <span class="status-indicator">
          <span class="status-dot" :class="form.enabled ? 'dot-active' : 'dot-inactive'"></span>
          <span class="status-label">{{ form.enabled ? '自动扫描运行中' : '自动扫描已停用' }}</span>
        </span>
        <span v-if="form.enabled" class="status-freq">每 {{ form.scanInterval }} 分钟一次</span>
      </div>
      <label class="status-toggle">
        <span class="toggle-text">{{ form.enabled ? '停用' : '启用' }}</span>
        <n-switch v-model:value="form.enabled" size="small" />
      </label>
    </div>

    <!-- ── 主区：左右布局 ── -->
    <div class="dir-layout">

      <!-- 左：路径配置 -->
      <div class="admin-panel dir-panel">
        <header class="panel-head">
          <span class="panel-title">目录路径配置</span>
          <span class="panel-hint">服务器绝对路径，以 <code>/</code> 开头</span>
        </header>

        <div class="dir-list">
          <div
            v-for="f in dirFields"
            :key="f.key"
            class="dir-row"
            :style="`--accent:${f.color}`"
          >
            <div class="dir-row-head">
              <span class="dir-badge" :style="`background:${f.tagBg};color:${f.color}`">{{ f.tag }}</span>
              <span class="dir-name">{{ f.name }}</span>
            </div>
            <p class="dir-desc">{{ f.desc }}</p>
            <n-input
              v-model:value="(form as any)[f.key]"
              :placeholder="f.placeholder"
              size="small"
              class="dir-input"
            />
          </div>
        </div>
      </div>

      <!-- 右：扫描 + 流转 -->
      <aside class="dir-side">

        <!-- 扫描设置 -->
        <div class="admin-panel side-card">
          <header class="panel-head">
            <span class="panel-title">扫描频率</span>
          </header>
          <div class="interval-row">
            <span class="interval-label">扫描间隔</span>
            <n-input-number
              v-model:value="form.scanInterval"
              :min="1" :max="1440"
              size="small"
              style="width:88px"
            />
            <span class="interval-unit">分钟</span>
          </div>
          <p class="interval-note">
            每 <strong>{{ form.scanInterval }}</strong> 分钟扫描主目录，发现新文件立即触发 AI 解析。
          </p>
        </div>

        <!-- 文件流转 -->
        <div class="admin-panel side-card">
          <header class="panel-head">
            <span class="panel-title">文件流转路径</span>
          </header>
          <ol class="flow-list">
            <li v-for="(step, i) in flowSteps" :key="step.key" class="flow-item">
              <div class="flow-icon-col">
                <span class="flow-icon" :style="`background:${step.iconBg};color:${step.color}`">
                  <n-icon :size="11"><Folder /></n-icon>
                </span>
                <span v-if="i < flowSteps.length - 1" class="flow-line"></span>
              </div>
              <div class="flow-body">
                <div class="flow-row">
                  <span class="flow-name">{{ step.name }}</span>
                  <span class="flow-badge" :style="`background:${step.iconBg};color:${step.color}`">{{ step.badge }}</span>
                </div>
                <span class="flow-desc">{{ step.desc }}</span>
              </div>
            </li>
          </ol>
        </div>

      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NInput, NInputNumber, NSwitch, NIcon } from 'naive-ui'
import { Folder } from '@vicons/tabler'

const store = useAppStore()
const message = useMessage()
const cfg = store.dirConfig

const form = reactive({
  mainDir:      cfg?.mainDir      ?? '/data/wechat/incoming',
  archiveDir:   cfg?.archiveDir   ?? '/data/wechat/archive',
  tempDir:      cfg?.tempDir      ?? '/data/wechat/processing',
  failedDir:    cfg?.failedDir    ?? '/data/wechat/failed',
  backupDir:    cfg?.backupDir    ?? '/data/wechat/processed',
  scanInterval: cfg?.scanInterval ?? 5,
  enabled:      cfg?.enabled      ?? true,
})

const dirFields = [
  {
    key: 'mainDir',    name: '主目录',    tag: '入口',  color: '#C2410C', tagBg: '#FEF0E6',
    desc: '系统持续监控该目录，新文件到达后立即触发 AI 解析任务。',
    placeholder: '/data/wechat/incoming',
  },
  {
    key: 'tempDir',    name: '临时目录',  tag: '处理中', color: '#0369A1', tagBg: '#E3F1FA',
    desc: 'AI 解析过程中的中间文件临时存放目录，处理完成后自动清理。',
    placeholder: '/data/wechat/processing',
  },
  {
    key: 'archiveDir', name: '归档目录',  tag: '成功',  color: '#047857', tagBg: '#E2F4EC',
    desc: '人工确认后的日报文件将被移入此目录长期保存。',
    placeholder: '/data/wechat/archive',
  },
  {
    key: 'failedDir',  name: '失败目录',  tag: '异常',  color: '#DC2626', tagBg: '#FDEBEB',
    desc: '解析失败的文件移至此处，支持手动触发重试或人工核查。',
    placeholder: '/data/wechat/failed',
  },
  {
    key: 'backupDir',  name: '备份目录',  tag: '常驻',  color: '#B45309', tagBg: '#FCF0DC',
    desc: '所有日报原始文件的独立备份，不受解析状态影响。',
    placeholder: '/data/wechat/processed',
  },
]

const flowSteps = [
  { key: 'main',    name: '主目录',   badge: '入口',  color: '#C2410C', iconBg: '#FEF0E6', desc: '新文件到达，触发扫描任务' },
  { key: 'temp',    name: '临时目录', badge: '处理中', color: '#0369A1', iconBg: '#E3F1FA', desc: 'AI 解析中，生成结构化内容' },
  { key: 'archive', name: '归档目录', badge: '成功',  color: '#047857', iconBg: '#E2F4EC', desc: '人工确认后自动归档' },
  { key: 'failed',  name: '失败目录', badge: '异常',  color: '#DC2626', iconBg: '#FDEBEB', desc: '解析出错，等待人工介入' },
  { key: 'backup',  name: '备份目录', badge: '常驻',  color: '#B45309', iconBg: '#FCF0DC', desc: '同步复制原始文件，持久保留' },
]

const save     = () => message.success('目录配置已保存')
const testScan = () => message.info('正在扫描目录，共发现 2 个待处理文件')
</script>

<style scoped>
/* ── 状态条 ── */
.status-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  margin-bottom: 16px;
  transition: background 0.25s, border-color 0.25s;
}
.is-on  { background: #F0FDF4; border-color: rgba(4,120,87,.18); }
.is-off { background: var(--bg-elevated); border-color: var(--border-default); }

.status-strip-left { display: flex; align-items: center; gap: 14px; }
.status-indicator  { display: flex; align-items: center; gap: 7px; }
.status-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.dot-active  {
  background: var(--color-success);
  box-shadow: 0 0 0 0 rgba(4,120,87,.5);
  animation: blink 2s infinite;
}
@keyframes blink {
  0%   { box-shadow: 0 0 0 0   rgba(4,120,87,.5); }
  70%  { box-shadow: 0 0 0 5px rgba(4,120,87,0); }
  100% { box-shadow: 0 0 0 0   rgba(4,120,87,0); }
}
.dot-inactive { background: var(--text-disabled); }
.status-label { font-size: 13px; font-weight: 650; color: var(--text-primary); }
.status-freq  {
  font-size: 11px; font-weight: 600;
  padding: 2px 9px; border-radius: 20px;
  background: rgba(4,120,87,.1); color: var(--color-success);
}
.status-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.toggle-text   { font-size: 12px; color: var(--text-secondary); user-select: none; }

/* ── 主布局 ── */
.dir-layout {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 16px;
  align-items: start;
}

/* ── 公共 Panel Head ── */
.panel-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  justify-content: space-between;
  padding-bottom: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.panel-title { font-size: 13px; font-weight: 700; color: var(--text-primary); }
.panel-hint  { font-size: 11px; color: var(--text-muted); }
.panel-hint code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--bg-elevated);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── 目录列表 ── */
.dir-panel  { padding: 20px 24px; }
.dir-list   { display: flex; flex-direction: column; gap: 0; }

.dir-row {
  padding: 14px 0 14px 16px;
  border-left: 2.5px solid var(--accent);
  margin-bottom: 12px;
  transition: padding-left .15s;
}
.dir-row:last-child { margin-bottom: 0; }
.dir-row:hover { padding-left: 20px; }

.dir-row-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dir-badge {
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .02em;
}
.dir-name { font-size: 13px; font-weight: 650; color: var(--text-primary); }
.dir-desc {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.55;
  margin: 0 0 9px;
  max-width: 520px;
}
.dir-input { font-family: 'JetBrains Mono', monospace; font-size: 12px; }

/* ── 右侧栏 ── */
.dir-side { display: flex; flex-direction: column; gap: 14px; }
.side-card { padding: 18px 20px; }

/* 扫描频率 */
.interval-row  { display: flex; align-items: center; gap: 9px; margin-bottom: 10px; }
.interval-label { font-size: 13px; font-weight: 600; color: var(--text-primary); white-space: nowrap; }
.interval-unit  { font-size: 12px; color: var(--text-secondary); }
.interval-note  {
  font-size: 12px; color: var(--text-secondary); line-height: 1.6; margin: 0;
}
.interval-note strong { color: var(--text-primary); }

/* 流转步骤 */
.flow-list {
  list-style: none;
  margin: 0; padding: 0;
  display: flex; flex-direction: column;
}
.flow-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.flow-icon-col {
  display: flex; flex-direction: column; align-items: center;
  flex-shrink: 0;
}
.flow-icon {
  width: 26px; height: 26px;
  border-radius: var(--radius-xs);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.flow-line {
  width: 1px; flex: 1;
  min-height: 14px;
  background: var(--border-default);
  margin: 3px 0;
}
.flow-body {
  flex: 1; min-width: 0;
  padding: 3px 0 14px;
}
.flow-item:last-child .flow-body { padding-bottom: 0; }
.flow-row  { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 2px; }
.flow-name { font-size: 12px; font-weight: 650; color: var(--text-primary); }
.flow-badge {
  padding: 1px 6px; border-radius: 8px;
  font-size: 10px; font-weight: 600;
  flex-shrink: 0;
}
.flow-desc { font-size: 11px; color: var(--text-muted); line-height: 1.4; }

@media (max-width: 860px) {
  .dir-layout { grid-template-columns: 1fr; }
}
</style>
