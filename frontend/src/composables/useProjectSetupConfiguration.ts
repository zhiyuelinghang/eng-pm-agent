import { computed, reactive, ref, type Ref } from 'vue'

import api, { type ApiEnvelope } from '@/api/client'
import { useAppStore, type ProjectBaseInfoInput } from '@/stores/app'
import type {
  ApiProjectConnectorConfig,
  ProjectBaseInfoForm,
  ProjectConnectorConfig,
  ProjectConnectorKey,
} from '@/views/workspace/project-setup/types'
import { MessageCircle } from '@vicons/tabler'

type SetupMessage = {
  success: (content: string) => void
  warning: (content: string) => void
  error: (content: string) => void
}

type SetupConfigurationOptions = {
  store: ReturnType<typeof useAppStore>
  message: SetupMessage
  configProjectId: Ref<string>
  run: (action: () => Promise<unknown>, success: string) => void
}

export function useProjectSetupConfiguration(options: SetupConfigurationOptions) {
  const { store, message, configProjectId, run } = options
  const projectBaseInfoForm = reactive<ProjectBaseInfoForm>({
    name: '',
    engineeringTypeDescription: '',
    contractStartDate: '',
    contractEndDate: '',
    contractDurationDays: '',
    contractAmountWanYuan: '',
    constructionUnitName: '',
    generalContractorUnitName: '',
    supervisionUnitName: '',
    designUnitName: '',
    surveyUnitName: '',
  })
  const projectConnectorLoading = ref(false)
  const projectConnectorSaving = ref(false)
  const projectConnectorTesting = ref(false)
  const projectConnectorClearing = ref(false)
  const activeProjectConnectorKey = ref<ProjectConnectorKey>('wecom')
  const projectConnectors = reactive<ProjectConnectorConfig[]>([
    { key: 'wecom', label: '企业微信', description: '配置项目群机器人，用于任务下发、节点流转和逾期提醒。', connectionLabel: '项目群名称', connectionPlaceholder: '例如：项目管理群', secretLabel: '群机器人 Webhook', secretPlaceholder: '粘贴企业微信群机器人的完整 Webhook', connectionId: '', secret: '', configured: false, hasSecret: false, updatedAt: '', icon: MessageCircle },
    { key: 'feishu', label: '飞书', description: '配置当前项目使用的飞书应用或项目群机器人。', connectionLabel: '应用 ID / 机器人 Webhook', connectionPlaceholder: '输入应用 ID 或项目群机器人 Webhook', secretLabel: '应用 Secret / 签名密钥', secretPlaceholder: '输入应用密钥或签名密钥', connectionId: '', secret: '', configured: false, hasSecret: false, updatedAt: '', icon: MessageCircle },
    { key: 'dingtalk', label: '钉钉', description: '配置当前项目使用的钉钉应用或项目群机器人。', connectionLabel: '应用 Key / 机器人 Webhook', connectionPlaceholder: '输入应用 Key 或项目群机器人 Webhook', secretLabel: '应用 Secret / 加签密钥', secretPlaceholder: '输入应用密钥或加签密钥', connectionId: '', secret: '', configured: false, hasSecret: false, updatedAt: '', icon: MessageCircle },
  ])
  const activeProjectConnector = computed(() => (
    projectConnectors.find(item => item.key === activeProjectConnectorKey.value)
  ))
  const projectConnectorBusy = computed(() => (
    projectConnectorLoading.value
    || projectConnectorSaving.value
    || projectConnectorTesting.value
    || projectConnectorClearing.value
  ))
  const projectBaseInfoCompletedCount = computed(() => {
    const values = [
      projectBaseInfoForm.name,
      projectBaseInfoForm.engineeringTypeDescription,
      projectBaseInfoForm.contractStartDate,
      projectBaseInfoForm.contractEndDate,
      projectBaseInfoForm.contractDurationDays,
      projectBaseInfoForm.contractAmountWanYuan === 0 ? '0' : projectBaseInfoForm.contractAmountWanYuan,
      projectBaseInfoForm.constructionUnitName,
      projectBaseInfoForm.generalContractorUnitName,
      projectBaseInfoForm.supervisionUnitName,
      projectBaseInfoForm.designUnitName,
      projectBaseInfoForm.surveyUnitName,
    ]
    return values.filter(value => value !== '' && value !== null && value !== undefined).length
  })

  function syncProjectBaseInfo(projectId = configProjectId.value) {
    const project = store.projects.find(item => item.id === projectId)
    Object.assign(projectBaseInfoForm, {
      name: project?.name || '',
      engineeringTypeDescription: project?.engineeringTypeDescription || '',
      contractStartDate: project?.contractStartDate || '',
      contractEndDate: project?.contractEndDate || '',
      contractDurationDays: project?.contractDurationDays ?? '',
      contractAmountWanYuan: project?.contractAmountWanYuan ?? '',
      constructionUnitName: project?.constructionUnitName || '',
      generalContractorUnitName: project?.generalContractorUnitName || '',
      supervisionUnitName: project?.supervisionUnitName || '',
      designUnitName: project?.designUnitName || '',
      surveyUnitName: project?.surveyUnitName || '',
    })
  }

  function saveProjectBaseInfo() {
    if (!configProjectId.value || !projectBaseInfoForm.name.trim()) return
    if (
      projectBaseInfoForm.contractStartDate
      && projectBaseInfoForm.contractEndDate
      && projectBaseInfoForm.contractEndDate < projectBaseInfoForm.contractStartDate
    ) {
      message.warning('合同结束日期不能早于开始日期。')
      return
    }
    const payload: ProjectBaseInfoInput = {
      name: projectBaseInfoForm.name.trim(),
      engineeringTypeDescription: projectBaseInfoForm.engineeringTypeDescription.trim() || undefined,
      contractStartDate: projectBaseInfoForm.contractStartDate || undefined,
      contractEndDate: projectBaseInfoForm.contractEndDate || undefined,
      contractDurationDays: projectBaseInfoForm.contractDurationDays === '' ? undefined : projectBaseInfoForm.contractDurationDays,
      contractAmountWanYuan: projectBaseInfoForm.contractAmountWanYuan === '' ? undefined : projectBaseInfoForm.contractAmountWanYuan,
      constructionUnitName: projectBaseInfoForm.constructionUnitName.trim() || undefined,
      generalContractorUnitName: projectBaseInfoForm.generalContractorUnitName.trim() || undefined,
      supervisionUnitName: projectBaseInfoForm.supervisionUnitName.trim() || undefined,
      designUnitName: projectBaseInfoForm.designUnitName.trim() || undefined,
      surveyUnitName: projectBaseInfoForm.surveyUnitName.trim() || undefined,
    }
    run(async () => {
      await store.updateProject(configProjectId.value, payload)
      syncProjectBaseInfo(configProjectId.value)
    }, '项目基础信息已保存')
  }

  async function loadProjectConnectorSettings() {
    projectConnectorLoading.value = true
    for (const connector of projectConnectors) {
      connector.connectionId = ''
      connector.secret = ''
      connector.configured = false
      connector.hasSecret = false
      connector.updatedAt = ''
    }
    try {
      if (!configProjectId.value) return
      const response = await api.get<ApiEnvelope<ApiProjectConnectorConfig[]>>(`/projects/${configProjectId.value}/connectors`)
      for (const value of response.data.data) {
        const connector = projectConnectors.find(item => item.key === value.connector_type)
        if (!connector) continue
        connector.connectionId = value.connection_id || ''
        connector.configured = Boolean(value.configured)
        connector.hasSecret = Boolean(value.has_secret)
        connector.updatedAt = value.updated_at ? new Date(value.updated_at).toLocaleString('zh-CN', { hour12: false }) : ''
      }
    } catch (error: any) {
      message.error(error.response?.data?.detail || '项目连接配置加载失败。')
    } finally {
      projectConnectorLoading.value = false
    }
  }

  async function saveProjectConnector() {
    if (projectConnectorBusy.value) return
    const connector = activeProjectConnector.value
    if (!connector) return
    if (!connector.connectionId.trim()) {
      message.warning(`请填写${connector.connectionLabel}。`)
      return
    }
    if (connector.key === 'wecom' && !connector.hasSecret && !connector.secret.trim()) {
      message.warning('请填写企业微信群机器人 Webhook。')
      return
    }
    if (!configProjectId.value) return
    projectConnectorSaving.value = true
    try {
      const response = await api.put<ApiEnvelope<ApiProjectConnectorConfig>>(`/projects/${configProjectId.value}/connectors/${connector.key}`, {
        connection_id: connector.connectionId,
        secret: connector.secret || null,
      })
      const saved = response.data.data
      connector.connectionId = saved.connection_id
      connector.configured = saved.configured
      connector.hasSecret = saved.has_secret
      connector.updatedAt = saved.updated_at ? new Date(saved.updated_at).toLocaleString('zh-CN', { hour12: false }) : ''
      connector.secret = ''
      message.success(`${connector.label}连接信息已保存到项目。`)
    } catch (error: any) {
      message.error(error.response?.data?.detail || '项目连接配置保存失败。')
    } finally {
      projectConnectorSaving.value = false
    }
  }

  async function testProjectConnector() {
    if (projectConnectorBusy.value) return
    const connector = activeProjectConnector.value
    if (connector?.key !== 'wecom' || !connector.configured || !configProjectId.value) return
    projectConnectorTesting.value = true
    try {
      await api.post(`/projects/${configProjectId.value}/connectors/wecom/test`)
      message.success('测试消息已发送，请到项目群中确认。')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '企业微信测试消息发送失败。')
    } finally {
      projectConnectorTesting.value = false
    }
  }

  async function clearProjectConnector() {
    if (projectConnectorBusy.value) return
    const connector = activeProjectConnector.value
    if (!connector || !connector.configured || !configProjectId.value) return
    projectConnectorClearing.value = true
    try {
      await api.delete(`/projects/${configProjectId.value}/connectors/${connector.key}`)
      connector.connectionId = ''
      connector.secret = ''
      connector.configured = false
      connector.hasSecret = false
      connector.updatedAt = ''
      message.success(`${connector.label}连接配置已清除。`)
    } catch (error: any) {
      message.error(error.response?.data?.detail || '项目连接配置清除失败。')
    } finally {
      projectConnectorClearing.value = false
    }
  }

  return {
    projectBaseInfoForm,
    projectBaseInfoCompletedCount,
    projectConnectorLoading,
    projectConnectorSaving,
    projectConnectorTesting,
    projectConnectorClearing,
    activeProjectConnectorKey,
    projectConnectors,
    activeProjectConnector,
    projectConnectorBusy,
    syncProjectBaseInfo,
    saveProjectBaseInfo,
    loadProjectConnectorSettings,
    saveProjectConnector,
    testProjectConnector,
    clearProjectConnector,
  }
}
