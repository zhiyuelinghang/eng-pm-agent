import type {
  Project, Member, WbsItem, RiskSource, WbsRiskLink,
  Task, DailyReport, RiskDraft, FillPackage, RemindRule, DirConfig, OperationLog
} from '@/types'

export const mockProjects: Project[] = [
  {
    id: 'p1', name: '合流污水一期复线工程（总管部分）', ownerUnit: '上海市排水公司', status: 'active',
    description: '城市排水系统复线改造，全长 3.8km，含顶管、明挖、接收井等工序。', createdAt: '2026-05-01',
  },
  {
    id: 'p2', name: '苏州河沿线排水系统提标改造工程', ownerUnit: '上海城投水务集团', status: 'active',
    description: '沿线泵站、截流井及管网提标改造，覆盖 5 个施工片区。', createdAt: '2026-04-10',
  },
  {
    id: 'p3', name: '浦东新区雨污混接整治三期工程', ownerUnit: '浦东新区生态环境局', status: 'inactive',
    description: '居民区和市政道路雨污混接排查整治，当前处于进场筹备与方案报审阶段。', createdAt: '2026-06-01',
  },
]

export const mockMembers: Member[] = [
  { id: 'm1', name: '张伟', title: '项目负责人', phone: '138-0001-0001', email: 'zhangwei@corp.com', role: ['项目负责人', '重大风险确认'], projectId: 'p1' },
  { id: 'm2', name: '李明', title: '项目执行人', phone: '138-0001-0002', email: 'liming@corp.com', role: ['项目执行人', '顶管施工', '现场巡查'], projectId: 'p1' },
  { id: 'm3', name: '王芳', title: '资料与填报负责人', phone: '138-0001-0003', email: 'wangfang@corp.com', role: ['资料员', '日报整理', '草稿审核', '平台填报'], projectId: 'p1' },
  { id: 'm4', name: '陈刚', title: '实施管理员', phone: '138-0001-0004', email: 'chengang@corp.com', role: ['系统管理员', 'WBS导入', '风险源配置'], projectId: 'p1' },
  { id: 'm21', name: '赵晨', title: '项目经理', phone: '138-0002-0001', email: 'zhaochen@corp.com', role: ['项目负责人', '泵站改造', '重大风险确认'], projectId: 'p2' },
  { id: 'm22', name: '孙磊', title: '现场负责人', phone: '138-0002-0002', email: 'sunlei@corp.com', role: ['现场巡查', '截流井施工', '临水临电'], projectId: 'p2' },
  { id: 'm23', name: '周颖', title: '资料负责人', phone: '138-0002-0003', email: 'zhouying@corp.com', role: ['资料员', '日报整理', '方案报审'], projectId: 'p2' },
  { id: 'm24', name: '马强', title: '安全主管', phone: '138-0002-0004', email: 'maqiang@corp.com', role: ['安全员', '交通导改', '有限空间'], projectId: 'p2' },
  { id: 'm31', name: '沈洁', title: '项目经理', phone: '138-0003-0001', email: 'shenj@corp.com', role: ['项目负责人', '方案审批', '外部协调'], projectId: 'p3' },
  { id: 'm32', name: '胡斌', title: '排查负责人', phone: '138-0003-0002', email: 'hubin@corp.com', role: ['管线排查', 'CCTV检测', '现场巡查'], projectId: 'p3' },
  { id: 'm33', name: '顾娜', title: '资料与填报负责人', phone: '138-0003-0003', email: 'guna@corp.com', role: ['资料员', '台账维护', '平台填报'], projectId: 'p3' },
]

