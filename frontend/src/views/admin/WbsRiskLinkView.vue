<template>
  <div class="admin-view">
    <AdminPageHeader
      title="WBS-风险关联规则"
      subtitle="为 WBS 节点绑定对应风险源，设定提前预警天数与提醒方式，系统据此自动生成风险预警任务。"
    >
      <template #actions>
        <n-button type="primary" @click="dialogVisible = true">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          添加关联
        </n-button>
      </template>
    </AdminPageHeader>
    
    <div class="admin-panel admin-panel--pad">
      <n-data-table
        :columns="columns"
        :data="store.wbsRiskLinks"
        size="small"
        :bordered="true"
        :striped="true"
        class="admin-table"
      />
    </div>

    <n-modal v-model:show="dialogVisible" preset="dialog" title="添加 WBS-风险关联" style="width:480px">
      <n-form :model="form" class="dense-modal-form" label-width="100px" label-placement="left" size="small">
        <n-form-item label="WBS 节点">
          <n-select v-model:value="form.wbsId" :options="wbsOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="风险源">
          <n-select v-model:value="form.riskId" :options="riskOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="提前天数">
          <n-input-number v-model:value="form.alertDays" :min="1" :max="180" style="width:100%" />
        </n-form-item>
        <n-form-item label="提醒方式">
            <n-checkbox-group v-model:value="form.notifyMethods">
              <n-space item-style="display:flex">
                <n-checkbox value="app">APP 弹窗</n-checkbox>
                <n-checkbox value="sms">短信提示</n-checkbox>
              </n-space>
            </n-checkbox-group>
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="dialogVisible = false">取消</n-button>
        <n-button type="primary" @click="saveItem">保存</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, h } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NModal, NDataTable, NForm, NFormItem, NSelect, NInputNumber, NCheckboxGroup, NCheckbox, NSpace, NButton, NInput } from 'naive-ui'

const store = useAppStore()
const message = useMessage()

const dialogVisible = ref(false)
const form = reactive({ wbsId: '', riskId: '', alertDays: 14, notifyMethods: ['app', 'sms'] })

const wbsOptions = computed(() => store.wbsItems.map(w => ({ label: `${w.code} ${w.name}`, value: w.id })))
const riskOptions = computed(() => store.riskSources.map(r => ({ label: r.name, value: r.id })))

const wbsCode = (id: string) => store.wbsItems.find((w:any) => w.id === id)?.code ?? id
const riskLevel = (id: string) => store.riskSources.find((r:any) => r.id === id)?.level ?? 'medium'
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const levelClass = (l: string) => ({ critical: 'badge-danger', high: 'badge-warning', medium: 'badge-primary', low: 'badge-success' }[l] ?? '')

const saveItem = () => {
  if (!form.wbsId || !form.riskId) {
    message.warning('请先选择 WBS 节点和风险源')
    return
  }
  store.addWbsRiskLink({ wbsId: form.wbsId, riskId: form.riskId, alertDays: form.alertDays, notifyMethods: [...form.notifyMethods] })
  message.success('关联已添加')
  dialogVisible.value = false
}

const columns = [
  { 
    title: 'WBS 节点', 
    key: 'wbsId', 
    render: (row: any) => h('div', [
      h('span', { class: 'font-mono text-muted', style: 'margin-right:8px;' }, wbsCode(row.wbsId)),
      h('span', null, store.getWbsName(row.wbsId))
    ])
  },
  { 
    title: '风险源', 
    key: 'riskId', 
    render: (row: any) => h('div', { style: 'display:flex;align-items:center;gap:8px;' }, [
      h('span', { class: `badge ${levelClass(riskLevel(row.riskId))}` }, levelLabel(riskLevel(row.riskId))),
      h('span', null, store.getRiskName(row.riskId))
    ])
  },
  { 
    title: '提前天数', 
    key: 'alertDays', 
    width: 120,
    render: (row: any) => h('span', { class: 'text-warning font-mono', style: 'font-weight:600;' }, `${row.alertDays} 天`)
  },
  { 
    title: '提醒方式', 
    key: 'notifyMethods', 
    width: 180,
    render: (row: any) => row.notifyMethods?.join('、') ?? '—'
  },
  {
    title: '操作',
    key: 'action',
    width: 100,
    render: (row: any) => h('button', { class: 'tbtn tbtn--danger', onClick: () => {
      store.removeWbsRiskLink(row.id)
      message.success('关联已删除')
    }}, '删除')
  }
]
</script>

<style scoped>
@media (max-width: 768px) {
  .admin-view { padding: 16px; }
}
</style>
