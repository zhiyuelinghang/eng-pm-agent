(function () {
  const projects = [
    { id: "zhiru-health", name: "普陀区真如镇街道社区卫生服务中心异地扩建项目", type: "社区医院综合楼", manager: "待配置", stage: "施工阶段", status: "基础资料待完善", aliases: ["真如", "社区卫生服务中心", "异地扩建"], requiredDocs: ["施工合同", "施工组织设计", "总进度计划", "人员名单", "风险清单", "质量指标关联表"] },
  ];

  const projectMembers = [
    { projectId: "pit", name: "王经理", role: "项目经理" },
    { projectId: "pit", name: "赵安全", role: "安全员" },
    { projectId: "pit", name: "刘资料", role: "资料员" },
    { projectId: "pit", name: "陈施工", role: "施工单位" },
    { projectId: "pit", name: "周监理", role: "监理" },
    { projectId: "pit", name: "孙监测", role: "监测单位" },
    { projectId: "building-3", name: "李工", role: "项目经理" },
    { projectId: "building-3", name: "钱质量", role: "质量员" },
    { projectId: "building-3", name: "刘资料", role: "资料员" },
    { projectId: "pipe-network", name: "赵经理", role: "项目经理" },
    { projectId: "pipe-network", name: "陈工", role: "现场负责人" },
    { projectId: "pipe-network", name: "吴安全", role: "安全员" },
  ];

  const records = [
    { id: "wx-001", projectId: "pit", sourceType: "微信群", sourceName: "深基坑施工群", author: "张工", time: "2026-06-18 17:42", status: "待确认", confidence: "中", content: "北侧第一道支撑完成，明天计划开挖至-4.5m，监测点S3今日位移接近预警值。" },
    { id: "daily-001", projectId: "pit", sourceType: "日报", sourceName: "6月18日施工日报", author: "施工单位", time: "2026-06-18 20:00", status: "已入库", confidence: "高", content: "完成冠梁验收、降水井运行正常，夜间安排专人巡查边坡渗水。" },
    { id: "photo-001", projectId: "pit", sourceType: "照片", sourceName: "巡检照片-临边防护.jpg", author: "安全员", time: "2026-06-18 16:10", status: "待复核", confidence: "中", content: "AI识别：基坑西侧临边防护局部缺失，建议生成整改任务。" },
    { id: "platform-001", projectId: "pit", sourceType: "平台导出", sourceName: "基坑监测日报.xlsx", author: "监测平台", time: "2026-06-18 08:30", status: "待复核", confidence: "高", content: "S3测斜位移18mm，距预警阈值20mm较近，需人工核验数据来源。" },
    { id: "meeting-001", projectId: "pit", sourceType: "会议纪要", sourceName: "深基坑专项会纪要", author: "项目部", time: "2026-06-17 16:30", status: "已入库", confidence: "高", content: "会议要求开挖前完成支撑验收、降水记录复核、监测频次确认，安全员负责临边防护复查。" },
    { id: "file-001", projectId: "pit", sourceType: "工程文件", sourceName: "深基坑专项施工方案.pdf", author: "技术部", time: "2026-06-12 09:10", status: "已入库", confidence: "高", content: "方案包含分层开挖、支撑施工、降水监测、边坡防护和应急处置要求。" },
    { id: "wx-002", projectId: "building-3", sourceType: "微信群", sourceName: "3号楼施工群", author: "刘工", time: "2026-06-18 18:05", status: "已入库", confidence: "高", content: "3号楼今日浇筑混凝土120方，试块留置3组，未发现异常。" },
    { id: "meeting-002", projectId: "building-3", sourceType: "会议纪要", sourceName: "3号楼周例会纪要", author: "项目部", time: "2026-06-17 15:00", status: "已入库", confidence: "高", content: "质量员周三前复核钢筋保护层；资料员补齐混凝土浇筑记录。" },
    { id: "wx-003", projectId: "pipe-network", sourceType: "微信群", sourceName: "市政管网更新群", author: "陈工", time: "2026-06-18 19:10", status: "待确认", confidence: "中", content: "完成K0+320至K0+480沟槽开挖，交通导改标识不足，明天上午补设。" },
  ];

  const tasks = [
    { id: "task-001", projectId: "pit", title: "开挖前支撑验收条件核查", owner: "安全员", supervisor: "安全员", previousOwner: "AI", createdBy: "AI", flowType: "条件核查", dueDate: "2026-06-19", status: "待处理", type: "条件核查", sourceIds: ["meeting-001", "file-001"], needsInfo: false, phase: "启动", material: "支撑验收记录", closure: "未闭环", currentStepIndex: 1, steps: [
      { name: "AI发起核查", owner: "AI", dueDate: "2026-06-18", status: "已完成", material: "会议纪要/专项方案" },
      { name: "安全员条件复核", owner: "安全员", dueDate: "2026-06-19", status: "待处理", material: "支撑验收记录、监测频次确认" },
      { name: "项目经理确认", owner: "王经理", dueDate: "2026-06-19", status: "未开始", material: "开挖条件确认意见" },
    ] },
    { id: "task-002", projectId: "pit", title: "复核S3测斜位移接近预警", owner: "监测单位", supervisor: "安全员", previousOwner: "监测平台", createdBy: "AI", flowType: "风险处置", dueDate: "2026-06-18", status: "逾期", type: "风险处置", sourceIds: ["platform-001"], needsInfo: true, phase: "过程", material: "监测日报", closure: "待复核", currentStepIndex: 1, steps: [
      { name: "监测平台触发", owner: "监测平台", dueDate: "2026-06-18", status: "已完成", material: "基坑监测日报.xlsx" },
      { name: "监测单位复核", owner: "监测单位", dueDate: "2026-06-18", status: "逾期", material: "原始监测数据" },
      { name: "安全员监督确认", owner: "安全员", dueDate: "2026-06-19", status: "未开始", material: "复核意见" },
    ] },
    { id: "task-003", projectId: "pit", title: "整改西侧临边防护缺失", owner: "安全员", supervisor: "安全员", previousOwner: "施工单位", createdBy: "AI", flowType: "隐患整改", dueDate: "2026-06-19", status: "待处理", type: "隐患整改", sourceIds: ["photo-001"], needsInfo: true, phase: "复核", material: "整改照片", closure: "未闭环", currentStepIndex: 2, steps: [
      { name: "发现隐患", owner: "安全员", dueDate: "2026-06-18", status: "已完成", material: "巡检照片" },
      { name: "施工单位整改", owner: "施工单位", dueDate: "2026-06-19", status: "已反馈", material: "整改照片" },
      { name: "安全员复核", owner: "安全员", dueDate: "2026-06-19", status: "待处理", material: "复核意见" },
      { name: "闭环归档", owner: "资料员", dueDate: "2026-06-20", status: "未开始", material: "整改闭环清单" },
    ] },
    { id: "task-004", projectId: "pit", title: "补齐降水井运行记录", owner: "资料员", supervisor: "安全员", previousOwner: "AI", createdBy: "AI", flowType: "资料补全", dueDate: "2026-06-20", status: "待处理", type: "资料补全", sourceIds: ["daily-001"], needsInfo: false, phase: "过程", material: "降水记录", closure: "未闭环", currentStepIndex: 1, steps: [
      { name: "AI识别缺失", owner: "AI", dueDate: "2026-06-18", status: "已完成", material: "施工日报" },
      { name: "资料员补齐", owner: "资料员", dueDate: "2026-06-20", status: "进行中", material: "降水井运行记录" },
      { name: "安全员抽查", owner: "安全员", dueDate: "2026-06-20", status: "未开始", material: "抽查意见" },
    ] },
    { id: "task-005", projectId: "building-3", title: "补齐混凝土浇筑记录", owner: "资料员", supervisor: "质量员", previousOwner: "AI", createdBy: "AI", flowType: "资料补全", dueDate: "2026-06-19", status: "已完成", type: "资料补全", sourceIds: ["meeting-002"], needsInfo: false, phase: "归档", material: "浇筑记录", closure: "已闭环", currentStepIndex: 2, steps: [
      { name: "AI识别缺失", owner: "AI", dueDate: "2026-06-17", status: "已完成", material: "周例会纪要" },
      { name: "资料员补齐", owner: "资料员", dueDate: "2026-06-18", status: "已完成", material: "浇筑记录" },
      { name: "质量员复核", owner: "质量员", dueDate: "2026-06-19", status: "已完成", material: "复核意见" },
    ] },
    { id: "task-006", projectId: "pipe-network", title: "补设围挡和警示灯", owner: "施工队", supervisor: "安全员", previousOwner: "陈工", createdBy: "AI", flowType: "隐患整改", dueDate: "2026-06-18", status: "逾期", type: "隐患整改", sourceIds: ["wx-003"], needsInfo: true, phase: "整改", material: "整改照片", closure: "待复核", currentStepIndex: 1, steps: [
      { name: "发现隐患", owner: "陈工", dueDate: "2026-06-18", status: "已完成", material: "微信群消息" },
      { name: "施工队整改", owner: "施工队", dueDate: "2026-06-18", status: "逾期", material: "围挡和警示灯照片" },
      { name: "安全员复核", owner: "安全员", dueDate: "2026-06-19", status: "未开始", material: "复核照片" },
    ] },
    { id: "task-007", projectId: "pit", title: "完成冠梁验收资料归档", owner: "资料员", supervisor: "安全员", previousOwner: "安全员", createdBy: "人工布置", flowType: "资料补全", dueDate: "2026-06-18", status: "已完成", type: "资料补全", sourceIds: ["daily-001"], needsInfo: false, phase: "归档", material: "冠梁验收资料", closure: "已闭环", currentStepIndex: 2, steps: [
      { name: "安全员确认验收", owner: "安全员", dueDate: "2026-06-18", status: "已完成", material: "验收照片" },
      { name: "资料员归档", owner: "资料员", dueDate: "2026-06-18", status: "已完成", material: "冠梁验收资料" },
      { name: "闭环确认", owner: "安全员", dueDate: "2026-06-18", status: "已完成", material: "闭环记录" },
    ] },
  ];

  const docs = [
    { id: "doc-001", projectId: "pit", library: "project", folderId: "p01", name: "深基坑专项施工方案.pdf", type: "专项方案", status: "已归档", version: "V1.2", versionNote: "按专家论证意见补充监测频次", description: "深基坑支护、开挖、降水和应急处置专项方案", versions: ["V1.0 初版", "V1.1 补充降水措施", "V1.2 当前版"], sourceId: "file-001", links: "风险源：深基坑开挖；报告段落：施工条件" },
    { id: "doc-002", projectId: "pit", library: "project", folderId: "p04", name: "基坑监测日报.xlsx", type: "监测报告", status: "已归档", version: "V2.0", versionNote: "6月18日监测数据更新", description: "包含S3测斜位移、沉降观测和地下水位数据", versions: ["V1.0 6月17日", "V2.0 6月18日"], sourceId: "platform-001", links: "风险源：测斜位移；任务：S3复核" },
    { id: "doc-003", projectId: "pit", library: "project", folderId: "p09", name: "临边防护巡检照片.jpg", type: "照片", status: "待复核", version: "V1.0", versionNote: "现场巡检原始照片", description: "AI识别为西侧临边防护局部缺失", versions: ["V1.0 原始照片"], sourceId: "photo-001", links: "事件：临边防护缺失；任务：整改西侧临边" },
    { id: "doc-004", projectId: "pit", library: "project", folderId: "p03", name: "支撑验收记录", type: "验收资料", status: "缺失", version: "-", versionNote: "待施工单位补齐", description: "开挖前支撑验收资料，当前缺失", versions: [], sourceId: "meeting-001", links: "任务：开挖前条件核查" },
    { id: "doc-007", projectId: "pit", library: "project", folderId: "p08", name: "冠梁验收资料归档表.pdf", type: "验收资料", status: "已归档", version: "V1.0", versionNote: "冠梁验收闭环归档", description: "冠梁验收资料、验收照片和闭环记录", versions: ["V1.0 归档版"], sourceId: "daily-001", links: "任务：完成冠梁验收资料归档；证据：验收照片、闭环记录" },
    { id: "doc-005", projectId: "building-3", library: "project", folderId: "p05", name: "混凝土浇筑记录20260618.docx", type: "日报", status: "已归档", version: "V1.0", versionNote: "3号楼浇筑记录", description: "混凝土浇筑方量、试块留置和现场记录", versions: ["V1.0 归档版"], sourceId: "wx-002", links: "工序：混凝土浇筑" },
    { id: "doc-006", projectId: "pipe-network", library: "project", folderId: "p01", name: "交通导改方案", type: "施工方案", status: "缺失", version: "-", versionNote: "待补齐", description: "市政管网交通导改施工方案", versions: [], sourceId: "wx-003", links: "事件：交通导改不足" },
  ];

  const projectFolders = [
    { id: "p00", name: "00_项目总览", desc: "项目基本信息、组织架构、人员职责、关键里程碑" },
    { id: "p01", name: "01_合同图纸与方案", desc: "合同、图纸、施工组织设计、专项方案、技术交底、应急预案" },
    { id: "p02", name: "02_进度计划", desc: "总进度计划、WBS、周计划、月计划、实际进度对比" },
    { id: "p03", name: "03_质量安全管理", desc: "质量检查、安全检查、风险源台账、安全交底、问题隐患" },
    { id: "p04", name: "04_监测检测与试验", desc: "监测日报、测量记录、检测报告、试验报告、预警复核" },
    { id: "p05", name: "05_会议沟通与过程记录", desc: "会议纪要、往来函件、群聊记录、施工日报、周报、月报" },
    { id: "p06", name: "06_问题整改与任务闭环", desc: "任务派发、整改反馈、复核记录、闭环清单、证据链" },
    { id: "p07", name: "07_变更签证", desc: "工程内容变更、技术方案变更、计划节点变更、签证资料" },
    { id: "p08", name: "08_验收移交", desc: "分部分项验收、专项验收、移交资料、竣工图、竣工报告" },
    { id: "p09", name: "09_影像与原始数据", desc: "照片、视频、平台导出、数据库导出、IoT/监测原始文件" },
    { id: "p10", name: "10_AI整理成果", desc: "AI摘要、任务清单、风险清单、报告初稿、问答引用记录" },
    { id: "p99", name: "99_归档与历史版本", desc: "历史版本、阶段归档包、最终归档包" },
  ];

  const knowledgeFolders = [
    { id: "k01", name: "01_法规规范与标准", desc: "法律法规、国家标准、行业规范、地方监管要求、强制性条文" },
    { id: "k02", name: "02_企业制度与管理要求", desc: "企业质量、安全、进度、资料、审批、报告等内部制度" },
    { id: "k03", name: "03_专业技术知识", desc: "深基坑、脚手架、高支模、吊装、临电、消防、防水、结构施工" },
    { id: "k04", name: "04_检查规则与控制阈值", desc: "检查项、风险触发条件、监测预警阈值、质量验收判定规则" },
    { id: "k05", name: "05_流程模板与表单模板", desc: "风险核查、隐患整改、资料补全、报告审核、周报、检查表" },
    { id: "k06", name: "06_风险隐患与案例库", desc: "常见风险源、典型隐患、整改措施、事故案例、优秀做法" },
    { id: "k07", name: "07_AI知识包", desc: "AI知识包、抽取规则、问答索引、报告生成提示词" },
    { id: "k99", name: "99_废止与历史版本", desc: "已废止规范、旧制度、旧模板、旧规则版本" },
  ];

  const knowledgeDocs = [
    { id: "know-001", library: "knowledge", folderId: "k01", name: "深基坑工程技术规范.pdf", type: "法规规范与标准", status: "启用", version: "V2026", versionNote: "现行版本", description: "深基坑设计、施工、监测相关技术要求", scope: "深基坑", versions: ["V2024", "V2026"] },
    { id: "know-002", library: "knowledge", folderId: "k04", name: "S3测斜位移预警阈值规则", type: "检查规则与控制阈值", status: "启用", version: "V1.0", versionNote: "用于深基坑监测复核", description: "S3测斜位移>=18mm触发复核，>=20mm触发预警处置", scope: "深基坑", versions: ["V1.0"] },
    { id: "know-003", library: "knowledge", folderId: "k05", name: "隐患整改闭环流程模板", type: "流程模板与表单模板", status: "启用", version: "V1.1", versionNote: "增加复核归档节点", description: "发现、派单、整改、复核、闭环归档流程", scope: "通用", versions: ["V1.0", "V1.1"] },
  ];

  const initConfig = {
    processes: ["冠梁施工", "支撑安装", "分层开挖", "降水运行", "坑边防护", "监测复核"],
    riskSources: ["深基坑开挖", "支撑未验收", "测斜位移接近预警", "临边防护缺失", "降水异常"],
    peopleRelations: ["王经理-开挖审批", "安全员-临边防护", "监测单位-位移复核", "资料员-过程资料"],
    checks: ["开挖令", "支撑验收", "降水记录", "监测频次", "临边防护", "应急物资"],
    rules: ["开挖前必须完成支撑验收", "S3位移>=18mm触发复核", "降雨前触发排水检查", "临边防护照片异常触发整改"],
  };

  const scheduledTaskTemplates = [
    { id: "schedule-001", projectId: "pit", title: "每日08:30检查深基坑风险窗口", cycle: "每天 08:30", nextRun: "2026-06-19 08:30", channel: "系统任务", status: "启用" },
    { id: "schedule-002", projectId: "pit", title: "每日17:30收集基坑施工日报", cycle: "每天 17:30", nextRun: "2026-06-19 17:30", channel: "企业微信", status: "启用" },
    { id: "schedule-003", projectId: "building-3", title: "每日18:00汇总浇筑记录", cycle: "每天 18:00", nextRun: "2026-06-19 18:00", channel: "企业微信", status: "启用" },
  ];

  const oneOffTaskTemplates = [
    { id: "one-001", projectId: "pit", title: "明天开挖前确认支撑验收是否完成", owner: "王经理", runAt: "2026-06-19 09:00", status: "待执行" },
    { id: "one-002", projectId: "pit", title: "今晚复核S3测斜位移数据", owner: "监测单位", runAt: "2026-06-18 20:00", status: "待执行" },
    { id: "one-003", projectId: "pipe-network", title: "今晚检查围挡和警示灯照片", owner: "施工队", runAt: "2026-06-18 20:00", status: "待执行" },
  ];

  const riskWindows = [
    { projectId: "pit", name: "深基坑分层开挖窗口", wbs: "WBS-03 分层开挖", trigger: "开挖至-4.5m + S3位移18mm", status: "已触发", owner: "王经理", action: "开挖前条件核查、监测复核、临边防护复查" },
    { projectId: "pit", name: "降雨前排水检查", wbs: "WBS-04 降水运行", trigger: "天气预报中雨", status: "待触发", owner: "安全员", action: "排水沟、集水井、备用泵检查" },
  ];

  const qualityItems = [
    { projectId: "pit", item: "支撑轴力与验收资料一致性", status: "待核查", owner: "质量员", sourceIds: ["file-001"] },
    { projectId: "pit", item: "降水记录连续性", status: "资料缺失", owner: "资料员", sourceIds: ["daily-001"] },
    { projectId: "building-3", item: "钢筋保护层复核", status: "进行中", owner: "质量员", sourceIds: ["meeting-002"] },
  ];

  const events = [
    { projectId: "pit", type: "隐患事件", title: "基坑西侧临边防护缺失", status: "整改中", sourceIds: ["photo-001"], chain: ["发现", "派单", "整改中", "待复核", "未闭环"] },
    { projectId: "pit", type: "风险事件", title: "S3测斜位移接近预警", status: "待复核", sourceIds: ["platform-001"], chain: ["发现", "派单", "复核中", "未闭环"] },
    { projectId: "pipe-network", type: "隐患事件", title: "交通导改标识不足", status: "逾期", sourceIds: ["wx-003"], chain: ["发现", "派单", "逾期"] },
  ];

  const changes = [
    { projectId: "pit", title: "开挖计划节点调整", category: "计划节点变更", content: "分层开挖节点根据支撑验收资料复核情况顺延半天，待确认后进入下一层开挖。", time: "2026-06-18 18:00", sourceIds: ["wx-001", "meeting-001"] },
    { projectId: "pit", title: "S3监测复核责任调整", category: "重要人员变更", content: "S3监测复核由安全员协调调整为监测单位直接反馈，项目经理保留复核确认。", time: "2026-06-18 18:20", sourceIds: ["platform-001"] },
    { projectId: "pit", title: "临边防护整改技术措施补充", category: "技术方案变更", content: "西侧临边防护整改增加双道栏杆和警示标识，复核照片作为闭环依据。", time: "2026-06-18 19:10", sourceIds: ["photo-001"] },
    { projectId: "building-3", title: "浇筑记录归档范围调整", category: "工程内容变更", content: "浇筑记录补齐后纳入主体结构质量资料包统一归档。", time: "2026-06-18 20:10", sourceIds: ["wx-002"] },
  ];

  const projectStatusSamples = {
    pit: { progressRate: 92, progressStatus: "正常", plannedDelta: "滞后3%", riskWarnings: 1, safetyIssues: 1, qualityIssues: 2, taskCompletionRate: 35, mainRisk: "S3测斜位移18mm，距预警阈值20mm较近", mainSafety: "基坑西侧临边防护局部缺失", mainQuality: "支撑验收资料待核查、降水记录连续性不足", overall: "风险可控但需尽快完成复核和资料闭环" },
    "building-3": { progressRate: 96, progressStatus: "正常", plannedDelta: "基本一致", riskWarnings: 0, safetyIssues: 0, qualityIssues: 1, taskCompletionRate: 72, mainRisk: "暂无新增风险预警", mainSafety: "暂无新增安全隐患", mainQuality: "钢筋保护层复核仍在进行", overall: "整体推进正常，资料闭环需持续跟进" },
    "pipe-network": { progressRate: 84, progressStatus: "滞后", plannedDelta: "滞后8%", riskWarnings: 1, safetyIssues: 1, qualityIssues: 1, taskCompletionRate: 28, mainRisk: "沟槽开挖与交通导改存在交叉风险", mainSafety: "交通导改标识不足", mainQuality: "沟槽验收资料缺失", overall: "存在滞后和安全隐患，需优先完成整改闭环" },
  };

  const processSupervision = [
    { projectId: "pit", process: "支撑安装", yesterday: "完成北侧第一道支撑", today: "验收资料复核", progress: "滞后", quality: "支撑验收记录缺失，轴力资料待核查", risk: "未完成验收前不得进入下一层开挖", focus: "支撑验收资料、监测频次确认", key: true },
    { projectId: "pit", process: "分层开挖", yesterday: "准备开挖至-4.5m", today: "等待开挖条件确认", progress: "正常", quality: "开挖条件核查中", risk: "S3测斜位移18mm，接近20mm预警阈值", focus: "开挖前条件、监测复核、临边防护", key: true },
    { projectId: "pit", process: "降水运行", yesterday: "降水井运行正常", today: "持续巡查边坡渗水", progress: "正常", quality: "降水记录连续性不足", risk: "降雨前需检查排水沟、集水井和备用泵", focus: "降水记录补齐、夜间巡查记录", key: false },
    { projectId: "pit", process: "临边防护", yesterday: "发现西侧局部缺失", today: "施工单位整改并上传照片", progress: "滞后", quality: "整改照片待复核", risk: "临边防护缺失影响开挖安全条件", focus: "整改照片、复核意见、闭环证据", key: true },
    { projectId: "building-3", process: "混凝土浇筑", yesterday: "浇筑120方", today: "养护与试块记录整理", progress: "正常", quality: "试块留置3组，浇筑记录已补齐", risk: "暂无新增风险", focus: "养护记录、试块报告", key: false },
    { projectId: "pipe-network", process: "沟槽开挖", yesterday: "完成K0+320至K0+480", today: "补设交通导改标识", progress: "滞后", quality: "沟槽验收记录缺失", risk: "交通导改标识不足", focus: "围挡、警示灯、验收记录", key: true },
  ];

  // 将原深基坑演示数据统一归属到当前普陀项目，保留过程记录内容以便继续演示与配置。
  const legacyProjectId = "pit";
  const activeProjectId = "zhiru-health";
  [projectMembers, records, tasks, docs, scheduledTaskTemplates, oneOffTaskTemplates, riskWindows, qualityItems, events, changes, processSupervision]
    .forEach((items) => items.forEach((item) => {
      if (item.projectId === legacyProjectId) item.projectId = activeProjectId;
    }));
  projectStatusSamples[activeProjectId] = projectStatusSamples[legacyProjectId];

  const knowledgeRules = [
    { name: "深基坑专项方案规则", type: "制度规范", content: "开挖前完成支护验收、降水运行记录、监测方案确认。" },
    { name: "测斜位移控制阈值", type: "控制阈值", content: "S3测斜位移>=18mm触发复核，>=20mm触发预警处置。" },
    { name: "隐患整改闭环规则", type: "任务规则", content: "发现-派单-整改-复核-关闭，每一环节必须保留来源证据。" },
  ];

  const businessTools = [
    { name: "数据分析", desc: "自然查询工程数据库，生成表、图和分析结论。", starter: "帮我统计当前项目风险、隐患、质量问题和逾期任务。" },
    { name: "安全隐患", desc: "对巡检照片、隐患记录和整改反馈进行分析。", starter: "请分析基坑西侧临边防护隐患，并给出整改建议。" },
    { name: "趋势预测", desc: "基于监测数据、进度和风险状态预测趋势。", starter: "请预测S3测斜位移未来24小时风险趋势。" },
    { name: "风险诊断", desc: "按风险源、工序、资料、监测数据进行诊断。", starter: "请诊断深基坑开挖窗口当前主要风险。" },
    { name: "报告撰写", desc: "生成专项报告、整改闭环清单、周报。", starter: "请起草深基坑质量安全监督报告。" },
    { name: "报告审核", desc: "检查报告依据、缺失来源、数据一致性。", starter: "请审核深基坑报告是否缺少来源和证据链。" },
  ];

  const discussion = {
    initiator: "赵安全",
    topic: "深基坑开挖前条件确认讨论",
    linkedObject: "关联任务：开挖前支撑验收条件核查",
    status: "Dobby同步总结中",
    participants: [
      ...projectMembers.filter((member) => member.projectId === activeProjectId).map(({ name, role }) => ({ name, role })),
      { name: "Dobby", role: "智能体", ai: true },
    ],
    selectedMembers: ["王经理", "赵安全", "陈施工", "周监理", "孙监测", "Dobby"],
    messages: [
      { role: "赵安全", text: "支撑验收资料还没完全确认，西侧临边防护整改照片也需要复核。", type: "member" },
      { role: "孙监测", text: "S3测斜位移18mm，距离20mm预警阈值较近，建议复核原始数据。", type: "member" },
      { role: "王经理", text: "@Dobby 帮我判断开挖前还缺哪些关键条件。", type: "mention" },
      { role: "Dobby", text: "已检索会议纪要、监测日报和专项方案：当前缺支撑验收确认、S3原始数据复核、临边防护整改复核三项。", type: "ai", mode: "风险分析" },
      { role: "陈施工", text: "临边防护整改照片今天18点前补传。", type: "member" },
    ],
    aiSummary: {
      consensus: ["开挖前必须完成支撑验收确认", "S3测斜数据需复核原始记录", "临边防护整改照片需补传并复核"],
      openQuestions: ["支撑验收记录是否已由监理签认", "S3原始数据复核责任人是否为监测单位", "整改照片是否满足闭环归档要求"],
      suggestions: ["生成条件核查任务", "将S3复核关联到深基坑风险窗口", "讨论结束后形成会议纪要并归档"],
      sources: ["深基坑专项会纪要", "基坑监测日报.xlsx", "深基坑专项施工方案.pdf"],
      actions: ["生成待办", "生成会议纪要", "关联到风险事件", "归档讨论"],
    },
  };

  const titles = { chat: "Dobby互动台", status: "项目状态", tasks: "任务管理", docs: "知识管理", tools: "业务工具", discussion: "AI群讨论", settings: "设置" };
  const authUser = "PC";
  const authPasswordHash = "54e7aa43f82290297321f41c58c44e61c75b0b8da9e38eb177027a744436791b";
  const authAccounts = {
    [authUser]: authPasswordHash,
    zy: "0b137381cc97d7fc48de75e7f93ff04cca9fd3254a20124dc013deaa7e0d9cb9",
  };
  const authSessionKey = "projectCopilotAuth";
  const currentUserName = "赵安全";
  const currentUserRole = "安全员";
  const currentTaskUser = currentUserName;
  const today = new Date("2026-06-19T09:00:00");
  let selectedProjectId = "zhiru-health";
  let currentStatusTab = "latest";
  let currentTaskTab = "mine";
  let currentDocsTab = "upload";
  let projectDocQuery = "我想找深基坑支护方案、S3监测数据，以及相关预警阈值规则";
  let projectDocTypeFilter = "all";
  let projectDocFolderFilter = "all";
  let selectedProjectDocId = "doc-002";
  let projectDocNotice = "";
  let selectedToolAgent = "数据分析";
  let toolAgentNotice = "";
  let settingsMenuOpen = false;
  let currentSettingsSection = "engineering";
  let engineeringSettingsMode = "list";
  let projectPickerOpen = false;
  let creatingNewProject = false;
  let engineeringDetailOpen = "";
  let projectBasicConfigOpen = false;
  const engineeringImportedDetails = {
    description: { title: "工程项目描述", summary: "社区医院综合楼，地上6层、地下2层（含人防），总建筑面积约20992㎡，占地约5394㎡。合同工期2024-09-10至2027-09-09，合同额21410.82万元。", rows: ["建设单位：上海真如城市副中心发展有限公司", "施工总承包：上海城建市政工程（集团）有限公司", "监理单位：英泰克工程顾问上海有限公司", "设计单位：上海现代建筑装饰环境设计研究院有限公司", "勘察单位：创辉达设计股份有限公司"] },
    schedule: { title: "工序划分、计划、里程碑", summary: "已导入总进度计划（WBS）。项目计划区间为2025-01-01至2027-09-09。", rows: ["1.1 桩基、围护工程", "1.2 塔吊安拆施工", "1.3 土方开挖及支撑施工", "代表工序：地连墙施工、四轴搅拌桩、A区第一层土方开挖、第一道支撑施工"] },
    people: { title: "人员角色和范围", summary: "已导入总承包主要施工管理人员表。", rows: ["张怀德：项目经理", "程棚：项目常务副经理", "史鹏程：项目总工", "许闻博、张少梁：安全员", "瞿文斌：质量员", "睢英瑞：施工员", "王晓芸：材料员；袁君卿：机械员；史先争：测量员"] },
    risks: { title: "风险源，与工序关系", summary: "已导入工程风险识别清单，共3项二级风险。", rows: ["A区第一层土方开挖：地下室深基坑施工；开挖深度9.29m，邻近地铁15号线及居民楼", "第一道支撑、栈桥施工及养护：地下室超限梁模板支撑体系", "地连墙施工：履带吊双机抬吊；地连墙厚800mm、深21m"] },
    quality: { title: "关键质量指标，与工序关系", summary: "已导入工序质量指标关联表。", rows: ["桩基、围护：桩身完整性I、II类桩比例≥95%，围护位移≤30mm", "地连墙：垂直度≤1/200，沉渣≤100mm，超灌≥0.5m", "搅拌桩：水泥掺量≥15%，28天无侧限抗压强度≥1.0MPa", "A区第一层土方开挖：标高偏差≤±20mm，排水畅通无积水", "第一道支撑：轴线偏差≤10mm，养护时间≥14天"] },
  };
  const engineeringImportedTables = window.ZhiruImportedProjectData || {};
  let intakeLibrary = "project";
  let intakeFolderId = "p04";
  let intakeFileName = "";
  let intakeNotice = "";
  let pendingIntakeAction = "";
  let intakeDiagnosisOpen = false;
  let folderCreateOpen = false;
  let intakeDocSequence = 1;
  let intakeFolderSequence = 1;
  const openTreeNodes = new Set(["root:project", "project:current", "root:knowledge"]);
  let selectedPushTaskId = "";
  let selectedTaskDispositionId = "";
  let taskDispositionOpen = false;
  let selectedInfoRecordId = "";
  let infoDispositionOpen = false;
  let selectedHistoryTaskId = "";
  let historyTaskDetailOpen = false;
  let historyFilter = { name: "", start: "", end: "" };
  let taskNotice = "";
  let assignMode = "template";
  let draftFlow = null;

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const byProject = (items) => items.filter((item) => item.projectId === selectedProjectId);
  const currentProject = () => projects.find((item) => item.id === selectedProjectId);
  const source = (id) => records.find((record) => record.id === id);
  const isOverdue = (task) => !["已完成", "已关闭"].includes(task.status) && new Date(`${task.dueDate}T23:59:59`) < today;
  const missingDocs = () => byProject(docs).filter((doc) => doc.status === "缺失");
  const isCurrentUserPrincipal = (value) => value === currentUserName || value === currentUserRole;
  const discussionHumanCount = () => discussion.selectedMembers.filter((name) => name !== "Dobby").length;

  function init() {
    initAuth();
    $("#projectSelect").innerHTML = projects.map((item) => `<option value="${item.id}">${item.name}</option>`).join("");
    $("#projectSelect").value = selectedProjectId;
    if ($("#currentUserGreeting")) $("#currentUserGreeting").textContent = `欢迎${currentUserName}`;
    $("#projectSelect").addEventListener("change", (event) => {
      selectedProjectId = event.target.value;
      renderAll();
    });
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    $$("[data-view-target]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewTarget)));
    $$("[data-query]").forEach((button) => button.addEventListener("click", () => ask(button.dataset.query)));
    setupSettingsInteractions();
    $("#refreshAiQuestions").addEventListener("click", renderAiQuestions);
    $("#chatAttachment").addEventListener("change", renderAttachmentLabel);
    $("#chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = $("#chatInput").value.trim();
      if (text) {
        ask(text, $("#agentSelect").value);
        $("#chatInput").value = "";
      }
    });
    if ($("#taskBuilderForm")) {
      $("#taskBuilderForm").addEventListener("submit", (event) => {
        event.preventDefault();
        buildTaskFromLanguage($("#taskBuilderInput").value.trim());
      });
    }
    addMessage("assistant", "我是 Dobby。你可以直接问项目状态、资料、任务，也可以选择一个业务工具智能体来处理。");
    renderAll();
  }

  function initAuth() {
    const unlock = () => document.body.classList.remove("locked");
    $("#authForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const username = $("#authUser").value.trim();
      const password = $("#authPassword").value;
      const error = $("#authError");
      if (!window.crypto?.subtle) {
        error.textContent = "当前浏览器不支持本地密码校验，请使用现代浏览器或 HTTPS 页面。";
        return;
      }
      const passwordHash = await sha256(password);
      if (authAccounts[username] === passwordHash) {
        sessionStorage.setItem(authSessionKey, authPasswordHash);
        $("#authPassword").value = "";
        error.textContent = "";
        unlock();
      } else {
        error.textContent = "用户名或密码不正确";
      }
    });
    if (Object.values(authAccounts).includes(sessionStorage.getItem(authSessionKey))) unlock();
  }

  async function sha256(text) {
    const bytes = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function switchView(view) {
    $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
    $$(".view").forEach((panel) => panel.classList.toggle("active", panel.id === view));
    $("#view-title").textContent = titles[view];
  }

  function renderAll() {
    renderAiQuestions();
    renderStatus();
    renderTasks();
    renderDocs();
    renderTools();
    renderDiscussion();
  }

  function setupSettingsInteractions() {
    const launcher = $("#settingsLauncher");
    if (launcher) launcher.addEventListener("click", (event) => {
      event.stopPropagation();
      settingsMenuOpen = !settingsMenuOpen;
      renderSettingsMenu();
    });
    const menu = $("#settingsMenu");
    if (menu) menu.addEventListener("click", (event) => {
      event.stopPropagation();
      const action = event.target.closest("[data-settings-section]");
      if (!action) return;
      openSettingsSection(action.dataset.settingsSection);
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest?.(".settings-menu-wrap")) closeSettingsMenu();
    });
    renderSettingsMenu();
  }

  function renderSettingsMenu() {
    $("#settingsMenu")?.classList.toggle("active", settingsMenuOpen);
    $("#settingsLauncher")?.setAttribute("aria-expanded", String(settingsMenuOpen));
  }

  function closeSettingsMenu() {
    settingsMenuOpen = false;
    renderSettingsMenu();
  }

  function openSettingsSection(section) {
    if (section === "logout") {
      logoutCurrentUser();
      return;
    }
    closeSettingsMenu();
    if (section === "engineering") {
      openProjectPicker();
      return;
    }
    currentSettingsSection = section || "engineering";
    switchView("settings");
    if (currentSettingsSection === "personal") renderPersonalSettings();
    else renderEngineeringSettings();
  }

  function logoutCurrentUser() {
    sessionStorage.removeItem(authSessionKey);
    closeSettingsMenu();
    switchView("chat");
    document.body.classList.add("locked");
    $("#authUser").value = authUser;
    $("#authPassword").value = "";
    $("#authError").textContent = "";
  }

  function renderPersonalSettings() {
    const project = currentProject();
    $("#projectConfigLauncher").hidden = true;
    $("#settingsTitle").textContent = "个人";
    $("#settingsSubtitle").textContent = "管理个人账号，以及当前工程相关平台、邮件和协同工具的登录配置。";
    $("#view-title").textContent = "个人设置";
    $("#settingsTabs").innerHTML = "";
    $("#settingsContent").innerHTML = `<div class="personal-settings-grid account-settings-grid">
      ${renderAccountConfig(project)}
      ${renderPlatformCredentialConfig()}
      ${renderConnectorConfig("邮件配置", "project-mail", "项目邮箱", "project@example.com", "IMAP/SMTP，用于接收过程邮件、会议通知和外发报告草稿。")}
      ${renderConnectorConfig("企业微信配置", "wecom", "企业微信账号", "赵安全手机号", "用于接入项目群消息、任务提醒和转发同事处理。")}
      ${renderConnectorConfig("飞书配置", "feishu", "飞书账号", "feishu_user", "用于后续连接飞书群、飞书文档和审批消息。")}
      ${renderConnectorConfig("钉钉配置", "dingtalk", "钉钉账号", "dingtalk_user", "用于后续连接钉钉群、待办和组织通讯录。")}
    </div>`;
  }

  function renderAccountConfig(project) {
    return `<section class="config-block account-config-card">
      <div class="settings-card-head">
        <h4>个人账号</h4>
        <span class="permission-badge view">当前登录</span>
      </div>
      <div class="profile-lines">
        <span>用户名：${authUser}</span>
        <span>当前人员：${currentUserName}</span>
        <span>当前角色：${currentUserRole}</span>
        <span>所属项目：${project.name}</span>
        <span>访问方式：内部静态原型</span>
      </div>
      <div class="credential-form compact">
        <label>显示名称<input value="${currentUserName}" aria-label="显示名称"></label>
        <label>联系电话<input value="13800000000" aria-label="联系电话"></label>
      </div>
      <button type="button" class="secondary" disabled>修改密码（静态占位）</button>
    </section>`;
  }

  function renderPlatformCredentialConfig() {
    return `<section class="config-block account-config-card">
      <div class="settings-card-head">
        <h4>平台配置</h4>
        <span class="permission-badge edit">个人凭据</span>
      </div>
      <p class="muted">选择工程中已配置的平台，并维护本人登录用户名和密码。</p>
      <div class="credential-form">
        <label>平台
          <select>
            <option>监测平台</option>
            <option>项目管理平台</option>
            <option>资料管理平台</option>
            <option>质量安全检查平台</option>
          </select>
        </label>
        <label>用户名<input value="safety_user" aria-label="平台用户名"></label>
        <label>密码<input type="password" value="placeholder" aria-label="平台密码"></label>
      </div>
      <button type="button">保存平台账号（静态模拟）</button>
    </section>`;
  }

  function renderConnectorConfig(title, id, accountLabel, accountValue, desc) {
    return `<section class="config-block account-config-card">
      <div class="settings-card-head">
        <h4>${title}</h4>
        <span class="permission-badge preview-only">待校验</span>
      </div>
      <p class="muted">${desc}</p>
      <div class="credential-form">
        <label>${accountLabel}<input value="${accountValue}" aria-label="${title}${accountLabel}"></label>
        <label>登录密码 / 授权码<input type="password" value="placeholder" aria-label="${title}密码"></label>
        <label>接入状态
          <select aria-label="${title}接入状态">
            <option>未连接</option>
            <option>已连接</option>
            <option>暂停同步</option>
          </select>
        </label>
      </div>
      <button type="button" class="secondary">测试连接（静态模拟）</button>
    </section>`;
  }

  function renderEngineeringSettings() {
    currentSettingsSection = "engineering";
    const isList = engineeringSettingsMode === "list";
    $("#settingsTitle").textContent = isList ? "项目列表" : "项目配置";
    $("#settingsSubtitle").textContent = isList ? "选择一个项目进入工程基础配置，或新增项目后开始配置。" : "维护项目基础信息、工序计划、人员、风险和质量指标。";
    $("#view-title").textContent = isList ? "工程设置" : "项目配置";
    $("#settingsTabs").innerHTML = "";
    const projectConfigLauncher = $("#projectConfigLauncher");
    if (projectConfigLauncher) {
      projectConfigLauncher.hidden = isList;
      projectConfigLauncher.onclick = () => { projectBasicConfigOpen = true; renderProjectBasicConfigModal(); };
    }
    $("#settingsContent").innerHTML = isList ? renderEngineeringProjectList() : renderEngineeringWorkspace();
    $("[data-open-project-config]")?.addEventListener("click", () => { engineeringSettingsMode = "config"; renderEngineeringSettings(); });
    $("[data-add-project]")?.addEventListener("click", () => { engineeringSettingsMode = "config"; renderEngineeringSettings(); });
    $$("[data-engineering-detail]").forEach((button) => button.addEventListener("click", () => { engineeringDetailOpen = button.dataset.engineeringDetail; renderEngineeringDetailModalPortal(); }));
    renderEngineeringDetailModalPortal();
    renderProjectBasicConfigModal();
  }

  function openProjectPicker() {
    projectPickerOpen = true;
    const portal = document.getElementById("projectPickerPortal") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "projectPickerPortal" }));
    portal.innerHTML = `<div class="intake-modal-backdrop project-picker-backdrop" role="presentation">
      <section class="project-picker-modal" role="dialog" aria-modal="true" aria-labelledby="projectPickerTitle">
        <div class="intake-modal-head"><div><span>工程设置</span><h3 id="projectPickerTitle">选择项目</h3></div><button type="button" class="modal-icon-close" data-close-project-picker aria-label="关闭项目选择">×</button></div>
        <p>选择项目后进入工程配置页。</p>
        <div class="project-picker-list">${projects.map((project) => `<button type="button" class="project-picker-row" data-select-project="${project.id}"><span><strong>${project.name}</strong><small>${project.type} · ${project.stage}</small></span><b>配置 →</b></button>`).join("")}</div>
        <div class="intake-modal-actions"><button type="button" class="secondary" data-close-project-picker>取消</button><button type="button" data-add-project>新增项目</button></div>
      </section>
    </div>`;
    $("[data-close-project-picker]")?.addEventListener("click", closeProjectPicker);
    $$('[data-select-project]').forEach((button) => button.addEventListener("click", () => { selectedProjectId = button.dataset.selectProject; creatingNewProject = false; engineeringSettingsMode = "config"; closeProjectPicker(); switchView("settings"); renderEngineeringSettings(); }));
    $("#projectPickerPortal [data-add-project]")?.addEventListener("click", () => { creatingNewProject = true; closeProjectPicker(); projectBasicConfigOpen = true; renderProjectBasicConfigModal(); });
  }

  function closeProjectPicker() {
    projectPickerOpen = false;
    const portal = document.getElementById("projectPickerPortal");
    if (portal) portal.innerHTML = "";
  }

  function renderEngineeringProjectList() {
    const project = currentProject();
    return `<section class="surface project-list-panel"><div class="section-heading"><div><h3>项目列表</h3><p>当前仅保留 1 个项目</p></div><button type="button" data-add-project>新增项目</button></div><button type="button" class="project-list-row" data-open-project-config><span><strong>${project.name}</strong><small>${project.type} · ${project.stage}</small></span><span class="permission-badge edit">进入配置</span></button></section>`;
  }

  function renderEngineeringWorkspace() {
    const hasImportedDetails = selectedProjectId === activeProjectId && !creatingNewProject;
    return `<div><div class="engineering-init-workspace">
      <section class="engineering-ai-flow surface">
        <div class="ai-guide-card">
          <h4>Dobby 引导</h4>
          <p>还剩 8 项初始化内容。你只需要提供项目名称、工程文件或回答几个问题，AI会自动分类解析并放入平台。</p>
          <div class="init-next-actions">
            <span>先上传：合同、图纸、方案、组织架构</span>
            <span>再回答：工序、风险源、人员角色、平台来源</span>
            <span>最后确认：AI生成的工程初始化详情</span>
          </div>
        </div>
        <div class="engineering-chat-stream">
          <div class="message assistant-message">请先告诉我项目名称，或上传项目资料包。我会从资料中识别工程描述、工序、风险源、人员角色、信息源和平台配置。</div>
          <div class="message assistant-message">当前项目还没有完成初始化。建议从“项目名称 + 主要工程文件”开始。</div>
        </div>
        <div class="engineering-chat-input">
          <label class="file-action">
            <input type="file" multiple>
            <span>上传项目文件</span>
          </label>
          <textarea rows="4" placeholder="例如：这是某市政深基坑项目，请根据我上传的方案、图纸和组织架构进行初始化。"></textarea>
          <button type="button">发送给AI（静态模拟）</button>
        </div>
      </section>
      <aside class="engineering-detail-panel surface">
        <div class="section-heading compact">
          <div>
            <h3>完整详情</h3>
            <p>完成项亮色，可点击查看和修改；未完成项置灰并标注待办。</p>
          </div>
        </div>
        <div class="engineering-detail-list">
          ${hasImportedDetails ? renderEngineeringInitItem("📝", "工程项目描述", "已导入", "ready", ["项目名称", "工程类型", "项目阶段", "参建单位"], "description") : renderEngineeringInitItem("📝", "工程项目描述", "待办", "pending", ["项目名称", "工程类型", "项目阶段", "建设/施工/监理单位"])}
          ${hasImportedDetails ? renderEngineeringInitItem("⛓️", "工序划分、计划、里程碑", "已导入", "ready", ["WBS工序", "总进度计划", "关键节点"], "schedule") : renderEngineeringInitItem("⛓️", "工序划分、计划、里程碑", "待办", "pending", ["WBS工序", "总计划/周计划", "关键节点", "里程碑"])}
          ${hasImportedDetails ? renderEngineeringInitItem("👥", "人员角色和范围", "已导入", "ready", ["项目经理", "总工", "安全员", "质量员", "施工员"], "people") : renderEngineeringInitItem("👥", "人员角色和范围", "待办", "pending", ["项目经理", "安全员", "资料员", "施工单位", "监理"])}
          ${hasImportedDetails ? renderEngineeringInitItem("⚠️", "风险源，与工序关系", "已导入", "ready", ["风险源台账", "风险窗口", "关联工序"], "risks") : renderEngineeringInitItem("⚠️", "风险源，与工序关系", "待办", "pending", ["风险源台账", "风险窗口", "关联工序", "触发条件"])}
          ${hasImportedDetails ? renderEngineeringInitItem("✅", "关键质量指标，与工序关系", "已导入", "ready", ["质量验收项", "控制指标", "检查频次", "关联资料"], "quality") : renderEngineeringInitItem("✅", "关键质量指标，与工序关系", "待办", "pending", ["质量验收项", "控制指标", "检查频次", "关联资料"])}
          ${renderEngineeringInitItem("📡", "采集信息源配置", "待办", "pending", ["微信/企业微信", "邮件", "飞书", "钉钉", "平台导出", "日报/照片"])}
          ${renderEngineeringInitItem("⚙️", "平台配置", "待办", "pending", ["平台网址", "平台功能介绍", "账号范围", "输出端"])}
          ${renderEngineeringInitItem("🔁", "常用任务流程", "待办", "pending", ["风险核查", "隐患整改", "资料补全", "复核闭环", "报告生成"])}
        </div>
      </aside>
    </div>`;
  }

  function renderEngineeringInitItem(icon, title, status, state, items, detailId = "") {
    const disabled = state === "pending" ? " disabled" : "";
    return `<article class="engineering-detail-item ${state}" tabindex="0">
      <div class="detail-icon" aria-hidden="true">${icon}</div>
      <div class="detail-body">
        <div class="detail-title-row">
          <strong>${title}</strong>
          <span>${status}</span>
        </div>
        <div class="chip-list">${items.map((item) => `<span class="chip">${item}</span>`).join("")}</div>
      </div>
      <button type="button" class="secondary"${disabled}${detailId ? ` data-engineering-detail="${detailId}"` : ""}>查看/修改</button>
    </article>`;
  }

  function renderEngineeringDetailModalPortal() {
    const portal = document.getElementById("engineeringDetailPortal") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "engineeringDetailPortal" }));
    const detail = engineeringImportedDetails[engineeringDetailOpen];
    if (!detail) { portal.innerHTML = ""; return; }
    portal.innerHTML = `<div class="intake-modal-backdrop" role="presentation"><section class="engineering-detail-modal ${engineeringDetailOpen === "description" ? "" : "engineering-detail-modal-wide"}" role="dialog" aria-modal="true"><div class="intake-modal-head"><div><span>已导入工程资料</span><h3>${detail.title}</h3></div><button type="button" class="modal-icon-close" data-close-engineering-detail aria-label="关闭详情">×</button></div>${renderEngineeringDetailContent(detail, engineeringImportedTables[{ schedule: "wbs", people: "people", risks: "risks", quality: "quality" }[engineeringDetailOpen]])}</section></div>`;
    portal.querySelector("[data-close-engineering-detail]")?.addEventListener("click", () => { engineeringDetailOpen = ""; renderEngineeringDetailModalPortal(); });
  }

  function renderEngineeringDetailContent(detail, rows) {
    if (!rows?.length) return `<p>${detail.summary}</p><ul>${detail.rows.map((row) => `<li>${row}</li>`).join("")}</ul>`;
    const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    return `<p>${detail.summary} 已全量导入 ${rows.length} 条明细。</p><div class="engineering-table-wrap"><table class="engineering-data-table"><thead><tr>${headers.map((header) => `<th>${escapeAttr(header)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((header) => `<td>${escapeAttr(row[header] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function renderSettingList(...groups) {
    return groups.map(([title, items]) => `<section class="config-block"><h4>${title}</h4><div class="chip-list">${items.map((item) => `<span class="chip">${item}</span>`).join("")}</div></section>`).join("");
  }

  function renderSourceSummary() {
    const counts = byProject(records).reduce((acc, item) => {
      acc[item.sourceType] = (acc[item.sourceType] || 0) + 1;
      return acc;
    }, {});
    $("#sourceSummary").innerHTML = ["微信群", "日报", "照片", "平台导出", "会议纪要", "工程文件"].map((name) => `<div class="source-pill">${name}<strong>${counts[name] || 0}</strong></div>`).join("");
  }

  function renderAiQuestions() {
    const cards = aiPushTasks();
    if (!cards.some((task) => task.id === selectedPushTaskId)) {
      selectedPushTaskId = cards[0]?.id || "";
    }
    $("#aiQuestionQueue").innerHTML = cards.length ? cards.map((task) => `
      <article class="question-card compact ${task.id === selectedPushTaskId ? "selected" : ""} ${isOverdue(task) ? "overdue" : ""}" data-push-task="${task.id}">
        <div class="question-meta">${task.type} · ${task.status} · 截止 ${task.dueDate}</div>
        <h4>${task.title}</h4>
        <div class="question-meta">当前责任人：${taskCurrentOwner(task)}</div>
        <div class="question-meta">前序环节责任人：${previousOwner(task)}</div>
        <button type="button" data-dispose-task="${task.id}">处置</button>
      </article>
    `).join("") : `<div class="empty-state">当前没有需要AI推动的事项。</div>`;
    $$("#aiQuestionQueue [data-push-task]").forEach((card) => card.addEventListener("click", () => {
      selectedPushTaskId = card.dataset.pushTask;
      renderAiQuestions();
    }));
    $$("#aiQuestionQueue [data-dispose-task]").forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectedPushTaskId = button.dataset.disposeTask;
      renderAiQuestions();
    }));
    renderDispositionPanel(cards.find((task) => task.id === selectedPushTaskId));
  }

  function renderDispositionPanel(task) {
    if (!task) {
      $("#taskDispositionPanel").innerHTML = `<div class="empty-state">选择左侧任务后进行处置。</div>`;
      return;
    }
    $("#taskDispositionPanel").innerHTML = `
      <div class="disposition-head">
        <span>${task.type}</span>
        <strong>${task.title}</strong>
        <small>${task.status} · ${taskCurrentOwner(task)} · 截止 ${task.dueDate}</small>
      </div>
      <textarea id="dispositionReply" rows="4" placeholder="回复AI，例如：已完成整改，复核照片已上传"></textarea>
      <div class="disposition-tools">
        <label class="file-action">
          <input id="dispositionAttachment" type="file" multiple>
          <span id="dispositionAttachmentLabel">提交文件/图片</span>
        </label>
        <select id="dispositionForward">
          <option value="">转交其他同事</option>
          <option>王经理</option>
          <option>张工</option>
          <option>安全员</option>
          <option>资料员</option>
          <option>施工单位</option>
          <option>监测单位</option>
        </select>
      </div>
      <div class="disposition-actions">
        <button type="button" data-disposition-action="reply">回复AI</button>
        <button type="button" data-disposition-action="forward">转交</button>
        <button type="button" data-disposition-action="discussion">发起讨论</button>
      </div>
    `;
    $("#dispositionAttachment").addEventListener("change", renderDispositionAttachmentLabel);
    $$("[data-disposition-action]").forEach((button) => button.addEventListener("click", () => handleDispositionAction(task.id, button.dataset.dispositionAction)));
  }

  function handleDispositionAction(taskId, action) {
    const task = tasks.find((item) => item.id === taskId);
    const reply = $("#dispositionReply")?.value.trim();
    const forwardTo = $("#dispositionForward")?.value;
    const attachmentNames = fileNames("#dispositionAttachment");
    if (action === "forward") {
      if (!forwardTo) {
        addMessage("assistant", `请选择要转交的同事或单位。任务：${task.title}`);
        return;
      }
      task.previousOwner = task.owner;
      task.owner = forwardTo;
      if (currentStep(task)) currentStep(task).owner = forwardTo;
      task.needsInfo = true;
      addMessage("user", `将任务“${task.title}”转交给 ${forwardTo}`);
      addMessage("assistant", `已模拟转交。前序环节责任人更新为 ${task.previousOwner}，当前责任人为 ${task.owner}。`);
      renderAll();
      return;
    }
    if (action === "discussion") {
      addMessage("user", `围绕任务“${task.title}”发起AI群讨论`);
      addMessage("assistant", `已模拟发起讨论，并把任务带入AI群讨论空间。`);
      switchView("discussion");
      return;
    }
    addMessage("user", `处置任务“${task.title}”：${reply || "已收到，稍后补充。"}${attachmentNames ? `\n附件：${attachmentNames}` : ""}`);
    addMessage("assistant", `已记录处置反馈，当前任务仍保留人工复核闭环要求。`);
    if ($("#dispositionReply")) $("#dispositionReply").value = "";
  }

  function renderStatus() {
    const projectTasks = byProject(tasks);
    const open = projectTasks.filter((task) => !["已完成", "已关闭"].includes(task.status));
    const overdue = projectTasks.filter(isOverdue);
    const status = projectStatus();
    $("#metrics").innerHTML = [
      ["进度完成率", `${status.progressRate}%`, progressMetricClass(status.progressStatus)],
      ["风险预警数", status.riskWarnings, status.riskWarnings ? "warn" : "ok"],
      ["安全隐患数", status.safetyIssues, status.safetyIssues ? "danger" : "ok"],
      ["质量问题数", status.qualityIssues, status.qualityIssues ? "warn" : "ok"],
      ["待办任务数", open.length, open.length ? "warn" : "ok"],
      ["逾期任务", overdue.length, overdue.length ? "danger" : "ok"],
    ].map(metric).join("");
    $("#projectSummary").innerHTML = `<p>目前进度${status.progressRate}%，与周计划进度相比${status.plannedDelta}。主要风险关注：${status.mainRisk}。主要安全问题：${status.mainSafety}。存在的质量问题：${status.mainQuality}。任务完成率${status.taskCompletionRate}%，总体评价：${status.overall}。</p>`;
    $$("#statusTabs .tab-button").forEach((button) => button.addEventListener("click", () => {
      currentStatusTab = button.dataset.statusTab;
      $$("#statusTabs .tab-button").forEach((item) => item.classList.toggle("active", item === button));
      renderStatusPanel();
    }));
    renderStatusPanel();
  }

  function renderStatusPanel() {
    const panels = {
      latest: renderLatestInfo(),
      process: renderProcessSupervision(),
      execution: renderCardList(byProject(tasks), (item) => [item.title, `${item.phase} · ${item.status} · ${item.closure}`, `材料：${item.material}；来源：${sourceNames(item.sourceIds)}`]),
      changes: renderEngineeringChanges(),
    };
    $("#statusPanel").innerHTML = panels[currentStatusTab];
    bindStatusPanelActions();
  }

  function projectStatus() {
    return projectStatusSamples[selectedProjectId] || projectStatusSamples[activeProjectId];
  }

  function progressMetricClass(status) {
    if (status === "正常" || status === "超前") return "ok";
    if (status === "严重滞后") return "danger";
    return "warn";
  }

  function renderLatestInfo() {
    const projectRecords = byProject(records);
    return `
      <div class="latest-info-layout">
        <div class="latest-info-list">
          ${projectRecords.map((record) => `
            <article class="info-card ${canDisposeRecord(record) ? "pending-info" : ""}">
              <div class="info-card-meta"><span>${record.sourceType}</span><span class="info-status ${infoStatusClass(record.status)}">${record.status}</span></div>
              <div class="question-meta">置信度${record.confidence} · ${record.time}</div>
              <strong>${record.sourceName}</strong>
              <p>${record.content}</p>
              ${canDisposeRecord(record) ? `<button type="button" data-info-dispose="${record.id}">处置</button>` : ""}
            </article>
          `).join("")}
        </div>
      </div>
      ${infoDispositionOpen ? `<div class="intake-modal-backdrop" role="presentation"><section class="info-disposition-modal" role="dialog" aria-modal="true"><div class="intake-modal-head"><div><span>信息处置</span><h3>确认、否认或修订</h3></div><button type="button" class="modal-icon-close" data-close-info-disposition aria-label="关闭处置弹窗">×</button></div><div class="info-disposition">${renderInfoDisposition(projectRecords.find((record) => record.id === selectedInfoRecordId))}</div></section></div>` : ""}
    `;
  }

  function renderInfoDisposition(record) {
    if (!record) return `<div class="empty-state">选择待确认或待复核信息后进行处置。</div>`;
    return `
      <div class="disposition-head">
        <span>${record.sourceType} · ${record.status}</span>
        <strong>${record.sourceName}</strong>
        <small>置信度${record.confidence} · ${record.author}</small>
      </div>
      <p>${record.content}</p>
      <textarea id="infoRevision" rows="4" placeholder="修订信息，例如：S3测斜位移需以监测单位原始记录为准"></textarea>
      <div class="disposition-actions">
        <button type="button" data-info-action="confirm" data-record="${record.id}">确认</button>
        <button type="button" data-info-action="deny" data-record="${record.id}">否认</button>
        <button type="button" data-info-action="revise" data-record="${record.id}">修订</button>
      </div>
    `;
  }

  function canDisposeRecord(record) {
    return ["待确认", "待复核"].includes(record.status);
  }

  function bindStatusPanelActions() {
    $$("[data-info-dispose]").forEach((button) => button.addEventListener("click", () => {
      selectedInfoRecordId = button.dataset.infoDispose;
      infoDispositionOpen = true;
      renderStatusPanel();
    }));
    $("[data-close-info-disposition]")?.addEventListener("click", () => { infoDispositionOpen = false; renderStatusPanel(); });
    $$("[data-info-action]").forEach((button) => button.addEventListener("click", () => handleInfoAction(button.dataset.record, button.dataset.infoAction)));
  }

  function handleInfoAction(recordId, action) {
    const record = records.find((item) => item.id === recordId);
    const revision = $("#infoRevision")?.value.trim();
    if (!record) return;
    if (action === "confirm") {
      record.status = "已确认";
      addMessage("assistant", `已模拟确认最新信息：${record.sourceName}`);
    } else if (action === "deny") {
      record.status = "已否认";
      addMessage("assistant", `已模拟否认最新信息：${record.sourceName}`);
    } else {
      record.status = "已修订";
      if (revision) record.content = revision;
      addMessage("assistant", `已模拟修订最新信息：${record.sourceName}`);
    }
    infoDispositionOpen = false;
    renderStatus();
  }

  function renderProcessSupervision() {
    const items = byProject(processSupervision);
    return `<div class="process-grid">${items.map((item) => `
      <article class="process-card ${item.key ? "key-process" : ""}">
        <div class="process-card-head">
          <strong>${item.process}</strong>
          <span class="status ${processStatusClass(item.progress)}">${item.progress}</span>
        </div>
        <p><b>昨日完成量：</b>${item.yesterday}</p>
        <p><b>今日进度：</b>${item.today}</p>
        <p><b>质量验收数据：</b>${item.quality}</p>
        <p><b>关联风险数据：</b>${item.risk}</p>
        <p><b>关联关注点：</b>${item.focus}</p>
        <div class="question-meta">${item.key ? "重点关注工序" : "常规监管工序"}</div>
      </article>
    `).join("")}</div>`;
  }

  function processStatusClass(status) {
    if (status === "正常" || status === "超前") return "complete";
    if (status === "严重滞后") return "overdue";
    return "missing";
  }

  function renderEngineeringChanges() {
    return `<div class="card-grid">${byProject(changes).map((item) => `
      <article class="info-card">
        <div class="question-meta">${item.category} · ${item.time}</div>
        <strong>${item.title || item.type}</strong>
        <p>${item.content}</p>
        <div class="source-ref">证据文件：${sourceNames(item.sourceIds)}</div>
      </article>
    `).join("")}</div>`;
  }

  function renderTasks() {
    $$("#taskTabs .tab-button").forEach((button) => button.addEventListener("click", () => {
      currentTaskTab = button.dataset.taskTab;
      $$("#taskTabs .tab-button").forEach((item) => item.classList.toggle("active", item === button));
      renderTaskPanel();
    }));
    renderTaskPanel();
  }

  function renderTaskPanel() {
    const panels = {
      mine: renderMyTasksPanel(),
      history: renderHistoryTasksPanel(),
      assign: renderAssignTaskPanel(),
    };
    $("#taskPanel").innerHTML = `${taskNotice ? `<div id="taskNotice" class="task-notice">${taskNotice}</div>` : ""}${panels[currentTaskTab]}`;
    bindTaskPanelActions();
    renderHistoryTaskModalPortal();
  }

  function renderMyTasksPanel() {
    const related = byProject(tasks).filter(isTaskRelatedToCurrentUser);
    const waiting = aiPushTasks().filter(isWaitingForCurrentUser);
    const overdue = related.filter((task) => isOverdue(task) && !isTaskClosed(task));
    const other = related.filter((task) => !isTaskClosed(task) && !waiting.includes(task) && !overdue.includes(task));
    return `
      <div class="task-dashboard">
        <section class="task-section">
          <div class="section-heading compact"><h3>待处理任务</h3></div>
          <div class="task-group-grid task-dispose-grid">${waiting.length ? waiting.map((task) => renderActionTaskCard(task, true)).join("") : `<div class="empty-state">当前没有需要立即处理的任务。</div>`}</div>
          ${taskDispositionOpen ? `<div class="intake-modal-backdrop" role="presentation"><section class="task-disposition-modal" role="dialog" aria-modal="true"><div class="intake-modal-head"><div><span>任务处置</span><h3>处理待办任务</h3></div><button type="button" class="modal-icon-close" data-close-task-disposition aria-label="关闭任务处置">×</button></div><div class="disposition-panel">${renderTaskManageDisposition(tasks.find((task) => task.id === selectedTaskDispositionId))}</div></section></div>` : ""}
        </section>
        <section class="task-section">
          <div class="section-heading compact"><h3>已逾期任务</h3></div>
          <div class="task-group-grid">${overdue.length ? overdue.map(renderOverdueTaskCard).join("") : `<div class="empty-state">当前没有相关的逾期任务。</div>`}</div>
        </section>
        <section class="task-section">
          <div class="section-heading compact"><h3>执行中任务</h3></div>
          <div class="task-group-grid">${other.length ? other.map((task) => renderActionTaskCard(task, false)).join("") : `<div class="empty-state">暂无其他未闭环相关任务。</div>`}</div>
        </section>
      </div>
    `;
  }

  function renderHistoryTasksPanel() {
    const history = byProject(tasks).filter(isTaskClosed).filter(matchesHistoryFilter);
    if (!history.some((task) => task.id === selectedHistoryTaskId)) selectedHistoryTaskId = "";
    const selected = history.find((task) => task.id === selectedHistoryTaskId);
    return `
      <form id="historySearchForm" class="history-search">
        <input id="historyName" value="${escapeAttr(historyFilter.name)}" placeholder="按任务名称搜索">
        <input id="historyStart" type="date" value="${historyFilter.start}">
        <input id="historyEnd" type="date" value="${historyFilter.end}">
        <button type="submit">查询</button>
      </form>
      <div class="history-layout stacked">
        <section class="task-section">
          <div class="section-heading compact"><h3>查到的任务</h3></div>
          <div class="task-group-grid history-result-grid">${history.length ? history.map((task) => renderHistoryTaskCard(task)).join("") : `<div class="empty-state">没有匹配的历史任务。</div>`}</div>
        </section>
      </div>
    `;
  }

  function renderHistoryTaskModalPortal() {
    const portal = document.getElementById("historyTaskModalPortal") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "historyTaskModalPortal" }));
    const task = tasks.find((item) => item.id === selectedHistoryTaskId);
    if (currentTaskTab !== "history" || !historyTaskDetailOpen || !task) {
      portal.innerHTML = "";
      return;
    }
    portal.innerHTML = `<div class="intake-modal-backdrop history-modal-backdrop" role="presentation"><section class="history-task-modal" role="dialog" aria-modal="true"><div class="intake-modal-head"><h3 class="history-modal-title"><span>历史任务详情</span><b>· ${task.title}</b></h3><button type="button" class="modal-icon-close" data-close-history-detail aria-label="关闭任务详情">×</button></div><div class="history-task-detail">${renderTaskFlowDetail(task, false)}</div></section></div>`;
    portal.querySelector("[data-close-history-detail]")?.addEventListener("click", () => { historyTaskDetailOpen = false; renderTaskPanel(); });
  }

  function renderAssignTaskPanel() {
    if (!draftFlow) draftFlow = createDraftFlow("隐患整改", "整改现场隐患并完成复核闭环");
    return `
      <div class="assign-layout">
        <section class="surface">
          <h3>布置任务</h3>
          <form id="assignTaskForm" class="builder-form">
            <div class="segmented-control" aria-label="布置方式">
              <button type="button" class="${assignMode === "template" ? "active" : ""}" data-assign-mode="template">模板生成</button>
              <button type="button" class="${assignMode === "language" ? "active" : ""}" data-assign-mode="language">语言生成</button>
            </div>
            ${assignMode === "template" ? `
              <div class="assign-mode-panel">
                <select id="taskTypeSelect">
                  ${["条件核查", "隐患整改", "资料补全", "风险处置", "报告审核", "自定义"].map((type) => `<option value="${type}" ${draftFlow.type === type ? "selected" : ""}>${type}</option>`).join("")}
                </select>
                <input id="taskTopicInput" value="${escapeAttr(draftFlow.topic)}" placeholder="任务主题">
                <button type="button" data-build-flow="type">按模板生成流程</button>
              </div>
            ` : `
              <div class="assign-mode-panel">
                <textarea id="taskNaturalInput" rows="4" placeholder="例如：让施工单位今天补齐临边防护整改照片，安全员明天复核；每周五提醒资料员补齐监测报告"></textarea>
                <button type="button" data-build-flow="ai">AI理解生成流程</button>
              </div>
            `}
            <div class="assign-meta-grid">
              <label>执行方式
                <select id="taskRunMode" data-draft-field="runMode">
                  <option value="single" ${draftFlow.runMode === "single" ? "selected" : ""}>单次执行</option>
                  <option value="scheduled" ${draftFlow.runMode === "scheduled" ? "selected" : ""}>定时执行</option>
                </select>
              </label>
              <label>触发日期
                <input id="taskTriggerDate" type="date" data-draft-field="triggerDate" value="${draftFlow.triggerDate}">
              </label>
              <label>触发时间
                <input id="taskTriggerTime" type="time" data-draft-field="triggerTime" value="${draftFlow.triggerTime}">
              </label>
              <label>间隔/条件
                <input id="taskTriggerRule" data-draft-field="triggerRule" value="${escapeAttr(draftFlow.triggerRule)}" placeholder="例如：每天、每周五、监测日报入库后">
              </label>
              <label>抄送人
                <input id="taskCcInput" data-draft-field="cc" value="${escapeAttr(draftFlow.cc)}" placeholder="默认项目经理，可多人">
              </label>
              <div class="trigger-preview">触发说明：${taskTriggerText(draftFlow)}</div>
            </div>
          </form>
        </section>
        <section class="surface flow-editor">
          <div class="section-heading compact no-pad">
            <div>
              <h3>流程定义</h3>
              <p>节点可直接修改，所需材料可留空。</p>
            </div>
            <div class="toolbar">
              <button type="button" data-add-flow-step>新增节点</button>
              <button type="button" data-build-flow="type">重置为模板流程</button>
              <button type="submit" form="assignTaskForm">生成任务草稿</button>
            </div>
          </div>
          ${renderFlowLine(draftFlow.steps)}
          ${renderEditableFlowCards(draftFlow.steps)}
        </section>
      </div>
    `;
  }

  function bindTaskPanelActions() {
    $$("[data-manage-dispose]").forEach((button) => button.addEventListener("click", () => {
      selectedTaskDispositionId = button.dataset.manageDispose;
      taskDispositionOpen = true;
      renderTaskPanel();
    }));
    $("[data-close-task-disposition]")?.addEventListener("click", () => { taskDispositionOpen = false; renderTaskPanel(); });
    $$("[data-task-page-action]").forEach((button) => button.addEventListener("click", () => handleTaskPageAction(button.dataset.task, button.dataset.taskPageAction)));
    $$("[data-wechat-remind]").forEach((button) => button.addEventListener("click", () => sendWechatReminder(button.dataset.wechatRemind)));
    $$("[data-history-task]").forEach((button) => button.addEventListener("click", () => {
      selectedHistoryTaskId = button.dataset.historyTask;
      historyTaskDetailOpen = true;
      renderTaskPanel();
    }));
    const historyForm = $("#historySearchForm");
    if (historyForm) {
      historyForm.addEventListener("submit", (event) => {
        event.preventDefault();
        historyFilter = { name: $("#historyName").value.trim(), start: $("#historyStart").value, end: $("#historyEnd").value };
        selectedHistoryTaskId = "";
        renderTaskPanel();
      });
    }
    $$("#flowCards [data-flow-field]").forEach((input) => input.addEventListener("input", () => {
      draftFlow.steps[Number(input.dataset.stepIndex)][input.dataset.flowField] = input.value;
      renderFlowPreviewOnly();
    }));
    $$("[data-draft-field]").forEach((input) => {
      const update = () => {
        draftFlow[input.dataset.draftField] = input.value;
        const preview = $(".trigger-preview");
        if (preview) preview.textContent = `触发说明：${taskTriggerText(draftFlow)}`;
      };
      input.addEventListener("input", update);
      input.addEventListener("change", update);
    });
    $$("[data-assign-mode]").forEach((button) => button.addEventListener("click", () => {
      assignMode = button.dataset.assignMode;
      renderTaskPanel();
    }));
    $$("[data-remove-flow-step]").forEach((button) => button.addEventListener("click", () => {
      if (draftFlow.steps.length > 1) draftFlow.steps.splice(Number(button.dataset.removeFlowStep), 1);
      renderTaskPanel();
    }));
    const assignForm = $("#assignTaskForm");
    if (assignForm) {
      $$("[data-build-flow='type']").forEach((button) => button.addEventListener("click", () => {
        draftFlow = createDraftFlow($("#taskTypeSelect")?.value || draftFlow.type, $("#taskTopicInput")?.value.trim() || draftFlow.topic || "新建任务");
        renderTaskPanel();
      }));
      $$("[data-build-flow='ai']").forEach((button) => button.addEventListener("click", () => {
        const text = $("#taskNaturalInput")?.value || $("#taskTopicInput")?.value || "AI生成任务";
        draftFlow = createDraftFlow(inferTaskType(text), inferTaskTitle(text), true);
        draftFlow.runMode = text.includes("每天") || text.includes("每周") || text.includes("定时") ? "scheduled" : draftFlow.runMode;
        draftFlow.triggerRule = inferTriggerRule(text);
        renderTaskPanel();
      }));
      $("[data-add-flow-step]").addEventListener("click", () => {
        draftFlow.steps.push({ name: "新增节点", owner: currentTaskUser, dueDate: "2026-06-21", status: "未开始", material: "" });
        renderTaskPanel();
      });
      assignForm.addEventListener("submit", (event) => {
        event.preventDefault();
        createTaskFromDraft();
      });
    }
  }

  function renderFlowPreviewOnly() {
    const editor = $(".flow-editor");
    if (editor) {
      editor.querySelector(".flow-line").outerHTML = renderFlowLine(draftFlow.steps);
    }
  }

  function aiPushTasks() {
    return byProject(tasks).filter((task) => task.needsInfo || isOverdue(task) || ["待处理", "待整改", "待确认"].includes(task.status));
  }

  function isTaskClosed(task) {
    return task.status === "已完成" || task.status === "已关闭" || task.closure === "已闭环";
  }

  function currentStep(task) {
    return task.steps?.[task.currentStepIndex] || task.steps?.[0] || null;
  }

  function taskCurrentOwner(task) {
    return currentStep(task)?.owner || task.owner;
  }

  function isTaskRelatedToCurrentUser(task) {
    return isCurrentUserPrincipal(task.owner) || isCurrentUserPrincipal(task.supervisor) || task.steps?.some((step) => isCurrentUserPrincipal(step.owner));
  }

  function isWaitingForCurrentUser(task) {
    return !isTaskClosed(task) && isCurrentUserPrincipal(taskCurrentOwner(task)) && aiPushTasks().includes(task);
  }

  function renderActionTaskCard(task, actionable) {
    const step = currentStep(task);
    return `
      <article class="task-action-card ${actionable ? "actionable compact" : ""}">
        <div class="question-meta">${task.type} · ${task.status} · 监督人：${task.supervisor || "-"}</div>
        <h4>${task.title}</h4>
        <p>当前节点：${step?.name || task.phase} · ${taskCurrentOwner(task)} · 截止 ${step?.dueDate || task.dueDate}</p>
        ${actionable ? "" : `<p>闭环状态：${task.closure}；材料：${step?.material || task.material}</p>`}
        ${actionable ? `<button type="button" data-manage-dispose="${task.id}">处置</button>` : renderFlowLine(task.steps)}
      </article>
    `;
  }

  function renderTaskManageDisposition(task) {
    if (!task) return `<div class="empty-state">选择待处理任务后进行处置。</div>`;
    return `
      <div class="disposition-head">
        <span>${task.type} · ${currentStep(task)?.name || task.phase}</span>
        <strong>${task.title}</strong>
        <small>${task.status} · ${taskCurrentOwner(task)} · 截止 ${currentStep(task)?.dueDate || task.dueDate}</small>
      </div>
      <textarea id="tmDispositionReply" rows="4" placeholder="回复AI，例如：已完成复核，照片符合要求"></textarea>
      <div class="disposition-tools">
        <label class="file-action">
          <input id="tmDispositionAttachment" type="file" multiple>
          <span>提交文件/图片</span>
        </label>
        <select id="tmDispositionForward">
          <option value="">转交其他同事</option>
          <option>王经理</option>
          <option>张工</option>
          <option>安全员</option>
          <option>资料员</option>
          <option>施工单位</option>
          <option>监测单位</option>
        </select>
      </div>
      <div class="disposition-actions">
        <button type="button" data-task-page-action="reply" data-task="${task.id}">回复AI</button>
        <button type="button" data-task-page-action="forward" data-task="${task.id}">转交</button>
        <button type="button" data-task-page-action="discussion" data-task="${task.id}">发起讨论</button>
      </div>
    `;
  }

  function handleTaskPageAction(taskId, action) {
    const task = tasks.find((item) => item.id === taskId);
    const reply = $("#tmDispositionReply")?.value.trim();
    const forwardTo = $("#tmDispositionForward")?.value;
    if (action === "forward") {
      if (!forwardTo) return showTaskNotice(`请选择要转交的同事或单位。任务：${task.title}`);
      task.previousOwner = taskCurrentOwner(task);
      task.owner = forwardTo;
      if (currentStep(task)) currentStep(task).owner = forwardTo;
      showTaskNotice(`已模拟转交：${task.title} 转交给 ${forwardTo}`);
      renderAll();
      return;
    }
    if (action === "discussion") {
      showTaskNotice(`已模拟把“${task.title}”带入AI群讨论。`);
      switchView("discussion");
      return;
    }
    showTaskNotice(`已记录处置反馈：${task.title}；${reply || "已收到，稍后补充。"}`);
    if ($("#tmDispositionReply")) $("#tmDispositionReply").value = "";
  }

  function renderOverdueTaskCard(task) {
    const step = currentStep(task);
    const days = Math.max(Math.ceil((today - new Date(`${step?.dueDate || task.dueDate}T23:59:59`)) / 86400000), 1);
    return `
      <article class="task-action-card overdue-card">
        <div class="question-meta">${task.type} · 逾期${days}天</div>
        <h4>${task.title}</h4>
        <p>卡在：${step?.name || task.phase}；责任人：${step?.owner || task.owner}；截止：${step?.dueDate || task.dueDate}</p>
        <button type="button" data-wechat-remind="${task.id}">发送微信提醒</button>
      </article>
    `;
  }

  function sendWechatReminder(taskId) {
    const task = tasks.find((item) => item.id === taskId);
    const step = currentStep(task);
    showTaskNotice(`已模拟向 ${step?.owner || task.owner} 发送微信提醒：${task.title} 已逾期，请尽快处理。`);
  }

  function showTaskNotice(message) {
    taskNotice = message;
    addMessage("assistant", message);
    renderTaskPanel();
  }

  function matchesHistoryFilter(task) {
    if (historyFilter.name && !task.title.includes(historyFilter.name)) return false;
    if (historyFilter.start && task.dueDate < historyFilter.start) return false;
    if (historyFilter.end && task.dueDate > historyFilter.end) return false;
    return true;
  }

  function renderHistoryTaskCard(task) {
    return `
      <button type="button" class="history-task-card" data-history-task="${task.id}">
        <strong>${task.title}</strong>
        <span>${task.type} · ${task.status} · ${task.dueDate}</span>
        <em>查看详情 →</em>
      </button>
    `;
  }

  function renderTaskFlowDetail(task, editable) {
    return `
      <p class="muted">${task.type} · ${task.status} · 闭环状态：${task.closure}${task.cc ? ` · 抄送：${task.cc}` : ""}${task.runMode ? ` · ${task.runMode === "scheduled" ? "定时任务" : "单次任务"}` : ""}</p>
      ${renderFlowLine(task.steps)}
      ${editable ? renderEditableFlowCards(task.steps) : renderReadonlyFlowCards(task.steps)}
      <div class="source-ref">来源：${sourceNames(task.sourceIds)}</div>
      ${renderLinkedFiles(task)}
    `;
  }

  function renderLinkedFiles(task) {
    const linked = taskLinkedDocs(task);
    return `
      <section class="linked-files">
        <h4>关联文件</h4>
        ${linked.length ? `<div class="linked-file-grid">${linked.map((doc) => `
          <article class="linked-file-card">
            <strong>${doc.name}</strong>
            <span>${doc.type} · ${doc.status}</span>
            <p>${doc.links}</p>
          </article>
        `).join("")}</div>` : `<div class="empty-state">暂无直接关联文件。</div>`}
      </section>
    `;
  }

  function taskLinkedDocs(task) {
    const sourceIds = new Set(task.sourceIds || []);
    return byProject(docs).filter((doc) => sourceIds.has(doc.sourceId) || task.steps?.some((step) => step.material && doc.name.includes(step.material)));
  }

  function renderFlowLine(steps = []) {
    return `<div class="flow-line">${steps.map((step, index) => `<span class="flow-node ${flowStatusClass(step.status)}">${step.name}</span>${index < steps.length - 1 ? `<span class="flow-arrow">→</span>` : ""}`).join("")}</div>`;
  }

  function renderReadonlyFlowCards(steps = []) {
    return `<div class="flow-card-grid">${steps.map((step) => `
      <article class="flow-step-card">
        <strong>${step.name}</strong>
        <p>责任人：${step.owner}</p>
        <p>截止时间：${step.dueDate}</p>
        <p>状态：${step.status}</p>
        <p>材料/证据：${step.material || "无"}</p>
      </article>
    `).join("")}</div>`;
  }

  function renderEditableFlowCards(steps = []) {
    return `<div id="flowCards" class="flow-card-grid editable-flow">${steps.map((step, index) => `
      <article class="flow-step-card">
        <label>节点名称<input data-step-index="${index}" data-flow-field="name" value="${escapeAttr(step.name)}"></label>
        <label>责任人<input data-step-index="${index}" data-flow-field="owner" value="${escapeAttr(step.owner)}"></label>
        <label>截止时间<input type="date" data-step-index="${index}" data-flow-field="dueDate" value="${step.dueDate}"></label>
        <label>所需材料<input data-step-index="${index}" data-flow-field="material" value="${escapeAttr(step.material)}" placeholder="可为空"></label>
        <button type="button" data-remove-flow-step="${index}">删除节点</button>
      </article>
    `).join("")}</div>`;
  }

  function flowStatusClass(status) {
    if (status === "已完成" || status === "已反馈") return "complete";
    if (status === "逾期") return "overdue";
    if (status === "待处理" || status === "进行中") return "active";
    return "";
  }

  function createDraftFlow(type, topic, fromAi = false) {
    const flowType = type || "自定义";
    const title = topic || `${flowType}任务`;
    const templates = {
      条件核查: ["发起核查", "现场复核", "负责人确认", "资料归档"],
      隐患整改: ["发现隐患", "派单整改", "安全员复核", "闭环归档"],
      资料补全: ["识别缺失", "补齐资料", "复核资料", "归档"],
      风险处置: ["风险触发", "数据复核", "处置确认", "风险关闭"],
      报告审核: ["提交报告", "依据审核", "问题修订", "审核通过"],
      自定义: ["发起任务", "执行处理", "复核确认", "闭环归档"],
    };
    const owners = ["AI", "施工单位", currentTaskUser, "资料员"];
    return {
      type: flowType,
      topic: title,
      fromAi,
      runMode: fromAi && title.includes("每") ? "scheduled" : "single",
      triggerDate: "2026-06-20",
      triggerTime: "09:00",
      triggerRule: fromAi ? inferTriggerRule(title) : "到达触发时间后执行",
      cc: "项目经理",
      steps: (templates[flowType] || templates.自定义).map((name, index) => ({
        name,
        owner: owners[index] || currentTaskUser,
        dueDate: `2026-06-${20 + index}`,
        status: index === 0 ? "待处理" : "未开始",
        material: index === 0 ? "任务说明" : "",
      })),
    };
  }

  function createTaskFromDraft() {
    const newTask = {
      id: `task-${Date.now()}`,
      projectId: selectedProjectId,
      title: draftFlow.topic,
      owner: draftFlow.steps[0]?.owner || currentTaskUser,
      supervisor: currentTaskUser,
      cc: draftFlow.cc || "项目经理",
      previousOwner: "任务布置人",
      createdBy: "任务布置人",
      flowType: draftFlow.type,
      runMode: draftFlow.runMode,
      triggerDate: draftFlow.triggerDate,
      triggerTime: draftFlow.triggerTime,
      triggerRule: draftFlow.triggerRule,
      dueDate: draftFlow.steps.at(-1)?.dueDate || "2026-06-23",
      status: "待确认",
      type: draftFlow.type,
      sourceIds: [],
      needsInfo: true,
      phase: draftFlow.steps[0]?.name || "启动",
      material: draftFlow.steps[0]?.material || "无",
      closure: "未闭环",
      currentStepIndex: 0,
      steps: draftFlow.steps.map((step) => ({ ...step })),
    };
    tasks.unshift(newTask);
    selectedPushTaskId = newTask.id;
    showTaskNotice(`已生成任务草稿：${newTask.title}`);
    draftFlow = createDraftFlow("隐患整改", "整改现场隐患并完成复核闭环");
    currentTaskTab = "mine";
    $$("#taskTabs .tab-button").forEach((item) => item.classList.toggle("active", item.dataset.taskTab === "mine"));
    renderAll();
  }

  function taskTriggerText(flow) {
    if (flow.runMode === "scheduled") {
      return `${flow.triggerRule || "按设定间隔"}，${flow.triggerTime || "09:00"} 执行`;
    }
    return `${flow.triggerDate || "待定日期"} ${flow.triggerTime || "09:00"} 单次执行`;
  }

  function escapeAttr(value = "") {
    return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
  }

  function renderDocs() {
    $$("#docsTabs .tab-button").forEach((button) => button.addEventListener("click", () => {
      currentDocsTab = button.dataset.docsTab;
      $$("#docsTabs .tab-button").forEach((item) => item.classList.toggle("active", item === button));
      renderDocsPanel();
    }));
    renderDocsPanel();
  }

  function renderDocsPanel() {
    $$("#docsTabs .tab-button").forEach((button) => button.classList.toggle("active", button.dataset.docsTab === currentDocsTab));
    const candidate = similarDocCandidate(intakeFileName, intakeLibrary);
    const selectedFolder = currentIntakeFolder();
    const folderDocs = selectedFolderDocuments();
    const upload = `
      <div class="knowledge-explorer">
        <aside class="knowledge-tree-panel">
          ${renderDirectoryTree()}
        </aside>
        <section class="knowledge-intake-stack">
          <section class="knowledge-file-panel">
            <div class="file-panel-head">
              <div>
                <h3>${selectedFolder.name}</h3>
                <p>${selectedFolder.desc}</p>
                <div class="folder-path">实际存储路径：${currentFolderPath()}</div>
              </div>
              <button type="button" class="secondary" data-open-folder-create>新建子目录</button>
            </div>
            <div class="drop-zone">
              <strong>上传文件到当前目录</strong>
              <span>文件上传后，Dobby 会识别文件内容、推荐归档位置并提示版本处理方式。</span>
              <div class="upload-inline">
                <input id="intakeFileName" value="${escapeAttr(intakeFileName)}" placeholder="例如：基坑监测日报.xlsx">
                <button type="button" data-simulate-upload>上传并开始诊断</button>
              </div>
            </div>
            <div class="current-folder-files-head">
              <div>
                <h4>当前目录文件</h4>
                <span>共 ${folderDocs.length} 份资料</span>
              </div>
              <span>${currentFolderPath()}</span>
            </div>
            <div class="current-folder-file-list">
              ${folderDocs.length ? folderDocs.map(renderResourceFileCard).join("") : `<div class="empty-state">当前文件夹暂无资料。上传文件后可由 Dobby 诊断并确认归档。</div>`}
            </div>
          </section>
          ${intakeNotice ? `<div class="task-notice">${intakeNotice}</div>` : ""}
        </section>
      </div>
      ${folderCreateOpen ? renderFolderCreateModal(selectedFolder) : ""}
      ${intakeDiagnosisOpen ? renderIntakeDiagnosis(selectedFolder, candidate) : ""}`;
    const project = renderProjectDocumentSearch();
    $("#docsPanel").innerHTML = { upload, project }[currentDocsTab] || project;
    bindKnowledgePanelActions();
  }

  function infoStatusClass(status) {
    if (["待确认", "待复核"].includes(status)) return "pending";
    if (["已入库", "已确认"].includes(status)) return "archived";
    if (["已否认"].includes(status)) return "denied";
    return "revised";
  }

  function renderFolderCreateModal(selectedFolder) {
    return `<div class="intake-modal-backdrop" role="presentation">
      <section class="folder-create-modal" role="dialog" aria-modal="true" aria-labelledby="folderCreateTitle">
        <div class="intake-modal-head">
          <div>
            <span>目录管理</span>
            <h3 id="folderCreateTitle">新建子目录</h3>
          </div>
          <button type="button" class="modal-icon-close" data-cancel-folder-create aria-label="关闭新建子目录弹窗">×</button>
        </div>
        <p class="folder-create-tip">将在“${selectedFolder.name}”下创建新目录。</p>
        <form id="folderCreateForm" class="folder-create-form">
          <label for="customFolderName">目录名称</label>
          <input id="customFolderName" placeholder="例如：2026年7月监测日报" autofocus>
          <div class="intake-modal-actions">
            <button type="button" class="secondary" data-cancel-folder-create>取消</button>
            <button type="submit">创建目录</button>
          </div>
        </form>
      </section>
    </div></div>`;
  }

  function renderProjectBasicConfigModal() {
    const portal = document.getElementById("projectBasicConfigPortal") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "projectBasicConfigPortal" }));
    if (!projectBasicConfigOpen) { portal.innerHTML = ""; return; }
    const project = creatingNewProject ? { name: "", type: "", stage: "" } : currentProject();
    portal.innerHTML = `<div class="intake-modal-backdrop" role="presentation"><section class="project-basic-config-modal" role="dialog" aria-modal="true"><form id="engineeringBasicForm" class="engineering-basic-form"><div class="intake-modal-head"><div><span>项目基础信息</span><h3>项目配置保存</h3></div><button type="button" class="modal-icon-close" data-close-project-basic-config aria-label="关闭项目配置">×</button></div><label>项目名称<input id="engineeringProjectName" value="${escapeAttr(project.name)}" placeholder="请输入项目名称"></label><label>工程类型<input id="engineeringProjectType" value="${escapeAttr(project.type)}" placeholder="例如：房屋建筑工程"></label><label>项目阶段<select id="engineeringProjectStage"><option value="" ${!project.stage ? "selected" : ""} disabled>请选择项目阶段</option><option ${project.stage === "施工阶段" ? "selected" : ""}>施工阶段</option><option ${project.stage === "准备阶段" ? "selected" : ""}>准备阶段</option><option ${project.stage === "竣工阶段" ? "selected" : ""}>竣工阶段</option></select></label><div class="intake-modal-actions"><button type="button" class="secondary" data-close-project-basic-config>取消</button><button type="submit">保存配置</button></div></form></section></div>`;
    portal.querySelectorAll("[data-close-project-basic-config]").forEach((button) => button.addEventListener("click", () => { projectBasicConfigOpen = false; renderProjectBasicConfigModal(); }));
    portal.querySelector("#engineeringBasicForm")?.addEventListener("submit", (event) => { event.preventDefault(); const name = portal.querySelector("#engineeringProjectName").value.trim(); const type = portal.querySelector("#engineeringProjectType").value.trim(); const stage = portal.querySelector("#engineeringProjectStage").value; if (!name || !type || !stage) return; let project = currentProject(); if (creatingNewProject) { project = { id: `project-${Date.now()}`, name, type, stage, manager: "待配置", status: "基础资料待完善", aliases: [], requiredDocs: [] }; projects.push(project); selectedProjectId = project.id; } else { project.name = name; project.type = type; project.stage = stage; } creatingNewProject = false; projectBasicConfigOpen = false; engineeringSettingsMode = "config"; switchView("settings"); renderEngineeringSettings(); });
  }

  function renderIntakeDiagnosis(selectedFolder, candidate) {
    const recommendation = recommendFolder(intakeFileName, intakeLibrary);
    const recommendedPath = currentFolderPath(intakeLibrary, recommendation.id);
    const currentPath = currentFolderPath();
    return `<div class="intake-modal-backdrop" role="presentation">
      <section class="intake-diagnosis-modal" role="dialog" aria-modal="true" aria-labelledby="intakeDiagnosisTitle">
        <div class="intake-modal-head">
          <div>
            <span>文件上传完成</span>
            <h3 id="intakeDiagnosisTitle">Dobby AI 归档诊断</h3>
          </div>
          <button type="button" class="secondary" data-close-intake-diagnosis aria-label="关闭诊断">关闭</button>
        </div>
        <div class="diagnosis-file-summary">
          <strong>${intakeFileName}</strong>
          <span>当前上传目录：${selectedFolder.name}</span>
        </div>
        <div class="diagnosis-grid">
          <section>
            <h4>推荐归档位置</h4>
            <p>${recommendedPath}</p>
            <small>${recommendation.reason}</small>
            ${recommendation.id !== intakeFolderId ? `<button type="button" class="secondary" data-apply-ai-folder="${recommendation.id}">采用推荐目录</button>` : `<span class="recommendation-current">当前目录已匹配</span>`}
          </section>
          <section>
            <h4>版本判断</h4>
            ${candidate ? `<p>发现相似文件：<strong>${candidate.name}</strong></p><small>建议作为 ${nextVersion(candidate.version)} 版本入库，保留原版本记录。</small>` : `<p>未发现相似文件</p><small>建议作为新文件建立 V1.0 初始版本。</small>`}
          </section>
        </div>
        <div class="ai-confirm-fields">
          <label>文件内容描述<input id="intakeDescription" placeholder="描述文件内容、适用范围或关联工序"></label>
          <label>版本说明<input id="intakeVersionNote" placeholder="例如：补充6月20日监测数据"></label>
        </div>
        <div class="intake-modal-actions">
          <button type="button" class="secondary" data-close-intake-diagnosis>暂不归档</button>
          ${candidate ? `<button type="button" data-confirm-intake="version">确认入库为新版本</button>` : ""}
          <button type="button" data-confirm-intake="new">确认入库为新文件</button>
        </div>
      </section>
    </div>`;
  }

  function renderProjectDocumentSearch() {
    const results = projectDocumentResults();
    if (!results.some((doc) => doc.id === selectedProjectDocId)) selectedProjectDocId = results[0]?.id || "";
    const selectedDoc = results.find((doc) => doc.id === selectedProjectDocId) || fileQueryDocuments()[0];
    return `<div class="project-docs-workspace">
      <form id="projectDocSearchForm" class="project-doc-search surface">
        <div class="doc-search-box">
          <label>文件查询</label>
          <textarea id="projectDocQueryInput" rows="3" placeholder="描述想找的内容，例如：我想看深基坑支护方案、S3监测数据，以及相关预警阈值规则。">${escapeAttr(projectDocQuery)}</textarea>
        </div>
        <label>文件类型
          <select id="projectDocTypeFilter">
            <option value="all" ${projectDocTypeFilter === "all" ? "selected" : ""}>全部类型</option>
            ${projectDocumentTypes().map((type) => `<option value="${type}" ${projectDocTypeFilter === type ? "selected" : ""}>${type}</option>`).join("")}
          </select>
        </label>
        <label>目录范围
          <select id="projectDocFolderFilter">
            <option value="all" ${projectDocFolderFilter === "all" ? "selected" : ""}>全部文件目录</option>
            ${fileQueryFolderOptions()}
          </select>
        </label>
        <button type="submit">AI查找文件</button>
      </form>
      <div class="project-doc-layout">
        <section class="project-doc-results surface">
          <div class="result-head">
            <div>
              <h3>检索结果</h3>
              <p>当前项目工程资料 + 工程知识库</p>
            </div>
            <span>${results.length} 个文件</span>
          </div>
          <div class="project-doc-list">
            ${results.length ? results.map(renderProjectDocumentResult).join("") : `<div class="empty-state">未找到匹配文件，可换一种描述，或调整类型与目录范围。</div>`}
          </div>
        </section>
        ${renderProjectDocumentPreview(selectedDoc)}
      </div>
      ${projectDocNotice ? `<div class="task-notice">${projectDocNotice}</div>` : ""}
    </div>`;
  }

  function renderProjectDocumentResult(doc) {
    const selected = doc.id === selectedProjectDocId;
    return `<button type="button" class="project-doc-row ${selected ? "selected" : ""}" data-project-doc="${doc.id}">
      <div class="project-doc-main">
        <strong>${doc.name}</strong>
        <span>${doc.type} · ${doc.version || "V1.0"} · ${documentUpdatedAt(doc)}</span>
      </div>
      <p>${documentStoragePath(doc)}</p>
      <div class="doc-result-meta">
        <span>${documentMatchReason(doc, projectDocQuery)}</span>
        <span class="permission-badge ${permissionClass(documentPermission(doc))}">${documentPermission(doc)}</span>
      </div>
    </button>`;
  }

  function renderProjectDocumentPreview(doc) {
    if (!doc) return `<aside class="doc-preview-panel surface"><div class="empty-state">点击左侧文件后查看摘要、路径、版本和权限。</div></aside>`;
    const permission = documentPermission(doc);
    const canDownload = permission === "可下载";
    return `<aside class="doc-preview-panel surface">
      <div class="preview-head">
        <div>
          <h3>${doc.name}</h3>
          <p>${doc.type} · ${doc.status || "已入库"} · ${doc.version || "V1.0"}</p>
        </div>
        <span class="permission-badge ${permissionClass(permission)}">${permission}</span>
      </div>
      <div class="doc-summary-block">
        <strong>AI摘要</strong>
        <p>${documentSummary(doc)}</p>
      </div>
      <dl class="doc-preview-meta">
        <div><dt>实际路径</dt><dd>${documentStoragePath(doc)}</dd></div>
        <div><dt>版本说明</dt><dd>${doc.versionNote || "初始版本"}</dd></div>
        <div><dt>更新时间</dt><dd>${documentUpdatedAt(doc)}</dd></div>
        <div><dt>关联证据</dt><dd>${doc.sourceId ? sourceNames([doc.sourceId]) : "暂无来源记录"}</dd></div>
        <div><dt>关联对象</dt><dd>${doc.links || "暂无关联任务或风险"}</dd></div>
      </dl>
      <div class="doc-preview-actions">
        <button type="button" data-doc-action="${doc.id}" ${canDownload ? "" : "class=\"secondary\""}>${canDownload ? "下载原始文件" : "申请权限"}</button>
        <button type="button" class="secondary">预览文件摘要</button>
      </div>
    </aside>`;
  }

  function renderIntegratedDocumentSearch() {
    const groups = integratedSearchGroups();
    return `<div class="integrated-doc-search">
      <form id="integratedDocSearchForm" class="integrated-search-form surface">
        <div class="doc-search-box">
          <label>综合资料查询</label>
          <input id="integratedDocQueryInput" value="${escapeAttr(integratedDocQuery)}" placeholder="跨工程资料、制度知识、AI整理成果查询">
        </div>
        <button type="submit">综合查询</button>
      </form>
      <div class="integrated-result-groups">
        ${groups.map((group) => `<section class="integrated-group surface">
          <div class="result-head"><h3>${group.title}</h3><span>${group.items.length} 条</span></div>
          <div class="integrated-list">
            ${group.items.length ? group.items.map(renderIntegratedResult).join("") : `<div class="empty-state">暂无匹配结果</div>`}
          </div>
        </section>`).join("")}
      </div>
    </div>`;
  }

  function renderIntegratedResult(item) {
    const action = item.kind === "原始工程文件"
      ? `<button type="button" data-open-project-doc="${item.id}">查看原始文件</button>`
      : `<button type="button" class="secondary">查看摘要</button>`;
    return `<article class="integrated-result">
      <div>
        <strong>${item.name}</strong>
        <p>${item.meta}</p>
        <span>${item.content}</span>
      </div>
      ${action}
    </article>`;
  }

  function bindKnowledgePanelActions() {
    const projectSearchForm = $("#projectDocSearchForm");
    if (projectSearchForm) projectSearchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      projectDocQuery = $("#projectDocQueryInput")?.value.trim() || "";
      projectDocTypeFilter = $("#projectDocTypeFilter")?.value || "all";
      projectDocFolderFilter = $("#projectDocFolderFilter")?.value || "all";
      projectDocNotice = `AI已在当前项目工程资料和工程知识库中完成检索：${projectDocQuery || "全部文件"}`;
      renderDocsPanel();
    });
    $$("[data-project-doc]").forEach((button) => button.addEventListener("click", () => {
      selectedProjectDocId = button.dataset.projectDoc;
      projectDocNotice = "";
      renderDocsPanel();
    }));
    $$("[data-doc-action]").forEach((button) => button.addEventListener("click", () => {
      const doc = findAnyDocument(button.dataset.docAction);
      if (!doc) return;
      const permission = documentPermission(doc);
      projectDocNotice = permission === "可下载"
        ? `已模拟下载原始文件：${doc.name}`
        : `已提交权限申请：${doc.name}`;
      renderDocsPanel();
    }));
    $$("[data-tree-toggle]").forEach((button) => button.addEventListener("click", () => {
      const key = button.dataset.treeToggle;
      if (openTreeNodes.has(key)) openTreeNodes.delete(key);
      else openTreeNodes.add(key);
      renderDocsPanel();
    }));
    $$("[data-folder-select]").forEach((button) => button.addEventListener("click", () => {
      intakeLibrary = button.dataset.library;
      intakeFolderId = button.dataset.folderSelect;
      intakeNotice = "";
      intakeDiagnosisOpen = false;
      folderCreateOpen = false;
      renderDocsPanel();
    }));
    const fileInput = $("#intakeFileName");
    if (fileInput) fileInput.addEventListener("change", () => {
      intakeFileName = fileInput.value.trim();
      renderDocsPanel();
    });
    const simulateUpload = $("[data-simulate-upload]");
    if (simulateUpload) simulateUpload.addEventListener("click", () => {
      intakeFileName = $("#intakeFileName")?.value.trim() || "";
      if (!intakeFileName) {
        intakeNotice = "请先选择或填写要上传的文件名。";
        renderDocsPanel();
        return;
      }
      intakeNotice = "";
      intakeDiagnosisOpen = true;
      renderDocsPanel();
    });
    $$("[data-close-intake-diagnosis]").forEach((button) => button.addEventListener("click", () => {
      intakeDiagnosisOpen = false;
      renderDocsPanel();
    }));
    $$("[data-apply-ai-folder]").forEach((button) => button.addEventListener("click", () => {
      const recommendation = recommendFolder(intakeFileName, intakeLibrary);
      intakeFolderId = button.dataset.applyAiFolder;
      intakeNotice = `已采用 AI 推荐目录：${recommendation.name}。`;
      renderDocsPanel();
    }));
    $$("[data-confirm-intake]").forEach((button) => button.addEventListener("click", () => {
      intakeFileName = $("#intakeFileName")?.value.trim() || intakeFileName;
      const candidate = similarDocCandidate(intakeFileName, intakeLibrary);
      const choice = button.dataset.confirmIntake;
      const description = $("#intakeDescription")?.value.trim();
      const versionNote = $("#intakeVersionNote")?.value.trim();
      pendingIntakeAction = choice;
      if (choice === "version" && candidate) {
        const version = nextVersion(candidate.version);
        candidate.folderId = intakeFolderId;
        candidate.version = version;
        candidate.versionNote = versionNote || "用户确认的新版本";
        candidate.description = description || candidate.description || "用户入库资料";
        candidate.status = candidate.status === "缺失" ? "已入库" : candidate.status || "已入库";
        candidate.versions = [...(candidate.versions || []), `${version} ${candidate.versionNote}`];
        intakeNotice = `已确认入库：${intakeFileName} 将作为 ${candidate.name} 的新版本，并形成版本包。`;
      } else {
        const doc = {
          id: `intake-${intakeDocSequence++}`,
          projectId: selectedProjectId,
          library: intakeLibrary,
          folderId: intakeFolderId,
          name: intakeFileName,
          type: intakeLibrary === "knowledge" ? "知识资料" : "工程资料",
          status: intakeLibrary === "knowledge" ? "启用" : "已入库",
          version: "V1.0",
          versionNote: versionNote || "用户确认入库",
          description: description || "用户直接入库资料",
          scope: intakeLibrary === "knowledge" ? "通用" : undefined,
          versions: ["V1.0"],
        };
        (intakeLibrary === "knowledge" ? knowledgeDocs : docs).push(doc);
        intakeNotice = `已确认入库：${intakeFileName} 已作为新文件保存到 ${folderName(intakeFolderId)}。`;
      }
      intakeDiagnosisOpen = false;
      renderDocsPanel();
    }));
    const openFolderCreate = $("[data-open-folder-create]");
    if (openFolderCreate) openFolderCreate.addEventListener("click", () => {
      folderCreateOpen = true;
      renderDocsPanel();
    });
    const cancelFolderCreate = $("[data-cancel-folder-create]");
    if (cancelFolderCreate) cancelFolderCreate.addEventListener("click", () => {
      folderCreateOpen = false;
      renderDocsPanel();
    });
    const folderCreateForm = $("#folderCreateForm");
    if (folderCreateForm) folderCreateForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const library = intakeLibrary;
      const name = $("#customFolderName")?.value.trim();
      const desc = "用户自定义文件夹";
      if (!name) {
        intakeNotice = "请输入要新增的文件夹名称。";
        renderDocsPanel();
        return;
      }
      const target = libraryFolders(library);
      const parentId = intakeFolderId;
      const id = `${library === "project" ? "p" : "k"}x${intakeFolderSequence++}`;
      target.push({ id, name, desc: `${desc}，位于 ${folderName(parentId)} 下`, parentId });
      openTreeNodes.add(treeNodeKey(library, parentId));
      intakeLibrary = library;
      intakeFolderId = id;
      folderCreateOpen = false;
      intakeNotice = `已新增文件夹：${name}。`;
      renderDocsPanel();
    });
  }

  function currentIntakeFolder() {
    const folders = libraryFolders(intakeLibrary);
    return folders.find((folder) => folder.id === intakeFolderId) || folders[0] || { id: "", name: "未选择目录", desc: "请先选择资料库目录。" };
  }

  function selectedFolderDocuments() {
    const documents = intakeLibrary === "knowledge"
      ? knowledgeDocuments()
      : projectLibraryDocuments();
    return documents.filter((doc) => doc.folderId === intakeFolderId);
  }

  function renderDirectoryTree() {
    return `<div class="directory-tree" aria-label="工程资料目录树">
      ${renderToggleTreeNode("root:project", "A_项目工程资料库", "tree-root")}
      ${openTreeNodes.has("root:project") ? `<div class="tree-children">
        ${renderToggleTreeNode("project:current", projectStorageFolderName(), "tree-project")}
        ${openTreeNodes.has("project:current") ? `<div class="tree-children">${renderFolderTreeNodes("project")}</div>` : ""}
      </div>` : ""}
      ${renderToggleTreeNode("root:knowledge", "B_工程知识库", "tree-root knowledge-root")}
      ${openTreeNodes.has("root:knowledge") ? `<div class="tree-children">${renderFolderTreeNodes("knowledge")}</div>` : ""}
    </div>`;
  }

  function renderToggleTreeNode(key, label, className) {
    const open = openTreeNodes.has(key);
    return `<button type="button" class="tree-node tree-toggle-node ${className} ${open ? "open" : "collapsed"}" data-tree-toggle="${key}" aria-expanded="${open}">
      <span class="tree-caret">${open ? "▾" : "▸"}</span>
      <span class="folder-glyph"></span>
      <strong>${label}</strong>
    </button>`;
  }

  function renderFolderTreeNodes(library, parentId = "") {
    return libraryFolders(library)
      .filter((folder) => (folder.parentId || "") === parentId)
      .map((folder) => renderFolderTreeNode(folder, library))
      .join("");
  }

  function renderFolderTreeNode(folder, library) {
    const active = folder.id === intakeFolderId && library === intakeLibrary;
    const key = treeNodeKey(library, folder.id);
    const children = libraryFolders(library).filter((item) => item.parentId === folder.id);
    const open = openTreeNodes.has(key);
    return `<div class="tree-branch">
      <div class="tree-row">
        ${children.length ? `<button type="button" class="tree-caret-button" data-tree-toggle="${key}" aria-expanded="${open}">${open ? "▾" : "▸"}</button>` : `<span class="tree-caret-spacer"></span>`}
        <button type="button" class="tree-node tree-folder ${active ? "active" : ""}" data-folder-select="${folder.id}" data-library="${library}">
          <span class="folder-glyph"></span>
          <span class="tree-node-main">
            <strong>${folder.name}</strong>
            <span>${folder.desc}</span>
          </span>
        </button>
      </div>
      ${children.length && open ? `<div class="tree-children">${renderFolderTreeNodes(library, folder.id)}</div>` : ""}
    </div>`;
  }

  function treeNodeKey(library, folderId) {
    return `${library}:${folderId}`;
  }

  function projectCode(project = currentProject()) {
    return ({ "zhiru-health": "ZR-2026-001", "building-3": "B3-2026-001", "pipe-network": "PN-2026-001" })[project.id] || project.id.toUpperCase();
  }

  function projectStorageFolderName(project = currentProject()) {
    return `${project.name}_${projectCode(project)}`;
  }

  function currentFolderPath(library = intakeLibrary, folderId = intakeFolderId) {
    const segments = folderPathSegments(library, folderId).join(" / ");
    if (library === "knowledge") return `B_工程知识库 / ${segments}`;
    return `A_项目工程资料库 / ${projectStorageFolderName()} / ${segments}`;
  }

  function folderPathSegments(library, folderId) {
    const folders = libraryFolders(library);
    const segments = [];
    const visited = new Set();
    let current = folders.find((folder) => folder.id === folderId);
    while (current && !visited.has(current.id)) {
      visited.add(current.id);
      segments.unshift(current.name);
      current = folders.find((folder) => folder.id === current.parentId);
    }
    return segments.length ? segments : [folderName(folderId)];
  }

  function renderResourceFileCard(doc) {
    return `<article class="resource-file-card">
      <div class="resource-file-head">
        <strong>${doc.name}</strong>
        <span>${doc.version || "V1.0"}</span>
      </div>
      <p>${doc.description || doc.links || ""}</p>
      <div class="version-meta">${doc.type} · ${doc.status || "启用"} · 版本说明：${doc.versionNote || "初始版本"} · 历史版本：${doc.versions?.length || 1}</div>
    </article>`;
  }

  function renderFolderTree(title, folders, library) {
    return `<div class="folder-tree"><h4>${title}</h4>${folders.map((folder) => `<div class="folder-row ${folder.id === intakeFolderId && library === intakeLibrary ? "active" : ""}"><strong>${folder.name}</strong><span>${folder.desc}</span></div>`).join("")}</div>`;
  }

  function renderFolderCards(folders, documents) {
    return `<div class="folder-card-grid">${folders.map((folder) => {
      const items = documents.filter((doc) => doc.folderId === folder.id);
      return `<article class="folder-card">
        <div class="folder-card-head"><strong>${folder.name}</strong><span>${items.length} 份资料</span></div>
        <p>${folder.desc}</p>
        <div class="doc-version-list">${items.length ? items.map(renderDocVersionCard).join("") : `<div class="empty-state">暂无资料</div>`}</div>
      </article>`;
    }).join("")}</div>`;
  }

  function renderDocVersionCard(doc) {
    return `<div class="doc-version-card">
      <strong>${doc.name}</strong>
      <span>${doc.type} · ${doc.status || "启用"} · 当前版本 ${doc.version || "V1.0"}</span>
      <p>${doc.description || doc.links || ""}</p>
      <div class="version-meta">版本说明：${doc.versionNote || "初始版本"}；历史版本：${doc.versions?.length || 1}</div>
    </div>`;
  }

  function libraryFolders(library) {
    return library === "knowledge" ? knowledgeFolders : projectFolders;
  }

  function folderOptions(library, selectedId) {
    return libraryFolders(library).map((folder) => `<option value="${folder.id}" ${folder.id === selectedId ? "selected" : ""}>${folder.name}</option>`).join("");
  }

  function folderName(folderId) {
    return [...projectFolders, ...knowledgeFolders].find((folder) => folder.id === folderId)?.name || "未分类";
  }

  function projectLibraryDocuments() {
    return byProject(docs).filter((doc) => (doc.library || "project") === "project");
  }

  function fileQueryDocuments() {
    return [...projectLibraryDocuments(), ...knowledgeDocuments()];
  }

  function projectDocumentResults() {
    return fileQueryDocuments().filter((doc) => {
      if (projectDocTypeFilter !== "all" && doc.type !== projectDocTypeFilter) return false;
      if (projectDocFolderFilter !== "all" && `${doc.library || "project"}:${doc.folderId}` !== projectDocFolderFilter) return false;
      return matchesDocumentQuery(doc, projectDocQuery);
    });
  }

  function projectDocumentTypes() {
    return [...new Set(fileQueryDocuments().map((doc) => doc.type))];
  }

  function fileQueryFolderOptions() {
    const projectOptions = projectFolders.map((folder) => `<option value="project:${folder.id}" ${projectDocFolderFilter === `project:${folder.id}` ? "selected" : ""}>工程资料 / ${folder.name}</option>`).join("");
    const knowledgeOptions = knowledgeFolders.map((folder) => `<option value="knowledge:${folder.id}" ${projectDocFolderFilter === `knowledge:${folder.id}` ? "selected" : ""}>工程知识 / ${folder.name}</option>`).join("");
    return `${projectOptions}${knowledgeOptions}`;
  }

  function matchesDocumentQuery(doc, query) {
    const tokens = normalizeSearchTokens(query);
    if (!tokens.length) return true;
    const text = `${doc.name} ${doc.type} ${doc.status || ""} ${doc.description || ""} ${doc.links || ""} ${folderName(doc.folderId)} ${doc.versionNote || ""} ${doc.sourceId ? sourceNames([doc.sourceId]) : ""}`.toLowerCase();
    return tokens.some((token) => text.includes(token));
  }

  function normalizeSearchTokens(query = "") {
    const text = query.toLowerCase();
    const tokens = text.split(/[\s,，、。；;：:]+/).map((item) => item.trim()).filter((item) => item.length >= 2);
    const domainTerms = ["深基坑", "基坑", "支护", "开挖", "监测", "测斜", "预警", "阈值", "规则", "规范", "标准", "方案", "图纸", "合同", "验收", "支撑", "降水", "临边", "防护", "整改", "闭环", "照片", "日报", "会议", "纪要", "风险", "隐患", "质量", "安全"].filter((term) => text.includes(term));
    return [...new Set([...tokens, ...domainTerms])].filter((token) => !["我想", "想看", "需要", "查找", "查询", "相关", "内容", "文件", "资料"].includes(token));
  }

  function documentStoragePath(doc) {
    if (!doc) return "";
    if (doc.library === "knowledge") return `B_工程知识库 / ${folderPathSegments("knowledge", doc.folderId).join(" / ")} / ${doc.name}`;
    const project = projects.find((item) => item.id === doc.projectId) || currentProject();
    return `A_项目工程资料库 / ${projectStorageFolderName(project)} / ${folderPathSegments("project", doc.folderId).join(" / ")} / ${doc.name}`;
  }

  function documentSummary(doc) {
    if (doc.summary) return doc.summary;
    const evidence = doc.sourceId ? `关联来源为 ${sourceNames([doc.sourceId])}` : "暂无来源记录";
    return `AI根据文件名、目录、版本说明和关联记录提炼：${doc.description || doc.links || "该文件用于工程过程管理和追溯"}。${evidence}。`;
  }

  function documentUpdatedAt(doc) {
    if (doc.updatedAt) return doc.updatedAt;
    const record = doc.sourceId ? source(doc.sourceId) : null;
    return record?.time || "2026-06-18 18:00";
  }

  function documentPermission(doc) {
    if (!doc) return "需申请";
    if (doc.permission) return doc.permission;
    if (doc.library === "knowledge") return "可下载";
    if (doc.status === "缺失") return "需申请";
    if (["doc-001", "doc-007", "doc-005"].includes(doc.id)) return "可下载";
    if (["doc-003", "doc-006"].includes(doc.id)) return "需申请";
    return "仅预览";
  }

  function permissionClass(permission) {
    return ({ 可下载: "downloadable", 仅预览: "preview-only", 需申请: "request-needed" })[permission] || "request-needed";
  }

  function documentMatchReason(doc, query) {
    const tokens = normalizeSearchTokens(query);
    if (!tokens.length) return `${doc.library === "knowledge" ? "工程知识库文件" : "当前项目文件"}，位于 ${folderName(doc.folderId)}`;
    const name = doc.name.toLowerCase();
    const type = doc.type.toLowerCase();
    const folder = folderName(doc.folderId).toLowerCase();
    if (tokens.some((token) => name.includes(token))) return "命中文件名";
    if (tokens.some((token) => type.includes(token))) return "命中文件类型";
    if (tokens.some((token) => folder.includes(token))) return "命中目录范围";
    return "命中AI摘要或关联证据";
  }

  function findAnyDocument(id) {
    return [...docs, ...knowledgeDocuments()].find((doc) => doc.id === id);
  }

  function integratedSearchGroups() {
    const aiResults = [
      { id: "ai-result-001", kind: "AI整理成果", name: "深基坑风险与任务闭环摘要", meta: `AI整理成果 · ${currentProject().name}`, content: "汇总S3测斜位移、支撑验收、临边防护整改和未闭环任务，可用于报告草稿。" },
      { id: "ai-result-002", kind: "AI整理成果", name: "资料缺失清单", meta: `AI整理成果 · ${currentProject().name}`, content: "识别支撑验收记录、降水记录连续性等待补资料，并关联责任人和任务。" },
    ];
    const originalFiles = docs.map((doc) => ({
      id: doc.id,
      kind: "原始工程文件",
      name: doc.name,
      meta: `${projects.find((project) => project.id === doc.projectId)?.name || doc.projectId} · ${doc.type} · ${documentPermission(doc)}`,
      content: `${documentStoragePath(doc)}；${documentSummary(doc)}`,
    })).filter((item) => matchesIntegratedItem(item));
    const knowledge = knowledgeDocuments().map((doc) => ({
      id: doc.id,
      kind: "制度知识",
      name: doc.name,
      meta: `${doc.type} · ${doc.scope || "通用"} · ${doc.version || "V1.0"}`,
      content: `${documentStoragePath(doc)}；${doc.description}`,
    })).filter((item) => matchesIntegratedItem(item));
    return [
      { title: "原始工程文件", items: originalFiles },
      { title: "制度知识", items: knowledge },
      { title: "AI整理成果", items: aiResults.filter((item) => matchesIntegratedItem(item)) },
    ];
  }

  function matchesIntegratedItem(item) {
    const tokens = normalizeSearchTokens(integratedDocQuery);
    if (!tokens.length) return true;
    const text = `${item.name} ${item.meta} ${item.content}`.toLowerCase();
    return tokens.every((token) => text.includes(token));
  }

  function knowledgeDocuments() {
    return knowledgeDocs;
  }

  function similarDocCandidate(name, library) {
    const normalized = normalizeFileName(name);
    const items = library === "knowledge" ? knowledgeDocuments() : projectLibraryDocuments();
    return items.find((doc) => normalizeFileName(doc.name) === normalized || normalizeFileName(doc.name).includes(normalized) || normalized.includes(normalizeFileName(doc.name)));
  }

  function normalizeFileName(name = "") {
    return name.replace(/\.[^.]+$/, "").replace(/v\d+(\.\d+)?/ig, "").replace(/\d{8}|\d{4}-\d{2}-\d{2}/g, "").replace(/[ _（）()\-]/g, "").toLowerCase();
  }

  function nextVersion(version = "V1.0") {
    const match = version.match(/V(\d+)(?:\.(\d+))?/i);
    if (!match) return "V1.0";
    return `V${match[1]}.${Number(match[2] || 0) + 1}`;
  }

  function recommendFolder(fileName, library) {
    const name = fileName || "";
    if (library === "knowledge") {
      if (name.includes("规范") || name.includes("标准") || name.includes("法规")) return { id: "k01", name: folderName("k01"), reason: "文件名包含规范/标准/法规" };
      if (name.includes("制度") || name.includes("管理要求")) return { id: "k02", name: folderName("k02"), reason: "文件名包含制度或管理要求" };
      if (name.includes("阈值") || name.includes("规则") || name.includes("检查")) return { id: "k04", name: folderName("k04"), reason: "文件名包含规则或控制阈值" };
      if (name.includes("流程") || name.includes("模板") || name.includes("表单")) return { id: "k05", name: folderName("k05"), reason: "文件名包含流程/模板/表单" };
      if (name.includes("案例") || name.includes("隐患")) return { id: "k06", name: folderName("k06"), reason: "文件名包含案例或隐患" };
      return { id: "k03", name: folderName("k03"), reason: "默认归入专业技术知识" };
    }
    if (name.includes("合同") || name.includes("图纸") || name.includes("方案") || name.includes("交底")) return { id: "p01", name: folderName("p01"), reason: "文件名包含合同/图纸/方案/交底" };
    if (name.includes("计划") || name.includes("WBS") || name.includes("进度")) return { id: "p02", name: folderName("p02"), reason: "文件名包含计划或进度" };
    if (name.includes("质量") || name.includes("安全") || name.includes("风险")) return { id: "p03", name: folderName("p03"), reason: "文件名包含质量/安全/风险" };
    if (name.includes("监测") || name.includes("检测") || name.includes("试验") || name.includes("测斜")) return { id: "p04", name: folderName("p04"), reason: "文件名包含监测/检测/试验" };
    if (name.includes("会议") || name.includes("日报") || name.includes("周报") || name.includes("微信")) return { id: "p05", name: folderName("p05"), reason: "文件名包含会议或过程记录" };
    if (name.includes("整改") || name.includes("闭环")) return { id: "p06", name: folderName("p06"), reason: "文件名包含整改或闭环" };
    if (name.includes("变更") || name.includes("签证")) return { id: "p07", name: folderName("p07"), reason: "文件名包含变更或签证" };
    if (name.includes("验收") || name.includes("移交") || name.includes("竣工")) return { id: "p08", name: folderName("p08"), reason: "文件名包含验收/移交/竣工" };
    if (name.includes("照片") || name.includes("视频") || name.includes("导出") || name.includes("原始")) return { id: "p09", name: folderName("p09"), reason: "文件名包含影像或原始数据" };
    return { id: "p00", name: folderName("p00"), reason: "暂未命中特定关键词，建议先放入项目总览" };
  }

  function renderTools() {
    const current = businessTools.find((tool) => tool.name === selectedToolAgent) || businessTools[0];
    $("#toolGrid").innerHTML = `<div class="tool-agent-workspace">
      <aside class="tool-agent-list surface">
        <div class="section-heading">
          <div>
            <h3>专业智能体</h3>
            <p>选择一个智能体，继续用对话推进分析。</p>
          </div>
        </div>
        <div class="tool-agent-buttons">
          ${businessTools.map((tool) => `<button type="button" class="tool-agent-button ${tool.name === current.name ? "active" : ""}" data-tool-agent="${tool.name}">
            <strong>${tool.name}</strong>
            <span>${tool.desc}</span>
          </button>`).join("")}
        </div>
      </aside>
      <section class="tool-agent-chat surface">
        <div class="tool-chat-head">
          <div>
            <h3>${current.name}智能体</h3>
            <p>${current.desc}</p>
          </div>
          <span>当前项目：${currentProject().name}</span>
        </div>
        <div class="tool-chat-messages">
          <div class="message assistant-message">
            <strong>${current.name}智能体</strong>
            <p>我可以基于当前项目资料、任务、风险、隐患和报告内容继续分析。你可以直接描述要分析的问题。</p>
          </div>
          ${toolAgentNotice ? `<div class="message user-message"><p>${toolAgentNotice}</p></div><div class="message assistant-message"><strong>${current.name}智能体</strong><p>${toolAgentReply(current.name, toolAgentNotice)}</p></div>` : ""}
        </div>
        <form id="toolAgentForm" class="tool-agent-form">
          <textarea id="toolAgentInput" rows="3" placeholder="${current.starter}"></textarea>
          <div class="tool-agent-actions">
            <button type="submit">发送给${current.name}智能体</button>
            <button type="button" class="secondary" data-tool-starter="${escapeAttr(current.starter)}">填入示例问题</button>
          </div>
        </form>
      </section>
    </div>`;
    bindToolAgentActions();
  }

  function bindToolAgentActions() {
    $$("[data-tool-agent]").forEach((button) => button.addEventListener("click", () => {
      selectedToolAgent = button.dataset.toolAgent;
      toolAgentNotice = "";
      renderTools();
    }));
    const starterButton = $("[data-tool-starter]");
    if (starterButton) starterButton.addEventListener("click", () => {
      const input = $("#toolAgentInput");
      if (input) input.value = starterButton.dataset.toolStarter;
    });
    const form = $("#toolAgentForm");
    if (form) form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = $("#toolAgentInput")?.value.trim();
      if (!text) return;
      toolAgentNotice = text;
      renderTools();
    });
  }

  function toolAgentReply(agent, text) {
    const context = `已读取当前项目“${currentProject().name}”的状态、任务、风险、资料和来源记录。`;
    const replies = {
      数据分析: `${context} 下一步将把“${text}”转换为数据查询口径，并输出表格、图表和结论摘要。`,
      安全隐患: `${context} 下一步可上传或选择现场照片，我会识别隐患类型、影响工序和整改建议。`,
      趋势预测: `${context} 下一步将结合监测值、进度窗口和阈值规则，输出趋势判断和关注时间窗。`,
      风险诊断: `${context} 下一步将按风险源、工序、责任人、资料缺口和证据链给出诊断结论。`,
      报告撰写: `${context} 下一步将生成报告大纲、正文草稿和引用来源清单。`,
      报告审核: `${context} 下一步将检查报告依据、数据一致性、缺失来源和闭环证据。`,
    };
    return replies[agent] || `${context} 我会继续处理：${text}`;
  }

  function renderDiscussion() {
    $("#discussionSetup").innerHTML = `
      <div class="discussion-status-bar">
        <strong>${discussion.topic}</strong>
        <span>发起人：${discussion.initiator} · 项目成员 ${discussionHumanCount()} 人 · ${discussion.status}</span>
      </div>
      <div class="discussion-topic-form">
        <label>讨论主题<input value="${discussion.topic}" aria-label="讨论主题"></label>
        <label>关联对象<input value="${discussion.linkedObject}" aria-label="关联对象"></label>
      </div>
      <div>
        <h4>选择项目成员</h4>
        <div class="discussion-member-list">
          ${discussion.participants.map((member) => `<label class="member-toggle ${member.ai ? "ai-member" : ""}">
            <input type="checkbox" ${discussion.selectedMembers.includes(member.name) ? "checked" : ""} ${member.ai ? "disabled" : ""}>
            <span class="member-label">
              <strong>${member.name}</strong>
              <small>${member.role}</small>
            </span>
          </label>`).join("")}
        </div>
      </div>
      <button type="button">发起讨论（静态模拟）</button>
    `;
    $("#discussionThread").innerHTML = `
      <div class="section-heading compact">
        <div>
          <h3>讨论区</h3>
          <p>成员可以直接讨论，也可以 @Dobby 查资料、做分析、给建议。</p>
        </div>
      </div>
      <div class="discussion-messages">
        ${discussion.messages.map(renderDiscussionMessage).join("")}
      </div>
      <form class="discussion-input">
        <textarea rows="3" placeholder="输入讨论内容，例如：@Dobby 请查找支撑验收记录和S3监测日报。"></textarea>
        <div class="discussion-input-actions">
          <label class="file-action">
            <input type="file" multiple>
            <span>上传附件/图片</span>
          </label>
          <button type="button">发送消息</button>
          <button type="button" class="secondary">转为任务</button>
        </div>
      </form>
    `;
    $("#discussionAiPanel").innerHTML = `
      <div class="section-heading compact">
        <div>
          <h3>Dobby同步总结</h3>
          <p>Dobby根据讨论内容同步沉淀结论、待确认问题、资料引用和后续动作。</p>
        </div>
      </div>
      ${renderAiSummaryBlock("当前共识", discussion.aiSummary.consensus)}
      ${renderAiSummaryBlock("分歧/待确认问题", discussion.aiSummary.openQuestions)}
      ${renderAiSummaryBlock("AI建议", discussion.aiSummary.suggestions)}
      <section class="ai-summary-block">
        <h4>资料引用</h4>
        <div class="chip-list">${discussion.aiSummary.sources.map((item) => `<span class="chip">${item}</span>`).join("")}</div>
      </section>
      <section class="ai-summary-block">
        <h4>转化动作</h4>
        <div class="discussion-action-list">${discussion.aiSummary.actions.map((item) => `<button type="button">${item}</button>`).join("")}</div>
      </section>
    `;
  }

  function renderDiscussionMessage(message) {
    const tag = message.type === "ai" ? message.mode || "AI回复" : message.type === "mention" ? "@AI提问" : "成员发言";
    return `<article class="discussion-message ${message.type}">
      <div>
        <strong>${message.role}</strong>
        <span>${tag}</span>
      </div>
      <p>${message.text}</p>
    </article>`;
  }

  function renderAiSummaryBlock(title, items) {
    return `<section class="ai-summary-block">
      <h4>${title}</h4>
      <ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>
    </section>`;
  }

  function runDataQuery(rawQuestion, target) {
    const result = buildDataQueryResult(rawQuestion || "统计各项目逾期任务和资料缺失情况");
    const prefix = target === "docs" ? "docs" : "tool";
    $(`#${prefix}QueryNarrative`).innerHTML = `<strong>${result.title}</strong><br>${result.summary}`;
    $(`#${prefix}QueryMetrics`).innerHTML = result.metrics.map(metric).join("");
    $(`#${prefix}QueryChart`).innerHTML = renderBarChart(result.chartTitle, result.chartRows);
    $(`#${prefix}QueryTable`).innerHTML = renderQueryTable(result.columns, result.rows);
  }

  function buildDataQueryResult(question) {
    if (question.includes("来源") || question.includes("消息") || question.includes("记录")) {
      const rows = aggregate(records, "sourceType").map((row) => ({ ...row, example: records.find((record) => record.sourceType === row.name)?.sourceName }));
      return { title: "信息来源分布", summary: `共匹配到 ${records.length} 条动态采集记录。`, metrics: [["动态记录", records.length], ["待确认", records.filter((r) => r.status !== "已入库").length], ["照片", countType(records, "照片")], ["平台导出", countType(records, "平台导出")]], chartTitle: "来源类型记录数", chartRows: rows, columns: ["来源类型", "记录数", "代表记录"], rows: rows.map((row) => [row.name, row.count, row.example]) };
    }
    if (question.includes("责任人") || question.includes("谁") || question.includes("人员")) {
      const rows = aggregate(tasks, "owner").map((row) => ({ ...row, overdue: tasks.filter((task) => task.owner === row.name && isOverdue(task)).length }));
      return { title: "责任人任务排行", summary: rows[0] ? `当前任务最多的是 ${rows[0].name}，共 ${rows[0].count} 项。` : "暂无任务。", metrics: [["责任主体", rows.length], ["任务总数", tasks.length], ["逾期任务", tasks.filter(isOverdue).length], ["待确认", tasks.filter((task) => task.status === "待确认").length]], chartTitle: "责任人/单位任务数", chartRows: rows, columns: ["责任人/单位", "任务数", "逾期数"], rows: rows.map((row) => [row.name, row.count, row.overdue]) };
    }
    const rows = projects.map((project) => {
      const projectTasks = tasks.filter((task) => task.projectId === project.id);
      const missing = docs.filter((doc) => doc.projectId === project.id && doc.status === "缺失").length;
      const overdue = projectTasks.filter(isOverdue).length;
      return { name: project.name, stage: project.stage, overdue, missing, open: projectTasks.filter((task) => !["已完成", "已关闭"].includes(task.status)).length, count: overdue + missing };
    });
    return { title: "项目风险数据查询", summary: `已按“逾期任务 + 缺失资料”生成风险视图，共发现 ${rows.reduce((sum, row) => sum + row.count, 0)} 个关注点。`, metrics: [["项目数", projects.length], ["逾期任务", rows.reduce((sum, row) => sum + row.overdue, 0)], ["缺失资料", rows.reduce((sum, row) => sum + row.missing, 0)], ["开放待办", rows.reduce((sum, row) => sum + row.open, 0)]], chartTitle: "各项目风险点数量", chartRows: rows, columns: ["项目", "阶段", "逾期任务", "缺失资料", "开放待办"], rows: rows.map((row) => [row.name, row.stage, row.overdue, row.missing, row.open]) };
  }

  function ask(text, agent = "默认助手") {
    const attachmentNames = fileNames("#chatAttachment");
    addMessage("user", attachmentNames ? `${text}\n附件：${attachmentNames}` : text);
    let answer;
    if (text.includes("构建") || text.includes("建任务") || text.includes("提醒")) {
      buildTaskFromLanguage(text);
      answer = "已按你的语言指令构建任务草稿，并加入任务管理。";
    } else if (text.includes("周报") || text.includes("报告")) answer = weeklyReport();
    else if (text.includes("资料") || text.includes("齐全")) answer = docCheckText();
    else if (text.includes("待办") || text.includes("逾期") || text.includes("任务")) answer = taskText();
    else answer = statusText();
    addMessage("assistant", agentReply(agent, answer));
    renderAttachmentLabel(true);
  }

  function buildTaskFromLanguage(text) {
    if (!text) {
      if ($("#taskBuildResult")) $("#taskBuildResult").innerHTML = "<p>请输入要让AI构建的任务。</p>";
      return;
    }
    const flow = createDraftFlow(inferTaskType(text), inferTaskTitle(text), true);
    const newTask = { id: `task-${Date.now()}`, projectId: selectedProjectId, title: flow.topic, owner: inferOwner(text), supervisor: currentTaskUser, cc: flow.cc || "项目经理", previousOwner: "任务布置人", createdBy: "人工布置", flowType: flow.type, runMode: flow.runMode, triggerDate: flow.triggerDate, triggerTime: flow.triggerTime, triggerRule: inferTriggerRule(text), dueDate: inferDueDate(text), status: "待确认", type: flow.type, sourceIds: byProject(records).filter((record) => record.sourceType === "会议纪要").map((record) => record.id).slice(0, 1), needsInfo: true, phase: flow.steps[0]?.name || "启动", material: flow.steps[0]?.material || "无", closure: "未闭环", currentStepIndex: 0, steps: flow.steps };
    tasks.unshift(newTask);
    selectedPushTaskId = newTask.id;
    oneOffTaskTemplates.unshift({ id: `one-${Date.now()}`, projectId: selectedProjectId, title: `AI追问：${newTask.title}`, owner: newTask.owner, runAt: "2026-06-20 09:30", status: "待执行" });
    if ($("#taskBuildResult")) $("#taskBuildResult").innerHTML = `<div class="scheduled-card"><strong>AI已构建任务：${newTask.title}</strong><div class="scheduled-meta">${newTask.owner} · ${newTask.type} · 截止 ${newTask.dueDate}</div>${sourceBlock(newTask.sourceIds)}</div>`;
    if ($("#taskBuilderInput")) $("#taskBuilderInput").value = "";
    renderAll();
  }

  function statusText() {
    const current = currentProject();
    return `项目状态\n${current.name} 当前处于“${current.stage}”，状态为“${current.status}”。\n风险窗口 ${byProject(riskWindows).length} 个，动态信息 ${byProject(records).length} 条，未闭环任务 ${byProject(tasks).filter((task) => task.closure !== "已闭环").length} 项。`;
  }

  function taskText() {
    const items = byProject(tasks);
    return `任务进展\n${items.map((task) => `${task.title}：${task.status}，${task.owner}，${task.closure}`).join("\n")}\n\n来源：${sourceNames(items.flatMap((task) => task.sourceIds))}`;
  }

  function docCheckText() {
    const missing = missingDocs();
    return missing.length ? `资料不完整，缺失：${missing.map((doc) => doc.name).join("、")}。\n\n来源：${sourceNames(missing.map((doc) => doc.sourceId))}` : "资料清单当前无缺失项。";
  }

  function weeklyReport() {
    return `${currentProject().name} 深基坑质量安全报告初稿\n最新风险：${byProject(riskWindows).map((item) => item.name).join("；")}\n未闭环任务：${byProject(tasks).filter((task) => task.closure !== "已闭环").map((task) => task.title).join("；")}\n证据链：${byProject(events).map((event) => event.chain.join("→")).join("；")}`;
  }

  function metric([label, value, tone = ""]) {
    return `<div class="metric ${tone ? `metric-${tone}` : ""}"><span>${label}</span><strong>${value}</strong></div>`;
  }

  function taskToCard(task) {
    return { title: task.title, meta: `${task.type} · ${taskCurrentOwner(task)} · ${task.status}`, content: `当前节点：${currentStep(task)?.name || task.phase}；材料：${currentStep(task)?.material || task.material}；闭环：${task.closure}；来源：${sourceNames(task.sourceIds)}` };
  }

  function objectCard(item) {
    return [item.title, item.meta, item.content];
  }

  function renderCardList(items, projector) {
    return `<div class="card-grid">${items.map((item) => {
      const [title, meta, content] = projector(item);
      return `<article class="info-card"><div class="card-meta">${meta || ""}</div><h4>${title}</h4><p>${content || ""}</p></article>`;
    }).join("")}</div>`;
  }

  function renderBarChart(title, rows) {
    const max = Math.max(...rows.map((row) => row.count), 1);
    return `<h3>${title}</h3><div class="bar-chart">${rows.map((row) => `<div class="bar-row"><div class="bar-label">${row.name}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.max((row.count / max) * 100, row.count > 0 ? 8 : 0)}%"></div></div><div class="bar-value">${row.count}</div></div>`).join("")}</div>`;
  }

  function renderQueryTable(columns, rows) {
    return `<table><thead><tr>${columns.map((column) => `<th>${column}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  function inferTaskTitle(text) {
    const compact = text.replace(/^让AI|^帮我|^请/g, "").trim();
    return compact.length <= 28 ? compact || "待确认任务" : compact.slice(0, 28);
  }

  function inferOwner(text) {
    return ["施工单位", "安全员", "资料员", "质量员", "王经理", "赵经理", "张工", "监测单位"].find((name) => text.includes(name)) || "待确认";
  }

  function inferDueDate(text) {
    const date = text.match(/6月(\d{1,2})日/);
    if (date) return `2026-06-${date[1].padStart(2, "0")}`;
    if (text.includes("明天")) return "2026-06-20";
    if (text.includes("今天")) return "2026-06-19";
    return "2026-06-21";
  }

  function inferTriggerRule(text = "") {
    if (text.includes("每天")) return "每天";
    if (text.includes("每周五")) return "每周五";
    if (text.includes("每周")) return "每周";
    if (text.includes("每月")) return "每月";
    if (text.includes("日报") || text.includes("入库")) return "资料入库后触发";
    if (text.includes("监测")) return "监测数据更新后触发";
    return "到达触发时间后执行";
  }

  function inferTaskType(text) {
    if (text.includes("资料") || text.includes("上传") || text.includes("补交")) return "资料补全";
    if (text.includes("整改") || text.includes("隐患")) return "隐患整改";
    if (text.includes("风险") || text.includes("监测")) return "风险处置";
    if (text.includes("报告")) return "报告审核";
    return "条件核查";
  }

  function aggregate(items, key) {
    const groups = items.reduce((acc, item) => {
      const name = item[key];
      if (!acc[name]) acc[name] = { name, count: 0 };
      acc[name].count += 1;
      return acc;
    }, {});
    return Object.values(groups).sort((a, b) => b.count - a.count);
  }

  function countType(items, type) {
    return items.filter((item) => item.sourceType === type).length;
  }

  function sourceNames(ids) {
    return [...new Set(ids.filter(Boolean))].map((id) => {
      const item = source(id);
      return item ? `${item.sourceType}/${item.sourceName}` : id;
    }).join("；");
  }

  function previousOwner(task) {
    return task.previousOwner || (task.createdBy === "人工布置" ? "任务布置人" : "AI");
  }

  function renderAttachmentLabel(clear = false) {
    const input = $("#chatAttachment");
    const label = $("#attachmentLabel");
    if (!input || !label) return;
    if (clear) input.value = "";
    const names = fileNames("#chatAttachment");
    label.textContent = names || "附件";
  }

  function renderDispositionAttachmentLabel() {
    const label = $("#dispositionAttachmentLabel");
    if (!label) return;
    label.textContent = fileNames("#dispositionAttachment") || "提交文件/图片";
  }

  function fileNames(selector) {
    const input = $(selector);
    return input?.files?.length ? [...input.files].map((file) => file.name).join("、") : "";
  }

  function agentReply(agent, answer) {
    if (agent === "默认助手") return answer;
    const hints = {
      数据分析: "已按数据查询视角整理，可继续到业务工具生成表和图。",
      安全隐患: "已按隐患识别视角处理，可继续补充现场照片形成整改建议。",
      趋势预测: "已按监测数据、进度窗口和阈值规则进行趋势预测模拟。",
      风险诊断: "已按风险源、工序、资料和监测数据进行诊断模拟。",
      报告撰写: "已按报告初稿结构整理，后续可生成专项报告或闭环清单。",
      报告审核: "已按依据、来源、数据一致性进行审核模拟。",
    };
    return `已调用${agent}智能体。\n${hints[agent] || "已按所选业务工具处理。"}\n\n${answer}`;
  }

  function sourceBlock(ids) {
    return ids?.length ? `<div class="source-ref">来源：${sourceNames(ids)}</div>` : "";
  }

  function statusClass(status) {
    if (status === "逾期") return "overdue";
    if (status === "已完成" || status === "已关闭") return "closed";
    return "";
  }

  function addMessage(role, text) {
    const node = document.createElement("div");
    node.className = `message ${role}`;
    node.textContent = text;
    $("#chatMessages").append(node);
    $("#chatMessages").scrollTop = $("#chatMessages").scrollHeight;
  }

  init();
})();
