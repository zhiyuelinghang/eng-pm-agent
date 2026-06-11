<template>
  <div class="page-wrapper">
    <!-- Stat Strip -->
    <div class="stat-grid">
      <router-link to="/tasks" class="stat-card" :class="store.overdueTasks.length > 0 ? 'stat-danger' : ''">
        <div class="stat-icon danger"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></div>
        <div class="stat-body">
          <div class="stat-value">{{ store.overdueTasks.length }}</div>
          <div class="stat-label">逾期任务</div>
        </div>
        <div v-if="store.overdueTasks.length > 0" class="stat-pulse"></div>
      </router-link>
      <router-link to="/tasks" class="stat-card" :class="(store.pendingTasks.length + store.processingTasks.length) > 0 ? 'stat-warning' : ''">
        <div class="stat-icon warning"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg></div>
        <div class="stat-body">
          <div class="stat-value">{{ store.pendingTasks.length + store.processingTasks.length }}</div>
          <div class="stat-label">待处理任务</div>
        </div>
      </router-link>
      <router-link to="/daily-reports" class="stat-card">
        <div class="stat-icon info"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></div>
        <div class="stat-body">
          <div class="stat-value">{{ store.pendingDailyReports.length }}</div>
          <div class="stat-label">待确认日报</div>
        </div>
      </router-link>
      <router-link to="/drafts" class="stat-card">
        <div class="stat-icon primary"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></div>
        <div class="stat-body">
          <div class="stat-value">{{ store.pendingDrafts.length }}</div>
          <div class="stat-label">待审核草稿</div>
        </div>
      </router-link>
      <router-link to="/filling" class="stat-card">
        <div class="stat-icon accent"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg></div>
        <div class="stat-body">
          <div class="stat-value">{{ store.pendingFills.length }}</div>
          <div class="stat-label">待填报事项</div>
        </div>
      </router-link>
    </div>

    <div class="dashboard-body">
      <!-- Left column -->
      <div class="dashboard-left">
        <!-- Today tasks -->
        <section class="section-card">
          <div class="section-hd">
            <div class="section-hd-title">
              <span class="hd-dot"></span>今日待办
              <span class="hd-count">{{ todayTasks.length }}</span>
            </div>
            <router-link to="/tasks" class="hd-link">全部 <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></router-link>
          </div>
          <div class="task-list">
            <div v-for="task in todayTasks" :key="task.id" class="task-item" @click="router.push(`/tasks?id=${task.id}`)">
              <span :class="['risk-dot', `risk-dot--${task.riskLevel}`]"></span>
              <div class="task-body">
                <div class="task-title">{{ task.title }}</div>
                <div class="task-meta">
                  <span class="meta-type">{{ typeLabel(task.type) }}</span>
                  <span class="meta-sep">·</span>
                  <span>截止 {{ task.deadline }}</span>
                </div>
              </div>
              <span :class="['badge', statusClass(task.status)]">{{ statusLabel(task.status) }}</span>
            </div>
            <div v-if="todayTasks.length === 0" class="empty-state">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 今日暂无待办
            </div>
          </div>
        </section>

        <!-- Upcoming risks -->
        <section class="section-card">
          <div class="section-hd">
            <div class="section-hd-title">
              <span class="hd-dot hd-dot--warning"></span>即将触发风险
              <span class="hd-sub">未来 14 天</span>
            </div>
            <router-link to="/risks" class="hd-link">查看 <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></router-link>
          </div>
          <div class="risk-list">
            <div v-for="item in store.riskSources.slice(0,4)" :key="item.id" class="risk-row">
              <div :class="['risk-level-badge', `level-${item.level}`]">{{ levelLabel(item.level) }}</div>
              <div class="risk-row-body">
                <div class="risk-row-name">{{ item.name }}</div>
                <div class="risk-row-meta">{{ item.type }} · {{ store.getMemberName(item.responsibleId) }}</div>
              </div>
              <div class="risk-days">
                <span class="days-num">{{ daysUntil(item.id) }}</span>
                <span class="days-unit">天后</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- Right column -->
      <div class="dashboard-right">
        <!-- WBS progress -->
        <section class="section-card">
          <div class="section-hd">
            <div class="section-hd-title">
              <span class="hd-dot hd-dot--info"></span>WBS 进度
            </div>
            <router-link to="/admin/wbs" class="hd-link">详情 <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></router-link>
          </div>
          <div class="wbs-list">
            <div v-for="item in store.wbsItems.filter(w => w.level <= 2)" :key="item.id" class="wbs-row">
              <div class="wbs-row-hd">
                <span class="wbs-code font-mono">{{ item.code }}</span>
                <span class="wbs-name">{{ item.name }}</span>
                <span :class="['wbs-tag', `wbs-tag--${item.status}`]">{{ wbsStatusLabel(item.status) }}</span>
              </div>
              <div class="wbs-bar-wrap">
                <div class="wbs-bar-bg">
                  <div class="wbs-bar-fill" :style="{ width: item.progress + '%' }" :class="`fill-${item.status}`"></div>
                </div>
                <span class="wbs-pct font-mono">{{ item.progress }}%</span>
              </div>
            </div>
          </div>
        </section>

        <!-- Quick actions -->
        <section class="section-card">
          <div class="section-hd">
            <div class="section-hd-title"><span class="hd-dot hd-dot--accent"></span>快捷入口</div>
          </div>
          <div class="quick-grid">
            <router-link to="/daily-reports" class="quick-tile">
              <div class="qt-icon info"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div>
              <span>日报解析</span>
            </router-link>
            <router-link to="/drafts" class="quick-tile">
              <div class="qt-icon primary"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></div>
              <span>草稿审核</span>
            </router-link>
            <router-link to="/filling" class="quick-tile">
              <div class="qt-icon accent"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg></div>
              <span>填报助手</span>
            </router-link>
            <router-link to="/risks" class="quick-tile">
              <div class="qt-icon danger"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>
              <span>风险任务</span>
            </router-link>
          </div>
        </section>

        <!-- Recent logs -->
        <section class="section-card">
          <div class="section-hd">
            <div class="section-hd-title"><span class="hd-dot"></span>最近动态</div>
            <router-link to="/admin/logs" class="hd-link">全部 <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg></router-link>
          </div>
          <div class="log-list">
            <div v-for="log in store.logs.slice(0,5)" :key="log.id" class="log-row">
              <span :class="['log-dot', `log-dot--${log.level}`]"></span>
              <div class="log-body">
                <span class="log-action">{{ log.action }}</span>
                <span class="log-detail">{{ log.detail }}</span>
              </div>
              <span class="log-time font-mono">{{ log.time.slice(11,16) }}</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import type { Task } from '@/types'
