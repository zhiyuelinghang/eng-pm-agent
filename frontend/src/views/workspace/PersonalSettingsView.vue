<template>
  <main class="personal-settings-page">
    <section class="personal-settings-shell">
      <header class="personal-settings-head">
        <div class="profile-avatar" aria-hidden="true">{{ profileInitial }}</div>
        <div class="profile-heading">
          <span>个人中心</span>
          <h1>个人设置</h1>
          <p>维护个人账号、登录安全，以及平台和协同工具的连接信息。</p>
        </div>
        <div class="account-state">
          <i></i>
          <span>当前登录</span>
          <strong>{{ profile.username || '—' }}</strong>
        </div>
      </header>

      <div class="personal-settings-layout">
        <aside class="settings-rail" aria-label="个人设置目录">
          <div class="rail-profile">
            <strong>{{ profile.real_name || currentUserName }}</strong>
            <span>{{ profile.title || roleLabel }}</span>
          </div>
          <nav>
            <button v-for="item in settingSections" :key="item.key" type="button" :class="{ active: activeSection === item.key }" @click="activeSection = item.key">
              <n-icon :size="18"><component :is="item.icon" /></n-icon>
              <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
            </button>
          </nav>
          <p class="rail-note"><n-icon :size="16"><ShieldLock /></n-icon>敏感凭据不会在页面中回显。</p>
        </aside>

        <section ref="settingsMainRef" class="settings-main" :class="{ 'connection-mode': activeSection === 'connections' }">
          <section v-if="activeSection === 'account'" class="settings-section">
            <header class="section-head">
              <div><span>账号资料</span><h2>基本信息</h2><p>这些信息用于任务分派、协同通知和操作留痕。</p></div>
              <em>用户 ID：{{ profile.id || '—' }}</em>
            </header>
            <form class="settings-form account-form" @submit.prevent="saveProfile">
              <label>登录账号<input :value="profile.username" disabled></label>
              <label>显示名称<input v-model.trim="profile.real_name" required maxlength="100" placeholder="请输入显示名称"></label>
              <label>岗位 / 职务<input v-model.trim="profile.title" maxlength="100" placeholder="例如：项目现场负责人"></label>
              <label>所属单位<input v-model.trim="profile.org_name" maxlength="200" placeholder="请输入所属单位"></label>
              <label>联系电话<input v-model.trim="profile.phone" maxlength="50" inputmode="tel" placeholder="请输入联系电话"></label>
              <label>邮箱地址<input v-model.trim="profile.email" maxlength="200" type="email" placeholder="用于接收通知与报告"></label>
              <footer class="form-actions"><span>{{ profileUpdatedAt }}</span><button type="submit" class="primary-action" :disabled="profileSaving"><n-icon :size="17"><DeviceFloppy /></n-icon>{{ profileSaving ? '正在保存…' : '保存个人资料' }}</button></footer>
            </form>
          </section>

          <section v-else-if="activeSection === 'security'" class="settings-section">
            <header class="section-head">
              <div><span>登录安全</span><h2>修改登录密码</h2><p>修改成功后，当前会话继续有效；下次登录请使用新密码。</p></div>
              <em class="security-badge"><n-icon :size="15"><ShieldLock /></n-icon>账号受保护</em>
            </header>
            <form class="settings-form password-form" @submit.prevent="changePassword">
              <label>当前密码<input v-model="passwordForm.current_password" required type="password" autocomplete="current-password" placeholder="输入当前登录密码"></label>
              <label>新密码<input v-model="passwordForm.new_password" required minlength="8" type="password" autocomplete="new-password" placeholder="至少 8 位字符"></label>
              <label>确认新密码<input v-model="passwordForm.confirm_password" required minlength="8" type="password" autocomplete="new-password" placeholder="再次输入新密码"></label>
              <div class="password-guidance"><n-icon :size="18"><Key /></n-icon><div><strong>建议使用不重复的强密码</strong><span>至少 8 位，建议同时包含字母、数字和符号。</span></div></div>
              <footer class="form-actions"><span>平台不会以明文保存密码。</span><button type="submit" class="primary-action" :disabled="passwordSaving"><n-icon :size="17"><ShieldLock /></n-icon>{{ passwordSaving ? '正在更新…' : '更新密码' }}</button></footer>
            </form>
          </section>

          <section v-else class="settings-section connection-section">
            <header class="section-head">
              <div><span>连接配置</span><h2>平台与协同工具</h2><p>维护本人在外部平台中的账号标识，为后续消息同步和自动填报做准备。</p></div>
              <em>{{ configuredConnectorCount }}/{{ connectors.length }} 已配置</em>
            </header>
            <div class="connection-workspace">
              <nav class="connector-list" aria-label="连接类型">
                <button v-for="item in connectors" :key="item.key" type="button" :class="{ active: activeConnectorKey === item.key }" @click="activeConnectorKey = item.key">
                  <span class="connector-icon"><n-icon :size="18"><component :is="item.icon" /></n-icon></span>
                  <span><strong>{{ item.label }}</strong><small>{{ item.configured ? '连接信息已保存' : '尚未配置' }}</small></span>
                  <i :class="{ configured: item.configured }"></i>
                </button>
              </nav>

              <form v-if="activeConnector" class="connector-editor" @submit.prevent="saveConnector">
                <header><span class="connector-icon large"><n-icon :size="21"><component :is="activeConnector.icon" /></n-icon></span><div><h3>{{ activeConnector.label }}</h3><p>{{ activeConnector.description }}</p></div></header>
                <label v-if="activeConnector.key === 'platform'">平台类型<select v-model="activeConnector.platformType"><option>监测平台</option><option>项目管理平台</option><option>资料管理平台</option><option>质量安全检查平台</option></select></label>
                <label>{{ activeConnector.accountLabel }}<input v-model.trim="activeConnector.account" maxlength="200" :placeholder="activeConnector.accountPlaceholder"></label>
                <label>登录密码 / 授权码<input v-model="activeConnector.secret" type="password" autocomplete="new-password" placeholder="输入后仅用于本次配置，不在浏览器中保存"></label>
                <div class="credential-note"><n-icon :size="17"><ShieldLock /></n-icon><p><strong>凭据保护</strong><span>当前仅保存账号标识和配置状态，密码或授权码不会写入浏览器存储。</span></p></div>
                <footer class="form-actions"><span>{{ activeConnector.updatedAt ? `更新于 ${activeConnector.updatedAt}` : '尚未保存连接信息' }}</span><button type="submit" class="primary-action"><n-icon :size="17"><Link /></n-icon>保存连接信息</button></footer>
              </form>
            </div>
          </section>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { Building, DeviceFloppy, Key, Link, Mail, MessageCircle, PlugConnected, ShieldLock, UserCircle } from '@vicons/tabler'
