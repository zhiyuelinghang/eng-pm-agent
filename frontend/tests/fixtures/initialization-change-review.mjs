import { createApp, defineComponent, h, ref } from 'vue'
import Review from '../../src/components/initialization/InitializationChangeReview.vue'
import api from '../../src/api/client'
import globalStyles from '../../src/styles/global.css?raw'

// Use the real design tokens without making the global stylesheet's font request.
const style = document.createElement('style')
style.textContent = globalStyles.replace(/^@import[^\r\n]*[\r\n]*/gm, '') + `
  .fixture-shell { padding:32px; font-family:'Microsoft YaHei',sans-serif; }
  .fixture-shell h1 { font-size:24px; margin:0 0 12px; }
  .fixture-shell p { margin:8px 0; font-size:14px; }
  .fixture-shell label { display:flex; align-items:center; gap:10px; margin:22px 0; }
  .fixture-shell select, .fixture-shell button { padding:10px 16px; border:1px solid var(--border-emphasis); border-radius:6px; background:white; font-size:14px; }
  .fixture-shell button { cursor:pointer; color:var(--color-accent); }
`
document.head.append(style)
const scenario = new URLSearchParams(location.search).get('scenario') || 'mixed'
const applied = new Set(['quality:61'])
const snapshots = new Map()
let nextPreview = 0
let previewAttempts = 0
let applyAttempts = 0
const longDescription = '本工程包含地下综合管廊、雨污水分流改造与道路恢复工程。新资料补充了穿越既有轨道交通区段的施工组织要求：在施工前完成管线探测与监测点布设，围护结构分段验收后进入土方开挖，严格控制地下水位和周边建筑沉降。涉及居民出行的路段采用半幅施工，阶段验收后恢复通行。各专业负责人应及时同步进度与现场条件变化，保留旁站及质量检查记录。'
const record = (key, section, title, operation, before, after, target_id = null, candidates = []) => ({
  key, record_id: Number(key.split(':').at(-1)) || 1, section, title, operation, target_id, before, after, candidates,
  fields: Object.keys(after).filter(name => JSON.stringify(before?.[name]) !== JSON.stringify(after[name])).map(name => ({ name, before: before?.[name] ?? null, after: after[name] })), selected: false,
})
const base = [
  record('project:engineering_type_description', 'project', '工程概况', 'update', { engineering_type_description: '道路改造与地下管线工程，计划分段施工。' }, { engineering_type_description: longDescription }, 7),
  record('project:contract_duration_days', 'project', '合同工期', 'update', { contract_duration_days: 365 }, { contract_duration_days: 420 }, 7),
  record('personnel:21', 'personnel', '陈雨 · 项目经理', 'add', null, { real_name: '陈雨', identity_card_no: '测试证件 001', position_name: '项目经理', certificate_no: '测试注册证书 A023', responsibility_description: '组织项目施工与资源协调，审核关键节点计划，督促质量与安全问题闭环。' }),
  record('personnel:22', 'personnel', '周启明 · 安全员', 'update', { real_name: '周启明', position_name: '安全员', responsibility_description: '现场日常安全检查', certificate_no: '测试安全证 B031' }, { real_name: '周启明', position_name: '安全员', responsibility_description: '负责深基坑、吊装与夜间作业专项检查；复查隐患整改，形成每日检查记录。', certificate_no: '测试安全证 B031' }, 12),
  record('wbs:31', 'wbs', 'A.1.2 基坑围护与冠梁施工', 'update', { wbs_code: 'A.1.2', name: '基坑围护与冠梁施工', planned_start_at: '2026-09-20', planned_finish_at: '2026-10-15', duration_hours: 208, progress_percent: 0, parent_wbs_code: 'A.1', predecessor_wbs_codes: ['A.1.1'] }, { wbs_code: 'A.1.2', name: '基坑围护与冠梁施工', planned_start_at: '2026-09-23', planned_finish_at: '2026-10-20', duration_hours: 224, progress_percent: 0, parent_wbs_code: 'A.1', predecessor_wbs_codes: ['A.1.1'] }, 23),
  record('wbs:32', 'wbs', 'A.1.3 土方开挖与支撑安装', 'add', null, { wbs_code: 'A.1.3', name: '土方开挖与支撑安装', parent_wbs_code: 'A.1', predecessor_wbs_codes: ['A.1.2'], planned_start_at: '2026-10-21', planned_finish_at: '2026-11-12', priority_text: '高', item_type: '任务' }),
  record('risk:41', 'risks', '东侧深基坑临边作业', 'conflict', null, { risk_part: '东侧深基坑', related_process_name: '土方开挖与支撑安装', risk_level: '较大风险', evaluation_condition: '开挖深度超过 5 米且邻近既有道路，需要专项监测与分层验收。', summary: '每日巡查支撑节点与排水设施，降雨后复查临边防护。' }, null, [{ id: 41, title: '东侧基坑临边防护（较大风险）' }, { id: 42, title: '东侧基坑降水与位移监测（一般风险）' }]),
  record('risk:42', 'risks', '起重吊装区域', 'unchanged', { risk_part: '起重吊装区域', risk_level: '较大风险', related_process_name: '钢支撑吊装' }, { risk_part: '起重吊装区域', risk_level: '较大风险', related_process_name: '钢支撑吊装' }, 43),
  record('quality:61', 'quality_requirements', '混凝土强度验收', 'applied', null, { wbs_code: 'A.1.2', quality_acceptance_item: '混凝土强度', control_indicator: '达到设计强度要求', inspection_frequency: '每浇筑批次', related_documents: '混凝土试块报告、浇筑记录' }, 61),
  record('quality:62', 'quality_requirements', '支撑安装节点验收', 'add', null, { wbs_code: 'A.1.3', quality_acceptance_item: '支撑节点连接质量', control_indicator: '连接节点按设计要求紧固，焊缝质量符合专项方案，轴力施加记录完整。', inspection_frequency: '逐个节点检查', related_documents: '支撑施工记录、焊缝检测报告、预加轴力记录' }),
]
const envelope = (config, data) => ({ status: 200, statusText: 'OK', headers: {}, config, data: { success: true, data, message: '' } })
const apiFailure = (status, message) => ({ isAxiosError: true, response: { status, data: { detail: { message } } }, message })
api.defaults.adapter = async config => {
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  if (config.url?.endsWith('/change-preview')) {
    previewAttempts++
    await new Promise(resolve => setTimeout(resolve, scenario === 'slow' ? 5000 : 300))
    if (scenario === 'preview-error' && previewAttempts === 1) throw apiFailure(503, '项目资料读取暂时失败，请重新获取差异。')
    let changes = scenario === 'empty' ? [] : structuredClone(base)
    for (const change of changes) {
      if (applied.has(change.key)) change.operation = 'applied'
      else if (change.operation === 'conflict' && Object.hasOwn(body.resolutions || {}, change.key)) {
        const target = body.resolutions[change.key]
        change.target_id = target
        change.operation = target === null ? 'add' : 'update'
        change.before = target === null ? null : { risk_part: '东侧基坑', related_process_name: '土方开挖', risk_level: '一般风险', evaluation_condition: '深基坑作业' }
        change.fields = Object.keys(change.after).filter(name => change.before?.[name] !== change.after[name]).map(name => ({ name, before: change.before?.[name] ?? null, after: change.after[name] }))
      }
    }
    const selectedKeys = (body.selected_keys ?? changes.filter(change => ['add', 'update'].includes(change.operation)).map(change => change.key))
      .filter(key => changes.some(change => change.key === key && ['add', 'update', 'conflict'].includes(change.operation)))
    changes.forEach(change => { change.selected = selectedKeys.includes(change.key) })
    const issues = []
    if (selectedKeys.includes('project:contract_duration_days')) issues.push({ level: 'warning', section: 'project', change_key: 'project:contract_duration_days', field_name: 'contract_duration_days', title: '工期延长需要核对', message: '本次资料中的合同工期由 365 天调整为 420 天。', suggestion: '请核对批准的工期变更文件后继续。' })
    for (const change of changes.filter(item => item.selected && item.operation === 'conflict')) issues.push({ level: 'error', section: change.section, change_key: change.key, title: '存在多个相似记录', message: '请确认这条资料对应的项目记录，或将其明确作为新记录添加。' })
    if (scenario === 'validation-error' && selectedKeys.includes('wbs:32')) issues.push({ level: 'error', section: 'wbs', change_key: 'wbs:32', title: '缺少上级工序', message: '此项引用的上级工序暂时不存在。', suggestion: '可以先取消此项选择，提交已核对的其他内容。' })
    const result = { preview_id: `fixture-${++nextPreview}`, draft_id: 1, draft_revision: 1, baseline_hash: 'fixture-only', changes, selected_keys: selectedKeys, issues, can_apply: selectedKeys.length > 0 && !issues.some(issue => issue.level === 'error'), required_personnel_credentials: selectedKeys.includes('personnel:21') ? [{ identity_card_no: '测试证件 001', real_name: '陈雨', position_name: '项目经理', suggested_username: 'chenyu' }] : [], validation: { status: 'completed', package_version: '1.0.0' }, summary: Object.fromEntries(['add', 'update', 'unchanged', 'conflict', 'applied'].map(operation => [operation, changes.filter(change => change.operation === operation).length])) }
    result.summary.selected = selectedKeys.length
    snapshots.set(result.preview_id, selectedKeys)
    return envelope(config, result)
  }
  if (config.url?.endsWith('/apply-changes')) {
    await new Promise(resolve => setTimeout(resolve, 600))
    applyAttempts++
    if (scenario === 'stale' && applyAttempts === 1) throw apiFailure(409, '项目数据已更新')
    const selected = snapshots.get(body.preview_id) || []
    selected.forEach(key => applied.add(key))
    return envelope(config, { result: { status: 'partially_applied', counts: { selected: selected.length } } })
  }
  throw new Error(`独立测试页禁止访问未模拟的接口：${config.url}`)
}