const router = useRouter()
const store = useAppStore()
const todayTasks = computed(() => store.tasks.filter(t => ['pending','processing','overdue','waiting_confirm'].includes(t.status)))
const typeLabel = (type: Task['type']) => ({ risk_alert: '风险预警', material_missing: '材料缺项', daily_confirm: '日报确认', draft_review: '草稿审核', fill_platform: '平台填报' }[type] ?? type)
const statusLabel = (s: Task['status']) => ({ pending: '待处理', processing: '处理中', waiting_confirm: '待确认', done: '已完成', overdue: '已逾期', cancelled: '已取消' }[s] ?? s)
const statusClass = (s: Task['status']) => ({ pending: 'badge-info', processing: 'badge-primary', waiting_confirm: 'badge-warning', done: 'badge-success', overdue: 'badge-danger', cancelled: 'badge-muted' }[s] ?? '')
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const wbsStatusLabel = (s: string) => ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' }[s] ?? s)
const daysUntil = (riskId: string) => {
  const link = store.wbsRiskLinks.find(l => l.riskId === riskId)
  if (!link) return '—'
  const wbs = store.wbsItems.find(w => w.id === link.wbsId)
  if (!wbs) return '—'
  const diff = Math.ceil((new Date(wbs.planStart).getTime() - Date.now()) / 86400000)
  return diff > 0 ? diff : 0
}
</script>