import api, { type ApiEnvelope } from '@/api/client'

type SettingsSection = 'account' | 'security' | 'connections'
type UserProfile = {
  id: number | null
  username: string
  real_name: string
  phone: string
  email: string
  title: string
  org_name: string
  role: string
  updated_at: string
}
type ConnectorConfig = {
  key: string
  label: string
  description: string
  accountLabel: string
  accountPlaceholder: string
  account: string
  secret: string
  platformType: string
  configured: boolean
  updatedAt: string
  icon: any
}

const message = useMessage()
const activeSection = ref<SettingsSection>('account')
const settingsMainRef = ref<HTMLElement | null>(null)
const activeConnectorKey = ref('platform')
const profileSaving = ref(false)
const passwordSaving = ref(false)
const currentUserName = sessionStorage.getItem('current_user_name') || '当前用户'
const profile = reactive<UserProfile>({ id: null, username: '', real_name: currentUserName, phone: '', email: '', title: '', org_name: '', role: '', updated_at: '' })
const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' })

const settingSections = [
  { key: 'account' as const, label: '个人账号', description: '姓名、岗位与联系方式', icon: UserCircle },
  { key: 'security' as const, label: '登录安全', description: '修改密码与安全提示', icon: ShieldLock },
  { key: 'connections' as const, label: '连接配置', description: '平台、邮件与协同工具', icon: PlugConnected },
]
const connectors = reactive<ConnectorConfig[]>([
  { key: 'platform', label: '工程平台账号', description: '选择工程中已配置的平台，维护本人用于登录和自动填报的账号标识。', accountLabel: '平台用户名', accountPlaceholder: '例如：safety_user', account: '', secret: '', platformType: '监测平台', configured: false, updatedAt: '', icon: Building },
  { key: 'mail', label: '邮件配置', description: '用于接收过程邮件、会议通知和外发报告草稿。', accountLabel: '项目邮箱', accountPlaceholder: 'name@example.com', account: '', secret: '', platformType: '', configured: false, updatedAt: '', icon: Mail },
  { key: 'wecom', label: '企业微信配置', description: '用于接入项目群消息、任务提醒和转发同事处理。', accountLabel: '企业微信账号', accountPlaceholder: '手机号或企业微信账号', account: '', secret: '', platformType: '', configured: false, updatedAt: '', icon: MessageCircle },
  { key: 'feishu', label: '飞书配置', description: '用于后续连接飞书群、飞书文档和审批消息。', accountLabel: '飞书账号', accountPlaceholder: '请输入飞书账号', account: '', secret: '', platformType: '', configured: false, updatedAt: '', icon: MessageCircle },
  { key: 'dingtalk', label: '钉钉配置', description: '用于后续连接钉钉群、待办和组织通讯录。', accountLabel: '钉钉账号', accountPlaceholder: '请输入钉钉账号', account: '', secret: '', platformType: '', configured: false, updatedAt: '', icon: MessageCircle },
])

