<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-grid"></div>
    </div>

    <div class="login-card">
      <div class="login-logo">
        <div class="logo-mark">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            <path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
          </svg>
        </div>
        <div class="logo-text">
          <span class="logo-name">工程智管家</span>
          <span class="logo-sub">工程管理平台</span>
        </div>
        <!-- step 2 back button -->
        <button v-if="step === 2" class="back-btn" @click="step = 1" title="切换业务端">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
          </svg>
          重新选择
        </button>
      </div>

      <div class="login-body">
        <div class="slider-wrapper">
          <div class="slider-track" :style="{ transform: `translateX(${step === 1 ? '0%' : '-50%'})` }">
            <!-- Step 1: selection of terminal -->
            <div class="slide-pane">
              <h1 class="login-title">进入工程管理平台</h1>
              <p class="login-desc">选择身份后进入项目任务、进度、资料和协同会话。</p>

              <div class="role-selector">
                <button type="button" class="role-btn hover-card" @click="selectRole('site')">
                  <div class="role-icon-box site-color">
                    <svg class="role-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-3M9 9h2M9 13h2M9 17h2M15 13h2M15 17h2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  </div>
                  <div class="role-inner">
                    <span class="role-title">项目工作台</span>
                    <span class="role-desc">参与任务、风险确认、资料协同和智能跟进</span>
                  </div>
                  <div class="arrow-indicator">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                  </div>
                </button>
                <button type="button" class="role-btn hover-card" @click="selectRole('ops')">
                  <div class="role-icon-box ops-color">
                    <svg class="role-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 16a4 4 0 100-8 4 4 0 000 8z" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 8v4" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  </div>
                  <div class="role-inner">
                    <span class="role-title">管理视角</span>
                    <span class="role-desc">查看项目状态、资料流和工程数据底座</span>
                  </div>
                  <div class="arrow-indicator">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                  </div>
                </button>
              </div>
            </div>

            <!-- Step 2: input account and password -->
            <div class="slide-pane">
              <h1 class="login-title">
                登录到 <span :class="role === 'site' ? 'site-text' : 'ops-text'">{{ role === 'site' ? '项目工作台' : '管理视角' }}</span>
              </h1>
              <p class="login-desc">
                {{ role === 'site' ? '请使用现场负责人或执行人账号进入' : '使用管理账号进入统一工作平台' }}
              </p>

              <form class="login-form" @submit.prevent="handleLogin">
                <div class="form-group">
                  <label class="form-label">账号 ({{ role === 'site' ? '现场账号' : '运维账号' }})</label>
                  <div class="input-wrap">
                    <svg class="input-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
                    <input v-model="form.username" type="text" class="form-input" placeholder="请输入账号" autocomplete="username" />
                  </div>
                </div>
                <div class="form-group">
                  <label class="form-label">密码</label>
                  <div class="input-wrap">
                    <svg class="input-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                    <input v-model="form.password" :type="showPwd ? 'text' : 'password'" class="form-input" placeholder="请输入密码" autocomplete="current-password" />
                    <button type="button" class="pwd-toggle" @click="showPwd = !showPwd">
                      <svg v-if="showPwd" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                      <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    </button>
                  </div>
                </div>

                <div class="form-extra">
                  <label class="remember-label">
                    <input v-model="form.remember" type="checkbox" class="remember-check" />
                    <span>记住我</span>
                  </label>
                </div>

                <button type="submit" class="login-btn" :class="{ loading: isLoading }" :disabled="isLoading">
                  <span v-if="!isLoading">立即登录平台</span>
                  <span v-else class="btn-loading">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" class="spin-icon">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" stroke-dasharray="60" stroke-dashoffset="15" />
                    </svg>
                    身份验证中...
                  </span>
                </button>
              </form>

            </div>
          </div>
        </div>
      </div>

      <div class="login-footer">
        <span class="project-tag">总管标</span>
        <span>智能化工程管理工作平台</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
const router = useRouter()
const message = useMessage()

const step = ref(1)
const role = ref<'site' | 'ops'>('site')
const form = reactive({ username: 'user', password: 'demo2026', remember: false })
const showPwd = ref(false)
const isLoading = ref(false)

const selectRole = (newRole: 'site' | 'ops') => {
  role.value = newRole
  if (newRole === 'site') {
    form.username = 'user'
  } else {
    form.username = 'admin'
  }
  step.value = 2
}

