<template>
  <section class="platform-panel">
    <header><div><h2>{{ manage ? '工程平台' : '工程平台账号' }}</h2><p>{{ manage ? '维护平台名称、类型与地址，成员在个人设置中保存各自账号。' : '选择当前工程的平台，维护本人账号。' }}</p></div><button v-if="manage" :disabled="busy" @click="edit()">新增平台</button></header>
    <p v-if="!projectId">请先选择工程。</p><p v-else-if="loading" role="status">正在加载平台…</p>
    <p v-else-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <template v-else>
      <p v-if="!platforms.length && !editing" class="empty">尚未配置工程平台。{{ manage ? '点击新增平台开始配置。' : '请联系工程管理员在工程配置中添加。' }}</p>
      <div class="platform-list"><button v-for="platform in platforms" :key="platform.id" :class="{ active: selectedId === platform.id }" :disabled="busy" @click="selectPlatform(platform)"><strong>{{ platform.name }}</strong><span>{{ platform.platform_type }}{{ !manage ? (accounts.some(a => a.platform_id === platform.id) ? ' · 已配置账号' : ' · 未配置账号') : '' }}</span></button></div>
      <form v-if="manage && editing" @submit.prevent="savePlatform">
        <label>平台名称<input v-model.trim="form.name" required maxlength="100" :disabled="busy"></label><label>平台类型<select v-model="form.platform_type" :disabled="busy"><option>监测平台</option><option>项目管理平台</option><option>资料管理平台</option><option>质量安全检查平台</option><option>其他平台</option></select></label>
        <label class="wide">平台地址<input v-model.trim="form.url" required type="url" maxlength="2000" placeholder="https://" :disabled="busy"></label><label class="wide">说明<textarea v-model.trim="form.description" maxlength="4000" rows="3" :disabled="busy"></textarea></label>
        <footer><button type="button" :disabled="busy" @click="editing = false">取消</button><button class="primary" :disabled="busy">{{ busy ? '保存中…' : '保存平台' }}</button></footer>
      </form>
      <form v-else-if="!manage && selectedPlatform" @submit.prevent="saveAccount">
        <div class="wide"><strong>{{ selectedPlatform.name }}</strong> · <a :href="selectedPlatform.url" target="_blank" rel="noopener noreferrer">打开平台</a><p>{{ selectedPlatform.description }}</p></div>
        <label class="wide">平台用户名<input v-model.trim="accountForm.account_identifier" required maxlength="500" autocomplete="username" :disabled="busy"></label>
        <label class="wide">登录密码 / 授权码<input v-model="accountForm.secret" type="password" autocomplete="new-password" :disabled="busy" :placeholder="selectedAccount?.has_secret ? '留空则继续使用已保存的凭据' : '输入密码或授权码'"></label>
        <label v-if="legacyAccount && !selectedAccount" class="wide legacy-account"><input v-model="accountForm.use_legacy_account" type="checkbox" :disabled="busy" @change="useLegacy">关联历史账号 {{ legacyAccount.account_identifier }}（{{ legacyAccount.platform_type || '未标注平台' }}）及已保存凭据</label>
        <p class="wide">账号按工程和平台分别保存，密码仅以服务端密文保存。</p>
        <footer><button v-if="selectedAccount" type="button" :disabled="busy" @click="clearAccount">清除本人账号</button><button class="primary" :disabled="busy">{{ busy ? '保存中…' : '保存个人账号' }}</button></footer>
      </form>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import api, { type ApiEnvelope } from '@/api/client'