const profileInitial = computed(() => (profile.real_name || currentUserName).trim().slice(0, 1) || '用')
const roleLabel = computed(() => ({ admin: '管理员', user: '普通用户' }[profile.role] || '普通用户'))
const profileUpdatedAt = computed(() => profile.updated_at ? `资料更新于 ${formatTime(profile.updated_at)}` : '个人资料尚未更新')
const configuredConnectorCount = computed(() => connectors.filter(item => item.configured).length)
const activeConnector = computed(() => connectors.find(item => item.key === activeConnectorKey.value))
const connectorStorageKey = computed(() => `dobby-personal-connectors:${profile.id || sessionStorage.getItem('current_user_id') || 'current'}`)

function formatTime(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
}
function applyProfile(data: Partial<UserProfile>) {
  profile.id = data.id ?? profile.id
  profile.username = data.username || profile.username
  profile.real_name = data.real_name || profile.real_name
  profile.phone = data.phone || ''
  profile.email = data.email || ''
  profile.title = data.title || ''
  profile.org_name = data.org_name || ''
  profile.role = data.role || profile.role
  profile.updated_at = data.updated_at || profile.updated_at
}
async function loadProfile() {
  try {
    const response = await api.get<ApiEnvelope<UserProfile>>('/me')
    applyProfile(response.data.data)
    loadConnectorSettings()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '个人资料加载失败。')
  }
}
async function saveProfile() {
  if (!profile.real_name.trim()) {
    message.warning('显示名称不能为空。')
    return
  }
  profileSaving.value = true
  try {
    const response = await api.patch<ApiEnvelope<UserProfile>>('/me', {
      real_name: profile.real_name,
      phone: profile.phone || null,
      email: profile.email || null,
      title: profile.title || null,
      org_name: profile.org_name || null,
    })
    applyProfile(response.data.data)
    sessionStorage.setItem('current_user_name', profile.real_name)
    message.success('个人资料已保存')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '个人资料保存失败。')
  } finally {
    profileSaving.value = false
  }
}
async function changePassword() {
  if (passwordForm.new_password.length < 8) {
    message.warning('新密码至少需要 8 位字符。')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    message.warning('两次输入的新密码不一致。')
    return
  }
  passwordSaving.value = true
  try {
    await api.post('/me/password', { current_password: passwordForm.current_password, new_password: passwordForm.new_password })
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
    message.success('登录密码已更新')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '密码更新失败。')
  } finally {
    passwordSaving.value = false
  }
}
function loadConnectorSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(connectorStorageKey.value) || '{}') as Record<string, Partial<ConnectorConfig>>
    for (const connector of connectors) {
      const value = saved[connector.key]
      if (!value) continue
      connector.account = value.account || ''
      connector.platformType = value.platformType || connector.platformType
      connector.configured = Boolean(value.configured)
      connector.updatedAt = value.updatedAt || ''
    }
  } catch {
    localStorage.removeItem(connectorStorageKey.value)
  }
}
function saveConnector() {
  const connector = activeConnector.value
  if (!connector) return
  if (!connector.account.trim()) {
    message.warning(`请填写${connector.accountLabel}。`)
    return
  }
  connector.configured = true
  connector.updatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const saved = Object.fromEntries(connectors.map(item => [item.key, {
    account: item.account,
    platformType: item.platformType,
    configured: item.configured,
    updatedAt: item.updatedAt,
  }]))
  localStorage.setItem(connectorStorageKey.value, JSON.stringify(saved))
  connector.secret = ''
  message.success(`${connector.label}已保存；敏感凭据未写入浏览器。`)
}