<style scoped>
/* === Page Layout === */
.page-wrapper { padding: 20px 24px; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: var(--transition);
  position: relative;
  overflow: hidden;
  text-decoration: none;
}
.stat-card::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: var(--transition);
  background: linear-gradient(135deg, rgba(232,89,12,0.03), transparent);
}
.stat-card:hover { border-color: var(--border-emphasis); transform: translateY(-1px); box-shadow: var(--shadow-md); }
.stat-card:hover::before { opacity: 1; }
.stat-danger { border-color: rgba(220,38,38,0.35) !important; background: #FDF7F7 !important; }
.stat-warning { border-color: rgba(180,83,9,0.3) !important; background: #FCFAF5 !important; }
.stat-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.stat-icon.danger  { background: var(--color-danger-soft);  color: var(--color-danger); }
.stat-icon.warning { background: var(--color-warning-soft); color: var(--color-warning); }
.stat-icon.info    { background: var(--color-info-soft);    color: var(--color-info); }
.stat-icon.primary { background: var(--color-primary-soft); color: var(--color-primary); }
.stat-icon.accent  { background: var(--color-accent-soft);  color: var(--color-accent); }
.stat-value { font-size: 22px; font-weight: 700; color: var(--text-primary); line-height: 1; font-family: 'JetBrains Mono', monospace; }
.stat-label { font-size: 13px; color: var(--text-secondary); margin-top: 3px; }
.stat-pulse {
  position: absolute;
  top: 10px; right: 10px;
  width: 6px; height: 6px;
  background: var(--color-danger);
  border-radius: 50%;
  animation: pulse 1.8s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.8); } }

/* === Dashboard Body === */
.dashboard-body {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 16px;
  align-items: start;
}

/* === Section Card === */
.section-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  margin-bottom: 12px;
}
.section-card:last-child { margin-bottom: 0; }
.section-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-hd-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 700; color: var(--text-primary); }
.hd-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-primary); flex-shrink: 0; }
.hd-dot--warning { background: var(--color-warning); }
.hd-dot--info    { background: var(--color-info); }
.hd-dot--accent  { background: var(--color-accent); }
.hd-count {
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 20px;
  border: 1px solid var(--border-default);
}
.hd-sub { font-size: 12px; color: var(--text-muted); font-weight: 400; }
.hd-link { font-size: 13px; color: var(--color-primary); text-decoration: none; display: flex; align-items: center; gap: 2px; transition: var(--transition); }
.hd-link:hover { color: var(--color-primary-dark); }