export const mockWbs: WbsItem[] = [
  { id: 'w1', code: '1', name: '合流污水复线工程', level: 1, parentId: null, planStart: '2026-05-01', planEnd: '2026-12-31', progress: 28, status: 'in_progress', responsibleId: 'm1', projectId: 'p1' },
  { id: 'w2', code: '1.1', name: '施工准备', level: 2, parentId: 'w1', planStart: '2026-05-01', planEnd: '2026-05-15', actualStart: '2026-05-01', progress: 100, status: 'done', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w3', code: '1.2', name: '顶管始发井施工', level: 2, parentId: 'w1', planStart: '2026-05-16', planEnd: '2026-06-15', actualStart: '2026-05-18', progress: 65, status: 'in_progress', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w4', code: '1.2.1', name: '围护桩施工', level: 3, parentId: 'w3', planStart: '2026-05-16', planEnd: '2026-05-30', actualStart: '2026-05-18', progress: 100, status: 'done', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w5', code: '1.2.2', name: '基坑开挖', level: 3, parentId: 'w3', planStart: '2026-05-31', planEnd: '2026-06-10', actualStart: '2026-06-01', progress: 80, status: 'in_progress', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w6', code: '1.2.3', name: '底板及井壁施工', level: 3, parentId: 'w3', planStart: '2026-06-11', planEnd: '2026-06-20', progress: 0, status: 'not_started', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w7', code: '1.3', name: '顶管施工', level: 2, parentId: 'w1', planStart: '2026-06-21', planEnd: '2026-09-30', progress: 0, status: 'not_started', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w8', code: '1.3.1', name: '顶管机下井调试', level: 3, parentId: 'w7', planStart: '2026-06-21', planEnd: '2026-06-25', progress: 0, status: 'not_started', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w9', code: '1.3.2', name: 'DN2200 顶管推进（K0+000—K0+400）', level: 3, parentId: 'w7', planStart: '2026-06-26', planEnd: '2026-08-15', progress: 0, status: 'not_started', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w10', code: '1.4', name: '接收井及明挖段施工', level: 2, parentId: 'w1', planStart: '2026-09-01', planEnd: '2026-11-30', progress: 0, status: 'not_started', responsibleId: 'm2', projectId: 'p1' },
  { id: 'w21', code: '1', name: '苏州河排水系统提标改造', level: 1, parentId: null, planStart: '2026-04-15', planEnd: '2027-03-20', progress: 18, status: 'in_progress', responsibleId: 'm21', projectId: 'p2' },
  { id: 'w22', code: '1.1', name: '泵站临排系统搭设', level: 2, parentId: 'w21', planStart: '2026-04-15', planEnd: '2026-05-20', actualStart: '2026-04-18', progress: 100, status: 'done', responsibleId: 'm22', projectId: 'p2' },
  { id: 'w23', code: '1.2', name: '截流井改造施工', level: 2, parentId: 'w21', planStart: '2026-05-21', planEnd: '2026-08-30', actualStart: '2026-05-25', progress: 42, status: 'in_progress', responsibleId: 'm22', projectId: 'p2' },
  { id: 'w24', code: '1.2.1', name: '有限空间清淤与检测', level: 3, parentId: 'w23', planStart: '2026-06-01', planEnd: '2026-06-30', progress: 55, status: 'in_progress', responsibleId: 'm24', projectId: 'p2' },
  { id: 'w25', code: '1.3', name: '沿线交通导改及围挡', level: 2, parentId: 'w21', planStart: '2026-06-10', planEnd: '2026-07-15', progress: 30, status: 'in_progress', responsibleId: 'm24', projectId: 'p2' },
  { id: 'w26', code: '1.4', name: '泵站设备更新与联调', level: 2, parentId: 'w21', planStart: '2026-09-01', planEnd: '2026-12-20', progress: 0, status: 'not_started', responsibleId: 'm22', projectId: 'p2' },
  { id: 'w31', code: '1', name: '浦东雨污混接整治三期', level: 1, parentId: null, planStart: '2026-07-01', planEnd: '2027-01-31', progress: 6, status: 'not_started', responsibleId: 'm31', projectId: 'p3' },
  { id: 'w32', code: '1.1', name: '排查准备与片区划分', level: 2, parentId: 'w31', planStart: '2026-07-01', planEnd: '2026-07-20', progress: 30, status: 'in_progress', responsibleId: 'm31', projectId: 'p3' },
  { id: 'w33', code: '1.2', name: '小区管网 CCTV 检测', level: 2, parentId: 'w31', planStart: '2026-07-21', planEnd: '2026-09-30', progress: 0, status: 'not_started', responsibleId: 'm32', projectId: 'p3' },
  { id: 'w34', code: '1.3', name: '道路开挖及管线接驳', level: 2, parentId: 'w31', planStart: '2026-09-15', planEnd: '2026-11-30', progress: 0, status: 'not_started', responsibleId: 'm32', projectId: 'p3' },
  { id: 'w35', code: '1.4', name: '整治验收与台账闭环', level: 2, parentId: 'w31', planStart: '2026-12-01', planEnd: '2027-01-31', progress: 0, status: 'not_started', responsibleId: 'm33', projectId: 'p3' },
]