createApp(defineComponent({
  setup() {
    const open = ref(true)
    const count = ref(0)
    const scenarios = { mixed: '完整差异与长文本', empty: '空草稿', 'preview-error': '首次读取失败，可重试', 'validation-error': '单条核验错误', stale: '首次提交数据失效', readonly: '只读权限', slow: '较慢预览加载' }
    return () => h('main', { class: 'fixture-shell' }, [
      h('h1', '项目资料核对 · 独立交互测试'),
      h('p', '本页只操作内存测试数据，不登录、不访问真实后端、不修改业务数据。'),
      h('label', ['场景', h('select', { value: scenario, onChange: event => { location.search = `?scenario=${event.target.value}` } }, Object.entries(scenarios).map(([value, label]) => h('option', { value }, label)))]),
      h('button', { onClick: () => { open.value = true } }, '打开资料核对'),
      h('p', `已完成 ${count.value} 次模拟提交。关闭弹窗后可切换场景，或刷新页面重置。`),
      h(Review, { open: open.value, draft: { id: 1, revision: 1, status: 'collecting' }, projectId: '7', name: '城市更新综合管廊工程 · 一标段', admin: scenario !== 'readonly', onClose: () => { open.value = false }, onApplied: () => { count.value++ } }),
    ])
  },
})).mount('#app')
