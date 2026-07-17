<template>
  <div class="setup-page">
    <div class="setup-workspace">
      <aside class="project-navigator" aria-label="项目切换">
        <div class="project-navigator-head"><h2>项目</h2><button type="button" class="link-button" @click="openProjectCreate">新建项目</button></div>
        <div class="project-navigator-list">
          <button v-for="project in store.projects" :key="project.id" class="project-nav-item" :class="{ active: project.id === store.currentProjectId }" @click="store.selectProject(project.id)">
            <span class="project-status-dot"></span><span class="project-nav-info"><strong>{{ project.name }}</strong><small>{{ project.ownerUnit || '未填写所属单位' }}</small></span><em>{{ project.status === 'active' ? '进行中' : project.status }}</em>
          </button>
          <p v-if="!store.projects.length" class="empty">还没有项目。请新建第一份工程资料。</p>
        </div>
      </aside>

      <main v-if="store.currentProjectId" class="project-config-panel">
        <section class="project-context">
          <div class="project-context-title"><span class="project-status-dot"></span><h1>{{ store.currentProject?.name }}</h1></div>
          <dl class="project-context-meta"><div><dt>负责人</dt><dd>{{ store.currentProject?.ownerUnit || '未填写所属单位' }}</dd></div><div><dt>状态</dt><dd><span class="project-status-dot"></span>{{ store.currentProject?.status === 'active' ? '进行中' : store.currentProject?.status }}</dd></div><div class="configuration-progress"><dt>资料完善度</dt><dd><span class="progress-track"><i :style="{ width: `${configurationProgress.percent}%` }"></i></span>{{ configurationProgress.percent }}%（{{ configurationProgress.completed }}/{{ configurationProgress.total }}）</dd></div></dl>
        </section>

        <div v-if="projectCreateOpen" class="setup-modal-backdrop" @click.self="closeProjectCreate">
      <section class="setup-modal" role="dialog" aria-modal="true" aria-labelledby="project-create-title">
        <div class="setup-modal-head"><div><h2 id="project-create-title">新建工程项目</h2></div><button type="button" class="modal-close" aria-label="关闭新建工程项目窗口" :disabled="submitting" @click="closeProjectCreate">关闭</button></div>
        <form class="form-stack project-create-form" @submit.prevent="submitProject">
          <label>项目名称<input v-model.trim="projectForm.project_name" required placeholder="例如：真如社区卫生服务中心扩建项目"></label>
          <label>所属单位<input v-model.trim="projectForm.owner_unit" placeholder="建设单位或管理单位"></label>
          <label>工程说明<textarea v-model.trim="projectForm.description" rows="4" placeholder="工程范围、阶段和当前重点"></textarea></label>
          <div class="setup-modal-actions"><button type="button" class="modal-secondary" :disabled="submitting" @click="closeProjectCreate">取消</button><button type="submit" class="primary" :disabled="submitting">创建并进入配置</button></div>
        </form>
      </section>
        </div>

      <div class="project-config-scroll">
      <nav class="project-workspace-tabs" aria-label="项目资料工作台">
        <button v-for="tab in workspaceTabs" :key="tab.key" type="button" :class="{ active: activeWorkspaceTab === tab.key }" @click="activeWorkspaceTab = tab.key"><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <section v-if="activeWorkspaceTab === 'agent'" class="material-agent-workspace">
        <header class="material-workspace-head material-agent-head">
          <div><span>Dobby 临时资料问答</span><h2>项目资料补全</h2><p>基于当前项目资料库和基础数据进行临时问答；对话不会保存。</p></div>
        </header>
        <div class="agent-context-summary"><article><span>已入库资料</span><strong>{{ store.attachments.length }}</strong><small>份待核对</small></article><article><span>待确认日报</span><strong>{{ store.pendingDailyReports.length }}</strong><small>份待确认</small></article><article><span>待补全事项</span><strong>{{ materialMissingItems.length }}</strong><small>项项目字段</small></article></div>
        <div class="material-agent-chat">
          <div class="material-agent-messages">
            <div v-if="!materialAgentMessages.length" class="material-agent-welcome"><strong>我是 Dobby，已连接当前项目资料库。</strong><p>我可以读取当前项目的资料、日报、WBS、风险、质量指标、字段映射和待办任务。本页对话为临时问答，不会保存。</p><div><button v-for="suggestion in materialAgentSuggestions" :key="suggestion" type="button" @click="askMaterialAgent(suggestion)">{{ suggestion }}</button></div></div>
            <article v-for="item in materialAgentMessages" :key="item.id" :class="['material-agent-message', item.role]"><span>{{ item.role === 'assistant' ? 'D' : '我' }}</span><div><small>{{ item.role === 'assistant' ? 'Dobby · 临时资料问答' : '你的指令' }}</small><p>{{ item.content }}</p></div></article>
          </div>
          <p v-if="materialAgentError" class="material-agent-error">{{ materialAgentError }}</p>
          <form class="material-agent-composer" @submit.prevent="sendMaterialAgentMessage"><textarea v-model="materialAgentPrompt" :disabled="materialAgentLoading" placeholder="例如：检查当前已入库资料能补全哪些 WBS、风险和质量信息"></textarea><button type="submit" class="primary" :disabled="materialAgentLoading || !materialAgentPrompt.trim()">{{ materialAgentLoading ? '正在分析…' : '发送给 Dobby' }}</button></form>
        </div>
      </section>

      <section v-else-if="activeWorkspaceTab === 'progress'" class="material-progress-workspace">
        <header class="material-workspace-head"><div><span>资料进度</span><h2>当前项目资料完善度</h2><p>汇总智能体可用于补全项目数据的资料、解析结果和基础信息。</p></div><router-link to="/docs" class="secondary-action">继续上传资料</router-link></header>
        <div class="material-progress-overview"><article><span>完善度</span><strong>{{ configurationProgress.percent }}%</strong><p>{{ configurationProgress.completed }}/{{ configurationProgress.total }} 项已具备</p></article><article><span>资料分类</span><strong>{{ materialCategorySummary.length }}</strong><p>类已识别</p></article><article><span>待处理资料</span><strong>{{ store.pendingDailyReports.length + materialMissingItems.length }}</strong><p>需要确认或补全</p></article></div>
        <div class="material-progress-grid"><section class="material-checklist"><h3>资料与基础数据</h3><article v-for="item in materialCompletionItems" :key="item.label" :class="{ done: item.done }"><span></span><div><strong>{{ item.label }}</strong><p>{{ item.detail }}</p></div><em>{{ item.done ? '已具备' : '待补全' }}</em></article></section><section class="material-category-summary"><h3>已识别资料类别</h3><article v-for="item in materialCategorySummary" :key="item.category"><strong>{{ item.category }}</strong><span>{{ item.count }} 份</span></article><p v-if="!materialCategorySummary.length" class="empty">尚未上传资料。上传后会先按文件名称自动归类，再由 Dobby 协助复核。</p></section></div>
      </section>

      <section v-else-if="activeWorkspaceTab === 'materials'" class="material-manager-workspace">
        <header class="material-workspace-head"><div><span>资料查看 / 修改</span><h2>管理已入库资料</h2><p>在此查看文件、复核分类；上传、文件夹归档和版本管理仍在工程资料库中完成。</p></div><router-link to="/docs" class="secondary-action">打开工程资料库</router-link></header>
        <div v-if="store.attachments.length" class="material-manager-grid"><section class="material-file-list"><button v-for="file in store.attachments" :key="file.id" type="button" :class="{ active: selectedAttachmentId === file.id }" @click="selectAttachment(file.id)"><span>{{ file.category }}</span><div><strong>{{ file.fileName }}</strong><small>V{{ file.version }} · {{ formatFileSize(file.fileSize) }}</small></div></button></section><aside v-if="selectedAttachment" class="material-inspector"><span>当前资料</span><h3>{{ selectedAttachment.fileName }}</h3><dl><div><dt>版本</dt><dd>V{{ selectedAttachment.version }}</dd></div><div><dt>大小</dt><dd>{{ formatFileSize(selectedAttachment.fileSize) }}</dd></div><div><dt>入库时间</dt><dd>{{ formatTime(selectedAttachment.createdAt) }}</dd></div></dl><label>资料分类<select v-model="selectedAttachmentCategory"><option v-for="category in materialCategories" :key="category" :value="category">{{ category }}</option></select></label><div class="material-inspector-actions"><button type="button" class="primary" :disabled="submitting" @click="saveSelectedAttachmentCategory">保存分类</button><button v-if="selectedAttachment.category === '日报'" type="button" class="secondary-action" :disabled="submitting" @click="registerDailyAttachment(selectedAttachment.id)">登记日报</button></div></aside></div>
        <div v-else class="material-manager-empty"><strong>还没有已入库资料</strong><p>先将文件上传到工程资料库，Dobby 会在这里呈现分类、解析进度和可补全的信息。</p><router-link to="/docs" class="primary">前往上传资料</router-link></div>
      </section>

      <template v-else-if="false">
      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>项目成员与责任</h2><p>添加账号后可分派任务和确认事项。</p></div></div>
          <form class="compact-form" @submit.prevent="submitMember">
            <input v-model.trim="memberForm.name" required placeholder="姓名">
            <input v-model.trim="memberForm.username" placeholder="登录账号（可选）">
            <input v-model.trim="memberForm.title" placeholder="岗位，例如安全员">
            <button type="button" class="primary" :disabled="submitting" @click="submitMember">添加</button>
          </form>
          <div class="item-list">
            <div v-for="member in store.members" :key="member.id"><strong>{{ member.name }}</strong><span>{{ member.title }}</span><small>{{ member.role.join('、') || '未设置责任标签' }}</small></div>
            <p v-if="!store.members.length" class="empty">暂无成员。</p>
          </div>
        </article>

        <article class="panel">
          <div class="panel-head"><div><h2>WBS 工序基线</h2><p>工序是进度、预警和日报匹配的基准。</p></div></div>
          <form class="compact-form wbs-form" @submit.prevent="submitWbs">
            <input v-model.trim="wbsForm.code" required placeholder="编码，例如 1.1">
            <input v-model.trim="wbsForm.name" required placeholder="工序名称">
            <input v-model="wbsForm.planned_start" type="date">
            <input v-model="wbsForm.planned_finish" type="date">
            <button type="submit" class="primary" :disabled="submitting">添加工序</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.wbsItems" :key="item.id"><strong>{{ item.code }} · {{ item.name }}</strong><span>{{ item.planStart || '未排期' }} 至 {{ item.planEnd || '未排期' }}</span><small>{{ item.progress }}% · {{ item.status }}</small></div>
            <p v-if="!store.wbsItems.length" class="empty">暂无 WBS 工序。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>质量指标与工序</h2><p>把验收项、控制要求、检查频次和资料要求挂接到 WBS。</p></div></div>
          <form class="compact-form quality-form" @submit.prevent="submitQualityMetric">
            <select v-model="qualityForm.wbs_item_id"><option value="">关联 WBS（可选）</option><option v-for="item in store.wbsItems" :key="item.id" :value="item.id">{{ item.code }} · {{ item.name }}</option></select>
            <input v-model.trim="qualityForm.name" required placeholder="质量验收项">
            <input v-model.trim="qualityForm.requirement" required placeholder="控制指标或验收要求">
            <input v-model.trim="qualityForm.inspection_frequency" placeholder="检查频次">
            <button type="submit" class="primary" :disabled="submitting">添加指标</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.qualityMetrics" :key="item.id"><strong>{{ item.name }}</strong><span>{{ store.getWbsName(item.wbsId || '') }} · {{ item.inspectionFrequency || '频次待定' }}</span><small>{{ item.requirement }}</small></div>
            <p v-if="!store.qualityMetrics.length" class="empty">暂无质量指标。</p>
          </div>
        </article>
        <article class="panel">
          <div class="panel-head"><div><h2>外部平台字段映射</h2><p>生成填报包时会自动按已启用映射写入目标字段。</p></div></div>
          <form class="compact-form mapping-form" @submit.prevent="submitPlatformMapping">
            <input v-model.trim="mappingForm.platformName" required placeholder="平台名称，例如监管填报平台">
            <select v-model="mappingForm.sourceField"><option value="draft_title">草稿标题</option><option value="draft_content">草稿内容</option><option value="source_refs">来源资料</option></select>
            <input v-model.trim="mappingForm.targetField" required placeholder="平台目标字段">
            <label class="check-label"><input v-model="mappingForm.required" type="checkbox"> 必填</label>
            <button class="primary" :disabled="submitting">添加映射</button>
          </form>
          <div class="item-list">
            <div v-for="item in store.platformMappings" :key="item.id"><strong>{{ item.platformName }} · {{ item.targetField }}</strong><span>{{ sourceFieldLabel(item.sourceField) }}{{ item.required ? ' · 必填' : '' }}</span><small><button class="link-button" type="button" @click="store.removePlatformMapping(item.id)">删除</button></small></div>
            <p v-if="!store.platformMappings.length" class="empty">暂无字段映射；未配置时可手工填写填报字段。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>风险源与资料要求</h2><p>风险源定义后可关联工序，形成预警和上报闭环。</p></div></div>
          <form class="compact-form risk-form" @submit.prevent="submitRisk">
            <input v-model.trim="riskForm.name" required placeholder="风险源名称">
            <select v-model="riskForm.level"><option value="critical">重大</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select>
            <input v-model.trim="riskForm.risk_type" placeholder="风险类型">
            <input v-model.trim="riskForm.materials" placeholder="资料要求，使用顿号或逗号分隔">
            <button class="primary" :disabled="submitting">添加风险</button>
          </form>
          <div class="item-list">
            <div v-for="risk in store.riskSources" :key="risk.id"><strong>{{ risk.name }}</strong><span>{{ risk.type }} · {{ riskLabel(risk.level) }}</span><small>{{ risk.materials.join('、') || '未配置资料要求' }}</small></div>
            <p v-if="!store.riskSources.length" class="empty">暂无风险源。</p>
          </div>
        </article>
        <article class="panel audit-panel">
          <div class="panel-head"><div><h2>操作留痕</h2><p>项目基础数据的关键写操作自动记录。</p></div></div>
          <div class="item-list">
            <div v-for="log in store.logs.slice(0, 8)" :key="log.id"><strong>{{ log.action }}</strong><span>{{ log.detail }}</span><small>{{ formatTime(log.time) }}</small></div>
            <p v-if="!store.logs.length" class="empty">还没有操作记录。</p>
          </div>
        </article>
      </section>

      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>资料目录监控</h2><p>保存资料来源与扫描频率；开启后工作台会按此配置显示监控状态。</p></div></div>
          <form class="form-stack monitor-form" @submit.prevent="saveMonitoring">
            <label>资料接收目录<input v-model.trim="monitorForm.mainDir" placeholder="例如：\\\\server\\project\\incoming"></label>
            <div class="directory-pair"><label>归档目录<input v-model.trim="monitorForm.archiveDir" placeholder="已确认资料归档位置"></label><label>失败目录<input v-model.trim="monitorForm.failedDir" placeholder="解析失败资料位置"></label></div>
            <div class="directory-pair"><label>临时目录<input v-model.trim="monitorForm.tempDir" placeholder="处理中资料位置"></label><label>备份目录<input v-model.trim="monitorForm.backupDir" placeholder="备份位置"></label></div>
            <div class="monitor-controls"><label>扫描间隔（分钟）<input v-model.number="monitorForm.scanInterval" type="number" min="1" max="1440"></label><label class="check-label"><input v-model="monitorForm.enabled" type="checkbox"> 启用目录监控</label><button class="primary" :disabled="submitting">保存配置</button></div>
          </form>
        </article>
        <article class="panel">
          <div class="panel-head"><div><h2>风险预警规则</h2><p>配置预警提前量，作为风险关联和任务生成的统一规则来源。</p></div></div>
          <form class="compact-form reminder-form" @submit.prevent="addReminderRule">
            <select v-model="reminderForm.level"><option value="critical">重大风险</option><option value="high">高风险</option><option value="medium">中风险</option><option value="low">低风险</option></select>
            <input v-model.number="reminderForm.days" type="number" min="0" max="365" placeholder="提前天数">
            <button class="primary" type="submit">添加规则</button>
          </form>
          <div class="item-list">
            <div v-for="rule in monitorRules" :key="rule.id"><strong>{{ riskLabel(rule.level) }}</strong><span>提前 {{ rule.days }} 天预警</span><small><button type="button" class="link-button" @click="removeReminderRule(rule.id)">移除</button></small></div>
            <p v-if="!monitorRules.length" class="empty">暂无规则，可按风险等级添加预警提前量。</p>
          </div>
        </article>
      </section>
      </template>

      <template v-else>
        <section class="manual-config-workspace">
          <aside class="manual-config-tree" aria-label="人工配置目录">
            <div class="manual-config-tree-head"><span>配置目录</span><small>项目基础数据</small></div>
            <button v-for="section in manualSections" :key="section.key" type="button" :class="{ active: manualSection === section.key }" @click="selectManualSection(section.key)"><n-icon :size="17"><component :is="section.icon" /></n-icon><strong>{{ section.label }}</strong><em>{{ section.count }}</em></button>
          </aside>

          <section class="manual-config-list">
            <header class="manual-list-head"><div><span>人工配置</span><h2>{{ activeManualSection.label }}</h2><p>{{ activeManualSection.description }}</p></div><div class="manual-list-actions"><label class="manual-search"><n-icon :size="16"><Search /></n-icon><input v-model.trim="manualSearch" :placeholder="`搜索${activeManualSection.label}`"></label><button v-if="manualSection !== 'monitor'" type="button" class="primary" :disabled="submitting" @click="openManualEditor(manualSection)"><n-icon :size="16"><Plus /></n-icon>新建</button><button v-else type="button" class="primary" :disabled="submitting" @click="openManualEditor('monitor')"><n-icon :size="16"><Pencil /></n-icon>维护配置</button></div></header>
            <div class="manual-table-wrap">
              <table v-if="manualSection === 'members' && filteredMembers.length" class="manual-table"><thead><tr><th>姓名</th><th>岗位</th><th>联系电话</th><th>邮箱</th><th>责任标签</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredMembers" :key="item.id"><td><strong>{{ item.name }}</strong></td><td>{{ item.title || '未设置' }}</td><td>{{ item.phone || '—' }}</td><td>{{ item.email || '—' }}</td><td>{{ item.role.join('、') || '未设置' }}</td><td><button type="button" class="row-action" @click="openManualEditor('members', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'wbs' && filteredWbsItems.length" class="manual-table"><thead><tr><th>编码</th><th>工序名称</th><th>计划时间</th><th>进度</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredWbsItems" :key="item.id"><td><strong>{{ item.code }}</strong></td><td>{{ item.name }}</td><td>{{ item.planStart || '未排期' }}{{ item.planEnd ? ` 至 ${item.planEnd}` : '' }}</td><td>{{ item.progress }}%</td><td><span class="status-dot" :class="item.status"></span>{{ wbsStatusLabel(item.status) }}</td><td><button type="button" class="row-action" @click="openManualEditor('wbs', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'quality' && filteredQualityMetrics.length" class="manual-table"><thead><tr><th>质量指标</th><th>关联工序</th><th>检查频次</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredQualityMetrics" :key="item.id"><td><strong>{{ item.name }}</strong><small>{{ item.requirement }}</small></td><td>{{ item.wbsId ? store.getWbsName(item.wbsId) : '未关联' }}</td><td>{{ item.inspectionFrequency || '未设置' }}</td><td>{{ qualityStatusLabel(item.status) }}</td><td><button type="button" class="row-action" @click="openManualEditor('quality', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'risks' && filteredRisks.length" class="manual-table"><thead><tr><th>风险源</th><th>风险等级</th><th>类型</th><th>资料要求</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredRisks" :key="item.id"><td><strong>{{ item.name }}</strong></td><td><span class="risk-level" :class="item.level">{{ riskLabel(item.level) }}</span></td><td>{{ item.type }}</td><td>{{ item.materials.join('、') || '未设置' }}</td><td><button type="button" class="row-action" @click="openManualEditor('risks', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'mappings' && filteredMappings.length" class="manual-table"><thead><tr><th>平台</th><th>来源字段</th><th>目标字段</th><th>填报要求</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredMappings" :key="item.id"><td><strong>{{ item.platformName }}</strong></td><td>{{ sourceFieldLabel(item.sourceField) }}</td><td>{{ item.targetField }}</td><td>{{ item.required ? '必填' : '选填' }} · {{ item.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('mappings', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'monitor'" class="manual-table"><thead><tr><th>配置项</th><th>当前值</th><th>说明</th><th>操作</th></tr></thead><tbody><tr><td><strong>资料目录监控</strong></td><td>{{ monitorForm.enabled ? '已启用' : '未启用' }}</td><td>{{ monitorForm.mainDir || '尚未设置资料接收目录' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">查看 / 修改</button></td></tr><tr v-for="rule in monitorRules" :key="rule.id"><td><strong>{{ riskLabel(rule.level) }}预警</strong></td><td>提前 {{ rule.days }} 天</td><td>{{ rule.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">维护规则</button></td></tr></tbody></table>
              <div v-else class="manual-empty"><n-icon :size="28"><ListDetails /></n-icon><strong>还没有{{ activeManualSection.label }}</strong><p>点击右上角“新建”，在弹窗中补充项目基础数据。</p></div>
            </div>
          </section>
        </section>

        <div v-if="manualEditor.open" class="setup-modal-backdrop manual-editor-backdrop" @click.self="closeManualEditor">
          <section class="setup-modal manual-editor-modal" role="dialog" aria-modal="true" aria-labelledby="manual-editor-title">
            <header class="setup-modal-head"><div><h2 id="manual-editor-title">{{ manualEditor.mode === 'create' ? `新建${activeManualSection.label}` : `查看 / 修改${activeManualSection.label}` }}</h2></div><button type="button" class="modal-close" :disabled="submitting" aria-label="关闭编辑窗口" @click="closeManualEditor"><n-icon :size="17"><X /></n-icon></button></header>
            <form class="manual-editor-form" @submit.prevent="submitManualEditor">
              <template v-if="manualEditor.section === 'members'"><label>姓名<input v-model.trim="editorMemberForm.name" required placeholder="成员姓名"></label><label>登录账号<input v-model.trim="editorMemberForm.username" :disabled="manualEditor.mode === 'edit'" placeholder="新建时可填写"></label><label>岗位<input v-model.trim="editorMemberForm.title" placeholder="例如：安全员"></label><label>联系电话<input v-model.trim="editorMemberForm.phone" placeholder="联系电话"></label><label class="full-span">邮箱<input v-model.trim="editorMemberForm.email" type="email" placeholder="邮箱地址"></label></template>
              <template v-else-if="manualEditor.section === 'wbs'"><label>工序编码<input v-model.trim="editorWbsForm.code" required placeholder="例如 1.1"></label><label>工序名称<input v-model.trim="editorWbsForm.name" required placeholder="工序名称"></label><label>计划开始<input v-model="editorWbsForm.plannedStart" type="date"></label><label>计划完成<input v-model="editorWbsForm.plannedFinish" type="date"></label><label>进度<input v-model.number="editorWbsForm.progress" type="number" min="0" max="100"></label><label>状态<select v-model="editorWbsForm.status"><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="done">已完成</option><option value="delayed">已延期</option></select></label></template>
              <template v-else-if="manualEditor.section === 'quality'"><label>关联工序<select v-model="editorQualityForm.wbsId"><option value="">不关联工序</option><option v-for="item in store.wbsItems" :key="item.id" :value="item.id">{{ item.code }} · {{ item.name }}</option></select></label><label>检查频次<input v-model.trim="editorQualityForm.frequency" placeholder="例如：每周一次"></label><label class="full-span">质量指标<input v-model.trim="editorQualityForm.name" required placeholder="质量验收项"></label><label class="full-span">控制要求<textarea v-model.trim="editorQualityForm.requirement" required rows="4" placeholder="控制指标或验收要求"></textarea></label><label>状态<select v-model="editorQualityForm.status"><option value="pending">待配置</option><option value="processing">进行中</option><option value="passed">已通过</option><option value="failed">未通过</option></select></label></template>
              <template v-else-if="manualEditor.section === 'risks'"><label>风险源名称<input v-model.trim="editorRiskForm.name" required placeholder="风险源名称"></label><label>风险等级<select v-model="editorRiskForm.level"><option value="critical">重大</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label><label class="full-span">风险类型<input v-model.trim="editorRiskForm.type" placeholder="例如：高处作业"></label><label class="full-span">资料要求<textarea v-model.trim="editorRiskForm.materials" rows="3" placeholder="使用顿号或逗号分隔"></textarea></label><label class="full-span">控制要求<textarea v-model.trim="editorRiskForm.controlMeasures" rows="3" placeholder="控制措施或验收要求"></textarea></label></template>
              <template v-else-if="manualEditor.section === 'mappings'"><label>平台名称<input v-model.trim="editorMappingForm.platformName" required placeholder="例如：监管填报平台"></label><label>来源字段<select v-model="editorMappingForm.sourceField"><option value="draft_title">草稿标题</option><option value="draft_content">草稿内容</option><option value="source_refs">来源资料</option></select></label><label class="full-span">目标字段<input v-model.trim="editorMappingForm.targetField" required placeholder="平台目标字段"></label><label class="full-span">转换规则<input v-model.trim="editorMappingForm.transformRule" placeholder="例如：保留原文、拼接来源资料"></label><label class="check-label"><input v-model="editorMappingForm.required" type="checkbox"> 必填字段</label><label class="check-label"><input v-model="editorMappingForm.enabled" type="checkbox"> 启用映射</label></template>
              <template v-else><label class="full-span">资料接收目录<input v-model.trim="monitorForm.mainDir" placeholder="例如：\\server\project\incoming"></label><label>归档目录<input v-model.trim="monitorForm.archiveDir" placeholder="已确认资料归档位置"></label><label>失败目录<input v-model.trim="monitorForm.failedDir" placeholder="解析失败资料位置"></label><label>扫描间隔（分钟）<input v-model.number="monitorForm.scanInterval" type="number" min="1" max="1440"></label><label class="check-label"><input v-model="monitorForm.enabled" type="checkbox"> 启用目录监控</label><div class="manual-rule-editor full-span"><div><strong>风险预警规则</strong><small>配置后用于风险关联和任务生成。</small></div><div><select v-model="reminderForm.level"><option value="critical">重大风险</option><option value="high">高风险</option><option value="medium">中风险</option><option value="low">低风险</option></select><input v-model.number="reminderForm.days" type="number" min="0" max="365" placeholder="提前天数"><button type="button" class="secondary-action" @click="addReminderRule">添加规则</button></div><ul><li v-for="rule in monitorRules" :key="rule.id">{{ riskLabel(rule.level) }} · 提前 {{ rule.days }} 天 <button type="button" class="link-button" @click="removeReminderRule(rule.id)">移除</button></li><li v-if="!monitorRules.length">暂无预警规则。</li></ul></div></template>
              <footer class="manual-editor-actions"><button type="button" class="modal-secondary" :disabled="submitting" @click="closeManualEditor">取消</button><button class="primary" :disabled="submitting">{{ submitting ? '正在保存…' : '保存修改' }}</button></footer>
            </form>
          </section>
        </div>
      </template>
      </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowsLeftRight, ListDetails, Pencil, Plus, Search, Shield, Users, X } from '@vicons/tabler'
import api, { type ApiEnvelope } from '@/api/client'
import { useAppStore, type AttachmentRecord } from '@/stores/app'
import type { DirConfig, Member, PlatformFieldMapping, QualityMetric, RemindRule, RiskLevel, RiskSource, WbsItem } from '@/types'

type WorkspaceTab = 'agent' | 'progress' | 'materials' | 'manual'
type ManualSection = 'members' | 'wbs' | 'quality' | 'risks' | 'mappings' | 'monitor'
type MaterialAgentMessage = { id: string; role: 'assistant' | 'user'; content: string }
type ApiMaterialAssistantReply = { content: string }

const store = useAppStore()
const message = useMessage()
const submitting = ref(false)
const activeWorkspaceTab = ref<WorkspaceTab>('agent')
const workspaceTabs: Array<{ key: WorkspaceTab; label: string; hint: string }> = [
  { key: 'agent', label: 'Dobby 资料补全', hint: '默认' },
  { key: 'progress', label: '资料进度', hint: '核对缺口' },
  { key: 'materials', label: '资料查看 / 修改', hint: '分类与版本' },
  { key: 'manual', label: '人工配置', hint: '手工维护' },
]
const projectCreateOpen = ref(false)
const projectForm = reactive({ project_name: '', owner_unit: '', description: '' })
const memberForm = reactive({ name: '', username: '', title: '' })
const wbsForm = reactive({ code: '', name: '', planned_start: '', planned_finish: '' })
const riskForm = reactive<{ name: string; level: RiskLevel; risk_type: string; materials: string }>({ name: '', level: 'medium', risk_type: '', materials: '' })
const qualityForm = reactive({ wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' })
const mappingForm = reactive({ platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false })
const monitorForm = reactive<DirConfig>({ mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false })
const monitorRules = ref<RemindRule[]>([])
const reminderForm = reactive<{ level: RiskLevel; days: number }>({ level: 'medium', days: 7 })
const manualSection = ref<ManualSection>('wbs')
const manualSearch = ref('')
const manualEditor = reactive<{ open: boolean; mode: 'create' | 'edit'; section: ManualSection; itemId: string }>({ open: false, mode: 'create', section: 'wbs', itemId: '' })
const editorMemberForm = reactive({ name: '', username: '', title: '', phone: '', email: '' })
const editorWbsForm = reactive<{ code: string; name: string; plannedStart: string; plannedFinish: string; progress: number; status: WbsItem['status'] }>({ code: '', name: '', plannedStart: '', plannedFinish: '', progress: 0, status: 'not_started' })
const editorQualityForm = reactive<{ wbsId: string; name: string; requirement: string; frequency: string; status: QualityMetric['status'] }>({ wbsId: '', name: '', requirement: '', frequency: '', status: 'pending' })
const editorRiskForm = reactive<{ name: string; level: RiskLevel; type: string; materials: string; controlMeasures: string }>({ name: '', level: 'medium', type: '', materials: '', controlMeasures: '' })
const editorMappingForm = reactive({ platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', transformRule: '', required: false, enabled: true })
const materialAgentMessages = ref<MaterialAgentMessage[]>([])
const materialAgentPrompt = ref('')
const materialAgentLoading = ref(false)
const materialAgentError = ref('')
const selectedAttachmentId = ref('')
const selectedAttachmentCategory = ref('工程资料')
const materialCategories = ['工程资料', '合同图纸', '进度计划', '日报', '质量资料', '风险资料', '会议纪要', '验收资料', '其他']
const selectedAttachment = computed<AttachmentRecord | undefined>(() => store.attachments.find(item => item.id === selectedAttachmentId.value))
const materialCompletionItems = computed(() => [
  { label: '工程资料入库', done: store.attachments.length > 0, detail: store.attachments.length ? `已入库 ${store.attachments.length} 份资料` : '尚未上传资料' },
  { label: '资料自动分类', done: store.attachments.length > 0 && store.attachments.every(item => item.category && item.category !== '未分类'), detail: store.attachments.length ? `${materialCategorySummary.value.length} 类资料已识别` : '上传后将自动归类' },
  { label: '日报解析确认', done: store.dailyReports.length > 0 && !store.pendingDailyReports.length, detail: store.dailyReports.length ? `${store.dailyReports.length} 份日报，${store.pendingDailyReports.length} 份待确认` : '暂无日报解析记录' },
  { label: 'WBS 工序基线', done: store.wbsItems.length > 0, detail: store.wbsItems.length ? `已维护 ${store.wbsItems.length} 项工序` : '等待资料或人工补全' },
  { label: '风险源与资料要求', done: store.riskSources.length > 0, detail: store.riskSources.length ? `已维护 ${store.riskSources.length} 项风险源` : '等待智能体识别或人工补全' },
  { label: '质量验收信息', done: store.qualityMetrics.length > 0, detail: store.qualityMetrics.length ? `已维护 ${store.qualityMetrics.length} 项指标` : '尚未形成质量验收项' },
  { label: '填报字段映射', done: store.platformMappings.length > 0, detail: store.platformMappings.length ? `已维护 ${store.platformMappings.length} 个字段` : '尚未配置外部平台字段' },
])
const materialMissingItems = computed(() => materialCompletionItems.value.filter(item => !item.done))
const materialCategorySummary = computed(() => {
  const counts = new Map<string, number>()
  for (const item of store.attachments) counts.set(item.category || '未分类', (counts.get(item.category || '未分类') || 0) + 1)
  return [...counts.entries()].map(([category, count]) => ({ category, count })).sort((a, b) => b.count - a.count || a.category.localeCompare(b.category, 'zh-CN'))
})
const materialAgentSuggestions = computed(() => [
  '检查当前资料能补全哪些 WBS、风险和质量信息',
  '核对已入库资料的分类，并列出仍缺少的资料',
  '根据当前资料生成任务，推动资料补全和确认',
])
const configurationProgress = computed(() => {
  const completed = materialCompletionItems.value.filter(item => item.done).length
  const total = materialCompletionItems.value.length
  return { completed, total, percent: Math.round((completed / total) * 100) }
})
const manualSections = computed(() => [
  { key: 'members' as const, label: '项目成员', description: '维护成员账号、岗位与协作责任。', count: store.members.length, icon: Users },
  { key: 'wbs' as const, label: 'WBS 工序', description: '维护工序基线，供进度、日报和预警匹配。', count: store.wbsItems.length, icon: ListDetails },
  { key: 'quality' as const, label: '质量指标', description: '维护验收要求、检查频次与关联工序。', count: store.qualityMetrics.length, icon: Shield },
  { key: 'risks' as const, label: '风险源', description: '维护风险等级、控制要求和资料要求。', count: store.riskSources.length, icon: Shield },
  { key: 'mappings' as const, label: '字段映射', description: '维护外部平台填报字段的映射规则。', count: store.platformMappings.length, icon: ArrowsLeftRight },
  { key: 'monitor' as const, label: '监控与预警', description: '维护资料目录监控与风险预警提前量。', count: monitorRules.value.length + 1, icon: ListDetails },
])
const activeManualSection = computed(() => manualSections.value.find(item => item.key === manualSection.value) || manualSections.value[0])
function matchesManualSearch(...values: Array<string | undefined>) { const keyword = manualSearch.value.trim().toLowerCase(); return !keyword || values.some(value => value?.toLowerCase().includes(keyword)) }
const filteredMembers = computed(() => store.members.filter(item => matchesManualSearch(item.name, item.title, item.phone, item.email, item.role.join(' '))))
const filteredWbsItems = computed(() => store.wbsItems.filter(item => matchesManualSearch(item.code, item.name, item.planStart, item.planEnd)))
const filteredQualityMetrics = computed(() => store.qualityMetrics.filter(item => matchesManualSearch(item.name, item.requirement, item.inspectionFrequency, store.getWbsName(item.wbsId || ''))))
const filteredRisks = computed(() => store.riskSources.filter(item => matchesManualSearch(item.name, item.type, item.materials.join(' '), item.controlMeasures)))
const filteredMappings = computed(() => store.platformMappings.filter(item => matchesManualSearch(item.platformName, item.targetField, item.sourceField, item.transformRule)))

function selectManualSection(section: ManualSection) {
  manualSection.value = section
  manualSearch.value = ''
}

function resetManualEditorForms() {
  Object.assign(editorMemberForm, { name: '', username: '', title: '', phone: '', email: '' })
  Object.assign(editorWbsForm, { code: '', name: '', plannedStart: '', plannedFinish: '', progress: 0, status: 'not_started' })
  Object.assign(editorQualityForm, { wbsId: '', name: '', requirement: '', frequency: '', status: 'pending' })
  Object.assign(editorRiskForm, { name: '', level: 'medium', type: '', materials: '', controlMeasures: '' })
  Object.assign(editorMappingForm, { platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', transformRule: '', required: false, enabled: true })
}

function openManualEditor(section: ManualSection, item?: Member | WbsItem | QualityMetric | RiskSource | PlatformFieldMapping) {
  manualSection.value = section
  resetManualEditorForms()
  manualEditor.open = true
  manualEditor.mode = item ? 'edit' : 'create'
  manualEditor.section = section
  manualEditor.itemId = item?.id || ''

  if (!item) return
  if (section === 'members') {
    const member = item as Member
    Object.assign(editorMemberForm, { name: member.name, title: member.title || '', phone: member.phone || '', email: member.email || '' })
  } else if (section === 'wbs') {
    const wbs = item as WbsItem
    Object.assign(editorWbsForm, { code: wbs.code, name: wbs.name, plannedStart: wbs.planStart || '', plannedFinish: wbs.planEnd || '', progress: wbs.progress, status: wbs.status })
  } else if (section === 'quality') {
    const quality = item as QualityMetric
    Object.assign(editorQualityForm, { wbsId: quality.wbsId || '', name: quality.name, requirement: quality.requirement, frequency: quality.inspectionFrequency || '', status: quality.status })
  } else if (section === 'risks') {
    const risk = item as RiskSource
    Object.assign(editorRiskForm, { name: risk.name, level: risk.level, type: risk.type || '', materials: risk.materials.join('、'), controlMeasures: risk.controlMeasures || '' })
  } else if (section === 'mappings') {
    const mapping = item as PlatformFieldMapping
    Object.assign(editorMappingForm, { platformName: mapping.platformName, sourceField: mapping.sourceField, targetField: mapping.targetField, transformRule: mapping.transformRule || '', required: mapping.required, enabled: mapping.enabled })
  }
}

function closeManualEditor() {
  if (!submitting.value) manualEditor.open = false
}

function splitList(value: string) {
  return value.split(/[、,，;；\n]/).map(item => item.trim()).filter(Boolean)
}

function wbsStatusLabel(status: WbsItem['status']) {
  return ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' } as Record<WbsItem['status'], string>)[status]
}

function qualityStatusLabel(status: QualityMetric['status']) {
  return ({ pending: '待配置', processing: '进行中', passed: '已通过', failed: '未通过' } as Record<QualityMetric['status'], string>)[status]
}

function submitManualEditor() {
  const isEditing = manualEditor.mode === 'edit'
  const success = isEditing ? '项目配置已更新' : '项目配置已创建'
  void run(async () => {
    if (manualEditor.section === 'members') {
      const payload = { name: editorMemberForm.name, username: editorMemberForm.username || undefined, title: editorMemberForm.title, phone: editorMemberForm.phone, email: editorMemberForm.email, role: [] as string[] }
      if (isEditing) await store.updateMember(manualEditor.itemId, payload)
      else await store.saveMember(payload)
    } else if (manualEditor.section === 'wbs') {
      const payload = { code: editorWbsForm.code, name: editorWbsForm.name, planned_start: editorWbsForm.plannedStart, planned_finish: editorWbsForm.plannedFinish, progress: Number(editorWbsForm.progress) || 0, status: editorWbsForm.status }
      if (isEditing) await store.updateWbs(manualEditor.itemId, payload)
      else await store.createWbs(payload)
    } else if (manualEditor.section === 'quality') {
      const payload = { wbs_item_id: editorQualityForm.wbsId, name: editorQualityForm.name, requirement: editorQualityForm.requirement, inspection_frequency: editorQualityForm.frequency, status: editorQualityForm.status }
      if (isEditing) await store.updateQualityMetric(manualEditor.itemId, payload)
      else await store.createQualityMetric(payload)
    } else if (manualEditor.section === 'risks') {
      const payload = { name: editorRiskForm.name, level: editorRiskForm.level, risk_type: editorRiskForm.type || '综合风险', material_requirements: splitList(editorRiskForm.materials), control_requirements: editorRiskForm.controlMeasures }
      if (isEditing) await store.updateRisk(manualEditor.itemId, payload)
      else await store.createRisk(payload)
    } else if (manualEditor.section === 'mappings') {
      const payload: Omit<PlatformFieldMapping, 'id' | 'projectId'> = { platformName: editorMappingForm.platformName, sourceField: editorMappingForm.sourceField, targetField: editorMappingForm.targetField, transformRule: editorMappingForm.transformRule, required: editorMappingForm.required, enabled: editorMappingForm.enabled }
      if (isEditing) await store.updatePlatformMapping(manualEditor.itemId, payload)
      else await store.createPlatformMapping(payload)
    } else {
      await store.saveProjectSettings({ ...monitorForm, reminderRules: monitorRules.value })
    }
    manualEditor.open = false
  }, success)
}

watch(() => [store.currentProjectId, store.dirConfig, store.remindRules] as const, () => {
  Object.assign(monitorForm, store.dirConfig)
  monitorRules.value = store.remindRules.map(rule => ({ ...rule }))
}, { immediate: true, deep: true })

watch(() => store.currentProjectId, () => {
  activeWorkspaceTab.value = 'agent'
  materialAgentMessages.value = []
  selectedAttachmentId.value = ''
  materialAgentError.value = ''
}, { immediate: true })

watch(() => store.attachments, () => {
  if (!selectedAttachmentId.value || !store.attachments.some(item => item.id === selectedAttachmentId.value)) selectedAttachmentId.value = store.attachments[0]?.id || ''
}, { immediate: true, deep: true })

watch(selectedAttachment, attachment => {
  selectedAttachmentCategory.value = attachment?.category || '工程资料'
}, { immediate: true })

async function sendMaterialAgentMessage() {
  const content = materialAgentPrompt.value.trim()
  if (!content || !store.currentProjectId) return
  materialAgentLoading.value = true
  materialAgentError.value = ''
  try {
    materialAgentMessages.value = [...materialAgentMessages.value, { id: `user-${Date.now()}`, role: 'user', content }]
    materialAgentPrompt.value = ''
    const response = await api.post<ApiEnvelope<ApiMaterialAssistantReply>>(`/projects/${store.currentProjectId}/material-assistant`, { content })
    materialAgentMessages.value = [...materialAgentMessages.value, { id: `dobby-${Date.now()}`, role: 'assistant', content: response.data.data.content }]
  } catch (error: any) {
    materialAgentError.value = error.response?.data?.detail || '资料智能体暂时无法处理这条请求。'
  } finally {
    materialAgentLoading.value = false
  }
}

function askMaterialAgent(content: string) { materialAgentPrompt.value = content; void sendMaterialAgentMessage() }
function selectAttachment(attachmentId: string) { selectedAttachmentId.value = attachmentId }
function saveSelectedAttachmentCategory() { if (selectedAttachment.value) void run(() => store.updateAttachmentCategory(selectedAttachment.value!.id, selectedAttachmentCategory.value), '资料分类已更新') }
function registerDailyAttachment(attachmentId: string) { void run(() => store.parseDailyAttachment(attachmentId), '日报已登记并进入确认队列') }
function formatFileSize(size: number) { if (!size) return '—'; const units = ['B', 'KB', 'MB', 'GB']; let value = size; let index = 0; while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1 }; return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}` }

async function run(action: () => Promise<unknown>, success: string) {
  submitting.value = true
  try { await action(); message.success(success) } catch (error: any) { message.error(error.response?.data?.detail || '保存失败，请检查权限和服务连接。') } finally { submitting.value = false }
}
function openProjectCreate() { projectCreateOpen.value = true }
function closeProjectCreate() { if (!submitting.value) projectCreateOpen.value = false }
function submitProject() { void run(async () => { await store.createProject(projectForm); Object.assign(projectForm, { project_name: '', owner_unit: '', description: '' }); projectCreateOpen.value = false }, '项目已创建') }
function submitMember() { void run(async () => { await store.saveMember({ name: memberForm.name, username: memberForm.username, title: memberForm.title }); Object.assign(memberForm, { name: '', username: '', title: '' }) }, '成员已添加') }
function submitWbs() { void run(async () => { await store.createWbs(wbsForm); Object.assign(wbsForm, { code: '', name: '', planned_start: '', planned_finish: '' }) }, 'WBS 工序已添加') }
function submitRisk() { void run(async () => { const materials = riskForm.materials.split(/[、,，]/).map(item => item.trim()).filter(Boolean); await store.createRisk({ name: riskForm.name, level: riskForm.level, risk_type: riskForm.risk_type || '综合风险', material_requirements: materials }); Object.assign(riskForm, { name: '', level: 'medium', risk_type: '', materials: '' }) }, '风险源已添加') }
function submitQualityMetric() { void run(async () => { await store.createQualityMetric(qualityForm); Object.assign(qualityForm, { wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' }) }, '质量指标已添加') }
function submitPlatformMapping() { void run(async () => { await store.createPlatformMapping({ ...mappingForm, enabled: true }); Object.assign(mappingForm, { platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false }) }, '平台字段映射已添加') }
function saveMonitoring() { void run(() => store.saveProjectSettings({ ...monitorForm, reminderRules: monitorRules.value }), '目录与预警规则已保存') }
function addReminderRule() { const index = monitorRules.value.findIndex(rule => rule.level === reminderForm.level); const next = { id: `rule-${reminderForm.level}`, level: reminderForm.level, days: Number(reminderForm.days) || 0, enabled: true }; if (index >= 0) monitorRules.value[index] = next; else monitorRules.value.push(next); message.info('规则已加入，请点击“保存配置”生效') }
function removeReminderRule(ruleId: string) { monitorRules.value = monitorRules.value.filter(rule => rule.id !== ruleId); message.info('规则已移除，请点击“保存配置”生效') }
function riskLabel(level: RiskLevel) { return ({ critical: '重大风险', high: '高风险', medium: '中风险', low: '低风险' } as Record<RiskLevel, string>)[level] }
function sourceFieldLabel(value: string) { return ({ draft_title: '草稿标题', draft_content: '草稿内容', source_refs: '来源资料' } as Record<string, string>)[value] || value }
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '刚刚' }
</script>

<style scoped>
.setup-page { box-sizing:border-box; display:flex; width:100%; min-width:0; height:100%; padding:18px; overflow:hidden; color:var(--text-primary); }
.panel-head p { margin:0; color:var(--text-muted); font-size:13px; }.primary { border:0; border-radius:6px; padding:9px 14px; color:#fff; background:var(--color-primary); cursor:pointer; font-weight:700; }.primary:disabled { opacity:.55; cursor:not-allowed; }
.setup-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-top:18px; }.setup-page > .setup-grid:first-of-type { margin-top:0; }.panel { background:#fff; border:1px solid var(--border-default); border-radius:10px; padding:20px; min-width:0; }.panel-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:16px; }.panel-head h2 { margin:0 0 5px; font-size:16px; }.projects-panel { grid-column:1 / -1; }.form-stack { display:grid; gap:12px; }.form-stack label { display:grid; gap:6px; font-size:12px; font-weight:700; color:var(--text-secondary); }.form-stack input,.form-stack textarea,.compact-form input,.compact-form select { border:1px solid var(--border-emphasis); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--text-primary); }.form-stack textarea { resize:vertical; }.compact-form { display:grid; grid-template-columns:1fr 1fr 1fr auto; gap:8px; }.wbs-form { grid-template-columns:.45fr 1.25fr 1fr 1fr auto; }.risk-form { grid-template-columns:1.1fr .55fr .9fr 1.35fr auto; }.quality-form { grid-template-columns:1fr 1fr 1.4fr .8fr auto; }.mapping-form { grid-template-columns:1.2fr .9fr 1fr auto auto; }.reminder-form { grid-template-columns:1fr 1fr auto; }.directory-pair,.monitor-controls { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.monitor-controls { align-items:end; grid-template-columns:1fr 1fr auto; }.check-label { display:flex !important; align-items:center; gap:7px; padding-bottom:9px; }.check-label input { width:15px; height:15px; }.link-button { border:0; padding:0; background:transparent; color:var(--color-primary); cursor:pointer; font:inherit; font-weight:700; }.item-list { display:grid; gap:0; margin-top:16px; border-top:1px solid var(--border-default); }.item-list>div { display:grid; grid-template-columns:1.2fr 1fr .8fr; gap:10px; align-items:center; padding:11px 0; border-bottom:1px solid var(--border-default); font-size:12px; }.item-list strong { font-size:13px; }.item-list span,.item-list small { color:var(--text-muted); }.empty { color:var(--text-muted); font-size:13px; padding:14px 0; }.project-row { display:flex; text-align:left; align-items:center; gap:10px; width:100%; padding:12px 4px; border:0; border-bottom:1px solid var(--border-default); background:transparent; cursor:pointer; }.project-row.active { color:var(--color-primary); }.project-row>span { width:8px; height:8px; border-radius:50%; background:var(--color-success); }.project-row div { flex:1; }.project-row strong,.project-row p { display:block; margin:0; }.project-row p,.project-row em { margin-top:3px; color:var(--text-muted); font-size:11px; font-style:normal; }.config-summary { display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-top:18px; }.config-summary article { padding:16px; background:#f8faf9; border:1px solid var(--border-default); border-radius:9px; }.config-summary span,.config-summary p { display:block; color:var(--text-muted); font-size:12px; }.config-summary strong { display:block; margin:8px 0 3px; font-size:28px; }.config-summary p { margin:0; }
.setup-workspace { display:grid; flex:1 1 auto; min-height:0; grid-template-columns:300px minmax(0,1fr); align-items:stretch; gap:18px; }.project-navigator { min-height:0; overflow:hidden; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.project-navigator-head { display:flex; align-items:center; justify-content:space-between; min-height:64px; padding:0 18px; border-bottom:1px solid var(--border-default); }.project-navigator-head h2 { margin:0; font-size:16px; }.project-navigator-head .link-button { font-size:12px; }.project-nav-item { display:flex; align-items:flex-start; gap:10px; width:100%; min-width:0; padding:15px 16px; border:0; border-bottom:1px solid var(--border-default); border-left:3px solid transparent; background:transparent; color:var(--text-primary); font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,border-color .16s ease; }.project-nav-item:hover { background:#f8fbfa; }.project-nav-item.active { border-left-color:#0f8b7a; background:#eef7f4; }.project-status-dot { flex:0 0 auto; width:9px; height:9px; margin-top:5px; border-radius:50%; background:#aebcb9; }.project-nav-item.active .project-status-dot,.project-context .project-status-dot { background:#0f8b7a; }.project-nav-info { display:grid; flex:1 1 auto; min-width:0; gap:5px; }.project-nav-info strong { overflow:hidden; color:#25413e; font-size:13px; font-weight:750; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.project-nav-info small { overflow:hidden; color:var(--text-muted); font-size:11px; line-height:1.3; text-overflow:ellipsis; white-space:nowrap; }.project-nav-item em { flex:0 0 auto; margin-top:3px; color:var(--text-muted); font-size:11px; font-style:normal; white-space:nowrap; }.project-config-panel { display:grid; min-width:0; min-height:0; grid-template-rows:auto minmax(0,1fr); overflow:hidden; }.project-context { padding:20px 24px; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.project-context-title { display:flex; align-items:center; gap:10px; }.project-context-title .project-status-dot { margin-top:0; }.project-context-title h1 { margin:0; color:#203936; font-size:18px; line-height:1.35; }.project-context-meta { display:grid; grid-template-columns:minmax(210px,1.2fr) 150px minmax(250px,1fr); gap:16px 24px; margin:18px 0 0; }.project-context-meta div { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:10px; min-width:0; }.project-context-meta dt { color:var(--text-muted); font-size:12px; }.project-context-meta dd { display:flex; align-items:center; min-width:0; gap:7px; margin:0; overflow:hidden; color:#46635f; font-size:12px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.project-context-meta dd .project-status-dot { width:8px; height:8px; margin-top:0; }.configuration-progress { grid-template-columns:auto minmax(0,1fr) !important; }.progress-track { display:block; flex:1 1 auto; min-width:72px; max-width:120px; height:6px; overflow:hidden; border-radius:999px; background:#e4ece9; }.progress-track i { display:block; height:100%; border-radius:inherit; background:#0f8b7a; transition:width .2s ease; }.project-config-scroll { min-height:0; overflow-y:auto; padding-right:6px; }.project-config-scroll > .setup-grid:first-child { margin-top:18px; }
.project-workspace-tabs { position:sticky; top:0; z-index:3; display:flex; gap:8px; padding:12px 0; background:var(--bg-base); }.project-workspace-tabs button { display:grid; flex:1 1 0; min-width:0; gap:2px; border:1px solid var(--border-default); border-radius:7px; padding:9px 12px; color:var(--text-secondary); background:#fff; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,border-color .16s ease,color .16s ease; }.project-workspace-tabs button:hover { border-color:#b8d2cc; background:#f7fbf9; }.project-workspace-tabs button.active { border-color:#0f8b7a; color:#174e47; background:#e8f4f0; }.project-workspace-tabs strong { overflow:hidden; font-size:12px; font-weight:800; text-overflow:ellipsis; white-space:nowrap; }.project-workspace-tabs span { overflow:hidden; color:var(--text-muted); font-size:10px; text-overflow:ellipsis; white-space:nowrap; }.project-workspace-tabs button.active span { color:#4c7d75; }
.material-agent-workspace,.material-progress-workspace,.material-manager-workspace { display:grid; gap:16px; padding:20px; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.material-workspace-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }.material-workspace-head>div:first-child { min-width:0; }.material-workspace-head span { display:block; margin-bottom:5px; color:#0f766e; font-size:11px; font-weight:850; letter-spacing:.05em; }.material-workspace-head h2 { margin:0 0 6px; color:#1a3935; font-size:18px; line-height:1.35; }.material-workspace-head p { max-width:76ch; margin:0; color:var(--text-muted); font-size:12px; line-height:1.65; }.material-workspace-actions { display:flex; flex:0 0 auto; align-items:center; gap:8px; }.material-workspace-actions select,.material-inspector select { min-width:0; border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 9px; color:var(--text-secondary); background:#fff; font:inherit; font-size:12px; }.secondary-action { display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 11px; color:#315c56; background:#fff; font:inherit; font-size:12px; font-weight:750; text-decoration:none; white-space:nowrap; cursor:pointer; }.secondary-action:hover { border-color:#69a096; background:#f4faf8; }.agent-context-summary,.material-progress-overview { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.agent-context-summary article,.material-progress-overview article { padding:13px 14px; border:1px solid #e0ebe8; border-radius:8px; background:#f7fbfa; }.agent-context-summary span,.material-progress-overview span { display:block; color:#6a8581; font-size:11px; font-weight:750; }.agent-context-summary strong,.material-progress-overview strong { display:block; margin:5px 0 2px; color:#1b4943; font-size:23px; line-height:1.1; }.agent-context-summary p,.material-progress-overview p { margin:0; color:var(--text-muted); font-size:11px; }.material-agent-chat { display:grid; min-height:390px; grid-template-rows:minmax(260px,1fr) auto auto; border:1px solid var(--border-default); border-radius:8px; overflow:hidden; background:#fbfcfc; }.material-agent-messages { display:grid; align-content:start; gap:14px; min-height:0; overflow-y:auto; padding:18px; }.material-agent-welcome { display:grid; gap:11px; align-self:center; max-width:700px; margin:auto; padding:8px; color:#315954; text-align:center; }.material-agent-welcome strong { color:#183d38; font-size:16px; }.material-agent-welcome p { margin:0; color:var(--text-muted); font-size:13px; line-height:1.7; }.material-agent-welcome>div { display:flex; justify-content:center; flex-wrap:wrap; gap:8px; }.material-agent-welcome button { border:1px solid #b9d6cf; border-radius:999px; padding:7px 11px; color:#21675d; background:#eef8f5; font:inherit; font-size:12px; cursor:pointer; }.material-agent-message { display:flex; align-items:flex-start; gap:9px; max-width:min(92%,760px); }.material-agent-message>span { display:grid; flex:0 0 auto; place-items:center; width:28px; height:28px; border-radius:50%; color:#fff; background:#0f766e; font-size:12px; font-weight:800; }.material-agent-message>div { min-width:0; padding:10px 12px; border:1px solid #dce9e5; border-radius:4px 10px 10px; background:#fff; }.material-agent-message small { display:block; margin-bottom:4px; color:#64817d; font-size:10px; font-weight:800; }.material-agent-message p { margin:0; color:#355652; font-size:13px; line-height:1.65; white-space:pre-wrap; }.material-agent-message.user { justify-self:end; flex-direction:row-reverse; }.material-agent-message.user>span { background:#cd5b20; }.material-agent-message.user>div { border-color:#f0d8ca; border-radius:10px 4px 10px 10px; background:#fff9f5; }.material-agent-error { margin:0; padding:8px 14px; border-top:1px solid #f2ded5; color:#b64c1e; background:#fff7f3; font-size:12px; }.material-agent-composer { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; padding:12px; border-top:1px solid var(--border-default); background:#fff; }.material-agent-composer textarea { min-height:44px; max-height:120px; resize:vertical; border:1px solid var(--border-emphasis); border-radius:6px; padding:10px; color:var(--text-primary); font:inherit; font-size:13px; }.material-agent-composer textarea:focus { outline:2px solid rgba(15,118,110,.14); outline-offset:1px; border-color:#4f978a; }
.project-config-scroll > .setup-grid { grid-template-columns:1fr; gap:14px; }.project-config-scroll > .setup-grid .panel { padding:20px 22px; }.project-config-scroll > .setup-grid .panel-head { margin-bottom:15px; }.project-config-scroll > .setup-grid .item-list { margin-top:15px; }
.project-config-scroll { display:flex; flex-direction:column; }.project-workspace-tabs { flex:0 0 auto; }.project-config-scroll > .material-manager-workspace { display:grid; flex:1 1 auto; min-height:0; grid-template-rows:auto minmax(0,1fr); }.material-manager-workspace .material-manager-grid,.material-manager-workspace .material-manager-empty { min-height:0; height:100%; }.material-manager-workspace .material-manager-grid { grid-template-rows:minmax(0,1fr); }
.material-progress-grid { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(260px,.75fr); gap:16px; }.material-checklist,.material-category-summary { border:1px solid var(--border-default); border-radius:8px; overflow:hidden; }.material-checklist h3,.material-category-summary h3 { margin:0; padding:13px 15px; border-bottom:1px solid var(--border-default); color:#24443f; font-size:13px; }.material-checklist article { display:grid; grid-template-columns:9px minmax(0,1fr) auto; align-items:center; gap:10px; padding:12px 15px; border-top:1px solid var(--border-subtle); }.material-checklist article:first-of-type { border-top:0; }.material-checklist article>span { width:9px; height:9px; border-radius:50%; background:#c5d3d0; }.material-checklist article.done>span { background:#0f8b7a; }.material-checklist strong { display:block; color:#365550; font-size:12px; }.material-checklist p { margin:3px 0 0; color:var(--text-muted); font-size:11px; }.material-checklist em { color:#a36a2b; font-size:11px; font-style:normal; white-space:nowrap; }.material-checklist article.done em { color:#17806d; }.material-category-summary article { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:11px 15px; border-top:1px solid var(--border-subtle); color:#45635e; font-size:12px; }.material-category-summary article span { color:#6a8581; font-variant-numeric:tabular-nums; }.material-category-summary .empty { margin:0; padding:15px; line-height:1.65; }
.material-manager-grid { display:grid; min-height:400px; grid-template-columns:minmax(0,1fr) minmax(260px,.75fr); border:1px solid var(--border-default); border-radius:8px; overflow:hidden; }.material-file-list { display:grid; align-content:start; overflow:auto; background:#fcfdfd; }.material-file-list button { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:10px; width:100%; border:0; border-bottom:1px solid var(--border-subtle); padding:12px 14px; color:var(--text-primary); background:transparent; font:inherit; text-align:left; cursor:pointer; }.material-file-list button:hover { background:#f5faf8; }.material-file-list button.active { box-shadow:inset 3px 0 #0f8b7a; background:#eaf5f1; }.material-file-list button>span { padding:4px 6px; border-radius:4px; color:#39675f; background:#e6f0ed; font-size:10px; font-weight:800; white-space:nowrap; }.material-file-list strong,.material-file-list small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.material-file-list strong { color:#264640; font-size:12px; }.material-file-list small { margin-top:4px; color:var(--text-muted); font-size:11px; }.material-inspector { display:grid; align-content:start; gap:12px; padding:17px; border-left:1px solid var(--border-default); background:#fff; }.material-inspector>span { color:#66827d; font-size:11px; font-weight:800; }.material-inspector h3 { margin:0; color:#23433e; font-size:15px; line-height:1.5; }.material-inspector dl { display:grid; gap:7px; margin:0; padding:11px 0; border-top:1px solid var(--border-subtle); border-bottom:1px solid var(--border-subtle); }.material-inspector dl div { display:flex; justify-content:space-between; gap:12px; font-size:12px; }.material-inspector dt { color:var(--text-muted); }.material-inspector dd { margin:0; color:#45635e; text-align:right; }.material-inspector label { display:grid; gap:6px; color:#526e69; font-size:12px; font-weight:750; }.material-inspector-actions { display:flex; gap:8px; flex-wrap:wrap; }.material-manager-empty { display:grid; justify-items:center; gap:9px; min-height:330px; place-content:center; color:var(--text-muted); text-align:center; }.material-manager-empty strong { color:#3c5c57; font-size:14px; }.material-manager-empty p { max-width:48ch; margin:0; font-size:12px; line-height:1.65; }
.setup-modal-backdrop { position:fixed; inset:0; z-index:30; display:grid; place-items:center; padding:24px; background:rgba(15,32,35,.42); backdrop-filter:blur(2px); }.setup-modal { width:min(100%,560px); max-height:calc(100dvh - 48px); overflow:auto; padding:20px; border:1px solid rgba(28,56,57,.18); border-radius:12px; background:#fff; box-shadow:0 22px 56px rgba(15,39,42,.26); }.setup-modal-head { display:flex; justify-content:space-between; align-items:center; gap:14px; min-width:0; margin-bottom:12px; }.setup-modal-head>div { display:flex; flex:1 1 auto; align-items:baseline; gap:10px; min-width:0; }.setup-modal-head span { flex:0 0 auto; color:var(--color-primary); font-size:12px; font-weight:800; letter-spacing:.04em; white-space:nowrap; }.setup-modal-head h2 { flex:0 1 auto; overflow:hidden; min-width:0; margin:0; color:#173235; font-size:17px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.setup-modal-head p { flex:1 1 14rem; overflow:hidden; min-width:5rem; max-width:none; margin:0; color:var(--text-muted); font-size:12px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }.setup-modal-head .modal-close { flex:0 0 auto; }.modal-close,.modal-secondary { border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 12px; color:var(--text-secondary); background:#fff; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.modal-close:disabled,.modal-secondary:disabled { opacity:.55; cursor:not-allowed; }.project-create-form { gap:14px; }.setup-modal-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }.compact-form > * { min-width:0; }.compact-form input,.compact-form select { width:100%; min-width:0; }
.project-config-scroll > .manual-config-workspace { flex:1 1 auto; min-height:0; }
.project-config-scroll > .material-agent-workspace { display:grid; flex:1 1 auto; min-height:0; grid-template-rows:auto auto minmax(0,1fr); gap:10px; padding:14px 18px; }.material-agent-head { min-height:0; }.material-agent-head h2 { margin-bottom:3px; font-size:16px; }.material-agent-head p { max-width:none; font-size:12px; line-height:1.45; }.agent-context-summary { gap:0; overflow:hidden; border:1px solid #e0ebe8; border-radius:7px; background:#f8fbfa; }.agent-context-summary article { display:flex; align-items:baseline; gap:7px; min-width:0; padding:9px 13px; border:0; border-right:1px solid #e0ebe8; border-radius:0; background:transparent; }.agent-context-summary article:last-child { border-right:0; }.agent-context-summary span { flex:0 1 auto; overflow:hidden; color:#69847f; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.agent-context-summary strong { flex:0 0 auto; margin:0; color:#1b4943; font-size:19px; font-variant-numeric:tabular-nums; }.agent-context-summary small { overflow:hidden; color:#7b918c; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.material-agent-chat { min-height:0; height:100%; grid-template-rows:minmax(200px,1fr) auto auto; }
.project-navigator { display:grid; grid-template-rows:auto minmax(0,1fr); }.project-navigator-list { min-height:0; overflow-y:auto; }
.manual-config-workspace { display:grid; min-height:0; grid-template-columns:176px minmax(0,1fr); margin-top:8px; border:1px solid var(--border-default); border-radius:10px; overflow:hidden; background:#fff; }
.manual-config-tree { display:grid; align-content:start; min-width:0; padding:10px; border-right:1px solid var(--border-default); background:#fbfcfc; overflow-y:auto; }
.manual-config-tree-head { display:grid; gap:2px; padding:7px 8px 11px; color:#284b46; }
.manual-config-tree-head span { font-size:12px; font-weight:850; }
.manual-config-tree-head small { color:var(--text-muted); font-size:10px; }
.manual-config-tree button { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; width:100%; border:0; border-radius:6px; padding:9px 8px; color:#4d6864; background:transparent; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,color .16s ease; }
.manual-config-tree button:hover { background:#f0f7f5; color:#22594f; }.manual-config-tree button.active { color:#17564d; background:#e3f2ee; }.manual-config-tree button strong { overflow:hidden; font-size:12px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }.manual-config-tree button em { min-width:18px; color:#78908b; font-size:10px; font-style:normal; font-variant-numeric:tabular-nums; text-align:right; }.manual-config-tree button.active em { color:#2c7d70; }
.manual-config-list { display:grid; min-width:0; min-height:0; grid-template-rows:auto minmax(0,1fr); }.manual-list-head { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:17px 19px 15px; border-bottom:1px solid var(--border-default); }.manual-list-head>div:first-child { min-width:0; }.manual-list-head span { display:block; margin-bottom:4px; color:#0f766e; font-size:11px; font-weight:850; letter-spacing:.05em; }.manual-list-head h2 { margin:0; color:#1a3935; font-size:17px; line-height:1.35; }.manual-list-head p { max-width:62ch; margin:4px 0 0; color:var(--text-muted); font-size:12px; line-height:1.55; }.manual-list-actions { display:flex; flex:0 0 auto; align-items:center; gap:8px; }.manual-search { display:flex; align-items:center; width:228px; gap:7px; border:1px solid var(--border-emphasis); border-radius:6px; padding:0 9px; color:#718782; background:#fff; }.manual-search input { min-width:0; width:100%; border:0; outline:0; padding:8px 0; color:var(--text-primary); background:transparent; font:inherit; font-size:12px; }.manual-list-actions .primary { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }.manual-table-wrap { min-height:0; overflow:auto; background:#fff; }.manual-table { width:100%; min-width:720px; border-collapse:collapse; color:#3f5d58; font-size:12px; }.manual-table th { position:sticky; top:0; z-index:1; padding:11px 15px; border-bottom:1px solid var(--border-default); color:#647d78; background:#f7faf9; font-size:11px; font-weight:800; text-align:left; white-space:nowrap; }.manual-table td { padding:13px 15px; border-bottom:1px solid var(--border-subtle); vertical-align:middle; line-height:1.45; }.manual-table tbody tr { transition:background .14s ease; }.manual-table tbody tr:hover { background:#f8fbfa; }.manual-table strong { color:#294842; font-weight:750; }.manual-table small { display:block; max-width:42ch; margin-top:3px; overflow:hidden; color:var(--text-muted); font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.row-action { border:0; padding:4px 0; color:#197163; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; white-space:nowrap; }.row-action:hover { color:#0e5b50; text-decoration:underline; }.status-dot { display:inline-block; width:7px; height:7px; margin-right:6px; border-radius:50%; background:#abb9b6; }.status-dot.in_progress { background:#129f88; }.status-dot.done { background:#2278a5; }.status-dot.delayed { background:#d76835; }.risk-level { display:inline-flex; align-items:center; border-radius:4px; padding:2px 6px; font-size:11px; white-space:nowrap; }.risk-level.critical { color:#9c351d; background:#fcebe5; }.risk-level.high { color:#a85d1c; background:#fff1dc; }.risk-level.medium { color:#3e716b; background:#e8f4f0; }.risk-level.low { color:#617f79; background:#eff5f3; }.manual-empty { display:grid; min-height:260px; place-content:center; justify-items:center; gap:8px; padding:24px; color:#78908b; text-align:center; }.manual-empty strong { color:#3a5a55; font-size:14px; }.manual-empty p { margin:0; color:var(--text-muted); font-size:12px; }.manual-editor-modal { width:min(100%,680px); }.manual-editor-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 16px; }.manual-editor-form label { display:grid; gap:6px; color:#4e6964; font-size:12px; font-weight:750; }.manual-editor-form input,.manual-editor-form select,.manual-editor-form textarea { min-width:0; border:1px solid var(--border-emphasis); border-radius:6px; padding:9px 10px; color:var(--text-primary); background:#fff; font:inherit; font-size:13px; }.manual-editor-form textarea { resize:vertical; }.manual-editor-form .full-span { grid-column:1 / -1; }.manual-editor-form .check-label { align-self:end; padding-bottom:0; font-weight:650; }.manual-rule-editor { display:grid; gap:10px; padding:12px; border:1px solid #e0ebe8; border-radius:8px; background:#f8fbfa; }.manual-rule-editor>div { display:flex; align-items:center; justify-content:space-between; gap:10px; }.manual-rule-editor strong,.manual-rule-editor small { display:block; }.manual-rule-editor strong { color:#31544f; font-size:12px; }.manual-rule-editor small { margin-top:3px; color:var(--text-muted); font-size:11px; }.manual-rule-editor>div+div { justify-content:flex-start; }.manual-rule-editor select,.manual-rule-editor input { min-width:0; flex:1 1 0; padding:7px 8px; font-size:12px; }.manual-rule-editor .secondary-action { padding:7px 9px; }.manual-rule-editor ul { display:flex; flex-wrap:wrap; gap:7px; margin:0; padding:0; list-style:none; }.manual-rule-editor li { padding:4px 7px; border-radius:4px; color:#57746e; background:#eaf3f0; font-size:11px; }.manual-editor-actions { display:flex; grid-column:1 / -1; justify-content:flex-end; gap:8px; padding-top:4px; }.manual-config-workspace button:focus-visible,.manual-table button:focus-visible,.manual-editor-form input:focus,.manual-editor-form select:focus,.manual-editor-form textarea:focus,.manual-search:focus-within { outline:2px solid rgba(15,118,110,.22); outline-offset:1px; }
@media (max-width:1380px) and (min-width:1001px) { .project-config-scroll > .setup-grid { grid-template-columns:1fr; } }
@media (max-width:1000px) { .setup-page { display:block; height:auto; min-height:100%; overflow:visible; }.setup-workspace { display:block; min-height:0; }.project-navigator { min-height:0; margin-bottom:18px; }.project-config-panel { display:block; min-width:0; overflow:visible; }.project-config-scroll { overflow:visible; padding-right:0; }.project-workspace-tabs { position:static; overflow-x:auto; }.project-workspace-tabs button { flex:0 0 155px; }.material-progress-grid,.material-manager-grid { grid-template-columns:1fr; }.material-inspector { border-top:1px solid var(--border-default); border-left:0; }.project-config-scroll > .material-agent-workspace { min-height:520px; }.manual-config-workspace { min-height:520px; grid-template-columns:1fr; }.manual-config-tree { grid-template-columns:repeat(3,minmax(150px,1fr)); grid-auto-rows:min-content; border-right:0; border-bottom:1px solid var(--border-default); overflow:auto; }.manual-config-tree-head { grid-column:1 / -1; }.setup-grid { grid-template-columns:1fr; }.config-summary { grid-template-columns:repeat(2,1fr); }.compact-form,.wbs-form,.risk-form { grid-template-columns:1fr 1fr; }.compact-form button { grid-column:span 2; } } @media (max-width:600px) { .setup-page { padding:18px; }.project-context { padding:16px; }.project-context-title h1 { font-size:16px; }.project-context-meta { grid-template-columns:1fr; gap:9px; margin-top:15px; }.project-context-meta div { grid-template-columns:60px minmax(0,1fr); }.project-nav-item { padding:13px 14px; }.material-agent-workspace,.material-progress-workspace,.material-manager-workspace { padding:15px; }.material-workspace-head { display:grid; gap:12px; }.material-workspace-actions { justify-content:space-between; }.agent-context-summary,.material-progress-overview { grid-template-columns:1fr; }.project-config-scroll > .material-agent-workspace { min-height:500px; padding:14px; }.agent-context-summary article { border-right:0; border-bottom:1px solid #e0ebe8; }.agent-context-summary article:last-child { border-bottom:0; }.material-agent-chat { min-height:340px; }.material-agent-composer { grid-template-columns:1fr; }.material-manager-grid { min-height:0; }.manual-config-workspace { min-height:500px; }.manual-config-tree { display:flex; gap:3px; padding:7px; overflow-x:auto; }.manual-config-tree-head { display:none; }.manual-config-tree button { flex:0 0 auto; grid-template-columns:auto minmax(0,1fr); width:auto; }.manual-config-tree button em { display:none; }.manual-list-head { display:grid; padding:15px; }.manual-list-actions { width:100%; }.manual-search { width:auto; flex:1 1 auto; }.manual-editor-form { grid-template-columns:1fr; }.manual-editor-form .full-span,.manual-editor-actions { grid-column:auto; }.manual-rule-editor>div { display:grid; }.manual-editor-actions { justify-content:stretch; }.manual-editor-actions button { flex:1 1 auto; }.config-summary { grid-template-columns:1fr 1fr; }.item-list>div { grid-template-columns:1fr; gap:3px; }.panel-head { gap:10px; }.setup-modal-backdrop { padding:12px; }.setup-modal { max-height:calc(100dvh - 24px); padding:16px; border-radius:10px; }.setup-modal-head { gap:12px; }.setup-modal-actions { justify-content:stretch; }.setup-modal-actions button { flex:1 1 auto; } }
@media (max-width:600px) { .setup-modal-head span,.setup-modal-head p { display:none; } }
</style>
