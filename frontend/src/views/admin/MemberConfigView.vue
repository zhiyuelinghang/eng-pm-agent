<template>
  <div class="admin-view">
    <AdminPageHeader
      title="全局成员与责任配置"
      subtitle="维护项目团队成员及其角色，并查看每人所负责的风险源。"
    >
      <template #actions>
        <n-button type="primary" @click="openAdd">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          添加成员
        </n-button>
      </template>
    </AdminPageHeader>
    <div class="admin-panel">
      <n-data-table :columns="columns" :data="store.members" :bordered="false" size="small" class="admin-table" />
    </div>

    <n-modal v-model:show="dialogVisible" preset="dialog" :title="isEdit ? '编辑成员' : '添加成员'" style="width:480px">
      <n-form :model="form" label-width="80px" label-placement="left">
        <n-form-item label="姓名"><n-input v-model:value="form.name" /></n-form-item>
        <n-form-item label="职位"><n-input v-model:value="form.title" /></n-form-item>
        <n-form-item label="电话"><n-input v-model:value="form.phone" /></n-form-item>
        <n-form-item label="邮箱"><n-input v-model:value="form.email" /></n-form-item>
        <n-form-item label="角色">
          <n-select v-model:value="form.role" multiple :options="roleOptions" style="width:100%" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="dialogVisible = false">取消</n-button>
        <n-button type="primary" @click="saveMember">保存</n-button>
      </template>
    </n-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, h } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NModal, NForm, NFormItem, NInput, NSelect, NButton, NDataTable } from 'naive-ui'
import type { Member } from '@/types'
const store = useAppStore()
const message = useMessage()
const roleOptions = [
  { label: '项目负责人', value: '项目负责人' }, { label: '技术负责人', value: '技术负责人' },
  { label: '安全员', value: '安全员' }, { label: '施工员', value: '施工员' },
  { label: '资料员', value: '资料员' }, { label: '平台填报', value: '平台填报' },
]
const dialogVisible = ref(false)
const isEdit = ref(false)
const form = reactive<Partial<Member>>({ name: '', title: '', phone: '', email: '', role: [] })
const responsibleRisks = (memberId: string) => store.riskSources.filter(r => r.responsibleId === memberId || r.confirmatorId === memberId)
const openAdd = () => { isEdit.value = false; Object.assign(form, { id: undefined, name: '', title: '', phone: '', email: '', role: [] }); dialogVisible.value = true }
const editMember = (m: Member) => { isEdit.value = true; Object.assign(form, { ...m }); dialogVisible.value = true }
const saveMember = () => { store.saveMember({ ...form }); message.success(isEdit.value ? '成员信息已更新' : '成员已添加'); dialogVisible.value = false }
const columns = [
  { title: '姓名', key: 'name', width: 100 },
  { title: '职位', key: 'title', width: 120 },
  { title: '电话', key: 'phone', width: 140 },
  { title: '邮箱', key: 'email' },
  { title: '负责风险源', key: 'risks', minWidth: 200, render: (row: Member) => {
    const risks = responsibleRisks(row.id)
    return risks.length
      ? h('div', { class: 'risk-tags' }, risks.map(r => h('span', { key: r.id, class: 'risk-mini-tag' }, r.name)))
      : h('span', { class: 'text-muted' }, '—')
  }},
  { title: '操作', key: 'action', width: 100, align: 'right' as const, render: (row: Member) =>
    h('button', { class: 'tbtn', onClick: () => editMember(row) }, '编辑')
  },
]
</script>
<style scoped>
.risk-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.risk-mini-tag { padding: 1px 6px; background: var(--color-primary-dim); color: var(--color-primary); border-radius: 4px; font-size: 11px; }
</style>