/* === Task List === */
.task-list { display: flex; flex-direction: column; gap: 5px; }
.task-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
}
.task-item:hover { border-color: var(--border-primary); background: var(--bg-elevated); }
.risk-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.risk-dot--critical { background: var(--color-danger); }
.risk-dot--high     { background: var(--color-warning); }
.risk-dot--medium   { background: var(--color-info); }
.risk-dot--low      { background: var(--color-success); }
.task-body { flex: 1; min-width: 0; }
.task-title { font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.task-meta { font-size: 12px; color: var(--text-muted); margin-top: 1px; display: flex; align-items: center; gap: 6px; }
.meta-type { color: var(--text-secondary); }
.meta-sep { color: var(--border-emphasis); }
.empty-state { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 12px; color: var(--text-muted); font-size: 12px; }

/* === Risk List === */
.risk-list { display: flex; flex-direction: column; gap: 5px; }
.risk-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}
.risk-level-badge { padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.level-critical { background: var(--color-danger-soft);  color: var(--color-danger); }
.level-high     { background: var(--color-warning-soft); color: var(--color-warning); }
.level-medium   { background: var(--color-info-soft);    color: var(--color-info); }
.level-low      { background: var(--color-success-soft); color: var(--color-success); }
.risk-row-body { flex: 1; min-width: 0; }
.risk-row-name { font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.risk-row-meta { font-size: 12px; color: var(--text-muted); margin-top: 1px; }
.risk-days { text-align: right; flex-shrink: 0; }
.days-num { font-size: 16px; font-weight: 700; color: var(--color-warning); font-family: 'JetBrains Mono', monospace; }
.days-unit { font-size: 11px; color: var(--text-muted); margin-left: 1px; }

/* === WBS List === */
.wbs-list { display: flex; flex-direction: column; gap: 12px; }
.wbs-row-hd { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
.wbs-code { font-size: 12px; color: var(--text-muted); flex-shrink: 0; }
.wbs-name { font-size: 14px; color: var(--text-primary); flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wbs-tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }
.wbs-tag--done        { background: var(--color-success-soft); color: var(--color-success); }
.wbs-tag--in_progress { background: var(--color-primary-soft); color: var(--color-primary); }
.wbs-tag--not_started { background: var(--bg-elevated); color: var(--text-muted); border: 1px solid var(--border-default); }
.wbs-tag--delayed     { background: var(--color-danger-soft);  color: var(--color-danger); }
.wbs-bar-wrap { display: flex; align-items: center; gap: 8px; }
.wbs-bar-bg { flex: 1; height: 3px; background: var(--bg-elevated); border-radius: 2px; overflow: hidden; }
.wbs-bar-fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
.fill-done        { background: var(--color-success); }
.fill-in_progress { background: var(--color-primary); }
.fill-not_started { background: var(--text-disabled); }
.fill-delayed     { background: var(--color-danger); }
.wbs-pct { font-size: 12px; color: var(--text-muted); width: 34px; text-align: right; flex-shrink: 0; }

/* === Quick Grid === */
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.quick-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 14px 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: var(--transition);
}
.quick-tile:hover { background: var(--bg-elevated); color: var(--text-primary); border-color: var(--border-emphasis); transform: translateY(-1px); }
.qt-icon { width: 32px; height: 32px; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; font-size: 15px; }
.qt-icon.info    { background: var(--color-info-soft);    color: var(--color-info); }
.qt-icon.primary { background: var(--color-primary-soft); color: var(--color-primary); }
.qt-icon.accent  { background: var(--color-accent-soft);  color: var(--color-accent); }
.qt-icon.danger  { background: var(--color-danger-soft);  color: var(--color-danger); }

/* === Log List === */
.log-list { display: flex; flex-direction: column; gap: 8px; }
.log-row { display: flex; align-items: flex-start; gap: 8px; }
.log-dot { width: 5px; height: 5px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.log-dot--info    { background: var(--color-info); }
.log-dot--success { background: var(--color-success); }
.log-dot--warning { background: var(--color-warning); }
.log-dot--error   { background: var(--color-danger); }
.log-body { flex: 1; min-width: 0; }
.log-action { font-size: 13px; font-weight: 600; color: var(--text-primary); display: block; }
.log-detail { font-size: 12px; color: var(--text-secondary); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.log-time { font-size: 12px; color: var(--text-muted); flex-shrink: 0; }

@media (max-width: 1200px) {
  .dashboard-body { grid-template-columns: 1fr; }
}

@media (max-width: 1024px) {
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 768px) {
  .page-wrapper { padding: 12px 16px; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .stat-card { padding: 10px 12px; gap: 8px; }
  .stat-icon { width: 32px; height: 32px; font-size: 14px; }
  .stat-value { font-size: 16px; }
  .stat-label { font-size: 11px; }
  
  .dashboard-body { gap: 12px; }
  .section-card { padding: 12px; margin-bottom: 12px; }
  .quick-grid { gap: 8px; }
  .task-item { padding: 8px 10px; }
}

@media (max-width: 480px) {
  .stat-grid { grid-template-columns: 1fr 1fr; }
}
</style>