export const mockRisks: RiskSource[] = [
  { id: 'r1', name: '深基坑坍塌风险', level: 'critical', type: '安全风险', controlStart: '2026-05-31', controlEnd: '2026-06-20', responsibleId: 'm2', confirmatorId: 'm1', materials: ['基坑监测日报', '围护桩检测报告', '变形监测数据', '应急预案审批件'], controlMeasures: '每日监测围护桩位移，超警戒值立即暂停并上报；设置应急响应预案。', projectId: 'p1' },
  { id: 'r2', name: '顶管机掘进偏差风险', level: 'high', type: '质量风险', controlStart: '2026-06-26', controlEnd: '2026-08-15', responsibleId: 'm2', confirmatorId: 'm3', materials: ['顶管推进记录表', '轴线测量报告', '纠偏记录'], controlMeasures: '每推进 5 环记录轴线偏差，偏差超 30mm 立即纠偏。', projectId: 'p1' },
  { id: 'r3', name: '施工降水导致地面沉降风险', level: 'high', type: '环境风险', controlStart: '2026-05-31', controlEnd: '2026-07-10', responsibleId: 'm2', confirmatorId: 'm1', materials: ['地表沉降监测报告', '周边建筑物监测报告', '降水井水位记录'], controlMeasures: '每天监测地表沉降，周边建筑物累计沉降超 20mm 立即启动应急预案。', projectId: 'p1' },
  { id: 'r4', name: '混凝土结构裂缝风险', level: 'medium', type: '质量风险', controlStart: '2026-06-11', controlEnd: '2026-07-09', responsibleId: 'm2', confirmatorId: 'm3', materials: ['混凝土配合比报告', '养护记录', '裂缝检查记录'], controlMeasures: '严格控制水灰比，浇筑后持续养护，发现裂缝及时处理并上报。', projectId: 'p1' },
  { id: 'r21', name: '泵站临排能力不足风险', level: 'critical', type: '运行风险', controlStart: '2026-04-15', controlEnd: '2026-05-20', responsibleId: 'm22', confirmatorId: 'm21', materials: ['临排流量测试记录', '泵组试运行报告', '应急抽排方案'], controlMeasures: '临排系统每日试运行，暴雨预警期间安排备用泵组和应急发电。', projectId: 'p2' },
  { id: 'r22', name: '有限空间作业中毒窒息风险', level: 'critical', type: '安全风险', controlStart: '2026-06-01', controlEnd: '2026-06-30', responsibleId: 'm24', confirmatorId: 'm21', materials: ['有限空间审批单', '气体检测记录', '通风记录', '监护人签到表'], controlMeasures: '先通风后检测再作业，作业全过程设置专人监护和救援装备。', projectId: 'p2' },
  { id: 'r23', name: '交通导改占路投诉风险', level: 'medium', type: '协调风险', controlStart: '2026-06-10', controlEnd: '2026-07-15', responsibleId: 'm24', confirmatorId: 'm23', materials: ['交通导改审批', '围挡布置照片', '告示张贴记录'], controlMeasures: '分段围挡，提前公示绕行路线，夜间施工控制噪声。', projectId: 'p2' },
  { id: 'r31', name: '地下管线误碰风险', level: 'high', type: '安全风险', controlStart: '2026-09-15', controlEnd: '2026-11-30', responsibleId: 'm32', confirmatorId: 'm31', materials: ['管线交底记录', '探挖确认单', '产权单位确认意见'], controlMeasures: '开挖前完成物探与人工探挖，重点管线旁站确认后施工。', projectId: 'p3' },
  { id: 'r32', name: '居民区施工扰民风险', level: 'medium', type: '协调风险', controlStart: '2026-07-21', controlEnd: '2026-11-30', responsibleId: 'm33', confirmatorId: 'm31', materials: ['居民告知单', '投诉处理台账', '夜间施工审批'], controlMeasures: '敏感时段降低噪声，建立居民沟通群并闭环处理投诉。', projectId: 'p3' },
]