const handleLogin = async () => {
  if (!form.username || !form.password) {
    message.warning('请输入账号和密码')
    return
  }
  isLoading.value = true
  await new Promise(r => setTimeout(r, 900))
  isLoading.value = false
  sessionStorage.setItem('logged_in', '1')
  sessionStorage.setItem('user_role', role.value)
  message.success('登录成功')
  router.push('/workbench')
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-base);
  position: relative;
  overflow: hidden;
}
.login-bg { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.bg-grid {
  position: absolute;
  inset: 0;
  background-color: rgba(246, 247, 243, 0.92);
  background-image:
    linear-gradient(rgba(246,247,243,0.62), rgba(246,247,243,0.76)),
    url('https://picsum.photos/seed/engineering-command-login/1800/1200'),
    linear-gradient(rgba(27,36,48,0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(27,36,48,0.035) 1px, transparent 1px);
  background-size: cover, cover, 40px 40px, 40px 40px;
  background-position: center;
}

.login-card {
  position: relative;
  z-index: 1;
  width: 400px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.login-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px 28px 20px;
  border-bottom: 1px solid var(--border-default);
  position: relative;
}
.logo-mark {
  width: 42px;
  height: 42px;
  background: var(--color-primary);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(232,89,12,0.3);
  flex-shrink: 0;
}
.logo-name { display: block; font-size: 15px; font-weight: 700; color: var(--text-primary); }
.logo-sub { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; font-family: 'JetBrains Mono', monospace; }

/* back button stage 2 */
.back-btn {
  position: absolute;
  right: 28px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-hover);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}
.back-btn:hover {
  background: var(--border-emphasis);
  color: var(--text-primary);
}

.login-body { 
  padding: 0; 
  overflow: hidden; 
  position: relative;
}

/* 轨道滑块视图 */
.slider-wrapper {
  overflow: hidden;
  width: 100%;
}
.slider-track {
  display: flex;
  width: 200%; /* 包含两个 100% 宽度的幻灯滑块 */
  transition: transform 0.5s cubic-bezier(0.16, 1, 0.3, 1); /* 硬加速滑动 */
  will-change: transform;
}
.slide-pane {
  width: 50%; /* 每个面板刚好占卡片 body 的 100% 宽度 */
  flex-shrink: 0;
  padding: 28px 28px 20px;
  box-sizing: border-box;
}

.login-title { font-size: 22px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.login-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 24px; line-height: 1.4; }

/* 角色与功能端选择器 - step 1 重新打磨 */
.role-selector {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 8px;
}
.role-btn {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  text-align: left;
  width: 100%;
  position: relative;
}
.role-icon-box {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: var(--transition);
}
.site-color {
  background: rgba(232, 89, 12, 0.08); /* primary warm orange soft bg */
  color: var(--color-primary);
}
.ops-color {
  background: rgba(100, 116, 139, 0.08); /* slate metal gray soft bg */
  color: #475569;
}

.role-inner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.role-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.role-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}

.arrow-indicator {
  opacity: 0;
  transform: translateX(-4px);
  transition: all 0.2s ease;
  color: var(--text-muted);
}
.role-btn:hover .arrow-indicator {
  opacity: 1;
  transform: translateX(0);
}
/* 主题字颜色高亮 */
.site-text {
  color: var(--color-primary);
}
.ops-text {
  color: #475569;
}

.login-form { display: flex; flex-direction: column; gap: 16px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
.input-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  padding: 0 12px;
  transition: var(--transition);
}
.input-wrap:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-dim); }
.input-icon { color: var(--text-muted); font-size: 15px; flex-shrink: 0; }
.form-input {
  flex: 1;
  height: 40px;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 14px;
  font-family: inherit;
}
.form-input::placeholder { color: var(--text-disabled); }
.pwd-toggle { background: none; border: none; cursor: pointer; color: var(--text-muted); display: flex; align-items: center; padding: 4px; border-radius: 4px; transition: var(--transition); }
.pwd-toggle:hover { color: var(--text-secondary); background: var(--bg-hover); }

.form-extra { display: flex; align-items: center; }
.remember-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--text-secondary); }
.remember-check { width: 14px; height: 14px; accent-color: var(--color-primary); cursor: pointer; }

.login-btn {
  width: 100%;
  height: 42px;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 4px;
}
.login-btn:hover:not(:disabled) { background: var(--color-primary-light); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(232,89,12,0.3); }
.login-btn:disabled { opacity: 0.7; cursor: not-allowed; }
.btn-loading { display: flex; align-items: center; gap: 8px; }
.spin-icon { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.login-footer {
  padding: 14px 28px;
  border-top: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-muted);
}
.project-tag {
  padding: 2px 8px;
  background: var(--color-primary-dim);
  color: var(--color-primary);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

/* 渐变滑动淡入淡出动画 - 重新向 Apple/Vercel 设计美学对齐 */
.fade-slide-enter-active {
  transition: all 0.45s cubic-bezier(0.16, 1, 0.3, 1); /* 苹果经典的舒缓弹性曲线 */
}
.fade-slide-leave-active {
  transition: all 0.25s cubic-bezier(0.32, 94, 0.6, 1); /* 极快速、不拖泥带水地淡出 */
}
.fade-slide-enter-from {
  opacity: 0;
  transform: scale(0.965); /* 带有柔和而高级的三维纵深感的自里向外缩放 */
  filter: blur(4px); /* 引入微量的磨砂玻璃背景模糊过渡，极其写意 */
}
.fade-slide-leave-to {
  opacity: 0;
  transform: scale(1.025); /* 优雅地向屏幕外层微微扩大并淡出 */
  filter: blur(2px);
}
</style>
