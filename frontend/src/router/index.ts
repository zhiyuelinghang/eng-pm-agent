import { createRouter, createWebHashHistory } from 'vue-router'
import MainLayout from '@/components/layout/MainLayout.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: MainLayout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/site/DashboardView.vue'), meta: { title: '工地首页', group: 'site', icon: 'HomeFilled' } },
        { path: 'tasks', name: 'Tasks', component: () => import('@/views/site/TaskCenterView.vue'), meta: { title: '任务中心', group: 'site', icon: 'List' } },
        { path: 'risks', name: 'Risks', component: () => import('@/views/site/RiskTaskView.vue'), meta: { title: '风险任务', group: 'site', icon: 'Warning' } },
        { path: 'daily-reports', name: 'DailyReports', component: () => import('@/views/site/DailyReportView.vue'), meta: { title: '日报解析', group: 'site', icon: 'Document' } },
        { path: 'drafts', name: 'Drafts', component: () => import('@/views/site/DraftReviewView.vue'), meta: { title: '草稿审核', group: 'site', icon: 'EditPen' } },
        { path: 'filling', name: 'Filling', component: () => import('@/views/site/FillingAssistantView.vue'), meta: { title: '填报助手', group: 'site', icon: 'Upload' } },
        { path: 'members', name: 'SiteMembers', component: () => import('@/views/admin/MemberConfigView.vue'), meta: { title: '用户与班组', group: 'site', icon: 'User' } },
        { path: 'admin/project', name: 'AdminProject', component: () => import('@/views/admin/ProjectConfigView.vue'), meta: { title: '项目配置', group: 'admin', icon: 'Setting' } },
        { path: 'admin/members', name: 'AdminMembers', component: () => import('@/views/admin/MemberConfigView.vue'), meta: { title: '成员与责任', group: 'admin', icon: 'User' } },
        { path: 'admin/wbs', name: 'AdminWbs', component: () => import('@/views/admin/WbsImportView.vue'), meta: { title: 'WBS 导入', group: 'admin', icon: 'Grid' } },
        { path: 'admin/risk-sources', name: 'AdminRiskSources', component: () => import('@/views/admin/RiskSourceView.vue'), meta: { title: '风险源管理', group: 'admin', icon: 'CircleCloseFilled' } },
        { path: 'admin/wbs-risk-link', name: 'AdminWbsRiskLink', component: () => import('@/views/admin/WbsRiskLinkView.vue'), meta: { title: 'WBS-风险关联', group: 'admin', icon: 'Share' } },
        { path: 'admin/daily-dir', name: 'AdminDailyDir', component: () => import('@/views/admin/DailyDirConfigView.vue'), meta: { title: '日报目录配置', group: 'admin', icon: 'FolderOpened' } },
        { path: 'admin/rules', name: 'AdminRules', component: () => import('@/views/admin/RemindRuleView.vue'), meta: { title: '提醒规则', group: 'admin', icon: 'Bell' } },
        { path: 'admin/templates', name: 'AdminTemplates', component: () => import('@/views/admin/ReportTemplateView.vue'), meta: { title: '上报模板配置', group: 'admin', icon: 'Document' } },
        { path: 'admin/field-mapping', name: 'AdminFieldMapping', component: () => import('@/views/admin/PlatformFieldMappingView.vue'), meta: { title: '平台字段映射', group: 'admin', icon: 'Connection' } },
        { path: 'admin/logs', name: 'AdminLogs', component: () => import('@/views/admin/OperationLogView.vue'), meta: { title: '操作日志', group: 'admin', icon: 'Tickets' } },
      ],
    },
  ],
})

export default router

router.beforeEach((to) => {
  const loggedIn = sessionStorage.getItem('logged_in')
  if (!to.meta?.public && !loggedIn) {
    return { path: '/login' }
  }
  
  if (loggedIn) {
    const userRole = sessionStorage.getItem('user_role') || 'site'
    if (userRole === 'site' && to.path.startsWith('/admin')) {
      return { path: '/dashboard' }
    }
    if (userRole === 'ops' && !to.path.startsWith('/admin') && to.path !== '/login') {
      return { path: '/admin/project' }
    }
  }
})