export const mockLinks: WbsRiskLink[] = [
  { id: 'l1', wbsId: 'w5', riskId: 'r1', alertDays: 7, notifyMethods: ['系统通知', '邮件'], basis: '深基坑安全管控规范 § 4.2', responsibleId: 'm2' },
  { id: 'l2', wbsId: 'w5', riskId: 'r3', alertDays: 3, notifyMethods: ['系统通知'], basis: '降水影响评估报告', responsibleId: 'm2' },
  { id: 'l3', wbsId: 'w9', riskId: 'r2', alertDays: 14, notifyMethods: ['系统通知', '邮件', '短信'], basis: '顶管施工方案', responsibleId: 'm2' },
  { id: 'l21', wbsId: 'w22', riskId: 'r21', alertDays: 5, notifyMethods: ['系统通知', '短信'], basis: '泵站临排专项方案', responsibleId: 'm22' },
  { id: 'l22', wbsId: 'w24', riskId: 'r22', alertDays: 3, notifyMethods: ['系统通知', '短信', '电话'], basis: '有限空间作业管理办法', responsibleId: 'm24' },
  { id: 'l23', wbsId: 'w25', riskId: 'r23', alertDays: 2, notifyMethods: ['系统通知'], basis: '交通导改审批意见', responsibleId: 'm24' },
  { id: 'l31', wbsId: 'w34', riskId: 'r31', alertDays: 7, notifyMethods: ['系统通知', '短信'], basis: '地下管线保护方案', responsibleId: 'm32' },
  { id: 'l32', wbsId: 'w33', riskId: 'r32', alertDays: 3, notifyMethods: ['系统通知'], basis: '居民区文明施工方案', responsibleId: 'm33' },
]

export const mockTasks: Task[] = [
  { id: 't1', title: '深基坑坍塌风险预警 — 基坑开挖阶段', type: 'risk_alert', riskLevel: 'critical', projectId: 'p1', linkedWbsIds: ['w5'], linkedRiskId: 'r1', responsibleId: 'm2', confirmatorId: 'm1', deadline: '2026-06-12', status: 'processing', missingCount: 2, triggerReason: 'WBS 工序「基坑开挖」计划于 2026-06-01 开始，距当前日期触发提前 7 天提醒规则', createdAt: '2026-06-03' },
  { id: 't2', title: '地面沉降监测材料缺项', type: 'material_missing', riskLevel: 'high', projectId: 'p1', linkedWbsIds: ['w5'], linkedRiskId: 'r3', responsibleId: 'm2', confirmatorId: 'm1', deadline: '2026-06-10', status: 'overdue', missingCount: 1, triggerReason: '风险上报草稿生成时检测到「地表沉降监测报告」缺失', createdAt: '2026-06-05' },
  { id: 't3', title: '日报解析确认 — 2026-06-09 施工日报', type: 'daily_confirm', riskLevel: 'low', projectId: 'p1', linkedWbsIds: [], responsibleId: 'm3', confirmatorId: 'm3', deadline: '2026-06-10', status: 'pending', missingCount: 0, triggerReason: '微信群日报目录发现新文件「2026-06-09日报.docx」，解析完成待人工确认', createdAt: '2026-06-10' },
  { id: 't4', title: '风险草稿审核 — 深基坑风险进展上报', type: 'draft_review', riskLevel: 'critical', projectId: 'p1', linkedWbsIds: [], linkedRiskId: 'r1', responsibleId: 'm3', confirmatorId: 'm1', deadline: '2026-06-11', status: 'waiting_confirm', missingCount: 0, triggerReason: '深基坑风险进展草稿已准备，需资料负责人审核确认后生成填报包', createdAt: '2026-06-09' },
  { id: 't5', title: '顶管推进偏差风险预警 — 提前 14 天准备材料', type: 'risk_alert', riskLevel: 'high', projectId: 'p1', linkedWbsIds: ['w9'], linkedRiskId: 'r2', responsibleId: 'm2', confirmatorId: 'm3', deadline: '2026-06-23', status: 'pending', missingCount: 3, triggerReason: 'WBS 工序「DN2200 顶管推进」计划于 2026-06-26 开始，触发 14 天提前预警', createdAt: '2026-06-10' },
  { id: 't6', title: '平台填报 — 深基坑风险进展上报（股份平台）', type: 'fill_platform', riskLevel: 'critical', projectId: 'p1', linkedWbsIds: [], linkedRiskId: 'r1', responsibleId: 'm3', confirmatorId: 'm3', deadline: '2026-06-12', status: 'pending', missingCount: 0, triggerReason: '草稿已确认，填报包已生成，等待启动网页填报助手', createdAt: '2026-06-09' },
]

