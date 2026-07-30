import { createRouter, createWebHashHistory } from 'vue-router'
import MainLayout from '@/components/layout/MainLayout.vue'
import AiWorkPlatformView from '@/views/workspace/AiWorkPlatformView.vue'
import ProjectSetupView from '@/views/workspace/ProjectSetupView.vue'
import { useAppStore } from '@/stores/app'

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
      redirect: '/workbench',
      children: [
        { path: 'workbench', name: 'WorkBench', component: AiWorkPlatformView, meta: { title: '工作首页', group: 'workspace', requiresProject: true } },
        { path: 'ai', name: 'AiWorkspace', component: AiWorkPlatformView, meta: { title: '智能协同', group: 'workspace', requiresProject: true } },
        { path: 'tasks', name: 'TaskManagement', component: AiWorkPlatformView, meta: { title: '任务管理', group: 'workspace', requiresProject: true } },
        { path: 'project', name: 'ProjectStatus', component: AiWorkPlatformView, meta: { title: '项目状态', group: 'workspace', requiresProject: true } },
        { path: 'docs', name: 'EngineeringDocs', component: () => import('@/views/workspace/DocumentLibraryView.vue'), meta: { title: '工程资料', group: 'workspace', requiresProject: true } },
        { path: 'tools', name: 'BusinessTools', component: () => import('@/views/workspace/BusinessToolsView.vue'), meta: { title: '业务工具', group: 'workspace', requiresProject: true } },
        { path: 'profile', name: 'PersonalSettings', component: () => import('@/views/workspace/PersonalSettingsView.vue'), meta: { title: '个人设置', group: 'workspace' } },
        { path: 'settings', name: 'ProjectSetup', component: ProjectSetupView, meta: { title: '工程配置', group: 'workspace' } },
        { path: 'dashboard', redirect: '/workbench' },
        { path: 'risks', redirect: '/tasks' },
        { path: 'daily-reports', redirect: '/docs' },
        { path: 'drafts', redirect: '/docs' },
        { path: 'filling', redirect: '/docs' },
        { path: 'members', redirect: '/workbench' },
        { path: 'admin/:pathMatch(.*)*', redirect: '/project' },
      ],
    },
  ],
})

export default router

router.beforeEach(async (to) => {
  const loggedIn = sessionStorage.getItem('logged_in') && sessionStorage.getItem('access_token')
  if (!to.meta?.public && !loggedIn) {
    return { path: '/login' }
  }
  
  if (loggedIn) {
    const userRole = sessionStorage.getItem('user_role') || 'user'
    if (userRole === 'user' && to.path.startsWith('/admin')) {
      return { path: '/workbench' }
    }

    if (to.matched.some(record => record.meta.requiresProject)) {
      const store = useAppStore()
      try {
        await store.loadProjectCatalog()
      } catch {
        return
      }
      if (store.projectCatalogLoaded && store.projects.length === 0) {
        return { path: '/settings', query: { projectRequired: '1' } }
      }
    }
  }
})