type Platform = { id: number; name: string; platform_type: string; url: string; description: string }
type Account = { platform_id: number; account_identifier: string; has_secret: boolean }
const props = defineProps<{ projectId: string; manage?: boolean }>()
const message = useMessage(), platforms = ref<Platform[]>([]), accounts = ref<Account[]>([])
const legacyAccount = ref<{ account_identifier: string; platform_type: string } | null>(null)
const selectedId = ref<number | null>(null), loading = ref(false), busy = ref(false), editing = ref(false), error = ref('')
const selectedPlatform = computed(() => platforms.value.find(item => item.id === selectedId.value))
const selectedAccount = computed(() => accounts.value.find(item => item.platform_id === selectedId.value))
const form = reactive({ name: '', platform_type: '监测平台', url: '', description: '' })
const accountForm = reactive({ account_identifier: '', secret: '', use_legacy_account: false })
let generation = 0
onBeforeUnmount(() => { generation++ })
async function load() {
  const projectId = props.projectId, version = ++generation
  platforms.value = []; accounts.value = []; selectedId.value = null; editing.value = false; error.value = ''; legacyAccount.value = null
  Object.assign(accountForm, { account_identifier: '', secret: '', use_legacy_account: false })
  if (!projectId) return
  loading.value = true
  try {
    const [platformRows, accountRows, legacy] = await Promise.all([
      api.get<ApiEnvelope<Platform[]>>(`/projects/${projectId}/platforms`),
      props.manage ? Promise.resolve(null) : api.get<ApiEnvelope<Account[]>>(`/projects/${projectId}/my-platform-accounts`),
      props.manage ? Promise.resolve(null) : api.get<ApiEnvelope<Array<{ connector_type: string; account_identifier: string; platform_type: string }>>>('/me/connectors'),
    ])
    if (version !== generation) return
    platforms.value = platformRows.data.data; accounts.value = accountRows?.data.data || []
    legacyAccount.value = legacy?.data.data.find(item => item.connector_type === 'platform') || null
    if (platforms.value[0]) selectPlatform(platforms.value[0])
  } catch (err: any) { if (version === generation) error.value = err.response?.data?.detail || '平台配置加载失败' }
  finally { if (version === generation) loading.value = false }
}
function edit(platform?: Platform) {
  selectedId.value = platform?.id || null
  Object.assign(form, platform || { name: '', platform_type: '监测平台', url: '', description: '' }); editing.value = true
}
function selectPlatform(platform: Platform) {
  selectedId.value = platform.id
  if (props.manage) edit(platform)
  else Object.assign(accountForm, { account_identifier: selectedAccount.value?.account_identifier || '', secret: '', use_legacy_account: false })
}
function useLegacy() { if (accountForm.use_legacy_account && legacyAccount.value) accountForm.account_identifier = legacyAccount.value.account_identifier }
async function savePlatform() {
  if (busy.value) return
  busy.value = true
  const projectId = props.projectId
  try {
    const payload = { name: form.name, platform_type: form.platform_type, url: form.url, description: form.description }, url = `/projects/${projectId}/platforms`
    await (selectedId.value ? api.put(`${url}/${selectedId.value}`, payload) : api.post(url, payload))
    if (props.projectId === projectId) { message.success('工程平台已保存'); await load() }
  } catch (err: any) { message.error(err.response?.data?.detail || '平台保存失败') }
  finally { busy.value = false }
}
async function saveAccount() {
  if (busy.value || !selectedId.value) return
  busy.value = true
  const projectId = props.projectId, platformId = selectedId.value
  try {
    const result = await api.put<ApiEnvelope<Account>>(`/projects/${projectId}/my-platform-accounts/${platformId}`, { ...accountForm, secret: accountForm.secret || null })
    if (props.projectId !== projectId) return
    accounts.value = [...accounts.value.filter(item => item.platform_id !== platformId), result.data.data]; accountForm.secret = ''; accountForm.use_legacy_account = false
    message.success('个人平台账号已保存')
  } catch (err: any) { message.error(err.response?.data?.detail || '个人平台账号保存失败') }
  finally { busy.value = false }
}
async function clearAccount() {
  if (busy.value || !selectedId.value) return
  busy.value = true
  const projectId = props.projectId, platformId = selectedId.value
  try {
    await api.delete(`/projects/${projectId}/my-platform-accounts/${platformId}`)
    if (props.projectId !== projectId) return
    accounts.value = accounts.value.filter(item => item.platform_id !== platformId); Object.assign(accountForm, { account_identifier: '', secret: '', use_legacy_account: false }); message.success('本人平台账号已清除')
  } catch (err: any) { message.error(err.response?.data?.detail || '账号清除失败') }
  finally { busy.value = false }
}
watch(() => props.projectId, load, { immediate: true })
</script>
<style scoped>
.platform-panel { padding: 24px; font-size: 14px; color: #183d38; overflow: auto; } header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; } h2 { margin: 0 0 8px; font-size: 20px; } p { color: #677e78; line-height: 1.6; } button, input, select, textarea { font: inherit; } button { cursor: pointer; padding: 9px 15px; border: 1px solid #ceded7; border-radius: 6px; background: white; color: #1c5046; } button:disabled { opacity: .5; cursor: wait; } .platform-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 20px 0; } .platform-list button { display: grid; gap: 6px; text-align: left; } .platform-list span { font-size: 12px; } .platform-list .active { background: #e8f4ed; border-color: #407a63; } form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; padding-top: 12px; max-width: 880px; } label { display: grid; gap: 8px; } input, select, textarea { box-sizing: border-box; width: 100%; padding: 10px; border: 1px solid #cbdad3; border-radius: 6px; background: white; } .wide, footer { grid-column: 1 / -1; } .legacy-account { display: flex; align-items: center; } .legacy-account input { width: auto; } footer { display: flex; justify-content: flex-end; gap: 10px; } .primary { background: #236348; color: white; } a { color: #246749; } .empty { padding: 36px 0; } @media (max-width: 700px) { form { grid-template-columns: 1fr; } .platform-panel { padding: 16px; } }
</style>