onMounted(loadProfile)
watch(activeSection, async () => {
  await nextTick()
  settingsMainRef.value?.scrollTo({ top: 0 })
})
</script>

<style scoped>
.personal-settings-page { height: 100%; min-height: 0; overflow: hidden; padding: 18px; background: #f3f6f4; }
.personal-settings-shell { display: grid; width: 100%; height: 100%; min-height: 0; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid #dce6e3; border-radius: 12px; background: #fff; box-shadow: 0 16px 36px rgba(24, 58, 52, .07); }
.personal-settings-head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 15px; padding: 22px 24px; border-bottom: 1px solid #dde7e4; background: radial-gradient(circle at 85% 20%, rgba(15, 118, 110, .1), transparent 36%), linear-gradient(110deg, #fff, #f5faf8); }
.profile-avatar { display: grid; width: 54px; height: 54px; place-items: center; border-radius: 14px; color: #fff; background: #163f3c; box-shadow: 0 8px 18px rgba(22, 63, 60, .18); font-size: 20px; font-weight: 800; }
.profile-heading { min-width: 0; }.profile-heading > span,.section-head > div > span { color: #0f766e; font-size: 12px; font-weight: 800; letter-spacing: .04em; }.profile-heading h1 { margin: 3px 0 4px; color: #173235; font-size: 23px; line-height: 1.2; letter-spacing: -.02em; }.profile-heading p,.section-head p { margin: 0; color: #667c77; font-size: 13px; line-height: 1.55; }
.account-state { display: grid; grid-template-columns: auto auto; align-items: center; gap: 4px 7px; min-width: 148px; padding: 10px 12px; border: 1px solid #d6e6e1; border-radius: 8px; background: rgba(255,255,255,.82); }.account-state i { width: 8px; height: 8px; border-radius: 50%; background: #12a27c; box-shadow: 0 0 0 3px rgba(18,162,124,.1); }.account-state span { color: #63807a; font-size: 12px; }.account-state strong { grid-column: 1 / -1; overflow: hidden; color: #234a45; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.personal-settings-layout { display: grid; min-height: 0; grid-template-columns: 250px minmax(0, 1fr); overflow: hidden; }
.settings-rail { display: flex; min-height: 0; flex-direction: column; padding: 18px 14px; border-right: 1px solid #e0e8e5; background: #f7faf8; }.rail-profile { display: grid; gap: 3px; padding: 5px 8px 15px; }.rail-profile strong { color: #1d3d39; font-size: 14px; }.rail-profile span { color: #728681; font-size: 12px; }
.settings-rail nav { display: grid; gap: 6px; }.settings-rail nav button { display: grid; width: 100%; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 10px; border: 0; border-radius: 8px; padding: 11px; color: #55706b; background: transparent; font: inherit; text-align: left; cursor: pointer; transition: background .18s ease, color .18s ease, transform .18s ease; }.settings-rail nav button > span { display: grid; gap: 2px; }.settings-rail nav button strong { font-size: 13px; }.settings-rail nav button small { color: #83938f; font-size: 12px; }.settings-rail nav button:hover { color: #173f3b; background: #eaf3f0; transform: translateX(2px); }.settings-rail nav button.active { color: #fff; background: #174c47; box-shadow: 0 7px 16px rgba(23,76,71,.14); }.settings-rail nav button.active small { color: rgba(255,255,255,.72); }
.rail-note { display: flex; align-items: flex-start; gap: 7px; margin: auto 6px 0; padding-top: 16px; border-top: 1px solid #dce6e3; color: #708681; font-size: 12px; line-height: 1.5; }.rail-note svg { flex: 0 0 auto; margin-top: 1px; color: #0f766e; }
.settings-main { min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; padding: 24px 28px 32px; scrollbar-gutter: stable; }.settings-section { display: grid; gap: 22px; }.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid #e2e9e7; }.section-head h2 { margin: 4px 0 5px; color: #173235; font-size: 20px; letter-spacing: -.015em; }.section-head em { display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto; margin-top: 6px; border-radius: 5px; padding: 5px 8px; color: #53736d; background: #edf4f2; font-size: 12px; font-style: normal; }.section-head em.security-badge { color: #0f766e; }
.settings-main.connection-mode { overflow: hidden; }
.settings-form { display: grid; gap: 16px; }.account-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }.settings-form label,.connector-editor label { display: grid; gap: 7px; color: #49645f; font-size: 13px; font-weight: 700; }.settings-form input,.connector-editor input,.connector-editor select { box-sizing: border-box; width: 100%; min-width: 0; min-height: 42px; border: 1px solid #cad9d5; border-radius: 7px; padding: 9px 11px; color: #193b37; background: #fff; font: inherit; font-size: 13px; outline: 0; transition: border-color .18s ease, box-shadow .18s ease; }.settings-form input:focus,.connector-editor input:focus,.connector-editor select:focus { border-color: #4e9187; box-shadow: 0 0 0 3px rgba(15,118,110,.1); }.settings-form input:disabled { color: #788984; background: #f1f4f3; cursor: not-allowed; }
.form-actions { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; gap: 14px; padding-top: 18px; border-top: 1px solid #e3eae8; }.form-actions > span { color: #7a8d88; font-size: 12px; }.primary-action { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; border: 0; border-radius: 7px; padding: 9px 14px; color: #fff; background: #d45f1f; box-shadow: 0 6px 14px rgba(212,95,31,.17); font: inherit; font-size: 13px; font-weight: 800; cursor: pointer; transition: transform .18s ease, filter .18s ease; }.primary-action:hover:not(:disabled) { filter: brightness(.96); transform: translateY(-1px); }.primary-action:disabled { opacity: .55; cursor: not-allowed; box-shadow: none; }
.password-form { max-width: 620px; }.password-guidance { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 10px; padding: 12px; border: 1px solid #d4e5e0; border-radius: 8px; color: #0f766e; background: #f0f7f5; }.password-guidance > div { display: grid; gap: 3px; }.password-guidance strong { color: #284f49; font-size: 13px; }.password-guidance span { color: #68807b; font-size: 12px; }.password-form .form-actions { grid-column: auto; }
.connection-section { height: 100%; min-height: 0; grid-template-rows: auto minmax(0, 1fr); }
.connection-workspace { display: grid; min-height: 0; grid-template-columns: 245px minmax(0,1fr); overflow: hidden; border: 1px solid #dce6e3; border-radius: 10px; }.connector-list { display: grid; min-height: 0; align-content: start; gap: 4px; overflow-y: auto; padding: 10px; border-right: 1px solid #e0e8e5; background: #f7faf8; scrollbar-gutter: stable; }.connector-list button { display: grid; width: 100%; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 9px; border: 0; border-radius: 7px; padding: 9px; color: #55706b; background: transparent; font: inherit; text-align: left; cursor: pointer; }.connector-list button > span:nth-child(2) { display: grid; min-width: 0; gap: 2px; }.connector-list strong { overflow: hidden; color: #294d47; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.connector-list small { color: #82938f; font-size: 12px; }.connector-list button > i { width: 7px; height: 7px; border-radius: 50%; background: #b7c2bf; }.connector-list button > i.configured { background: #10a079; }.connector-list button:hover,.connector-list button.active { background: #e7f1ee; }.connector-list button.active { box-shadow: inset 3px 0 #0f766e; }
.connector-icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 8px; color: #176b62; background: #dfeeea; }.connector-icon.large { width: 40px; height: 40px; }
.connector-editor { display: grid; min-height: 0; align-content: start; gap: 16px; overflow-x: hidden; overflow-y: auto; padding: 22px; scrollbar-gutter: stable; }.connector-editor > header { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 11px; padding-bottom: 15px; border-bottom: 1px solid #e2e9e7; }.connector-editor h3 { margin: 0 0 4px; color: #193b37; font-size: 17px; }.connector-editor header p { margin: 0; color: #6d817c; font-size: 12px; line-height: 1.55; }.credential-note { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 9px; padding: 11px; border-radius: 8px; color: #0f766e; background: #eef6f3; }.credential-note > p { display: grid; gap: 3px; margin: 0; }.credential-note strong { color: #315a54; font-size: 12px; }.credential-note span { color: #70837f; font-size: 12px; line-height: 1.5; }.connector-editor .form-actions { grid-column: auto; margin-top: 4px; }
button:focus-visible,input:focus-visible,select:focus-visible { outline: 2px solid rgba(15,118,110,.45); outline-offset: 2px; }
@media (max-width: 900px) { .personal-settings-layout { grid-template-columns: 210px minmax(0,1fr); }.settings-main { padding: 20px; }.connection-workspace { grid-template-columns: 210px minmax(0,1fr); } }
@media (max-width: 720px) { .personal-settings-page { height: auto; min-height: 100%; overflow: visible; padding: 10px; }.personal-settings-shell { height: auto; min-height: calc(100dvh - var(--header-height,56px) - 20px); overflow: visible; }.personal-settings-head { grid-template-columns: auto minmax(0,1fr); padding: 18px; }.account-state { display: none; }.personal-settings-layout { display: block; overflow: visible; }.settings-rail { border-right: 0; border-bottom: 1px solid #e0e8e5; }.settings-rail nav { grid-template-columns: repeat(3, minmax(0,1fr)); }.settings-rail nav button { grid-template-columns: auto; justify-items: center; text-align: center; }.settings-rail nav button small,.rail-profile,.rail-note { display: none; }.settings-main,.settings-main.connection-mode { overflow: visible; padding: 18px; }.account-form { grid-template-columns: 1fr; }.connection-section { height: auto; }.connection-workspace { grid-template-columns: 1fr; }.connector-list { grid-template-columns: repeat(2,minmax(0,1fr)); overflow: visible; border-right: 0; border-bottom: 1px solid #e0e8e5; }.connector-editor { overflow: visible; }.section-head { flex-direction: column; }.form-actions { align-items: stretch; flex-direction: column; }.primary-action { width: 100%; } }
</style>