export const mockDailyReports: DailyReport[] = [
  { id: 'dr1', fileName: '2026-06-09日报.docx', fileType: 'Word', date: '2026-06-09', constructionContent: '继续进行始发井基坑土方开挖，今日开挖深度 3.2m，累计开挖深度 8.6m（计划总深度 10.8m）。完成第三道钢支撑安装。', currentProgress: 80, cumulativeProgress: 65, problems: '局部位置渗水，已安排排水泵持续抽排；钢支撑端头混凝土强度不足，需补强处理。', tomorrowPlan: '继续土方开挖至设计标高，同步进行渗水处理，完成第四道支撑安装准备工作。', riskContent: '基坑监测数据：围护桩顶位移累计 18mm，距警戒值 30mm 仍有余量；地表沉降监测点 S-03 累计沉降 12mm。', monitorContent: '2026-06-09 监测：桩顶位移最大值 18mm，地表沉降 S-03 点 12mm，整体处于安全范围。', matchedWbsId: 'w5', confidence: 0.92, parseStatus: 'done', status: 'pending_confirm', projectId: 'p1', createdAt: '2026-06-10T07:30:00' },
  { id: 'dr2', fileName: '2026-06-08日报.docx', fileType: 'Word', date: '2026-06-08', constructionContent: '始发井基坑土方开挖，今日完成第 5~6 层土方开挖，深度约 1.5m。', currentProgress: 60, cumulativeProgress: 58, problems: '降雨影响，下午停工半天。', tomorrowPlan: '继续土方开挖，安装第三道钢支撑。', riskContent: '监测数据正常，桩顶位移最大值 15mm。', monitorContent: '2026-06-08 监测：桩顶位移最大值 15mm，处于安全范围。', matchedWbsId: 'w5', confidence: 0.89, parseStatus: 'done', status: 'confirmed', projectId: 'p1', createdAt: '2026-06-09T08:00:00' },
]

export const mockDrafts: RiskDraft[] = [
  {
    id: 'rd1', title: '深基坑坍塌风险进展上报草稿（2026-06-09）', riskId: 'r1', riskLevel: 'critical', projectId: 'p1',
    content: `一、风险概况\n本风险源：深基坑坍塌风险，风险等级：重大。关联工序：始发井基坑开挖（计划 2026-05-31 至 2026-06-10）。\n\n二、当前进展\n截至 2026-06-09，基坑开挖累计深度 8.6m，完成率约 80%。已完成三道钢支撑安装，第四道支撑正在准备中。\n\n三、监测情况\n围护桩顶位移累计最大值 18mm（警戒值 30mm），地表沉降监测点 S-03 累计 12mm，整体处于安全可控范围。`,
    hazardType: '深基坑坍塌',
    deadline: '2026-06-12',
    measures: '每日开展基坑监测，局部渗水持续抽排，钢支撑端头补强处理已完成 2 处。完成基坑开挖后立即浇筑底板混凝土，同步持续监测至底板达设计强度。',
    responsibleId: 'm2',
    missingItems: ['地表沉降监测报告（本周）', '渗水处理记录附图'],
    sourceRefs: ['2026-06-09日报.docx', '基坑监测数据表-0609.xlsx', 'WBS工序：始发井基坑开挖'],
    attachments: [
      { name: '基坑监测数据表-0609.xlsx', ready: true },
      { name: '现场照片-0609-001.jpg', ready: true },
      { name: '现场照片-0609-002.jpg', ready: true },
      { name: '地表沉降监测报告（本周）.pdf', ready: false },
      { name: '渗水处理记录附图.jpg', ready: false },
    ],
    status: 'reviewing', createdAt: '2026-06-09T18:00:00', updatedAt: '2026-06-09T18:00:00',
  },
]

export const mockFillPackages: FillPackage[] = [
  {
    id: 'fp1', draftId: 'rd1', platformName: '股份安全管理平台', processName: '重大风险动态管控月报',
    status: 'pending', deadline: '2026-06-12',
    fields: [
      { name: '项目名称', value: '合流污水一期复线工程（总管部分）总管标', required: true },
      { name: '风险源名称', value: '深基坑坍塌风险', required: true },
      { name: '风险等级', value: '重大风险', required: true },
      { name: '管控状态', value: '管控中', required: true },
      { name: '当前进展描述', value: '基坑开挖累计 8.6m，完成约 80%', required: true },
      { name: '监测数据摘要', value: '桩顶位移 18mm，地表沉降 12mm，处于安全范围', required: true },
      { name: '上报日期', value: '2026-06-09', required: true },
      { name: '上报人', value: '', placeholder: '请填写上报人姓名', required: true },
    ],
    attachments: [
      { name: '基坑监测数据表-0609.xlsx', ready: true },
      { name: '现场照片-0609-001.jpg', ready: true },
      { name: '现场照片-0609-002.jpg', ready: true },
    ],
    projectId: 'p1', createdAt: '2026-06-09T20:00:00',
  },
]

