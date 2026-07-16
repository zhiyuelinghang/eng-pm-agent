import { createRouter, createWebHashHistory } from 'vue-router'
import MainLayout from '@/components/layout/MainLayout.vue'
import AiWorkPlatformView from '@/views/workspace/AiWorkPlatformView.vue'

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
        { path: 'workbench', name: 'WorkBench', component: AiWorkPlatformView, meta: { title: '工作首页', group: 'workspace' } },
        { path: 'ai', name: 'AiWorkspace', component: AiWorkPlatformView, meta: { title: '智能协同', group: 'workspace' } },
        { path: 'tasks', name: 'TaskManagement', component: AiWorkPlatformView, meta: { title: '任务管理', group: 'workspace' } },
        { path: 'project', name: 'ProjectStatus', component: AiWorkPlatformView, meta: { title: '项目状态', group: 'workspace' } },
        { path: 'docs', name: 'EngineeringDocs', component: AiWorkPlatformView, meta: { title: '工程资料', group: 'workspace' } },
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

router.beforeEach((to) => {
  const loggedIn = sessionStorage.getItem('logged_in')
  if (!to.meta?.public && !loggedIn) {
    return { path: '/login' }
  }
  
  if (loggedIn) {
    const userRole = sessionStorage.getItem('user_role') || 'site'
    if (userRole === 'site' && to.path.startsWith('/admin')) {
      return { path: '/workbench' }
    }
  }
})
