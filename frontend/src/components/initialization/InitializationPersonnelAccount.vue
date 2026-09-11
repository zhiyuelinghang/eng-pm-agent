<template>
  <div class="personnel-account" :aria-label="`${name}的登录账号`">
    <template v-if="existingAccount">
      <span>登录账号</span><strong>{{ existingAccount.username }}</strong><span class="account-hint">沿用此账号</span>
    </template>
    <template v-else-if="credential && admin">
      <label>登录账号<input :value="credential.username" :aria-label="`${name}的登录账号`" :disabled="disabled" :aria-invalid="Boolean(error)" autocomplete="off" maxlength="64" @input="update('username', $event)"></label>
      <label>初始密码<span class="password-field"><input :value="credential.initial_password" :aria-label="`${name}的初始密码`" :disabled="disabled" :type="showPassword ? 'text' : 'password'" :aria-invalid="Boolean(error)" autocomplete="new-password" minlength="8" maxlength="12" @input="update('initial_password', $event)"><button type="button" :aria-label="`${showPassword ? '隐藏' : '显示'}${name}的初始密码`" :title="showPassword ? '隐藏初始密码' : '显示初始密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword"><NIcon :size="16"><EyeOff v-if="showPassword" /><Eye v-else /></NIcon></button><button type="button" :aria-label="`重新生成${name}的初始密码`" title="重新生成初始密码" :disabled="disabled" @click="regenerate"><NIcon :size="16"><Refresh /></NIcon></button></span></label>
      <span class="account-hint">已自动生成，确认提交后创建</span>
      <p v-if="error" class="account-error" role="alert">{{ error }}</p>
    </template>
    <span v-else class="account-hint">{{ !admin ? '新账号由管理员核对后创建。' : !selected ? '选择该人员后自动生成账号和初始密码。' : loading ? '正在生成账号和初始密码…' : '人员资料核验通过后自动生成账号和初始密码。' }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Eye, EyeOff, Refresh } from '@vicons/tabler'
import type { InitializationChangeCredential, InitializationChangePreview, InitializationCredentialField } from '@/types/initializationChanges'
import { generateInitializationPassword } from '@/utils/initializationChangePresentation'
const props = defineProps<{
  name: string; credential?: InitializationChangeCredential; existingAccount?: NonNullable<InitializationChangePreview['existing_personnel_accounts']>[number];
  admin: boolean; disabled: boolean; selected: boolean; loading?: boolean; error?: string;
}>()
const emit = defineEmits<{ change: [field: InitializationCredentialField, value: string] }>()
const showPassword = ref(true)
function update(field: InitializationCredentialField, event: Event) {
  if (props.admin && !props.disabled && !props.existingAccount) emit('change', field, (event.target as HTMLInputElement).value)
}
function regenerate() {
  if (props.admin && !props.disabled && !props.existingAccount) emit('change', 'initial_password', generateInitializationPassword())
}
</script>

<style scoped>
.personnel-account { display:flex; flex-wrap:wrap; align-items:center; gap:10px 20px; padding:10px 0 2px; color:var(--text-secondary); font-size:12px; }
.personnel-account > strong { color:var(--text-primary); font-size:13px; font-weight:600; }
label { display:flex; align-items:center; gap:8px; font-size:12px; white-space:nowrap; }
input { width:190px; min-height:34px; min-width:0; padding:6px 9px; border:1px solid var(--border-emphasis); border-radius:5px; color:var(--text-primary); background:var(--bg-surface); font:inherit; font-size:13px; }
input[aria-invalid='true'] { border-color:var(--color-danger); }
.password-field { display:flex; align-items:center; gap:5px; }.password-field input { width:170px; }
button { display:grid; place-items:center; width:30px; height:32px; padding:0; border:1px solid var(--border-default); border-radius:5px; color:var(--text-secondary); background:var(--bg-surface); cursor:pointer; }
button:hover { background:var(--color-accent-soft); color:var(--color-accent); }
input:disabled,button:disabled { opacity:.6; cursor:default; }
button:focus-visible,input:focus-visible { outline:2px solid var(--color-accent); outline-offset:2px; }
.account-hint { color:var(--text-muted); font-size:12px; }.account-error { flex-basis:100%; margin:0; font-size:12px; color:var(--color-danger); }
</style>