export const mockRemindRules: RemindRule[] = [
  { id: 'rule1', level: 'critical', days: 14, enabled: true, frequency: '每日' },
  { id: 'rule2', level: 'high', days: 7, enabled: true, frequency: '每日' },
  { id: 'rule3', level: 'medium', days: 3, enabled: true, frequency: '每日' },
  { id: 'rule4', level: 'low', days: 1, enabled: true, frequency: '每日' },
]

export const mockRemindRulesByProject: Record<string, RemindRule[]> = {
  p1: mockRemindRules,
  p2: [
    { id: 'rule-p2-1', level: 'critical', days: 10, enabled: true, frequency: '每日' },
    { id: 'rule-p2-2', level: 'high', days: 6, enabled: true, frequency: '每日' },
    { id: 'rule-p2-3', level: 'medium', days: 2, enabled: true, frequency: '工作日' },
    { id: 'rule-p2-4', level: 'low', days: 1, enabled: false, frequency: '工作日' },
  ],
  p3: [
    { id: 'rule-p3-1', level: 'critical', days: 12, enabled: true, frequency: '每日' },
    { id: 'rule-p3-2', level: 'high', days: 5, enabled: true, frequency: '每日' },
    { id: 'rule-p3-3', level: 'medium', days: 2, enabled: true, frequency: '工作日' },
    { id: 'rule-p3-4', level: 'low', days: 1, enabled: true, frequency: '工作日' },
  ],
}

export const mockDirConfig: DirConfig = {
  mainDir: '/data/wechat/incoming',
  archiveDir: '/data/wechat/archive',
  tempDir: '/data/wechat/processing',
  failedDir: '/data/wechat/failed',
  backupDir: '/data/wechat/processed',
  scanInterval: 5,
  enabled: true,
}

export const mockDirConfigsByProject: Record<string, DirConfig> = {
  p1: mockDirConfig,
  p2: {
    mainDir: '/data/projects/suzhou-river/daily/incoming',
    archiveDir: '/data/projects/suzhou-river/daily/archive',
    tempDir: '/data/projects/suzhou-river/daily/processing',
    failedDir: '/data/projects/suzhou-river/daily/failed',
    backupDir: '/data/projects/suzhou-river/daily/backup',
    scanInterval: 10,
    enabled: true,
  },
  p3: {
    mainDir: '/data/projects/pudong-mixconnect/daily/incoming',
    archiveDir: '/data/projects/pudong-mixconnect/daily/archive',
    tempDir: '/data/projects/pudong-mixconnect/daily/processing',
    failedDir: '/data/projects/pudong-mixconnect/daily/failed',
    backupDir: '/data/projects/pudong-mixconnect/daily/backup',
    scanInterval: 30,
    enabled: false,
  },
}

export const mockLogs: OperationLog[] = [
  { id: 'log1', time: '2026-06-10 07:35', operator: '系统', action: '日报文件扫描', detail: '发现新文件：2026-06-09日报.docx，开始解析', level: 'info' },
  { id: 'log2', time: '2026-06-10 07:36', operator: '系统', action: '日报解析完成', detail: '文件「2026-06-09日报.docx」解析完成，置信度 92%，等待确认', level: 'success' },
  { id: 'log3', time: '2026-06-09 18:05', operator: '系统', action: '草稿生成完成', detail: '深基坑坍塌风险进展上报草稿生成，发现缺项 2 条', level: 'warning' },
  { id: 'log4', time: '2026-06-09 09:00', operator: '陈刚', action: 'WBS 导入', detail: '成功导入 WBS 工序 10 条', level: 'success' },
  { id: 'log5', time: '2026-06-05 14:20', operator: '系统', action: '任务生成', detail: '生成风险预警任务：地面沉降监测材料缺项', level: 'warning' },
  { id: 'log6', time: '2026-06-03 08:00', operator: '系统', action: '任务生成', detail: '生成风险预警任务：深基坑坍塌风险预警', level: 'info' },
]

