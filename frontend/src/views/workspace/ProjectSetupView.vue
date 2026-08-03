<template>
  <div class="setup-page">
    <div class="setup-workspace">
      <aside class="project-navigator" aria-label="项目切换">
        <div class="project-navigator-head"><h2>项目</h2><button type="button" class="link-button" @click="openProjectCreate">新建项目</button></div>
        <div class="project-navigator-list">
          <button v-for="project in store.projects" :key="project.id" class="project-nav-item" :class="{ active: project.id === configProjectId }" @click="selectConfigProject(project.id)">
            <strong class="project-nav-name">{{ project.name }}</strong>
          </button>
          <div v-if="!store.projectCatalogLoaded" class="project-list-loading" aria-label="正在加载项目">
            <i></i><span></span><small></small>
          </div>
          <div v-else-if="!store.projects.length" class="project-list-empty">
            <span><n-icon :size="18"><ListDetails /></n-icon></span>
            <strong>暂无项目</strong>
            <p>创建后会显示在这里，方便切换和继续完善。</p>
            <button type="button" @click="openProjectCreate"><n-icon :size="15"><Plus /></n-icon>创建第一个项目</button>
          </div>
        </div>
      </aside>

      <main v-if="configProjectId" class="project-config-panel">
      <div class="project-config-scroll">
      <nav class="project-workspace-tabs" aria-label="项目资料工作台">
        <button v-for="tab in workspaceTabs" :key="tab.key" type="button" :class="{ active: activeWorkspaceTab === tab.key }" @click="selectWorkspaceTab(tab.key)"><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <section v-if="activeWorkspaceTab === 'agent'" class="material-agent-workspace">
        <div class="material-agent-chat" :class="{ 'has-draft': materialAgentDraft }">
          <div
            ref="materialAgentViewport"
            class="material-agent-messages"
            :class="{ empty: !materialAgentMessages.length && !materialAgentStreamingTrace }"
            :aria-busy="materialAgentConversationLoading"
            @scroll.passive="handleMaterialAgentScroll"
          >
            <div
              v-if="materialAgentConversationLoading && !materialAgentMessages.length && !materialAgentStreamingTrace"
              class="material-agent-history-loading"
              aria-live="polite"
            >
              <span aria-hidden="true"></span>
              <strong>正在读取历史对话</strong>
              <p>正在同步当前项目的初始化会话，请稍候。</p>
            </div>
            <div v-else-if="!materialAgentMessages.length && !materialAgentStreamingTrace" class="material-agent-welcome">
              <span class="material-agent-welcome-mark" aria-hidden="true">D</span>
              <div>
                <small>项目初始化</small>
                <strong>从现有资料开始完善项目</strong>
                <p>直接说明已知信息，或添加工程说明、人员表、WBS、风险清单和质量指标文件。整理结果会先交给你核对，确认后再写入项目。</p>
              </div>
            </div>
            <article v-for="item in materialAgentMessages" :key="item.id" :class="['material-agent-message', item.role]">
              <span>{{ item.role === 'assistant' ? 'D' : '我' }}</span>
              <div>
                <small>{{ item.role === 'assistant' ? 'Dobby · 项目初始化助手' : '你的指令' }}</small>
                <AgentMessageContent
                  v-if="item.role === 'assistant'"
                  :content="item.content"
                  :runtime-trace="item.runtimeTrace"
                  :show-plan="false"
                  @confirm="confirmMaterialAgentToolCall"
                />
                <p v-else>{{ item.content }}</p>
                <ul v-if="item.attachments?.length" class="material-agent-message-files">
                  <li v-for="file in item.attachments" :key="file.id"><n-icon :size="14"><Paperclip /></n-icon>{{ file.name }}<small>{{ formatFileSize(file.size) }}</small></li>
                </ul>
              </div>
            </article>
            <article v-if="materialAgentStreamingTrace" class="material-agent-message assistant">
              <span>D</span>
              <div>
                <small>Dobby · 项目初始化助手</small>
                <AgentMessageContent
                  :runtime-trace="materialAgentStreamingTrace"
                  :show-plan="false"
                  streaming
                  @confirm="confirmMaterialAgentToolCall"
                />
              </div>
            </article>
          </div>
          <p v-if="materialAgentError" class="material-agent-error">{{ materialAgentError }}</p>
          <section
            v-if="materialAgentDraft"
            class="initialization-draft-dock"
            :class="[`status-${materialAgentDraft.status}`, { collapsed: initializationDraftCollapsed }]"
            aria-label="项目初始化草稿"
          >
            <button
              v-if="initializationDraftCollapsed"
              type="button"
              class="initialization-draft-collapsed"
              aria-controls="initialization-draft-content"
              aria-expanded="false"
              @click="initializationDraftCollapsed = false"
            >
              <span class="initialization-draft-dot" aria-hidden="true"></span>
              <strong>{{ initializationDraftCollapsedLabel(materialAgentDraft) }}</strong>
              <n-icon :size="16" aria-hidden="true"><ChevronUp /></n-icon>
            </button>
            <div v-else id="initialization-draft-content" class="initialization-draft-content">
              <header class="initialization-draft-head">
                <div class="initialization-draft-title">
                  <span class="initialization-draft-dot" aria-hidden="true"></span>
                  <div>
                    <small>初始化草稿</small>
                    <strong>{{ initializationDraftStatusLabel(materialAgentDraft.status) }}</strong>
                  </div>
                  <em>{{ initializationDraftStageHint(materialAgentDraft) }}</em>
                </div>
                <div class="initialization-draft-actions">
                  <button
                    type="button"
                    class="initialization-draft-collapse"
                    aria-controls="initialization-draft-content"
                    aria-expanded="true"
                    @click="initializationDraftCollapsed = true"
                  >
                    <n-icon :size="15" aria-hidden="true"><ChevronDown /></n-icon>
                    <span>收起</span>
                  </button>
                  <button type="button" class="initialization-draft-review" @click="openInitializationDraftReview">
                    {{ materialAgentDraft.status === 'applied' ? '查看内容' : '核对草稿' }}
                  </button>
                </div>
              </header>
              <div class="initialization-draft-summary">
                <span><strong>{{ materialAgentDraft.summary.project_fields }}</strong>项工程信息</span>
                <span>
                  <strong>{{ materialAgentDraft.summary.personnel }}</strong>名人员
                  · {{ materialAgentDraft.summary.position_assignments }}条任职
                </span>
                <span><strong>{{ materialAgentDraft.summary.wbs }}</strong>项 WBS</span>
                <span><strong>{{ materialAgentDraft.summary.risks }}</strong>项风险</span>
                <span><strong>{{ materialAgentDraft.summary.quality_requirements }}</strong>项质量指标</span>
              </div>
              <footer class="initialization-draft-meta">
                <span v-if="materialAgentDraft.workflow && materialAgentDraft.workflow.stage !== 'completed'">
                  已完成 {{ materialAgentDraft.workflow.completed_sections.length }}/{{ materialAgentDraft.workflow.expected_sections.length }} 个专项分区
                  <template v-if="materialAgentDraft.workflow.pending_sections.length">，等待：{{ initializationSectionLabels(materialAgentDraft.workflow.pending_sections) }}</template>
                </span>
                <span v-else>{{ materialAgentDraft.validation_issues.length ? initializationDraftIssueSummary : '结构校验已通过，确认前不会写入项目' }}</span>
                <small v-if="materialAgentDraft.source_files.length">来源：{{ materialAgentDraft.source_files.join('、') }}</small>
                <small v-else>来源：本次问答</small>
              </footer>
            </div>
          </section>
          <section
            v-if="materialAgentExecutionPlan"
            class="material-agent-plan-dock"
            :class="{
              collapsed: materialAgentPlanCollapsed,
              completed: materialAgentPlanCompleted,
              interrupted: materialAgentExecutionPlan.status === 'interrupted',
            }"
            aria-label="当前执行计划"
          >
            <button
              v-if="materialAgentPlanCollapsed"
              type="button"
              class="material-agent-plan-collapsed"
              aria-controls="material-agent-plan-content"
              aria-expanded="false"
              @click="materialAgentPlanCollapsed = false"
            >
              <span class="material-agent-plan-dot" aria-hidden="true"></span>
              <strong>执行计划</strong>
              <span>{{ materialAgentPlanCompletedCount }}/{{ materialAgentExecutionPlan.tasks.length }}</span>
              <em>{{ materialAgentPlanCurrentLabel }}</em>
              <n-icon :size="16" aria-hidden="true"><ChevronUp /></n-icon>
            </button>
            <div v-else id="material-agent-plan-content" class="material-agent-plan-content">
              <header>
                <div>
                  <span class="material-agent-plan-dot" aria-hidden="true"></span>
                  <strong>执行计划</strong>
                  <em>{{ materialAgentPlanStatusLabel }}</em>
                </div>
                <button
                  type="button"
                  aria-controls="material-agent-plan-content"
                  aria-expanded="true"
                  @click="materialAgentPlanCollapsed = true"
                >
                  <n-icon :size="15" aria-hidden="true"><ChevronDown /></n-icon>
                  <span>收起</span>
                </button>
              </header>
              <div class="material-agent-plan-progress" aria-hidden="true">
                <i :style="{ width: `${materialAgentPlanProgress}%` }"></i>
              </div>
              <ul>
                <li
                  v-for="task in materialAgentExecutionPlan.tasks"
                  :key="String(task.id)"
                  :class="task.state"
                >
                  <i aria-hidden="true"></i>
                  <span>{{ task.subject }}</span>
                  <small>
                    <span v-if="task.owner">{{ task.owner }} · </span>
                    {{ materialAgentTaskStateLabel(task.state) }}
                  </small>
                </li>
              </ul>
            </div>
          </section>
          <form class="material-agent-composer" @submit.prevent="sendMaterialAgentMessage">
            <input ref="materialAgentFileInput" class="visually-hidden" type="file" multiple accept=".xls,.xlsx,.csv,.docx,.pptx,.pdf,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp,.tif,.tiff" @change="selectMaterialAgentFiles">
            <div v-if="materialAgentFiles.length" class="material-agent-file-tray">
              <div class="material-agent-file-head"><span>已选择 {{ materialAgentFiles.length }} 个附件</span><button type="button" @click="clearMaterialAgentFiles">清空</button></div>
              <ul>
                <li v-for="(file, index) in materialAgentFiles" :key="`${file.name}-${file.size}-${file.lastModified}`">
                  <n-icon :size="17"><Paperclip /></n-icon>
                  <span><strong>{{ file.name }}</strong><small>{{ formatFileSize(file.size) }}</small></span>
                  <button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeMaterialAgentFile(index)"><n-icon :size="15"><X /></n-icon></button>
                </li>
              </ul>
            </div>
            <div class="material-agent-composer-row">
              <button type="button" class="material-agent-attach" title="添加项目附件" aria-label="添加项目附件" :disabled="materialAgentLoading" @click="openMaterialAgentFilePicker"><n-icon :size="19"><Paperclip /></n-icon></button>
              <textarea v-model="materialAgentPrompt" :disabled="materialAgentLoading" placeholder="描述需要补充的工程信息，或添加附件"></textarea>
              <button v-if="materialAgentLoading || materialAgentStopping" type="button" class="material-agent-stop" :disabled="materialAgentStopping" @click="stopMaterialAgentMessage">{{ materialAgentStopping ? '正在停止…' : '停止分析' }}</button>
              <button v-else type="submit" class="primary" :disabled="!materialAgentPrompt.trim() && !materialAgentFiles.length">发送给 Dobby</button>
            </div>
            <small class="material-agent-composer-hint">支持 XLS/XLSX、DOCX、PPTX、PDF、图片、CSV、TXT、Markdown；原始附件交由 AgentScope 初始化助手解析</small>
          </form>
        </div>
      </section>

      <section v-else-if="activeWorkspaceTab === 'connections'" class="project-connection-workspace">
        <header class="project-connection-head"><div><span>连接配置</span><h2>项目协同工具</h2><p>维护当前项目使用的消息连接信息，用于后续通知和协同能力接入。</p></div><em>{{ configuredProjectConnectorCount }}/{{ projectConnectors.length }} 已配置</em></header>
        <div class="project-connection-grid">
          <nav class="project-connector-list" aria-label="项目连接类型">
            <button v-for="item in projectConnectors" :key="item.key" type="button" :class="{ active: activeProjectConnectorKey === item.key }" @click="activeProjectConnectorKey = item.key">
              <span class="project-connector-icon"><n-icon :size="18"><component :is="item.icon" /></n-icon></span>
              <span><strong>{{ item.label }}</strong><small>{{ item.configured ? '连接信息已保存' : '尚未配置' }}</small></span>
              <i :class="{ configured: item.configured }"></i>
            </button>
          </nav>
          <form v-if="activeProjectConnector" class="project-connector-editor" @submit.prevent="saveProjectConnector">
            <header><span class="project-connector-icon large"><n-icon :size="21"><component :is="activeProjectConnector.icon" /></n-icon></span><div><h3>{{ activeProjectConnector.label }}</h3><p>{{ activeProjectConnector.description }}</p></div></header>
            <label>{{ activeProjectConnector.connectionLabel }}<input v-model.trim="activeProjectConnector.connectionId" maxlength="500" :placeholder="activeProjectConnector.connectionPlaceholder"></label>
            <label>{{ activeProjectConnector.secretLabel }}<input v-model="activeProjectConnector.secret" type="password" autocomplete="new-password" placeholder="输入后仅用于本次配置，不在浏览器中保存"></label>
            <div class="project-credential-note"><n-icon :size="17"><ShieldLock /></n-icon><p><strong>凭据保护</strong><span>当前仅保存连接标识和配置状态，密钥不会写入浏览器存储。</span></p></div>
            <footer class="project-connector-actions"><span>{{ activeProjectConnector.updatedAt ? `更新于 ${activeProjectConnector.updatedAt}` : '尚未保存连接信息' }}</span><button type="submit" class="primary"><n-icon :size="17"><Link /></n-icon>保存连接信息</button></footer>
          </form>
        </div>
      </section>

      <template v-else-if="false">
      <section class="setup-grid">
        <article class="panel">
          <div class="panel-head"><div><h2>项目成员与责任</h2><p>添加账号后可分派任务和确认事项。</p></div></div>
          <form class="compact-form" @submit.prevent="submitMember">
            <input v-model.trim="memberForm.name" required placeholder="姓名">
            <input v-model.trim="memberForm.username" placeholder="登录账号（可选）">
            <input v-model.trim="memberForm.positionName" placeholder="岗位，例如安全员">
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
              <div v-if="configScopeLoading" class="manual-data-loading" aria-label="正在加载正式项目数据"><i></i><span></span><span></span><span></span></div>

              <section v-else-if="manualSection === 'members'" class="manual-data-panel personnel-browser">
                <div v-if="filteredMembers.length" class="personnel-card-list">
                  <article v-for="item in filteredMembers" :key="item.id" class="personnel-card">
                    <header class="personnel-profile">
                      <span class="personnel-avatar">{{ item.name.slice(0, 1) }}</span>
                      <div><h3>{{ item.name }}</h3><p>账号：{{ item.username }} · 身份证：{{ maskedIdentityCard(item.identityCardNo) }}</p></div>
                      <em v-if="item.positions.length > 1">兼任 {{ item.positions.length }} 岗</em>
                      <em v-else>单一任职</em>
                    </header>
                    <div class="personnel-card-content">
                      <span>项目职务</span>
                      <div v-if="item.positions.length" class="personnel-position-tags">
                        <button v-for="position in item.positions" :key="position.id" type="button" :title="`查看${position.name}任职详情`" @click="openPersonnelDetail(item, position)">{{ position.name }}</button>
                      </div>
                      <p v-else>该成员尚未配置项目职务。</p>
                      <small v-if="item.positions.length">点击职务标签查看证书编号和岗位职责</small>
                    </div>
                    <footer><button type="button" class="personnel-detail-link" @click="openPersonnelDetail(item)">查看任职详情</button><button type="button" class="row-action" @click="openMemberPositionEditor(item)">添加兼任岗位</button></footer>
                  </article>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><Users /></n-icon><strong>{{ manualSearch ? '没有匹配的项目成员' : '还没有项目成员' }}</strong><p>{{ manualSearch ? '可尝试搜索姓名、账号、岗位或证书编号。' : '点击右上角“新建”，添加人员及其首个项目岗位。' }}</p></div>
              </section>

              <section v-else-if="manualSection === 'wbs'" class="manual-data-panel wbs-browser">
                <div class="wbs-browser-toolbar"><span v-if="manualSearch">找到 {{ visibleManualWbsRows.length }} 个相关节点，已保留上级路径</span><div><button type="button" @click="expandAllManualWbs">全部展开</button><button type="button" @click="collapseAllManualWbs">收起任务组</button></div></div>
                <div v-if="visibleManualWbsRows.length" class="wbs-tree-table-wrap">
                  <table class="manual-table wbs-tree-table">
                    <thead><tr><th>计划层级（WBS）</th><th>计划区间</th><th>工期与负责人</th><th>完成进度</th><th>状态与优先级</th><th>前置工序</th><th>操作</th></tr></thead>
                    <tbody>
                      <tr v-for="row in visibleManualWbsRows" :key="row.item.id" :class="{ 'wbs-group-row': row.hasChildren }">
                        <td><div class="wbs-tree-node" :class="{ root: row.depth === 0 }" :style="{ '--wbs-depth': String(row.depth) }"><button v-if="row.hasChildren" type="button" class="wbs-tree-toggle" :class="{ collapsed: isManualWbsCollapsed(row.item.id) }" :aria-label="isManualWbsCollapsed(row.item.id) ? '展开下级工序' : '收起下级工序'" @click="toggleManualWbs(row.item.id)"><n-icon :size="15"><ChevronDown /></n-icon></button><i v-else></i><span><em>{{ row.item.code }}</em><strong>{{ row.item.name }}</strong><small>{{ formalWbsItemType(row.item) ? `${formalWbsItemType(row.item)} · ` : '' }}第 {{ row.item.level }} 级</small></span></div></td>
                        <td><strong>{{ formatFormalDate(row.item.planStart) || '未排期' }}</strong><small>{{ formatFormalDate(row.item.planEnd) ? `至 ${formatFormalDate(row.item.planEnd)}` : '未设置完成日期' }}</small></td>
                        <td><strong>{{ formatWbsDuration(row.item.durationHours) }}</strong><small>{{ row.item.assignedToText || '未分配负责人' }}</small></td>
                        <td><div class="wbs-progress"><div><i :style="{ width: `${Math.min(100, Math.max(0, row.item.progress))}%` }"></i></div><span>{{ formatProgress(row.item.progress) }}%</span></div></td>
                        <td><span v-if="formalWbsStatusLabel(row.item)" class="wbs-status-chip" :class="row.item.status"><i></i>{{ formalWbsStatusLabel(row.item) }}</span><span v-else class="manual-muted">—</span><small v-if="formalWbsPriorityLabel(row.item.priorityText)">{{ formalWbsPriorityLabel(row.item.priorityText) }}</small></td>
                        <td><div v-if="row.item.predecessorCodes?.length" class="wbs-predecessors"><span v-for="code in row.item.predecessorCodes" :key="code">{{ code }}</span></div><span v-else class="manual-muted">无</span></td>
                        <td><button type="button" class="row-action" @click="openManualEditor('wbs', row.item)">查看 / 修改</button></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><ListDetails /></n-icon><strong>{{ manualSearch ? '没有匹配的 WBS 节点' : '还没有 WBS 工序' }}</strong><p>{{ manualSearch ? '搜索结果会保留父级路径，试试工序编码或名称。' : '点击右上角“新建”，补充项目计划基线。' }}</p></div>
              </section>

              <section v-else-if="manualSection === 'quality'" class="manual-data-panel quality-browser">
                <div v-if="filteredQualityMetrics.length" class="quality-data-table-wrap">
                  <table class="manual-table quality-data-table">
                    <thead><tr><th>WBS 工序</th><th>质量验收项</th><th>控制指标</th><th>检查频次</th><th>关联资料</th><th>操作</th></tr></thead>
                    <tbody><tr v-for="item in filteredQualityMetrics" :key="item.id"><td><code>{{ item.wbsCode || '—' }}</code><strong>{{ item.wbsName || configWbsName(item.wbsId || '', item.wbsCode) || '未匹配工序' }}</strong></td><td>{{ item.acceptanceItem || '未填写' }}</td><td>{{ item.controlIndicator || '未填写' }}</td><td>{{ item.inspectionFrequency || '未设置' }}</td><td>{{ item.relatedDocuments || item.requiredMaterials.join('、') || '未设置' }}</td><td><button type="button" class="row-action" @click="openManualEditor('quality', item)">查看 / 修改</button></td></tr></tbody>
                  </table>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><Shield /></n-icon><strong>{{ manualSearch ? '没有匹配的质量要求' : '还没有质量要求' }}</strong><p>{{ manualSearch ? '可按 WBS 编码、验收项、控制指标或资料名称搜索。' : '点击右上角“新建”，为 WBS 工序配置验收要求。' }}</p></div>
              </section>

              <section v-else-if="manualSection === 'risks'" class="manual-data-panel risk-browser">
                <div v-if="filteredRisks.length" class="risk-card-list">
                  <article v-for="item in filteredRisks" :key="item.id" class="risk-record-card">
                    <header><span class="risk-serial">第 {{ String(item.serialNo || 0).padStart(2, '0') }} 项</span><div><h3>{{ item.riskPart || item.name }}</h3><p>{{ item.relatedProcessName || item.type || '未注明相关工序' }}</p></div><span class="risk-level" :class="item.level">{{ formalRiskLevelLabel(item) }}</span><button type="button" class="row-action" @click="openManualEditor('risks', item)">查看 / 修改</button></header>
                    <div class="risk-context single"><span><strong>风险窗口</strong>{{ formatRiskWindow(item) }}</span></div>
                    <dl><div><dt>评价条件</dt><dd>{{ item.evaluationCondition || item.controlMeasures || '未填写' }}</dd></div><div><dt>风险摘要</dt><dd>{{ item.summary || '未填写' }}</dd></div></dl>
                  </article>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><Shield /></n-icon><strong>{{ manualSearch ? '没有匹配的风险源' : '还没有风险源' }}</strong><p>{{ manualSearch ? '可按风险部位、相关工序、等级或评价条件搜索。' : '点击右上角“新建”，补充项目风险清单。' }}</p></div>
              </section>

              <table v-else-if="manualSection === 'mappings' && filteredMappings.length" class="manual-table"><thead><tr><th>平台</th><th>来源字段</th><th>目标字段</th><th>填报要求</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredMappings" :key="item.id"><td><strong>{{ item.platformName }}</strong></td><td>{{ sourceFieldLabel(item.sourceField) }}</td><td>{{ item.targetField }}</td><td>{{ item.required ? '必填' : '选填' }} · {{ item.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('mappings', item)">查看 / 修改</button></td></tr></tbody></table>
              <table v-else-if="manualSection === 'monitor'" class="manual-table"><thead><tr><th>配置项</th><th>当前值</th><th>说明</th><th>操作</th></tr></thead><tbody><tr><td><strong>资料目录监控</strong></td><td>{{ monitorForm.enabled ? '已启用' : '未启用' }}</td><td>{{ monitorForm.mainDir || '尚未设置资料接收目录' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">查看 / 修改</button></td></tr><tr v-for="rule in monitorRules" :key="rule.id"><td><strong>{{ riskLabel(rule.level) }}预警</strong></td><td>提前 {{ rule.days }} 天</td><td>{{ rule.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">维护规则</button></td></tr></tbody></table>
              <div v-else class="manual-empty"><n-icon :size="28"><ListDetails /></n-icon><strong>还没有{{ activeManualSection.label }}</strong><p>点击右上角“新建”，在弹窗中补充项目基础数据。</p></div>
            </div>
          </section>
        </section>

        <div v-if="personnelDetailMember" class="setup-modal-backdrop personnel-detail-backdrop" @click.self="closePersonnelDetail">
          <section class="setup-modal personnel-detail-modal" role="dialog" aria-modal="true" aria-labelledby="personnel-detail-title">
            <header class="setup-modal-head"><div><h2 id="personnel-detail-title">{{ personnelDetailMember.name }} · 任职详情</h2><p>账号：{{ personnelDetailMember.username }} · 身份证：{{ maskedIdentityCard(personnelDetailMember.identityCardNo) }}</p></div><button type="button" class="modal-close" aria-label="关闭任职详情" @click="closePersonnelDetail"><n-icon :size="17"><X /></n-icon></button></header>
            <div class="personnel-detail-list">
              <article v-for="position in personnelDetailMember.positions" :key="position.id" :class="{ selected: position.id === personnelDetailPositionId }">
                <header><span>{{ String(position.serialNo || 0).padStart(2, '0') }}</span><div><h3>{{ position.name }}</h3><p>{{ position.certificateNo ? `证书编号 ${position.certificateNo}` : '未登记证书编号' }}</p></div><button type="button" class="row-action" @click="editPersonnelDetailPosition(personnelDetailMember, position)">编辑任职</button></header>
                <div><strong>岗位职责</strong><p>{{ position.responsibilityDescription || '暂未填写该岗位的职责说明。' }}</p></div>
              </article>
              <div v-if="!personnelDetailMember.positions.length" class="personnel-detail-empty">该成员尚未配置项目职务。</div>
            </div>
            <footer class="personnel-detail-actions"><span>{{ personnelDetailMember.systemRole === 'admin' ? '平台管理员账号' : '普通项目账号' }}</span><button type="button" class="modal-secondary" @click="closePersonnelDetail">关闭</button><button type="button" class="primary" @click="addPersonnelDetailPosition(personnelDetailMember)"><n-icon :size="16"><Plus /></n-icon>添加兼任岗位</button></footer>
          </section>
        </div>

        <div v-if="manualEditor.open" class="setup-modal-backdrop manual-editor-backdrop" @click.self="closeManualEditor">
          <section class="setup-modal manual-editor-modal" :class="{ 'record-editor-modal': formalDataEditorOpen }" role="dialog" aria-modal="true" aria-labelledby="manual-editor-title">
            <header class="setup-modal-head"><div><span v-if="manualEditorContextLabel">{{ manualEditorContextLabel }}</span><h2 id="manual-editor-title">{{ manualEditorTitle }}</h2><p v-if="manualEditorContextDescription">{{ manualEditorContextDescription }}</p></div><button type="button" class="modal-close" :disabled="submitting" aria-label="关闭编辑窗口" @click="closeManualEditor"><n-icon :size="17"><X /></n-icon></button></header>
            <form class="manual-editor-form" :class="{ 'record-editor-form': formalDataEditorOpen }" @submit.prevent="submitManualEditor">
              <template v-if="manualEditor.section === 'members'">
                <label>姓名<input v-model.trim="editorMemberForm.name" required :disabled="Boolean(manualEditor.itemId)" placeholder="成员姓名"></label>
                <label>身份证号<input v-model.trim="editorMemberForm.identityCardNo" required :disabled="Boolean(manualEditor.itemId)" placeholder="用于识别同一平台账号"></label>
                <label>登录账号<input v-model.trim="editorMemberForm.username" :disabled="Boolean(manualEditor.itemId) || manualEditor.mode === 'edit'" placeholder="留空时按姓名生成拼音"></label>
                <label v-if="manualEditor.mode === 'create' && !manualEditor.itemId">初始密码<span class="manual-password-field"><input v-model="editorMemberForm.password" required minlength="8" maxlength="12" type="text" autocomplete="new-password" placeholder="自动生成 8–12 位密码"><button type="button" @click="editorMemberForm.password = generateInitializationPassword()">换一个</button></span></label>
                <label>岗位<input v-model.trim="editorMemberForm.positionName" required placeholder="例如：安全员"></label>
                <label>证书编号<input v-model.trim="editorMemberForm.certificateNo" placeholder="没有可留空"></label>
                <label class="full-span">岗位职责<textarea v-model.trim="editorMemberForm.responsibilityDescription" rows="4" placeholder="说明此人在该岗位承担的职责"></textarea></label>
                <p class="manual-member-account-note full-span">身份证号用于识别人员：系统已有账号时只加入当前项目；同一成员可继续添加多个岗位，不会重复创建账号。</p>
              </template>
              <template v-else-if="manualEditor.section === 'wbs'">
                <fieldset class="record-editor-fieldset full-span">
                  <legend>结构与归属</legend>
                  <div class="record-editor-grid">
                    <label>WBS 编码<input v-model.trim="editorWbsForm.code" required maxlength="128" placeholder="例如 1.1"></label>
                    <label class="record-editor-span-2">工序名称<input v-model.trim="editorWbsForm.name" required maxlength="300" placeholder="填写完整工序名称"></label>
                    <label>查找上级工序<input v-model.trim="editorWbsForm.parentSearch" placeholder="输入编码或名称筛选"></label>
                    <label>上级工序<select v-model="editorWbsForm.parentId" @change="syncEditorWbsLevelWithParent"><option value="">无上级工序（根节点）</option><option v-for="item in filteredEditorWbsParentOptions" :key="item.id" :value="item.id">{{ item.code }} · {{ item.name }}</option></select></label>
                    <label>层级<input v-model.number="editorWbsForm.level" required type="number" min="1" max="100"></label>
                    <label>同级排序<input v-model.number="editorWbsForm.sortOrder" required type="number" min="0"></label>
                    <label>节点类型<input v-model.trim="editorWbsForm.itemType" list="wbs-item-type-options" maxlength="100" placeholder="例如：任务、里程碑"><datalist id="wbs-item-type-options"><option value="项目"></option><option value="汇总任务"></option><option value="任务组"></option><option value="任务"></option><option value="里程碑"></option></datalist></label>
                    <label>负责人<input v-model.trim="editorWbsForm.assignedToText" list="wbs-assignee-options" maxlength="300" placeholder="未分配可留空"><datalist id="wbs-assignee-options"><option v-for="member in configScope.members" :key="member.id" :value="member.name"></option></datalist></label>
                    <label>标识颜色<input v-model.trim="editorWbsForm.colorValue" maxlength="50" placeholder="例如 #2F7D70"></label>
                  </div>
                </fieldset>

                <fieldset class="record-editor-fieldset full-span">
                  <legend>计划与执行</legend>
                  <div class="record-editor-grid">
                    <label>计划开始<input v-model="editorWbsForm.plannedStart" type="date"></label>
                    <label>计划完成<input v-model="editorWbsForm.plannedFinish" type="date"></label>
                    <label>截止日期<input v-model="editorWbsForm.deadline" type="date"></label>
                    <label>完成进度（%）<input v-model.number="editorWbsForm.progress" type="number" min="0" max="100" step="0.01"></label>
                    <label>状态<input v-model.trim="editorWbsForm.statusText" list="wbs-status-options" maxlength="100" placeholder="空状态可留空"><datalist id="wbs-status-options"><option value="打开"></option><option value="未开始"></option><option value="进行中"></option><option value="已完成"></option><option value="已延期"></option></datalist><small>保留导入状态原值；留空表示未设置。</small></label>
                    <label>优先级<input v-model.trim="editorWbsForm.priorityText" list="wbs-priority-options" maxlength="100" placeholder="未设置可留空"><datalist id="wbs-priority-options"><option value="紧急"></option><option value="高"></option><option value="中"></option><option value="普通"></option><option value="低"></option></datalist></label>
                    <label>计划工期（小时）<input v-model.number="editorWbsForm.durationHours" type="number" min="0" step="0.01" placeholder="未设置"></label>
                    <label>预估工时（小时）<input v-model.number="editorWbsForm.estimatedHours" type="number" min="0" step="0.01" placeholder="未设置"></label>
                    <label>已登记工时（分钟）<input v-model.number="editorWbsForm.timeLogMinutes" type="number" min="0" step="1" placeholder="未设置"></label>
                  </div>
                </fieldset>

                <fieldset class="record-editor-fieldset full-span">
                  <legend>依赖、成本与工作内容</legend>
                  <div class="record-editor-grid">
                    <label>预算<input v-model.number="editorWbsForm.budget" type="number" min="0" step="0.01" placeholder="未设置"></label>
                    <label>实际成本<input v-model.number="editorWbsForm.actualCost" type="number" min="0" step="0.01" placeholder="未设置"></label>
                    <div class="record-editor-span-3 wbs-dependency-field"><span>前置工序</span><div class="wbs-dependency-picker"><label class="wbs-dependency-search"><n-icon :size="16"><Search /></n-icon><input v-model.trim="editorWbsForm.predecessorSearch" placeholder="按 WBS 编码或工序名称查找"></label><div v-if="selectedEditorWbsPredecessors.length" class="wbs-dependency-selected"><button v-for="item in selectedEditorWbsPredecessors" :key="item.id" type="button" :title="`移除前置工序 ${item.code}`" @click="removeEditorWbsPredecessor(item.id)"><strong>{{ item.code }}</strong><span>{{ item.name }}</span><n-icon :size="14"><X /></n-icon></button></div><p v-else>尚未选择前置工序</p><div class="wbs-dependency-options"><label v-for="item in filteredEditorWbsPredecessorOptions" :key="item.id"><input v-model="editorWbsForm.predecessorIds" type="checkbox" :value="item.id"><span><strong>{{ item.code }}</strong>{{ item.name }}</span></label><p v-if="!filteredEditorWbsPredecessorOptions.length">没有符合条件的工序</p></div></div></div>
                    <label class="record-editor-span-3">工作内容与说明<textarea v-model.trim="editorWbsForm.description" rows="6" maxlength="20000" placeholder="填写该工序的范围、交付内容、验收边界或其他说明"></textarea></label>
                  </div>
                </fieldset>

                <fieldset v-if="manualEditorWbsItem && hasManualEditorWbsSource" class="record-editor-fieldset wbs-source-fieldset full-span">
                  <legend>来源信息（只读）</legend>
                  <dl>
                    <div><dt>Microsoft Project UID</dt><dd>{{ manualEditorWbsItem.mspUid || '—' }}</dd></div>
                    <div><dt>Microsoft Project ID</dt><dd>{{ manualEditorWbsItem.mspId || '—' }}</dd></div>
                    <div><dt>来源创建人</dt><dd>{{ manualEditorWbsItem.sourceCreator || '—' }}</dd></div>
                    <div><dt>来源创建时间</dt><dd>{{ formatSourceDateTime(manualEditorWbsItem.sourceCreatedAt) || '—' }}</dd></div>
                    <div class="wbs-source-path"><dt>来源文件</dt><dd>{{ manualEditorWbsItem.sourceProjectPath || '—' }}</dd></div>
                  </dl>
                </fieldset>
              </template>
              <template v-else-if="manualEditor.section === 'quality'">
                <fieldset class="record-editor-fieldset full-span">
                  <legend>关联工序</legend>
                  <div class="record-editor-grid">
                    <label class="record-editor-span-3">查找 WBS<input v-model.trim="editorQualityForm.wbsSearch" placeholder="输入编码或工序名称筛选"></label>
                    <label class="record-editor-span-3">选择工序<select v-model="editorQualityForm.wbsId" required size="6"><option v-for="item in filteredEditorQualityWbsOptions" :key="item.id" :value="item.id">{{ item.code }} · {{ item.name }}</option></select><small>质量要求必须关联一个明确的 WBS 工序。</small></label>
                  </div>
                </fieldset>
                <fieldset class="record-editor-fieldset full-span">
                  <legend>验收与控制要求</legend>
                  <div class="record-editor-grid">
                    <label class="record-editor-span-2">质量验收项<input v-model.trim="editorQualityForm.name" required maxlength="300" placeholder="填写验收项目或检查内容"></label>
                    <label>检查频次<input v-model.trim="editorQualityForm.frequency" placeholder="例如：每道工序一次"></label>
                    <label class="record-editor-span-3">控制指标<textarea v-model.trim="editorQualityForm.requirement" required rows="6" maxlength="20000" placeholder="填写验收标准、允许偏差或控制指标"></textarea></label>
                    <label class="record-editor-span-3">关联资料<textarea v-model.trim="editorQualityForm.relatedDocuments" rows="5" maxlength="20000" placeholder="填写检查记录、检测报告、验收资料等，可使用顿号或换行分隔"></textarea></label>
                  </div>
                </fieldset>
              </template>
              <template v-else-if="manualEditor.section === 'risks'">
                <fieldset class="record-editor-fieldset full-span">
                  <legend>风险识别与窗口</legend>
                  <div class="record-editor-grid">
                    <label>风险序号<input v-model.number="editorRiskForm.serialNo" required type="number" min="1" step="1"></label>
                    <label>风险等级<input v-model.trim="editorRiskForm.levelText" required list="risk-level-options" maxlength="50" placeholder="例如：重大"><datalist id="risk-level-options"><option value="重大"></option><option value="较大"></option><option value="一般"></option><option value="低"></option></datalist></label>
                    <label class="record-editor-span-3">风险部位或事项<input v-model.trim="editorRiskForm.name" required maxlength="300" placeholder="填写具体风险部位、对象或事项"></label>
                    <label class="record-editor-span-3">相关工序<input v-model.trim="editorRiskForm.type" required maxlength="300" placeholder="填写风险对应的施工工序或作业类型"></label>
                    <label>风险开始日期<input v-model="editorRiskForm.plannedStart" type="date"></label>
                    <label>风险结束日期<input v-model="editorRiskForm.plannedFinish" type="date"></label>
                  </div>
                </fieldset>
                <fieldset class="record-editor-fieldset full-span">
                  <legend>评价与处置依据</legend>
                  <div class="record-editor-grid">
                    <label class="record-editor-span-3">评价条件与控制要求<textarea v-model.trim="editorRiskForm.evaluationCondition" required rows="6" maxlength="20000" placeholder="填写触发条件、判定标准、控制措施或处置要求"></textarea></label>
                    <label class="record-editor-span-3">风险摘要<textarea v-model.trim="editorRiskForm.summary" rows="5" maxlength="20000" placeholder="概括风险影响、关注重点或所需资料"></textarea></label>
                  </div>
                </fieldset>
              </template>
              <template v-else-if="manualEditor.section === 'mappings'"><label>平台名称<input v-model.trim="editorMappingForm.platformName" required placeholder="例如：监管填报平台"></label><label>来源字段<select v-model="editorMappingForm.sourceField"><option value="draft_title">草稿标题</option><option value="draft_content">草稿内容</option><option value="source_refs">来源资料</option></select></label><label class="full-span">目标字段<input v-model.trim="editorMappingForm.targetField" required placeholder="平台目标字段"></label><label class="full-span">转换规则<input v-model.trim="editorMappingForm.transformRule" placeholder="例如：保留原文、拼接来源资料"></label><label class="check-label"><input v-model="editorMappingForm.required" type="checkbox"> 必填字段</label><label class="check-label"><input v-model="editorMappingForm.enabled" type="checkbox"> 启用映射</label></template>
              <template v-else><label class="full-span">资料接收目录<input v-model.trim="monitorForm.mainDir" placeholder="例如：\\server\project\incoming"></label><label>归档目录<input v-model.trim="monitorForm.archiveDir" placeholder="已确认资料归档位置"></label><label>失败目录<input v-model.trim="monitorForm.failedDir" placeholder="解析失败资料位置"></label><label>扫描间隔（分钟）<input v-model.number="monitorForm.scanInterval" type="number" min="1" max="1440"></label><label class="check-label"><input v-model="monitorForm.enabled" type="checkbox"> 启用目录监控</label><div class="manual-rule-editor full-span"><div><strong>风险预警规则</strong><small>配置后用于风险关联和任务生成。</small></div><div><select v-model="reminderForm.level"><option value="critical">重大风险</option><option value="high">高风险</option><option value="medium">中风险</option><option value="low">低风险</option></select><input v-model.number="reminderForm.days" type="number" min="0" max="365" placeholder="提前天数"><button type="button" class="secondary-action" @click="addReminderRule">添加规则</button></div><ul><li v-for="rule in monitorRules" :key="rule.id">{{ riskLabel(rule.level) }} · 提前 {{ rule.days }} 天 <button type="button" class="link-button" @click="removeReminderRule(rule.id)">移除</button></li><li v-if="!monitorRules.length">暂无预警规则。</li></ul></div></template>
              <footer class="manual-editor-actions"><button type="button" class="modal-secondary" :disabled="submitting" @click="closeManualEditor">取消</button><button class="primary" :disabled="submitting">{{ submitting ? '正在保存…' : manualEditor.mode === 'edit' ? '保存修改' : '确认创建' }}</button></footer>
            </form>
          </section>
        </div>
      </template>
      </div>
      </main>

      <section v-else class="project-empty-stage">
        <div v-if="!store.projectCatalogLoaded" class="project-empty-loading" aria-label="正在加载项目">
          <i></i><span></span><span></span><button type="button" disabled></button>
        </div>
        <div v-else class="project-empty-content">
          <div v-if="projectRequiredNotice" class="project-required-notice">
            <n-icon :size="17"><Shield /></n-icon>
            <span><strong>当前功能需要项目</strong>请先完成项目创建，其他业务菜单随后自动开放。</span>
          </div>
          <span class="project-empty-kicker">项目初始化</span>
          <h1>先建立项目，再逐步补全工程资料</h1>
          <p class="project-empty-description">首次创建只需要填写项目名称。项目建立后，可通过 Dobby 配置助手问答或上传附件，继续完善人员、WBS、风险源和质量指标。</p>
          <button type="button" class="project-empty-primary" @click="openProjectCreate">
            <n-icon :size="18"><Plus /></n-icon>
            新建工程项目
          </button>
          <ol class="project-init-path">
            <li><span>01</span><div><strong>创建项目</strong><small>只填写项目名称</small></div></li>
            <li><span>02</span><div><strong>补充资料</strong><small>问答或上传附件</small></div></li>
            <li><span>03</span><div><strong>核对入库</strong><small>确认后形成项目数据</small></div></li>
          </ol>
        </div>
      </section>

      <div v-if="projectCreateOpen" class="setup-modal-backdrop" @click.self="closeProjectCreate">
        <section class="setup-modal" role="dialog" aria-modal="true" aria-labelledby="project-create-title">
          <div class="setup-modal-head">
            <div><h2 id="project-create-title">新建工程项目</h2><p>先创建项目，其他工程信息将在初始化阶段逐步补全。</p></div>
          </div>
          <form class="form-stack project-create-form" @submit.prevent="submitProject">
            <label>项目名称<input v-model.trim="projectForm.name" required maxlength="200" autofocus placeholder="请输入项目名称"></label>
            <div class="setup-modal-actions"><button type="button" class="modal-secondary" :disabled="submitting" @click="closeProjectCreate">取消</button><button type="submit" class="primary" :disabled="submitting || !projectForm.name.trim()">创建项目</button></div>
          </form>
        </section>
      </div>

      <div v-if="initializationDraftReviewOpen && materialAgentDraft" class="setup-modal-backdrop initialization-review-backdrop" @click.self="closeInitializationDraftReview">
        <section class="setup-modal initialization-review-modal" role="dialog" aria-modal="true" aria-labelledby="initialization-review-title">
          <header class="setup-modal-head">
            <div><h2 id="initialization-review-title" :title="configProjectName">{{ configProjectName }} · 初始化草稿核对</h2></div>
            <button type="button" class="modal-close" :disabled="initializationDraftApplying" aria-label="关闭核对窗口" @click="closeInitializationDraftReview"><n-icon :size="17"><X /></n-icon></button>
          </header>

          <div class="initialization-review-body">
            <section v-if="draftProjectFields.length" class="initialization-review-section initialization-project-section">
              <header class="initialization-project-head">
                <div><h3>工程基本信息</h3><p>核对从项目资料中识别的合同信息与参建单位。</p></div>
                <span>{{ draftProjectFields.length }} 项已识别</span>
              </header>
              <article v-if="draftProjectDescription" class="initialization-project-description">
                <span>{{ draftProjectDescription.label }}</span>
                <p>{{ draftProjectDescription.value }}</p>
              </article>
              <div v-if="draftProjectContractFields.length" class="initialization-project-contract-grid">
                <article v-for="item in draftProjectContractFields" :key="item.key">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </article>
              </div>
              <div v-if="draftProjectUnitFields.length" class="initialization-project-units">
                <h4>参建单位</h4>
                <dl>
                  <div
                    v-for="item in draftProjectUnitFields"
                    :key="item.key"
                    :class="{ primary: item.key === 'construction_unit_name' }"
                  >
                    <dt>{{ item.label }}</dt>
                    <dd>{{ item.value }}</dd>
                  </div>
                </dl>
              </div>
            </section>

            <section v-if="materialAgentDraft.payload.personnel.length" class="initialization-review-data-section">
              <button type="button" class="initialization-review-data-toggle" :class="{ expanded: initializationReviewExpanded.personnel }" :aria-expanded="initializationReviewExpanded.personnel" @click="initializationReviewExpanded.personnel = !initializationReviewExpanded.personnel">
                <n-icon :size="16" aria-hidden="true"><ChevronDown /></n-icon>
                <span><strong>人员</strong><small>身份、岗位、证书与登录账号</small></span>
                <em>{{ materialAgentDraft.summary.personnel }} 人 · {{ materialAgentDraft.summary.position_assignments }} 条任职</em>
              </button>
              <div v-show="initializationReviewExpanded.personnel" class="initialization-personnel-list">
                <article
                  v-for="item in initializationPersonnelReviewRows"
                  :key="`${item.identity_card_no}-${item.serial_no}`"
                  class="initialization-personnel-card"
                >
                  <header class="initialization-personnel-profile">
                    <span>{{ String(item.serial_no).padStart(2, '0') }}</span>
                    <div>
                      <h4>{{ item.real_name }}</h4>
                      <p>{{ item.position_name }}</p>
                    </div>
                    <em v-if="item.credential">将新建账号</em>
                    <em v-else-if="item.existingAccount" class="existing">已匹配账号</em>
                    <em v-else-if="item.sharedCredential" class="shared">共用账号</em>
                  </header>
                  <dl class="initialization-personnel-facts">
                    <div>
                      <dt>身份证号</dt>
                      <dd>{{ item.identity_card_no }}</dd>
                    </div>
                    <div>
                      <dt>证书编号</dt>
                      <dd>{{ item.certificate_no || '' }}</dd>
                    </div>
                    <div class="responsibility">
                      <dt>岗位职责</dt>
                      <dd>{{ item.responsibility_description || '' }}</dd>
                    </div>
                  </dl>
                  <div v-if="item.credential" class="initialization-personnel-credential">
                    <div>
                      <strong>将新建平台账号</strong>
                      <span>已按姓名自动生成，可修改</span>
                    </div>
                    <label>
                      登录账号
                      <input v-model.trim="item.credential.username" autocomplete="off" maxlength="64" spellcheck="false" placeholder="自动生成拼音账号">
                    </label>
                    <label>
                      初始密码
                      <span class="initialization-generated-password">
                        <input v-model="item.credential.initial_password" type="text" autocomplete="new-password" maxlength="12" spellcheck="false" placeholder="自动生成 8–12 位密码">
                        <button type="button" @click="item.credential.initial_password = generateInitializationPassword()">换一个</button>
                      </span>
                    </label>
                    <p>确认入库时创建账号。请将初始密码安全交给本人，并提醒首次登录后修改。</p>
                  </div>
                  <div v-else-if="item.existingAccount" class="initialization-personnel-account-ready existing">
                    <small>已关联现有平台账号</small>
                    <strong>{{ item.existingAccount.username }}</strong>
                    <span>身份证号匹配成功。确认后只把该账号加入当前项目，不会重建账号或修改密码。</span>
                  </div>
                  <div v-else-if="item.sharedCredential" class="initialization-personnel-account-ready shared">
                    <small>同一人员兼任岗位</small>
                    <strong>{{ item.sharedCredential.username }}</strong>
                    <span>该岗位将与同一身份证号的其他岗位共用上方新账号，不会重复创建用户。</span>
                  </div>
                  <div v-else class="initialization-personnel-account-ready">
                    <strong>账号状态待确认</strong>
                    <span>请重新打开草稿获取最新账号匹配结果。</span>
                  </div>
                </article>
              </div>
            </section>

            <section v-if="materialAgentDraft.payload.wbs.length" class="initialization-review-data-section">
              <button type="button" class="initialization-review-data-toggle" :class="{ expanded: initializationReviewExpanded.wbs }" :aria-expanded="initializationReviewExpanded.wbs" @click="initializationReviewExpanded.wbs = !initializationReviewExpanded.wbs">
                <n-icon :size="16" aria-hidden="true"><ChevronDown /></n-icon>
                <span><strong>WBS</strong><small>工序计划、执行状态与层级关系</small></span>
                <em>{{ materialAgentDraft.payload.wbs.length }} 项</em>
              </button>
              <div v-show="initializationReviewExpanded.wbs" class="initialization-wbs-content">
                <div class="initialization-wbs-toolbar">
                  <div>
                    <strong>树形工序结构</strong>
                    <span>当前显示 {{ visibleInitializationWbsRows.length }}/{{ materialAgentDraft.payload.wbs.length }} 项</span>
                    <em v-if="initializationWbsSequenceWarningCount" class="sequence-warning">
                      <n-icon :size="15" aria-hidden="true"><AlertTriangle /></n-icon>
                      {{ initializationWbsSequenceWarningCount }} 项时间线异常
                    </em>
                    <em v-if="initializationWbsDependencyWarningCount">
                      <n-icon :size="15" aria-hidden="true"><AlertTriangle /></n-icon>
                      {{ initializationWbsDependencyWarningCount }} 项依赖日期需核对
                    </em>
                  </div>
                  <div>
                    <button type="button" @click="expandAllInitializationWbs">全部展开</button>
                    <button type="button" @click="collapseAllInitializationWbs">全部收起</button>
                  </div>
                </div>
                <div class="initialization-wbs-table-wrap">
                  <table class="initialization-wbs-table">
                    <thead>
                      <tr>
                        <th>WBS 编码</th>
                        <th>工序名称</th>
                        <th>计划开始</th>
                        <th>计划完成</th>
                        <th>进度</th>
                        <th>状态</th>
                        <th>优先级</th>
                        <th>前置 WBS</th>
                        <th>上级</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="row in visibleInitializationWbsRows"
                        :key="row.item.wbs_code"
                        :class="{
                          'is-wbs-group': row.hasChildren,
                          'has-sequence-warning': row.sequenceWarnings.length,
                          'has-dependency-warning': row.dependencyWarnings.length,
                        }"
                        :title="[...row.sequenceWarnings, ...row.dependencyWarnings].join('；')"
                      >
                        <td><strong>{{ row.item.wbs_code }}</strong></td>
                        <td class="initialization-wbs-name">
                          <div
                            class="initialization-wbs-tree-node"
                            :class="{ root: row.depth === 0 }"
                            :style="{ '--wbs-depth': row.depth }"
                          >
                            <button
                              v-if="row.hasChildren"
                              type="button"
                              class="initialization-wbs-node-toggle"
                              :class="{ collapsed: isInitializationWbsCollapsed(row.item.wbs_code) }"
                              :aria-label="`${isInitializationWbsCollapsed(row.item.wbs_code) ? '展开' : '收起'} ${row.item.wbs_code} ${row.item.name}`"
                              :aria-expanded="!isInitializationWbsCollapsed(row.item.wbs_code)"
                              @click="toggleInitializationWbsNode(row.item.wbs_code)"
                            >
                              <n-icon :size="14" aria-hidden="true"><ChevronDown /></n-icon>
                            </button>
                            <span v-else class="initialization-wbs-leaf" aria-hidden="true"></span>
                            <span class="initialization-wbs-node-copy">
                              <strong>{{ row.item.name }}</strong>
                              <small v-if="row.item.item_type">{{ displayWbsItemType(row.item.item_type) }}</small>
                              <em v-if="row.sequenceWarnings.length">时间线异常</em>
                            </span>
                          </div>
                        </td>
                        <td>{{ formatInitializationDate(row.item.planned_start_at) }}</td>
                        <td>{{ formatInitializationDate(row.item.planned_finish_at) }}</td>
                        <td>{{ formatInitializationProgress(row.item.progress_percent) }}</td>
                        <td>{{ displayWbsStatusText(row.item.status_text) || '—' }}</td>
                        <td>{{ displayWbsPriorityText(row.item.priority_text, '') || '—' }}</td>
                        <td class="initialization-wbs-dependencies">
                          <span v-for="code in row.item.predecessor_wbs_codes || []" :key="code">{{ code }}</span>
                          <em v-if="row.dependencyWarnings.length">需核对</em>
                        </td>
                        <td>{{ row.item.parent_wbs_code || '' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section v-if="materialAgentDraft.payload.risks.length" class="initialization-review-data-section">
              <button type="button" class="initialization-review-data-toggle" :class="{ expanded: initializationReviewExpanded.risks }" :aria-expanded="initializationReviewExpanded.risks" @click="initializationReviewExpanded.risks = !initializationReviewExpanded.risks">
                <n-icon :size="16" aria-hidden="true"><ChevronDown /></n-icon>
                <span><strong>风险源</strong><small>风险部位、评价条件与风险窗口</small></span>
                <em>{{ materialAgentDraft.payload.risks.length }} 项</em>
              </button>
              <div v-show="initializationReviewExpanded.risks" class="initialization-risk-list">
                <article v-for="item in materialAgentDraft.payload.risks" :key="`${item.serial_no}-${item.risk_part}`" class="initialization-risk-card">
                  <header class="initialization-risk-head">
                    <div>
                      <span>序号 {{ item.serial_no }}</span>
                      <h4>{{ item.risk_part }}</h4>
                    </div>
                    <strong>{{ item.risk_level }}</strong>
                  </header>
                  <dl class="initialization-risk-facts">
                    <div>
                      <dt>相关工序</dt>
                      <dd>{{ item.related_process_name }}</dd>
                    </div>
                    <div v-if="item.risk_window_start_date || item.risk_window_end_date">
                      <dt>风险窗口</dt>
                      <dd class="initialization-risk-window">
                        <time v-if="item.risk_window_start_date" :datetime="item.risk_window_start_date">{{ formatInitializationDate(item.risk_window_start_date) }}</time>
                        <span v-if="item.risk_window_start_date && item.risk_window_end_date">至</span>
                        <time v-if="item.risk_window_end_date" :datetime="item.risk_window_end_date">{{ formatInitializationDate(item.risk_window_end_date) }}</time>
                      </dd>
                    </div>
                  </dl>
                  <div class="initialization-risk-details">
                    <section>
                      <h5>风险评价条件</h5>
                      <p>{{ item.evaluation_condition }}</p>
                    </section>
                    <section v-if="item.summary">
                      <h5>风险情况简述</h5>
                      <p>{{ item.summary }}</p>
                    </section>
                  </div>
                </article>
              </div>
            </section>

            <section v-if="materialAgentDraft.payload.quality_requirements.length" class="initialization-review-data-section">
              <button type="button" class="initialization-review-data-toggle" :class="{ expanded: initializationReviewExpanded.quality }" :aria-expanded="initializationReviewExpanded.quality" @click="initializationReviewExpanded.quality = !initializationReviewExpanded.quality">
                <n-icon :size="16" aria-hidden="true"><ChevronDown /></n-icon>
                <span><strong>质量指标</strong><small>按 WBS 编码关联质量要求</small></span>
                <em>{{ materialAgentDraft.payload.quality_requirements.length }} 项</em>
              </button>
              <div v-show="initializationReviewExpanded.quality" class="initialization-quality-table-wrap">
                <table class="initialization-quality-table">
                  <thead>
                    <tr>
                      <th>WBS 编码</th>
                      <th>质量验收项目</th>
                      <th>控制指标</th>
                      <th>检查频次</th>
                      <th>相关资料</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(item, index) in materialAgentDraft.payload.quality_requirements"
                      :key="`${item.wbs_code}-${index}`"
                    >
                      <td><code>{{ item.wbs_code }}</code></td>
                      <td><strong>{{ item.quality_acceptance_item }}</strong></td>
                      <td>{{ item.control_indicator || '' }}</td>
                      <td>{{ item.inspection_frequency || '' }}</td>
                      <td>{{ item.related_documents || '' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="materialAgentDraft.validation_issues.length" class="initialization-review-section draft-issues">
              <header class="draft-issues-heading">
                <div>
                  <h3>需要你确认的内容</h3>
                  <p>已按业务内容整理。必须修正的问题会阻止入库，其余提醒可核对后继续。</p>
                </div>
                <span>{{ materialAgentDraft.validation_issues.length }} 项</span>
              </header>
              <div class="draft-issues-summary" aria-label="校验问题统计">
                <span v-if="initializationDraftErrorCount" class="error"><strong>{{ initializationDraftErrorCount }}</strong> 项必须修正</span>
                <span v-if="initializationDraftWarningCount" class="warning"><strong>{{ initializationDraftWarningCount }}</strong> 项需要核对</span>
              </div>
              <div class="draft-issue-groups">
                <article
                  v-for="group in initializationDraftIssueGroups"
                  :key="group.key"
                  class="draft-issue-group"
                  :class="group.level"
                >
                  <button
                    type="button"
                    class="draft-issue-group-toggle"
                    :aria-expanded="Boolean(initializationIssueGroupsExpanded[group.key])"
                    @click="initializationIssueGroupsExpanded[group.key] = !initializationIssueGroupsExpanded[group.key]"
                  >
                    <span class="draft-issue-group-icon" aria-hidden="true"><n-icon :size="17"><AlertTriangle /></n-icon></span>
                    <span class="draft-issue-group-copy">
                      <strong>{{ group.label }}</strong>
                      <small>{{ group.description }}</small>
                    </span>
                    <span class="draft-issue-group-count">{{ group.items.length }} 项</span>
                    <n-icon class="draft-issue-group-chevron" :size="16" aria-hidden="true"><ChevronDown /></n-icon>
                  </button>
                  <ul v-show="initializationIssueGroupsExpanded[group.key]">
                    <li v-for="(issue, index) in group.items" :key="`${issue.path}-${index}`" :class="issue.level">
                      <header>
                        <div>
                          <strong>{{ issue.title }}</strong>
                          <span v-if="issue.reference">{{ issue.reference }}</span>
                        </div>
                        <em>{{ issue.level === 'error' ? '必须修正' : '需要核对' }}</em>
                      </header>
                      <p>{{ issue.description }}</p>
                      <div class="draft-issue-guidance">
                        <strong>怎么处理</strong>
                        <span>{{ issue.guidance }}</span>
                      </div>
                    </li>
                  </ul>
                </article>
              </div>
              <label v-if="draftHasWarnings && !draftHasErrors" class="initialization-partial-confirm"><input v-model="initializationDraftAllowPartial" type="checkbox">我已核对待补充项，确认先按当前草稿完成部分初始化</label>
            </section>

          </div>

          <footer class="initialization-review-actions">
            <span v-if="materialAgentDraft.status === 'applied'">该版本已经写入正式项目数据。</span>
            <span v-else-if="!isPlatformAdmin">只有平台管理员可以确认正式入库。</span>
            <span v-else-if="materialAgentDraft.status === 'collecting'">专业智能体仍在整理草稿，全部相关分区完成后将自动进入统一核验。</span>
            <span v-else-if="materialAgentDraft.status === 'reviewing'">核验智能体正在进行跨专业检查，核验完成后才可确认入库。</span>
            <span v-else>确认后将以该草稿整体写入项目基础数据。</span>
            <button type="button" class="modal-secondary" :disabled="initializationDraftApplying" @click="closeInitializationDraftReview">关闭</button>
            <button v-if="materialAgentDraft.status !== 'applied' && isPlatformAdmin" type="button" class="primary" :disabled="!canApplyInitializationDraft" @click="applyInitializationDraft">{{ initializationDraftApplying ? '正在入库…' : '确认并写入项目' }}</button>
          </footer>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon, useMessage } from 'naive-ui'
import dayjs from 'dayjs'
import { AlertTriangle, ArrowsLeftRight, ChevronDown, ChevronUp, Link, ListDetails, MessageCircle, Paperclip, Pencil, Plus, Search, Shield, ShieldLock, Users, X } from '@vicons/tabler'
import api, { type ApiEnvelope } from '@/api/client'
import {
  streamAgentConversationConfirmation,
  streamAgentConversationMessage,
} from '@/api/agentStream'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import { useAppStore, type ProjectConfigScope } from '@/stores/app'
import type { DirConfig, Member, MemberPosition, PlatformFieldMapping, QualityMetric, RemindRule, RiskLevel, RiskSource, WbsItem } from '@/types'
import {
  applyAgentRuntimeEvents,
  createEmptyRuntimeTrace,
  runtimeTraceFromExtraData,
  type AgentRuntimeTrace,
  type AgentTask,
  type AgentToolCallBlock,
  type ApiAgentMessage,
} from '@/types/agentRuntime'

type WorkspaceTab = 'agent' | 'manual' | 'connections'
type ManualSection = 'members' | 'wbs' | 'quality' | 'risks' | 'mappings' | 'monitor'
type ManualWbsTreeRow = { item: WbsItem; depth: number; hasChildren: boolean }
type InitializationAttachment = { id: string; name: string; size: number }
type MaterialAgentMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  attachments?: InitializationAttachment[]
  runtimeTrace?: AgentRuntimeTrace | null
}
type ApiAgentConversation = {
  id: number
  project_id: number
  user_id: number
  agent_id: string
  agent_name: string
  conversation_type: 'initialization'
  title: string
  agentscope_session_id?: string | null
  status: string
}
type ApiInitializationFile = {
  id: number
  project_id: number
  conversation_id: number
  file_name: string
  file_size: number
}
type InitializationDraftIssue = {
  level: 'error' | 'warning'
  path: string
  message: string
}
type InitializationDraftIssueGroupKey = 'project' | 'personnel' | 'wbs_content' | 'wbs_timeline' | 'wbs_structure' | 'risks' | 'quality' | 'other'
type InitializationDraftIssuePresentation = InitializationDraftIssue & {
  category: InitializationDraftIssueGroupKey
  title: string
  description: string
  guidance: string
  reference?: string
}
type InitializationDraftIssueGroup = {
  key: InitializationDraftIssueGroupKey
  label: string
  description: string
  level: 'error' | 'warning'
  items: InitializationDraftIssuePresentation[]
}
type InitializationDraftPersonnel = {
  serial_no: number
  real_name: string
  identity_card_no: string
  position_name: string
  certificate_no: string
  responsibility_description: string
}
type InitializationDraftWbs = {
  wbs_code: string
  parent_wbs_code?: string | null
  predecessor_wbs_codes?: string[]
  name: string
  planned_start_at?: string | null
  planned_finish_at?: string | null
  progress_percent?: number | string | null
  status_text?: string | null
  priority_text?: string | null
  duration_hours?: number | string | null
  level?: number | null
  item_type?: string | null
}
type InitializationWbsTreeRow = {
  item: InitializationDraftWbs
  depth: number
  ancestorCodes: string[]
  hasChildren: boolean
  sequenceWarnings: string[]
  dependencyWarnings: string[]
}
type InitializationDraftRisk = {
  serial_no: number
  related_process_name: string
  risk_part: string
  risk_level: string
  evaluation_condition: string
  risk_window_start_date?: string | null
  risk_window_end_date?: string | null
  summary?: string | null
}
type InitializationDraftQuality = {
  wbs_code: string
  quality_acceptance_item: string
  control_indicator: string
  inspection_frequency: string
  related_documents: string
}
type ApiInitializationDraft = {
  id: number
  project_id: number
  conversation_id: number
  status: 'collecting' | 'reviewing' | 'invalid' | 'ready' | 'applied' | 'rejected'
  revision: number
  payload: {
    project: Record<string, string | number | null>
    personnel: InitializationDraftPersonnel[]
    wbs: InitializationDraftWbs[]
    risks: InitializationDraftRisk[]
    quality_requirements: InitializationDraftQuality[]
  }
  validation_issues: InitializationDraftIssue[]
  source_files: string[]
  workflow?: {
    stage: 'collecting' | 'reviewing' | 'completed'
    run_revision: number
    expected_sections: string[]
    completed_sections: string[]
    pending_sections: string[]
    reviewer_agent_id?: string | null
    semantic_issues: InitializationDraftIssue[]
    review_summary?: string | null
  } | null
  required_personnel_credentials: Array<{
    identity_card_no: string
    real_name: string
    position_name: string
    suggested_username: string
  }>
  existing_personnel_accounts: Array<{
    identity_card_no: string
    user_id: number
    username: string
    real_name: string
  }>
  summary: {
    project_fields: number
    personnel: number
    position_assignments: number
    wbs: number
    risks: number
    quality_requirements: number
  }
}
type InitializationCredentialForm = {
  identity_card_no: string
  real_name: string
  position_name: string
  suggested_username: string
  username: string
  initial_password: string
}
type ProjectConnectorKey = 'wecom' | 'feishu' | 'dingtalk'
type ProjectConnectorConfig = {
  key: ProjectConnectorKey
  label: string
  description: string
  connectionLabel: string
  connectionPlaceholder: string
  secretLabel: string
  connectionId: string
  secret: string
  configured: boolean
  updatedAt: string
  icon: any
}

const store = useAppStore()
const message = useMessage()
const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const configScopeLoading = ref(false)
const configProjectId = ref('')
const configProjectName = computed(() => store.projects.find(project => project.id === configProjectId.value)?.name || '当前项目')
const projectRequiredNotice = computed(() => route.query.projectRequired === '1')
const configScope = reactive<ProjectConfigScope>({ members: [], wbsItems: [], riskSources: [], qualityMetrics: [], platformMappings: [], dirConfig: { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false }, remindRules: [] })
const activeWorkspaceTab = ref<WorkspaceTab>('agent')
const workspaceTabs: Array<{ key: WorkspaceTab; label: string; hint: string }> = [
  { key: 'agent', label: 'Dobby 配置助手', hint: '初始化' },
  { key: 'manual', label: '人工配置', hint: '手工维护' },
  { key: 'connections', label: '连接配置', hint: '协同工具' },
]
const projectCreateOpen = ref(false)
const projectForm = reactive({ name: '' })
const memberForm = reactive({
  name: '',
  username: '',
  identityCardNo: '',
  password: '',
  positionName: '',
})
const wbsForm = reactive({ code: '', name: '', planned_start: '', planned_finish: '' })
const riskForm = reactive<{ name: string; level: RiskLevel; risk_type: string; materials: string }>({ name: '', level: 'medium', risk_type: '', materials: '' })
const qualityForm = reactive({ wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' })
const mappingForm = reactive({ platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false })
const monitorForm = reactive<DirConfig>({ mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false })
const monitorRules = ref<RemindRule[]>([])
const reminderForm = reactive<{ level: RiskLevel; days: number }>({ level: 'medium', days: 7 })
const manualSection = ref<ManualSection>('members')
const manualSearch = ref('')
const collapsedManualWbsIds = ref<Set<string>>(new Set())
const personnelDetailMemberId = ref('')
const personnelDetailPositionId = ref('')
const manualEditor = reactive<{
  open: boolean
  mode: 'create' | 'edit'
  section: ManualSection
  itemId: string
  assignmentId: string
}>({ open: false, mode: 'create', section: 'wbs', itemId: '', assignmentId: '' })
const editorMemberForm = reactive({
  name: '',
  username: '',
  identityCardNo: '',
  password: '',
  positionName: '',
  certificateNo: '',
  responsibilityDescription: '',
})
const editorWbsForm = reactive({
  code: '',
  name: '',
  parentId: '',
  parentSearch: '',
  level: 1,
  sortOrder: 0,
  colorValue: '',
  assignedToText: '',
  itemType: '',
  plannedStart: '',
  plannedFinish: '',
  deadline: '',
  progress: 0,
  statusText: '',
  priorityText: '',
  durationHours: '' as number | '',
  estimatedHours: '' as number | '',
  timeLogMinutes: '' as number | '',
  budget: '' as number | '',
  actualCost: '' as number | '',
  predecessorIds: [] as string[],
  predecessorSearch: '',
  description: '',
})
const editorQualityForm = reactive({ wbsId: '', wbsSearch: '', name: '', requirement: '', frequency: '', relatedDocuments: '' })
const editorRiskForm = reactive({
  serialNo: 1,
  name: '',
  levelText: '一般',
  type: '',
  plannedStart: '',
  plannedFinish: '',
  evaluationCondition: '',
  summary: '',
})
const editorMappingForm = reactive({ platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', transformRule: '', required: false, enabled: true })
const materialAgentMessages = ref<MaterialAgentMessage[]>([])
const materialAgentConversationLoading = ref(false)
const materialAgentPrompt = ref('')
const materialAgentSending = ref(false)
const materialAgentConfirming = ref(false)
const materialAgentLoading = computed(
  () => materialAgentSending.value || materialAgentConfirming.value,
)
const materialAgentStopping = ref(false)
const materialAgentError = ref('')
const materialAgentFileInput = ref<HTMLInputElement | null>(null)
const materialAgentFiles = ref<File[]>([])
const materialAgentViewport = ref<HTMLElement | null>(null)
const materialAgentFollowOutput = ref(true)
const materialAgentConversationId = ref<number | null>(null)
const materialAgentConversationStatus = ref('')
const materialAgentStreamingTrace = shallowRef<AgentRuntimeTrace | null>(null)
const materialAgentPlanCollapsed = ref(false)
let materialAgentStreamAbortController: AbortController | null = null
let materialAgentConfirmAbortController: AbortController | null = null
let materialAgentReconcileSequence = 0
let materialConversationLoadSequence = 0
const activeMaterialAgentStatuses = new Set([
  'creating',
  'running',
  'interrupting',
  'awaiting_permission',
  'awaiting_external_result',
])
const materialAgentExecutionPlan = computed(() => {
  if (materialAgentStreamingTrace.value) {
    const tasks = materialAgentStreamingTrace.value.tasksContext?.tasks || []
    return tasks.length
      ? { tasks, status: materialAgentStreamingTrace.value.status }
      : null
  }
  const latestAssistant = [...materialAgentMessages.value]
    .reverse()
    .find(item => item.role === 'assistant')
  const tasks = latestAssistant?.runtimeTrace?.tasksContext?.tasks || []
  return tasks.length
    ? {
        tasks,
        status: latestAssistant?.runtimeTrace?.status || 'completed',
      }
    : null
})
const materialAgentPlanCompletedCount = computed(() => (
  materialAgentExecutionPlan.value?.tasks.filter(
    task => task.state === 'completed',
  ).length || 0
))
const materialAgentPlanCompleted = computed(() => {
  const plan = materialAgentExecutionPlan.value
  return Boolean(
    plan?.tasks.length
    && materialAgentPlanCompletedCount.value === plan.tasks.length,
  )
})
const materialAgentPlanProgress = computed(() => {
  const total = materialAgentExecutionPlan.value?.tasks.length || 0
  return total
    ? Math.round(materialAgentPlanCompletedCount.value * 100 / total)
    : 0
})
const materialAgentPlanCurrentLabel = computed(() => {
  const plan = materialAgentExecutionPlan.value
  if (!plan) return ''
  const current = plan.tasks.find(task => task.state === 'in_progress')
  if (current) return current.subject
  if (materialAgentPlanCompleted.value) return '全部完成'
  if (plan.status === 'interrupted') return '已停止'
  return plan.tasks.find(task => task.state !== 'completed')?.subject || ''
})
const materialAgentPlanStatusLabel = computed(() => {
  const plan = materialAgentExecutionPlan.value
  if (!plan) return ''
  if (materialAgentPlanCompleted.value) return '已完成'
  if (plan.status === 'interrupted') return '已停止'
  if (plan.status === 'error') return '异常结束'
  if (activeMaterialAgentStatuses.has(plan.status)) return '执行中'
  return '待继续'
})

function materialAgentTaskStateLabel(state: AgentTask['state']) {
  return ({
    pending: '待处理',
    in_progress: '进行中',
    completed: '已完成',
  } as Record<string, string>)[state] || state
}
const materialAgentDraft = ref<ApiInitializationDraft | null>(null)
const initializationDraftCollapsed = ref(false)
const initializationDraftReviewOpen = ref(false)
const collapsedInitializationWbsCodes = ref<Set<string>>(new Set())
const initializationReviewExpanded = reactive({
  personnel: true,
  wbs: true,
  risks: true,
  quality: true,
})
const initializationIssueGroupsExpanded = reactive<Record<InitializationDraftIssueGroupKey, boolean>>({
  project: true,
  personnel: true,
  wbs_content: true,
  wbs_timeline: false,
  wbs_structure: true,
  risks: true,
  quality: true,
  other: true,
})
const initializationDraftApplying = ref(false)
const initializationDraftAllowPartial = ref(false)
const initializationCredentialForms = ref<InitializationCredentialForm[]>([])
const activeProjectConnectorKey = ref<ProjectConnectorKey>('wecom')
const projectConnectors = reactive<ProjectConnectorConfig[]>([
  { key: 'wecom', label: '企业微信', description: '配置当前项目使用的企业微信应用或项目群机器人。', connectionLabel: '企业 ID / 机器人 Webhook', connectionPlaceholder: '输入企业 ID 或项目群机器人 Webhook', secretLabel: '应用 Secret / 签名密钥', connectionId: '', secret: '', configured: false, updatedAt: '', icon: MessageCircle },
  { key: 'feishu', label: '飞书', description: '配置当前项目使用的飞书应用或项目群机器人。', connectionLabel: '应用 ID / 机器人 Webhook', connectionPlaceholder: '输入应用 ID 或项目群机器人 Webhook', secretLabel: '应用 Secret / 签名密钥', connectionId: '', secret: '', configured: false, updatedAt: '', icon: MessageCircle },
  { key: 'dingtalk', label: '钉钉', description: '配置当前项目使用的钉钉应用或项目群机器人。', connectionLabel: '应用 Key / 机器人 Webhook', connectionPlaceholder: '输入应用 Key 或项目群机器人 Webhook', secretLabel: '应用 Secret / 加签密钥', connectionId: '', secret: '', configured: false, updatedAt: '', icon: MessageCircle },
])
const activeProjectConnector = computed(() => projectConnectors.find(item => item.key === activeProjectConnectorKey.value))
const configuredProjectConnectorCount = computed(() => projectConnectors.filter(item => item.configured).length)
const projectConnectorStorageKey = computed(() => `dobby-project-connectors:${configProjectId.value || 'current'}`)
const manualSections = computed(() => [
  { key: 'members' as const, label: '项目成员', description: '维护成员账号、岗位与协作责任。', count: configScope.members.length, icon: Users },
  { key: 'wbs' as const, label: 'WBS进度管理', description: '维护工序基线，供进度、日报和预警匹配。', count: configScope.wbsItems.length, icon: ListDetails },
  { key: 'quality' as const, label: '质量指标', description: '维护验收要求、检查频次与关联工序。', count: configScope.qualityMetrics.length, icon: Shield },
  { key: 'risks' as const, label: '风险源', description: '维护风险等级、控制要求和资料要求。', count: configScope.riskSources.length, icon: Shield },
  { key: 'mappings' as const, label: '字段映射', description: '维护外部平台填报字段的映射规则。', count: configScope.platformMappings.length, icon: ArrowsLeftRight },
  { key: 'monitor' as const, label: '监控与预警', description: '维护资料目录监控与风险预警提前量。', count: monitorRules.value.length + 1, icon: ListDetails },
])
const activeManualSection = computed(() => manualSections.value.find(item => item.key === manualSection.value) || manualSections.value[0])
function matchesManualSearch(...values: Array<string | undefined>) { const keyword = manualSearch.value.trim().toLowerCase(); return !keyword || values.some(value => value?.toLowerCase().includes(keyword)) }
const filteredMembers = computed(() => configScope.members.filter(item => matchesManualSearch(
  item.name,
  item.username,
  item.identityCardNo,
  item.title,
  item.role.join(' '),
  ...item.positions.map(position => position.certificateNo),
)))
const personnelDetailMember = computed(() => (
  configScope.members.find(item => item.id === personnelDetailMemberId.value) || null
))
const manualEditorTitle = computed(() => {
  if (manualEditor.section !== 'members') {
    return manualEditor.mode === 'create'
      ? `新建${activeManualSection.value.label}`
      : `查看 / 修改${activeManualSection.value.label}`
  }
  if (manualEditor.mode === 'edit') return '修改成员岗位'
  return manualEditor.itemId ? '为成员添加岗位' : '新建项目成员'
})
const formalDataEditorOpen = computed(() => ['wbs', 'quality', 'risks'].includes(manualEditor.section))
const manualEditorContextLabel = computed(() => {
  if (manualEditor.section === 'wbs') return manualEditor.mode === 'edit' ? editorWbsForm.code : '新建节点'
  if (manualEditor.section === 'quality') {
    const wbs = configScope.wbsItems.find(item => item.id === editorQualityForm.wbsId)
    return wbs?.code || '质量要求'
  }
  if (manualEditor.section === 'risks') return `第 ${String(editorRiskForm.serialNo || 0).padStart(2, '0')} 项`
  return ''
})
const manualEditorContextDescription = computed(() => {
  if (manualEditor.section === 'wbs') return editorWbsForm.name || '填写 WBS 结构、计划与执行信息'
  if (manualEditor.section === 'quality') return editorQualityForm.name || '维护工序对应的验收与控制要求'
  if (manualEditor.section === 'risks') return editorRiskForm.name || '维护风险关联、窗口与评价依据'
  return ''
})
const manualEditorWbsItem = computed(() => (
  manualEditor.section === 'wbs'
    ? configScope.wbsItems.find(item => item.id === manualEditor.itemId) || null
    : null
))
const editorWbsUnavailableParentIds = computed(() => {
  const ids = new Set<string>()
  if (!manualEditor.itemId) return ids
  ids.add(manualEditor.itemId)
  let changed = true
  while (changed) {
    changed = false
    for (const item of configScope.wbsItems) {
      if (item.parentId && ids.has(item.parentId) && !ids.has(item.id)) {
        ids.add(item.id)
        changed = true
      }
    }
  }
  return ids
})
const editorWbsParentOptions = computed(() => configScope.wbsItems.filter(item => !editorWbsUnavailableParentIds.value.has(item.id)))
const filteredEditorWbsParentOptions = computed(() => {
  const keyword = editorWbsForm.parentSearch.trim().toLowerCase()
  return editorWbsParentOptions.value.filter(item => item.id === editorWbsForm.parentId || !keyword || `${item.code} ${item.name}`.toLowerCase().includes(keyword))
})
const editorWbsPredecessorOptions = computed(() => configScope.wbsItems.filter(item => item.id !== manualEditor.itemId))
const selectedEditorWbsPredecessors = computed(() => {
  const selectedIds = new Set(editorWbsForm.predecessorIds)
  return configScope.wbsItems.filter(item => selectedIds.has(item.id))
})
const filteredEditorWbsPredecessorOptions = computed(() => {
  const keyword = editorWbsForm.predecessorSearch.trim().toLowerCase()
  return editorWbsPredecessorOptions.value.filter(item => !keyword || `${item.code} ${item.name}`.toLowerCase().includes(keyword))
})
function filterEditorWbsOptions(keyword: string, selectedId = '') {
  const normalized = keyword.trim().toLowerCase()
  return configScope.wbsItems.filter(item => item.id === selectedId || !normalized || `${item.code} ${item.name}`.toLowerCase().includes(normalized))
}
const filteredEditorQualityWbsOptions = computed(() => filterEditorWbsOptions(editorQualityForm.wbsSearch, editorQualityForm.wbsId))
const hasManualEditorWbsSource = computed(() => {
  const item = manualEditorWbsItem.value
  return Boolean(item && (item.mspUid || item.mspId || item.sourceCreator || item.sourceCreatedAt || item.sourceProjectPath))
})
const manualWbsTree = computed(() => {
  const items = [...configScope.wbsItems]
  const ids = new Set(items.map(item => item.id))
  const children = new Map<string, WbsItem[]>()
  const roots: WbsItem[] = []
  const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
  const compare = (left: WbsItem, right: WbsItem) => (
    (left.sortOrder || 0) - (right.sortOrder || 0) || collator.compare(left.code, right.code)
  )
  for (const item of items) {
    if (item.parentId && ids.has(item.parentId)) {
      children.set(item.parentId, [...(children.get(item.parentId) || []), item])
    } else roots.push(item)
  }
  roots.sort(compare)
  for (const rows of children.values()) rows.sort(compare)

  const result: ManualWbsTreeRow[] = []
  const visited = new Set<string>()
  const walk = (item: WbsItem, depth: number) => {
    if (visited.has(item.id)) return
    visited.add(item.id)
    const descendants = children.get(item.id) || []
    result.push({ item, depth, hasChildren: descendants.length > 0 })
    descendants.forEach(child => walk(child, depth + 1))
  }
  roots.forEach(item => walk(item, 0))
  items.filter(item => !visited.has(item.id)).sort(compare).forEach(item => walk(item, 0))
  return { rows: result, children }
})
const visibleManualWbsRows = computed(() => {
  const keyword = manualSearch.value.trim().toLowerCase()
  const rows = manualWbsTree.value.rows
  if (keyword) {
    const byId = new Map(configScope.wbsItems.map(item => [item.id, item]))
    const visibleIds = new Set<string>()
    for (const row of rows) {
      const item = row.item
      if (!matchesManualSearch(item.code, item.name, item.itemType, item.assignedToText, item.statusText, item.priorityText, item.description)) continue
      let cursor: WbsItem | undefined = item
      while (cursor && !visibleIds.has(cursor.id)) {
        visibleIds.add(cursor.id)
        cursor = cursor.parentId ? byId.get(cursor.parentId) : undefined
      }
    }
    return rows.filter(row => visibleIds.has(row.item.id))
  }
  const hiddenParents = new Set<string>()
  return rows.filter(row => {
    const parentHidden = row.item.parentId ? hiddenParents.has(row.item.parentId) : false
    if (parentHidden || (row.item.parentId && collapsedManualWbsIds.value.has(row.item.parentId))) {
      hiddenParents.add(row.item.id)
      return false
    }
    return true
  })
})
const filteredQualityMetrics = computed(() => configScope.qualityMetrics.filter(item => matchesManualSearch(
  item.wbsCode,
  item.wbsName,
  item.acceptanceItem,
  item.controlIndicator,
  item.inspectionFrequency,
  item.relatedDocuments,
)))
const filteredRisks = computed(() => configScope.riskSources.filter(item => matchesManualSearch(
  item.riskPart,
  item.relatedProcessName,
  item.levelText,
  item.evaluationCondition,
  item.summary,
)))
const filteredMappings = computed(() => configScope.platformMappings.filter(item => matchesManualSearch(item.platformName, item.targetField, item.sourceField, item.transformRule)))
const isPlatformAdmin = computed(() => sessionStorage.getItem('user_role') === 'admin')
const draftHasErrors = computed(() => materialAgentDraft.value?.validation_issues.some(item => item.level === 'error') ?? false)
const draftHasWarnings = computed(() => materialAgentDraft.value?.validation_issues.some(item => item.level === 'warning') ?? false)
const initializationDraftErrorCount = computed(() => (
  materialAgentDraft.value?.validation_issues.filter(item => item.level === 'error').length || 0
))
const initializationDraftWarningCount = computed(() => (
  (materialAgentDraft.value?.validation_issues.length || 0) - initializationDraftErrorCount.value
))
const initializationDraftIssueSummary = computed(() => {
  return [
    initializationDraftErrorCount.value ? `${initializationDraftErrorCount.value} 项必须修正` : '',
    initializationDraftWarningCount.value ? `${initializationDraftWarningCount.value} 项需要核对` : '',
  ].filter(Boolean).join('，')
})
const initializationDraftIssueGroups = computed<InitializationDraftIssueGroup[]>(() => {
  const groupMetadata: Record<InitializationDraftIssueGroupKey, Pick<InitializationDraftIssueGroup, 'label' | 'description'>> = {
    project: { label: '工程基本信息', description: '工程日期或基础资料需要补充、修正' },
    personnel: { label: '人员信息', description: '人员名单中存在重复或缺失内容' },
    wbs_content: { label: 'WBS 工序内容', description: '工序名称或基础内容需要核对' },
    wbs_timeline: { label: 'WBS 时间线', description: '工序日期、编码顺序或前置时间需要核对' },
    wbs_structure: { label: 'WBS 层级与关联', description: '工序的上级、层级或前置关系需要修正' },
    risks: { label: '风险源', description: '风险清单及其关联工序需要核对' },
    quality: { label: '质量指标', description: '质量指标及其关联工序需要核对' },
    other: { label: '其他内容', description: '还有未归类的内容需要核对' },
  }
  const order: InitializationDraftIssueGroupKey[] = [
    'project',
    'personnel',
    'wbs_content',
    'wbs_timeline',
    'wbs_structure',
    'risks',
    'quality',
    'other',
  ]
  const grouped = new Map<InitializationDraftIssueGroupKey, InitializationDraftIssuePresentation[]>()
  for (const issue of materialAgentDraft.value?.validation_issues || []) {
    const presentation = presentInitializationDraftIssue(issue)
    grouped.set(presentation.category, [...(grouped.get(presentation.category) || []), presentation])
  }
  return order
    .filter(key => grouped.has(key))
    .map(key => {
      const items = grouped.get(key) || []
      return {
        key,
        ...groupMetadata[key],
        level: (items.some(item => item.level === 'error') ? 'error' : 'warning') as 'error' | 'warning',
        items,
      }
    })
    .sort((left, right) => {
      if (left.level === right.level) return order.indexOf(left.key) - order.indexOf(right.key)
      return left.level === 'error' ? -1 : 1
    })
})

function initializationIssueWbsCode(path: string) {
  if (!path.startsWith('wbs.')) return ''
  const detailedPath = path.match(/^wbs\.(.+)\.(name|planned_start_at|planned_finish_at|parent_wbs_code|level|predecessor_wbs_codes)$/)
  return detailedPath?.[1] || path.slice(4)
}

function presentInitializationDraftIssue(issue: InitializationDraftIssue): InitializationDraftIssuePresentation {
  const { path, message, level } = issue
  const wbsCode = initializationIssueWbsCode(path)
  const reference = wbsCode ? `WBS ${wbsCode}` : undefined
  const common = { ...issue, description: message, reference }

  if (path.startsWith('project')) {
    if (message.includes('竣工日期')) {
      return {
        ...common,
        category: 'project',
        title: '合同日期先后顺序有误',
        description: '合同竣工日期早于合同开工日期，这组日期无法作为有效工期。',
        guidance: '请回到工程基本信息，按照合同原件重新核对开工日期和竣工日期。',
      }
    }
    return {
      ...common,
      category: 'project',
      title: '工程基本信息尚未补充完整',
      guidance: '请在上方工程基本信息中核对已识别内容；缺少的内容可继续通过对话或附件补充。',
    }
  }

  if (path === 'personnel') {
    const identityCard = message.match(/身份证号\s+(\S+)/)?.[1]
    const serialNo = message.match(/人员序号\s+(\S+)/)?.[1]
    if (identityCard) {
      if (message.includes('对应多个岗位')) {
        return {
          ...common,
          category: 'personnel',
          title: '同一人员在项目中承担多个岗位',
          description: message,
          guidance: '请核对这些岗位是否确由同一人兼任。确认无误后，所有岗位会关联同一个平台账号，不会重复创建用户。',
        }
      }
      return {
        ...common,
        category: 'personnel',
        title: '人员名单中存在重复身份证号',
        description: `身份证号 ${identityCard} 在人员名单中出现了多次。系统无法判断是重复录入，还是同一人员兼任多个岗位。`,
        guidance: '请在上方人员板块找到对应人员；重复录入请删除多余记录，兼任岗位请合并为一名人员后补充岗位说明。',
      }
    }
    if (serialNo) {
      return {
        ...common,
        category: 'personnel',
        title: `人员序号 ${serialNo} 重复`,
        description: `人员名单中有多条记录使用了序号 ${serialNo}，入库后将无法稳定区分这些人员。`,
        guidance: '请对照原始人员表，为每条人员记录设置不同的序号。',
      }
    }
    return {
      ...common,
      category: 'personnel',
      title: message.includes('未识别') ? '尚未识别到项目人员' : '人员信息需要修正',
      guidance: '请展开上方人员板块核对名单；如资料中缺少人员信息，请继续上传人员表或手动补充。',
    }
  }

  if (path === 'wbs' || path.startsWith('wbs.')) {
    if (path.endsWith('.name') || path === 'wbs') {
      const placeholder = message.match(/名称[“"](.+?)[”"]/)?.[1]
      return {
        ...common,
        category: 'wbs_content',
        title: placeholder && reference ? `${reference} 的工序名称需要确认` : (message.includes('未识别') ? '尚未识别到 WBS 工序' : 'WBS 工序内容需要修正'),
        description: placeholder ? `当前工序名称为“${placeholder}”，看起来是表格中的占位文字，不是实际工序名称。` : message,
        guidance: reference ? `请在上方 WBS 板块找到 ${reference}，对照原始进度计划填写真实工序名称。` : '请继续上传进度计划，或在 WBS 板块补充工序。',
      }
    }

    if (path.endsWith('.planned_start_at') || path.endsWith('.planned_finish_at')) {
      if (message.includes('编码顺序与开始时间顺序冲突')) {
        const relatedCodes = [...message.matchAll(/WBS\s+([0-9.]+)/g)].map(match => match[1])
        const comparedCode = relatedCodes[1]
        return {
          ...common,
          category: 'wbs_timeline',
          title: `${reference || '该工序'} 的开始时间顺序异常`,
          description: comparedCode
            ? `按照同级 WBS 编码顺序，${comparedCode} 应先于 ${wbsCode} 开始，但草稿中的计划开始日期正好相反。`
            : '该工序的 WBS 编码顺序与计划开始日期顺序不一致。',
          guidance: `请在上方 WBS 板块对照原始进度计划，核对 ${reference || '该工序'} 的计划开始日期；系统不会自行猜测或调整日期。`,
        }
      }
      if (message.includes('早于前任')) {
        const predecessorCode = message.match(/前任\s+([0-9.]+)/)?.[1]
        return {
          ...common,
          category: 'wbs_timeline',
          title: `${reference || '该工序'} 与前置工序的时间有重叠`,
          description: predecessorCode
            ? `该工序在前置 WBS ${predecessorCode} 计划完成之前已经开始。可能是交叉施工，也可能是日期填写错误。`
            : '该工序在前置工序计划完成之前已经开始。',
          guidance: '请对照原始进度计划确认是否属于搭接施工；若不是，请修正工序日期或前置关系。',
        }
      }
      if (message.includes('早于父级')) {
        return {
          ...common,
          category: 'wbs_timeline',
          title: `${reference || '子工序'} 早于上级工序开始`,
          description: '子工序的计划开始日期早于上级工序的汇总开始日期，父子工序的时间范围不一致。',
          guidance: '请对照原始进度计划，核对该子工序或上级工序的计划开始日期。',
        }
      }
      if (message.includes('晚于父级')) {
        return {
          ...common,
          category: 'wbs_timeline',
          title: `${reference || '子工序'} 晚于上级工序完成`,
          description: '子工序的计划完成日期晚于上级工序的汇总完成日期，父子工序的时间范围不一致。',
          guidance: '请对照原始进度计划，核对该子工序或上级工序的计划完成日期。',
        }
      }
      if (message.includes('结束时间不能早于')) {
        return {
          ...common,
          category: 'wbs_timeline',
          title: `${reference || '该工序'} 的开始和完成日期有误`,
          description: '该工序的计划完成日期早于计划开始日期，无法形成有效工期。',
          guidance: '请对照原始进度计划，重新核对该工序的计划开始日期和计划完成日期。',
        }
      }
      return {
        ...common,
        category: 'wbs_timeline',
        title: `${reference || '该工序'} 的计划日期需要核对`,
        guidance: '请在上方 WBS 板块对照原始进度计划核对日期，系统不会自动改动。',
      }
    }

    let title = `${reference || 'WBS 工序'} 的层级或关联关系有误`
    let guidance = `请在上方 WBS 板块找到 ${reference || '对应工序'}，核对其编码、上级和前置工序。`
    if (message.includes('编码') && message.includes('重复')) title = `${reference || 'WBS 编码'} 重复`
    else if (message.includes('父级') || message.includes('上级')) title = `${reference || '该工序'} 的上级关系有误`
    else if (message.includes('层级')) title = `${reference || '该工序'} 的层级有误`
    else if (message.includes('前任') || message.includes('前置')) title = `${reference || '该工序'} 的前置关系有误`
    else if (message.includes('循环')) {
      title = `${reference || 'WBS 工序'} 形成了循环关系`
      guidance = '请检查该工序的上级或前置工序，移除相互指向的循环关系。'
    }
    return { ...common, category: 'wbs_structure', title, guidance }
  }

  if (path === 'risks' || path.startsWith('risks.')) {
    const serialNo = path.match(/^risks\.([^.]+)/)?.[1]
    const riskReference = serialNo ? `风险源第 ${serialNo} 项` : undefined
    return {
      ...common,
      category: 'risks',
      reference: riskReference,
      title: message.includes('未识别') ? '尚未识别到风险清单' : `${riskReference || '风险源信息'}需要修正`,
      guidance: '请在上方风险源板块找到对应记录，对照原始风险清单核对相关工序、风险等级和风险窗口。',
    }
  }

  if (path === 'quality_requirements' || path.startsWith('quality_requirements.')) {
    const qualityWbsCode = path.startsWith('quality_requirements.') ? path.slice('quality_requirements.'.length) : ''
    return {
      ...common,
      category: 'quality',
      reference: qualityWbsCode ? `WBS ${qualityWbsCode}` : undefined,
      title: message.includes('未识别') ? '尚未识别到工序质量指标' : '质量指标的关联工序需要修正',
      guidance: '请在上方质量指标板块找到对应记录，核对其 WBS 编码；同一工序存在重复指标时，请合并或删除多余记录。',
    }
  }

  return {
    ...common,
    category: 'other',
    title: level === 'error' ? '这项内容必须修正' : '这项内容需要核对',
    guidance: '请对照原始附件核对该内容；如无法确认，可继续询问初始化助手。',
  }
}

const initializationWbsTree = computed(() => {
  const items = materialAgentDraft.value?.payload.wbs || []
  const itemByCode = new Map(items.map(item => [item.wbs_code, item]))
  const childrenByParent = new Map<string, InitializationDraftWbs[]>()
  const roots: InitializationDraftWbs[] = []
  const compareWbsCode = (left: InitializationDraftWbs, right: InitializationDraftWbs) => (
    left.wbs_code.localeCompare(right.wbs_code, 'zh-CN', {
      numeric: true,
      sensitivity: 'base',
    })
  )

  for (const item of items) {
    const parentCode = item.parent_wbs_code || ''
    if (parentCode && itemByCode.has(parentCode)) {
      const siblings = childrenByParent.get(parentCode) || []
      siblings.push(item)
      childrenByParent.set(parentCode, siblings)
    } else {
      roots.push(item)
    }
  }
  roots.sort(compareWbsCode)
  for (const siblings of childrenByParent.values()) siblings.sort(compareWbsCode)

  const dependencyWarningsByCode = new Map<string, string[]>()
  for (const item of items) {
    const itemStart = item.planned_start_at ? Date.parse(item.planned_start_at) : Number.NaN
    const warnings = (item.predecessor_wbs_codes || []).flatMap((predecessorCode) => {
      const predecessor = itemByCode.get(predecessorCode)
      const predecessorFinish = predecessor?.planned_finish_at
        ? Date.parse(predecessor.planned_finish_at)
        : Number.NaN
      if (
        Number.isFinite(itemStart)
        && Number.isFinite(predecessorFinish)
        && itemStart < predecessorFinish
      ) {
        return [`计划开始早于前置 WBS ${predecessorCode} 的计划完成`]
      }
      return []
    })
    dependencyWarningsByCode.set(item.wbs_code, warnings)
  }

  const sequenceWarningsByCode = new Map<string, string[]>()
  const siblingGroups = [roots, ...childrenByParent.values()]
  for (const siblings of siblingGroups) {
    let latestStartedItem: InitializationDraftWbs | null = null
    for (const item of siblings) {
      const itemStart = item.planned_start_at
        ? Date.parse(item.planned_start_at)
        : Number.NaN
      if (!Number.isFinite(itemStart)) continue
      const latestStart = latestStartedItem?.planned_start_at
        ? Date.parse(latestStartedItem.planned_start_at)
        : Number.NaN
      if (
        latestStartedItem
        && Number.isFinite(latestStart)
        && itemStart < latestStart
      ) {
        sequenceWarningsByCode.set(item.wbs_code, [
          `计划开始早于编码在前的同级 WBS ${latestStartedItem.wbs_code}`,
        ])
      }
      if (!latestStartedItem || !Number.isFinite(latestStart) || itemStart >= latestStart) {
        latestStartedItem = item
      }
    }
  }

  const rows: InitializationWbsTreeRow[] = []
  const visited = new Set<string>()
  const append = (
    item: InitializationDraftWbs,
    depth: number,
    ancestorCodes: string[],
  ) => {
    if (visited.has(item.wbs_code)) return
    visited.add(item.wbs_code)
    const children = childrenByParent.get(item.wbs_code) || []
    rows.push({
      item,
      depth,
      ancestorCodes,
      hasChildren: children.length > 0,
      sequenceWarnings: sequenceWarningsByCode.get(item.wbs_code) || [],
      dependencyWarnings: dependencyWarningsByCode.get(item.wbs_code) || [],
    })
    for (const child of children) {
      append(child, depth + 1, [...ancestorCodes, item.wbs_code])
    }
  }
  for (const root of roots) append(root, 0, [])
  for (const item of items) {
    if (!visited.has(item.wbs_code)) append(item, 0, [])
  }

  return {
    rows,
    groupCodes: [...childrenByParent.keys()],
    sequenceWarningCount: [...sequenceWarningsByCode.values()].filter(warnings => warnings.length).length,
    dependencyWarningCount: [...dependencyWarningsByCode.values()].filter(warnings => warnings.length).length,
  }
})
const visibleInitializationWbsRows = computed(() => {
  const collapsedCodes = collapsedInitializationWbsCodes.value
  return initializationWbsTree.value.rows.filter(
    row => !row.ancestorCodes.some(code => collapsedCodes.has(code)),
  )
})
const initializationWbsDependencyWarningCount = computed(
  () => initializationWbsTree.value.dependencyWarningCount,
)
const initializationWbsSequenceWarningCount = computed(
  () => initializationWbsTree.value.sequenceWarningCount,
)
const projectFieldLabels: Record<string, string> = {
  engineering_type_description: '工程类型说明',
  contract_start_date: '合同开工',
  contract_end_date: '合同竣工',
  contract_duration_days: '合同工期',
  contract_amount_wan_yuan: '合同金额',
  construction_unit_name: '建设单位',
  general_contractor_unit_name: '总承包单位',
  supervision_unit_name: '监理单位',
  design_unit_name: '设计单位',
  survey_unit_name: '勘察单位',
}
const draftProjectFields = computed(() => Object.entries(materialAgentDraft.value?.payload.project || {})
  .filter(([, value]) => value !== null && value !== '')
  .map(([key, value]) => ({
    key,
    label: projectFieldLabels[key] || key,
    value: key === 'contract_duration_days'
      ? `${value} 天`
      : key === 'contract_amount_wan_yuan'
        ? `${value} 万元`
        : String(value),
  })))
const draftProjectDescription = computed(() => (
  draftProjectFields.value.find(item => item.key === 'engineering_type_description')
))
const draftProjectContractFields = computed(() => {
  const keys = new Set([
    'contract_start_date',
    'contract_end_date',
    'contract_duration_days',
    'contract_amount_wan_yuan',
  ])
  return draftProjectFields.value.filter(item => keys.has(item.key))
})
const draftProjectUnitFields = computed(() => {
  const keys = new Set([
    'construction_unit_name',
    'general_contractor_unit_name',
    'supervision_unit_name',
    'design_unit_name',
    'survey_unit_name',
  ])
  return draftProjectFields.value.filter(item => keys.has(item.key))
})
const initializationPersonnelReviewRows = computed(() => {
  const credentialByIdentityCard = new Map(
    initializationCredentialForms.value.map(item => [item.identity_card_no, item]),
  )
  const existingAccountByIdentityCard = new Map(
    (materialAgentDraft.value?.existing_personnel_accounts || []).map(item => [item.identity_card_no, item]),
  )
  const seenNewIdentityCards = new Set<string>()
  return (materialAgentDraft.value?.payload.personnel || []).map(item => {
    const account = existingAccountByIdentityCard.get(item.identity_card_no) || null
    const generatedCredential = credentialByIdentityCard.get(item.identity_card_no) || null
    const isRepeatedNewPerson = !account && Boolean(generatedCredential) && seenNewIdentityCards.has(item.identity_card_no)
    if (generatedCredential) seenNewIdentityCards.add(item.identity_card_no)
    return {
      ...item,
      existingAccount: account,
      credential: isRepeatedNewPerson ? null : generatedCredential,
      sharedCredential: isRepeatedNewPerson ? generatedCredential : null,
    }
  })
})
const canApplyInitializationDraft = computed(() => {
  const draft = materialAgentDraft.value
  if (
    !draft
    || !isPlatformAdmin.value
    || draft.status !== 'ready'
    || initializationDraftApplying.value
    || draftHasErrors.value
    || (draftHasWarnings.value && !initializationDraftAllowPartial.value)
  ) return false
  const usernames = initializationCredentialForms.value.map(item => item.username.trim())
  if (new Set(usernames).size !== usernames.length) return false
  return initializationCredentialForms.value.every(item => (
    item.username.trim().length > 0 && item.initial_password.length >= 8
  ))
})

function selectManualSection(section: ManualSection) {
  manualSection.value = section
  manualSearch.value = ''
}

function maskedIdentityCard(value: string) {
  if (!value) return '未登记身份证号'
  if (value.length <= 8) return `${value.slice(0, 2)}****`
  return `${value.slice(0, 3)} **** **** ${value.slice(-4)}`
}

function openPersonnelDetail(member: Member, position?: MemberPosition) {
  personnelDetailMemberId.value = member.id
  personnelDetailPositionId.value = position?.id || member.positions[0]?.id || ''
}

function closePersonnelDetail() {
  personnelDetailMemberId.value = ''
  personnelDetailPositionId.value = ''
}

function editPersonnelDetailPosition(member: Member, position: MemberPosition) {
  closePersonnelDetail()
  openMemberPositionEditor(member, position)
}

function addPersonnelDetailPosition(member: Member) {
  closePersonnelDetail()
  openMemberPositionEditor(member)
}

function isManualWbsCollapsed(itemId: string) {
  return !manualSearch.value && collapsedManualWbsIds.value.has(itemId)
}

function toggleManualWbs(itemId: string) {
  const next = new Set(collapsedManualWbsIds.value)
  if (next.has(itemId)) next.delete(itemId)
  else next.add(itemId)
  collapsedManualWbsIds.value = next
}

function expandAllManualWbs() {
  collapsedManualWbsIds.value = new Set()
}

function collapseAllManualWbs() {
  collapsedManualWbsIds.value = new Set(
    manualWbsTree.value.rows.filter(row => row.hasChildren).map(row => row.item.id),
  )
}

function formatFormalDate(value?: string) {
  if (!value) return ''
  return value.slice(0, 10)
}

function formatSourceDateTime(value?: string) {
  if (!value) return ''
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

function formatWbsDuration(value?: number) {
  if (value == null || Number.isNaN(value)) return '未计算工期'
  return `${Number.isInteger(value) ? value : value.toFixed(1)} 小时`
}

function formatProgress(value: number) {
  return Number.isInteger(value) ? value : value.toFixed(1)
}

function formatRiskWindow(item: RiskSource) {
  const start = formatFormalDate(item.controlStart)
  const end = formatFormalDate(item.controlEnd)
  if (start && end) return `${start} 至 ${end}`
  return start || end || '未设置风险窗口'
}

function resetManualEditorForms() {
  Object.assign(editorMemberForm, {
    name: '',
    username: '',
    identityCardNo: '',
    password: '',
    positionName: '',
    certificateNo: '',
    responsibilityDescription: '',
  })
  Object.assign(editorWbsForm, {
    code: '', name: '', parentId: '', parentSearch: '', level: 1, sortOrder: 0, colorValue: '', assignedToText: '', itemType: '',
    plannedStart: '', plannedFinish: '', deadline: '', progress: 0, statusText: '', priorityText: '',
    durationHours: '', estimatedHours: '', timeLogMinutes: '', budget: '', actualCost: '', predecessorIds: [], predecessorSearch: '', description: '',
  })
  Object.assign(editorQualityForm, { wbsId: '', wbsSearch: '', name: '', requirement: '', frequency: '', relatedDocuments: '' })
  Object.assign(editorRiskForm, {
    serialNo: 1, name: '', levelText: '一般', type: '', plannedStart: '', plannedFinish: '', evaluationCondition: '', summary: '',
  })
  Object.assign(editorMappingForm, { platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', transformRule: '', required: false, enabled: true })
}

function openManualEditor(section: ManualSection, item?: Member | WbsItem | QualityMetric | RiskSource | PlatformFieldMapping) {
  if (section === 'members') {
    openMemberPositionEditor(item as Member | undefined)
    return
  }
  manualSection.value = section
  resetManualEditorForms()
  manualEditor.open = true
  manualEditor.mode = item ? 'edit' : 'create'
  manualEditor.section = section
  manualEditor.itemId = item?.id || ''
  manualEditor.assignmentId = ''

  if (!item) {
    if (section === 'wbs') {
      editorWbsForm.sortOrder = Math.max(0, ...configScope.wbsItems.map(wbs => wbs.sortOrder || 0)) + 1
    } else if (section === 'risks') {
      editorRiskForm.serialNo = Math.max(0, ...configScope.riskSources.map(risk => risk.serialNo || 0)) + 1
    }
    return
  }
  if (section === 'wbs') {
    const wbs = item as WbsItem
    Object.assign(editorWbsForm, {
      code: wbs.code,
      name: wbs.name,
      parentId: wbs.parentId || '',
      parentSearch: '',
      level: wbs.level,
      sortOrder: wbs.sortOrder ?? 0,
      colorValue: wbs.colorValue || '',
      assignedToText: wbs.assignedToText || '',
      itemType: wbs.itemType || '',
      plannedStart: formatFormalDate(wbs.planStart),
      plannedFinish: formatFormalDate(wbs.planEnd),
      deadline: formatFormalDate(wbs.deadline),
      progress: wbs.progress,
      statusText: wbs.statusText || '',
      priorityText: wbs.priorityText || '',
      durationHours: wbs.durationHours ?? '',
      estimatedHours: wbs.estimatedHours ?? '',
      timeLogMinutes: wbs.timeLogMinutes ?? '',
      budget: wbs.budget ?? '',
      actualCost: wbs.actualCost ?? '',
      predecessorIds: [...(wbs.predecessorIds || [])],
      description: wbs.description || '',
    })
  } else if (section === 'quality') {
    const quality = item as QualityMetric
    Object.assign(editorQualityForm, {
      wbsId: quality.wbsId || '',
      wbsSearch: '',
      name: quality.acceptanceItem || quality.name,
      requirement: quality.controlIndicator || quality.requirement,
      frequency: quality.inspectionFrequency || '',
      relatedDocuments: quality.relatedDocuments || '',
    })
  } else if (section === 'risks') {
    const risk = item as RiskSource
    Object.assign(editorRiskForm, {
      serialNo: risk.serialNo || 1,
      name: risk.riskPart || risk.name,
      levelText: risk.levelText || formalRiskLevelLabel(risk).replace(/风险$/, ''),
      type: risk.relatedProcessName || risk.type || '',
      plannedStart: formatFormalDate(risk.controlStart),
      plannedFinish: formatFormalDate(risk.controlEnd),
      evaluationCondition: risk.evaluationCondition || risk.controlMeasures || '',
      summary: risk.summary || '',
    })
  } else if (section === 'mappings') {
    const mapping = item as PlatformFieldMapping
    Object.assign(editorMappingForm, { platformName: mapping.platformName, sourceField: mapping.sourceField, targetField: mapping.targetField, transformRule: mapping.transformRule || '', required: mapping.required, enabled: mapping.enabled })
  }
}

function openMemberPositionEditor(member?: Member, position?: MemberPosition) {
  manualSection.value = 'members'
  resetManualEditorForms()
  manualEditor.open = true
  manualEditor.mode = position ? 'edit' : 'create'
  manualEditor.section = 'members'
  manualEditor.itemId = member?.id || ''
  manualEditor.assignmentId = position?.id || ''
  Object.assign(editorMemberForm, {
    name: member?.name || '',
    username: member?.username || '',
    identityCardNo: member?.identityCardNo || '',
    password: member ? '' : generateInitializationPassword(),
    positionName: position?.name || '',
    certificateNo: position?.certificateNo || '',
    responsibilityDescription: position?.responsibilityDescription || '',
  })
}

function closeManualEditor() {
  if (!submitting.value) manualEditor.open = false
}

function optionalEditorNumber(value: number | '') {
  return value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
}

function syncEditorWbsLevelWithParent() {
  const parent = configScope.wbsItems.find(item => item.id === editorWbsForm.parentId)
  editorWbsForm.level = parent ? parent.level + 1 : 1
}

function removeEditorWbsPredecessor(itemId: string) {
  editorWbsForm.predecessorIds = editorWbsForm.predecessorIds.filter(id => id !== itemId)
}

function wbsStatusLabel(status: WbsItem['status']) {
  return ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' } as Record<WbsItem['status'], string>)[status]
}

function displayWbsStatusText(value?: string | null, fallback = '') {
  const raw = value?.trim() || ''
  const normalized = raw.toLowerCase().replace(/[\s-]+/g, '_')
  const translated: Record<string, string> = {
    not_started: '未开始',
    pending: '待处理',
    open: '打开',
    active: '活动',
    in_progress: '进行中',
    completed: '已完成',
    complete: '已完成',
    done: '已完成',
    delayed: '已延期',
    overdue: '已逾期',
  }
  return translated[normalized] || raw || fallback
}

function formalWbsStatusLabel(item: WbsItem) {
  return displayWbsStatusText(item.statusText)
}

function displayWbsPriorityText(value?: string | null, fallback = '未设置优先级') {
  if (!value?.trim()) return fallback
  const raw = value.trim()
  const translated: Record<string, string> = {
    critical: '紧急优先级',
    urgent: '紧急优先级',
    high: '高优先级',
    medium: '中优先级',
    normal: '普通优先级',
    low: '低优先级',
  }
  return translated[raw.toLowerCase()] || (raw.includes('优先级') ? raw : `${raw}优先级`)
}

function formalWbsPriorityLabel(value?: string) {
  return displayWbsPriorityText(value, '')
}

function displayWbsItemType(value: string | null | undefined) {
  const raw = value?.trim() || ''
  const normalized = raw.toLowerCase().replace(/[\s_-]+/g, '')
  const translated: Record<string, string> = {
    project: '项目',
    summary: '汇总任务',
    summarytask: '汇总任务',
    taskgroup: '任务组',
    group: '任务组',
    task: '任务',
    milestone: '里程碑',
  }
  return translated[normalized] || raw
}

function formalWbsItemType(item: WbsItem) {
  return displayWbsItemType(item.itemType)
}

function formalRiskLevelLabel(item: RiskSource) {
  const raw = item.levelText?.trim() || ''
  const translated: Record<string, string> = {
    critical: '重大风险',
    high: '高风险',
    medium: '中风险',
    low: '低风险',
  }
  return translated[raw.toLowerCase()] || raw || riskLabel(item.level)
}

function submitManualEditor() {
  const isEditing = manualEditor.mode === 'edit'
  const success = isEditing ? '项目配置已更新' : '项目配置已创建'
  void run(async () => {
    if (manualEditor.section === 'members') {
      const payload = {
        name: editorMemberForm.name,
        username: editorMemberForm.username || undefined,
        identityCardNo: editorMemberForm.identityCardNo,
        password: editorMemberForm.password || undefined,
        positionName: editorMemberForm.positionName,
        certificateNo: editorMemberForm.certificateNo,
        responsibilityDescription: editorMemberForm.responsibilityDescription,
      }
      if (isEditing) {
        await store.updateMemberPosition(
          manualEditor.assignmentId,
          payload,
          configProjectId.value,
        )
      }
      else await store.saveMember(payload, configProjectId.value)
    } else if (manualEditor.section === 'wbs') {
      const payload = {
        code: editorWbsForm.code,
        name: editorWbsForm.name,
        parent_id: editorWbsForm.parentId || null,
        level: Number(editorWbsForm.level) || 1,
        sort_order: Math.max(0, Number(editorWbsForm.sortOrder) || 0),
        color_value: editorWbsForm.colorValue || null,
        assigned_to_text: editorWbsForm.assignedToText || null,
        item_type: editorWbsForm.itemType || null,
        planned_start: editorWbsForm.plannedStart || null,
        planned_finish: editorWbsForm.plannedFinish || null,
        deadline: editorWbsForm.deadline || null,
        progress: Math.min(100, Math.max(0, Number(editorWbsForm.progress) || 0)),
        status: editorWbsForm.statusText || null,
        priority_text: editorWbsForm.priorityText || null,
        duration_hours: optionalEditorNumber(editorWbsForm.durationHours),
        estimated_hours: optionalEditorNumber(editorWbsForm.estimatedHours),
        time_log_minutes: optionalEditorNumber(editorWbsForm.timeLogMinutes),
        budget: optionalEditorNumber(editorWbsForm.budget),
        actual_cost: optionalEditorNumber(editorWbsForm.actualCost),
        predecessor_ids: [...editorWbsForm.predecessorIds],
        description: editorWbsForm.description || null,
      }
      if (isEditing) await store.updateWbs(manualEditor.itemId, payload, configProjectId.value)
      else await store.createWbs(payload, configProjectId.value)
    } else if (manualEditor.section === 'quality') {
      const payload = {
        wbs_item_id: editorQualityForm.wbsId,
        name: editorQualityForm.name,
        requirement: editorQualityForm.requirement,
        inspection_frequency: editorQualityForm.frequency || null,
        related_documents: editorQualityForm.relatedDocuments || null,
      }
      if (isEditing) await store.updateQualityMetric(manualEditor.itemId, payload, configProjectId.value)
      else await store.createQualityMetric(payload, configProjectId.value)
    } else if (manualEditor.section === 'risks') {
      const payload = {
        serial_no: Number(editorRiskForm.serialNo) || 1,
        name: editorRiskForm.name,
        level: editorRiskForm.levelText,
        risk_type: editorRiskForm.type,
        planned_start: editorRiskForm.plannedStart || null,
        planned_finish: editorRiskForm.plannedFinish || null,
        control_requirements: editorRiskForm.evaluationCondition || null,
        summary: editorRiskForm.summary || null,
      }
      if (isEditing) await store.updateRisk(manualEditor.itemId, payload, configProjectId.value)
      else await store.createRisk(payload, configProjectId.value)
    } else if (manualEditor.section === 'mappings') {
      const payload: Omit<PlatformFieldMapping, 'id' | 'projectId'> = { platformName: editorMappingForm.platformName, sourceField: editorMappingForm.sourceField, targetField: editorMappingForm.targetField, transformRule: editorMappingForm.transformRule, required: editorMappingForm.required, enabled: editorMappingForm.enabled }
      if (isEditing) await store.updatePlatformMapping(manualEditor.itemId, payload, configProjectId.value)
      else await store.createPlatformMapping(payload, configProjectId.value)
    } else {
      await store.saveProjectSettings({ ...monitorForm, reminderRules: monitorRules.value }, configProjectId.value)
    }
    manualEditor.open = false
  }, success)
}

let configLoadSequence = 0

async function loadConfigProjectScope(projectId = configProjectId.value) {
  if (!projectId) return
  const sequence = ++configLoadSequence
  configScopeLoading.value = true
  try {
    const scope = await store.fetchProjectConfigScope(projectId)
    if (sequence !== configLoadSequence || projectId !== configProjectId.value) return
    configScope.members = scope.members
    configScope.wbsItems = scope.wbsItems
    configScope.riskSources = scope.riskSources
    configScope.qualityMetrics = scope.qualityMetrics
    configScope.platformMappings = scope.platformMappings
    configScope.dirConfig = scope.dirConfig
    configScope.remindRules = scope.remindRules
    Object.assign(monitorForm, scope.dirConfig)
    monitorRules.value = scope.remindRules.map(rule => ({ ...rule }))
    const parentIds = new Set(scope.wbsItems.map(item => item.parentId).filter(Boolean))
    collapsedManualWbsIds.value = new Set(
      scope.wbsItems
        .filter(item => item.level > 1 && parentIds.has(item.id))
        .map(item => item.id),
    )
  } catch (error: any) {
    if (sequence === configLoadSequence) message.error(error.response?.data?.detail || '项目配置加载失败。')
  } finally {
    if (sequence === configLoadSequence) configScopeLoading.value = false
  }
}

function selectConfigProject(projectId: string) {
  if (projectId !== configProjectId.value) configProjectId.value = projectId
}

function selectWorkspaceTab(tab: WorkspaceTab) {
  activeWorkspaceTab.value = tab
  if (tab !== 'agent' || !configProjectId.value) return
  void loadMaterialAgentConversation(configProjectId.value)
  void loadInitializationDraft(configProjectId.value)
}

watch(() => [store.currentProjectId, store.projects.length] as const, () => {
  if (!configProjectId.value) configProjectId.value = store.currentProjectId || store.projects[0]?.id || ''
}, { immediate: true })

watch(configProjectId, projectId => {
  cancelMaterialAgentRequests()
  materialAgentReconcileSequence += 1
  materialAgentSending.value = false
  materialAgentConfirming.value = false
  materialAgentStopping.value = false
  activeWorkspaceTab.value = 'agent'
  materialAgentMessages.value = []
  materialAgentError.value = ''
  materialAgentConversationId.value = null
  materialAgentConversationStatus.value = ''
  materialAgentStreamingTrace.value = null
  materialAgentFollowOutput.value = true
  materialAgentPlanCollapsed.value = false
  materialAgentDraft.value = null
  initializationDraftCollapsed.value = false
  initializationDraftReviewOpen.value = false
  initializationCredentialForms.value = []
  clearMaterialAgentFiles()
  activeProjectConnectorKey.value = 'wecom'
  configScope.members = []
  configScope.wbsItems = []
  configScope.riskSources = []
  configScope.qualityMetrics = []
  configScope.platformMappings = []
  collapsedManualWbsIds.value = new Set()
  closePersonnelDetail()
  Object.assign(monitorForm, { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false })
  monitorRules.value = []
  loadProjectConnectorSettings()
  void loadConfigProjectScope(projectId)
  void loadMaterialAgentConversation(projectId)
  void loadInitializationDraft(projectId)
}, { immediate: true })

watch(
  () => (
    materialAgentExecutionPlan.value?.tasks
      .map(task => String(task.id))
      .join('|') || ''
  ),
  (signature, previousSignature) => {
    if (signature && signature !== previousSignature) {
      materialAgentPlanCollapsed.value = false
    }
  },
)

watch(() => store.projectSetupRefreshVersion, () => {
  if (!configProjectId.value) return
  activeWorkspaceTab.value = 'agent'
  void loadMaterialAgentConversation(configProjectId.value)
  void loadInitializationDraft(configProjectId.value)
})

function loadProjectConnectorSettings() {
  for (const connector of projectConnectors) {
    connector.connectionId = ''
    connector.secret = ''
    connector.configured = false
    connector.updatedAt = ''
  }
  try {
    const saved = JSON.parse(localStorage.getItem(projectConnectorStorageKey.value) || '{}') as Record<string, Partial<ProjectConnectorConfig>>
    for (const connector of projectConnectors) {
      const value = saved[connector.key]
      if (!value) continue
      connector.connectionId = value.connectionId || ''
      connector.configured = Boolean(value.configured)
      connector.updatedAt = value.updatedAt || ''
    }
  } catch {
    localStorage.removeItem(projectConnectorStorageKey.value)
  }
}

function saveProjectConnector() {
  const connector = activeProjectConnector.value
  if (!connector) return
  if (!connector.connectionId.trim()) {
    message.warning(`请填写${connector.connectionLabel}。`)
    return
  }
  connector.configured = true
  connector.updatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const saved = Object.fromEntries(projectConnectors.map(item => [item.key, {
    connectionId: item.connectionId,
    configured: item.configured,
    updatedAt: item.updatedAt,
  }]))
  localStorage.setItem(projectConnectorStorageKey.value, JSON.stringify(saved))
  connector.secret = ''
  message.success(`${connector.label}连接信息已保存；敏感凭据未写入浏览器。`)
}

function attachmentsFromMessage(item: ApiAgentMessage): InitializationAttachment[] {
  const raw = item.extra_data?.initialization_files
  if (!Array.isArray(raw)) return []
  return raw.flatMap((value) => {
    if (!value || typeof value !== 'object') return []
    const file = value as Record<string, unknown>
    const id = Number(file.id)
    const name = String(file.name || '')
    const size = Number(file.size) || 0
    return Number.isFinite(id) && name ? [{ id: String(id), name, size }] : []
  })
}

function mapMaterialAgentMessage(item: ApiAgentMessage): MaterialAgentMessage {
  const attachments = attachmentsFromMessage(item)
  return {
    id: String(item.id),
    role: item.role,
    content: item.content,
    attachments: attachments.length ? attachments : undefined,
    runtimeTrace: runtimeTraceFromExtraData(item.extra_data),
  }
}

const materialAgentBottomThreshold = 48

function isMaterialAgentViewportAtEnd(viewport: HTMLElement) {
  return (
    viewport.scrollHeight
    - viewport.scrollTop
    - viewport.clientHeight
    <= materialAgentBottomThreshold
  )
}

function handleMaterialAgentScroll() {
  const viewport = materialAgentViewport.value
  if (!viewport) return
  materialAgentFollowOutput.value = isMaterialAgentViewportAtEnd(viewport)
}

async function scrollMaterialAgentToEnd(
  behavior: ScrollBehavior = 'auto',
  force = false,
) {
  if (!force && !materialAgentFollowOutput.value) return
  await nextTick()
  if (!force && !materialAgentFollowOutput.value) return
  const viewport = materialAgentViewport.value
  if (!viewport) return
  viewport.scrollTo({
    top: viewport.scrollHeight,
    behavior,
  })
  materialAgentFollowOutput.value = true
}

async function loadMaterialAgentConversation(
  projectId = configProjectId.value,
): Promise<boolean> {
  if (!projectId) return false
  const sequence = ++materialConversationLoadSequence
  materialAgentConversationLoading.value = true
  materialAgentError.value = ''
  try {
    const response = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
      `/projects/${projectId}/agent-conversations`,
      { params: { conversation_type: 'initialization' } },
    )
    if (sequence !== materialConversationLoadSequence || projectId !== configProjectId.value) return false
    const conversation = [...response.data.data].sort((left, right) => left.id - right.id)[0]
    if (!conversation) {
      materialAgentConversationId.value = null
      materialAgentConversationStatus.value = ''
      materialAgentMessages.value = []
      materialAgentError.value = ''
      return true
    }
    materialAgentConversationId.value = conversation.id
    const messages = await api.get<ApiEnvelope<ApiAgentMessage[]>>(
      `/agent-conversations/${conversation.id}/messages`,
    )
    // The message endpoint reconciles a disconnected/finished AgentScope
    // turn. Read the conversation once more afterwards so the UI receives
    // the post-reconciliation status instead of its earlier SQLite snapshot.
    const refreshedConversations = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
      `/projects/${projectId}/agent-conversations`,
      { params: { conversation_type: 'initialization' } },
    )
    if (sequence !== materialConversationLoadSequence || projectId !== configProjectId.value) return false
    materialAgentMessages.value = messages.data.data.map(mapMaterialAgentMessage)
    materialAgentConversationStatus.value = (
      refreshedConversations.data.data.find(item => item.id === conversation.id)?.status
      || conversation.status
    )
    materialAgentError.value = ''
    void scrollMaterialAgentToEnd()
    return true
  } catch (error: any) {
    if (sequence === materialConversationLoadSequence) {
      materialAgentError.value = error.response?.data?.detail || '项目初始化会话加载失败。'
    }
    return false
  } finally {
    if (sequence === materialConversationLoadSequence) {
      materialAgentConversationLoading.value = false
    }
  }
}

async function loadInitializationDraft(projectId = configProjectId.value) {
  if (!projectId) return
  try {
    const response = await api.get<ApiEnvelope<ApiInitializationDraft | null>>(
      `/projects/${projectId}/initialization-drafts/latest`,
    )
    if (projectId !== configProjectId.value) return
    const nextDraft = response.data.data
    const previousDraft = materialAgentDraft.value
    if (
      nextDraft
      && (
        !previousDraft
        || nextDraft.id !== previousDraft.id
        || nextDraft.revision !== previousDraft.revision
      )
    ) {
      initializationDraftCollapsed.value = false
    }
    materialAgentDraft.value = nextDraft
  } catch (error: any) {
    if (projectId === configProjectId.value) {
      materialAgentError.value = error.response?.data?.detail || '初始化草稿加载失败。'
    }
  }
}

function initializationDraftStatusLabel(status: ApiInitializationDraft['status']) {
  return {
    collecting: '专项数据整理中',
    reviewing: '等待统一核验',
    invalid: '草稿需要修正',
    ready: '草稿可以核对',
    applied: '初始化已完成',
    rejected: '草稿已退回',
  }[status]
}

function initializationSectionLabels(sections: string[]) {
  const labels: Record<string, string> = {
    project: '工程信息',
    personnel: '人员与岗位',
    wbs: 'WBS 与进度',
    risks: '风险源',
    quality_requirements: '质量指标',
  }
  return sections.map(section => labels[section] || section).join('、')
}

function initializationDraftStageHint(draft: ApiInitializationDraft) {
  if (draft.status === 'applied') return '已写入项目'
  if (draft.status === 'collecting') return '专家处理中'
  if (draft.status === 'reviewing') return '等待核验专家'
  return '等待平台确认'
}

function initializationDraftCollapsedLabel(draft: ApiInitializationDraft) {
  if (draft.status === 'applied') return '初始化草稿已写入项目'
  if (draft.status === 'collecting') return '初始化草稿正在整理'
  if (draft.status === 'reviewing') return '初始化草稿等待核验'
  return '有待确认草稿'
}

function formatInitializationDate(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 10)
}

function formatInitializationProgress(value?: number | string | null) {
  if (value === null || value === undefined || value === '') return ''
  const progress = Number(value)
  return Number.isFinite(progress) ? `${progress}%` : String(value)
}

function isInitializationWbsCollapsed(code: string) {
  return collapsedInitializationWbsCodes.value.has(code)
}

function toggleInitializationWbsNode(code: string) {
  const next = new Set(collapsedInitializationWbsCodes.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  collapsedInitializationWbsCodes.value = next
}

function expandAllInitializationWbs() {
  collapsedInitializationWbsCodes.value = new Set()
}

function collapseAllInitializationWbs() {
  collapsedInitializationWbsCodes.value = new Set(initializationWbsTree.value.groupCodes)
}

function generateInitializationPassword(length = 12) {
  const targetLength = Math.min(12, Math.max(8, length))
  const characterGroups = [
    'ABCDEFGHJKLMNPQRSTUVWXYZ',
    'abcdefghijkmnopqrstuvwxyz',
    '23456789',
    '!@#$%&*',
  ]
  const randomIndex = (size: number) => {
    const value = new Uint32Array(1)
    window.crypto.getRandomValues(value)
    return value[0] % size
  }
  const password = characterGroups.map(group => group[randomIndex(group.length)])
  const allCharacters = characterGroups.join('')
  while (password.length < targetLength) {
    password.push(allCharacters[randomIndex(allCharacters.length)])
  }
  for (let index = password.length - 1; index > 0; index -= 1) {
    const swapIndex = randomIndex(index + 1)
    const currentCharacter = password[index]
    password[index] = password[swapIndex]
    password[swapIndex] = currentCharacter
  }
  return password.join('')
}

function openInitializationDraftReview() {
  const draft = materialAgentDraft.value
  if (!draft) return
  Object.assign(initializationReviewExpanded, {
    personnel: true,
    wbs: true,
    risks: true,
    quality: true,
  })
  for (const group of initializationDraftIssueGroups.value) {
    initializationIssueGroupsExpanded[group.key] = group.level === 'error' || group.items.length <= 3
  }
  collapsedInitializationWbsCodes.value = new Set()
  initializationDraftAllowPartial.value = false
  const currentCredentialByIdentityCard = new Map(
    initializationCredentialForms.value.map(item => [item.identity_card_no, item]),
  )
  initializationCredentialForms.value = draft.required_personnel_credentials.map(item => ({
    ...item,
    username: currentCredentialByIdentityCard.get(item.identity_card_no)?.username || item.suggested_username,
    initial_password: currentCredentialByIdentityCard.get(item.identity_card_no)?.initial_password || generateInitializationPassword(),
  }))
  initializationDraftReviewOpen.value = true
}

function closeInitializationDraftReview() {
  if (!initializationDraftApplying.value) initializationDraftReviewOpen.value = false
}

function initializationApplyError(error: any) {
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    return String(detail.message || '初始化草稿入库失败。')
  }
  return error.message || '初始化草稿入库失败。'
}

async function applyInitializationDraft() {
  const draft = materialAgentDraft.value
  if (!draft || !canApplyInitializationDraft.value) return
  initializationDraftApplying.value = true
  try {
    await api.post(
      `/projects/${configProjectId.value}/initialization-drafts/${draft.id}/apply`,
      {
        allow_partial: initializationDraftAllowPartial.value,
        personnel_credentials: initializationCredentialForms.value.map(item => ({
          identity_card_no: item.identity_card_no,
          username: item.username.trim(),
          initial_password: item.initial_password,
        })),
      },
      { timeout: 60_000 },
    )
    await Promise.all([
      loadInitializationDraft(),
      loadConfigProjectScope(),
    ])
    message.success('项目初始化数据已确认入库。')
  } catch (error: any) {
    message.error(initializationApplyError(error))
  } finally {
    initializationDraftApplying.value = false
  }
}

async function ensureMaterialAgentConversation(signal?: AbortSignal): Promise<number> {
  if (materialAgentConversationId.value) return materialAgentConversationId.value
  const response = await api.post<ApiEnvelope<ApiAgentConversation>>(
    `/projects/${configProjectId.value}/agent-conversations`,
    { conversation_type: 'initialization' },
    { signal },
  )
  materialAgentConversationId.value = response.data.data.id
  materialAgentConversationStatus.value = response.data.data.status
  return response.data.data.id
}

async function uploadMaterialAgentFiles(
  conversationId: number,
  files: File[],
  signal?: AbortSignal,
): Promise<ApiInitializationFile[]> {
  const uploaded: ApiInitializationFile[] = []
  for (const file of files) {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<ApiEnvelope<ApiInitializationFile>>(
      `/projects/${configProjectId.value}/agent-conversations/${conversationId}/initialization-files`,
      form,
      { timeout: 60_000, signal },
    )
    uploaded.push(response.data.data)
  }
  return uploaded
}

async function sendMaterialAgentMessage() {
  const requestedContent = materialAgentPrompt.value.trim()
  if (!configProjectId.value || materialAgentLoading.value || materialAgentStopping.value) return
  const selectedFiles = [...materialAgentFiles.value]
  if (!requestedContent && !selectedFiles.length) return
  const controller = new AbortController()
  materialAgentStreamAbortController = controller
  materialAgentSending.value = true
  materialAgentError.value = ''
  try {
    const conversationId = await ensureMaterialAgentConversation(controller.signal)
    const uploadedFiles = await uploadMaterialAgentFiles(
      conversationId,
      selectedFiles,
      controller.signal,
    )
    const content = requestedContent || '请读取并分析这些项目初始化附件，整理需要我核对的初始化信息。'
    const attachments = uploadedFiles.map(file => ({
      id: String(file.id),
      name: file.file_name,
      size: file.file_size,
    }))
    materialAgentMessages.value = [
      ...materialAgentMessages.value,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        attachments: attachments.length ? attachments : undefined,
      },
    ]
    materialAgentPrompt.value = ''
    clearMaterialAgentFiles()
    materialAgentStreamingTrace.value = createEmptyRuntimeTrace()
    await scrollMaterialAgentToEnd()
    const completion: { message: ApiAgentMessage | null } = { message: null }
    await streamAgentConversationMessage(
      conversationId,
      content,
      {
        onAccepted: payload => {
          materialAgentConversationStatus.value = payload.runtime_status
        },
        onEvents: async runtimeEvents => {
          materialAgentStreamingTrace.value = applyAgentRuntimeEvents(
            materialAgentStreamingTrace.value,
            runtimeEvents,
          )
          await scrollMaterialAgentToEnd()
        },
        onDone: payload => {
          completion.message = payload.message
          materialAgentConversationStatus.value = payload.runtime_status
        },
      },
      controller.signal,
      { initialization_file_ids: uploadedFiles.map(file => file.id) },
    )
    if (completion.message) {
      materialAgentMessages.value = [
        ...materialAgentMessages.value,
        mapMaterialAgentMessage(completion.message),
      ]
    }
    materialAgentStreamingTrace.value = null
    await loadInitializationDraft()
    await scrollMaterialAgentToEnd('smooth')
  } catch (error: any) {
    materialAgentStreamingTrace.value = null
    if (!isMaterialAgentCancellation(error)) {
      materialAgentError.value = error.response?.data?.detail || error.message || '项目初始化助手暂时无法处理这条请求。'
    }
  } finally {
    if (materialAgentStreamAbortController === controller) {
      materialAgentStreamAbortController = null
    }
    materialAgentSending.value = false
  }
}

function cloneMaterialAgentTrace(trace: AgentRuntimeTrace): AgentRuntimeTrace {
  return JSON.parse(JSON.stringify(trace)) as AgentRuntimeTrace
}

function traceHasPendingMaterialToolCall(
  trace: AgentRuntimeTrace | null | undefined,
  replyId: string,
  toolCallId: string,
) {
  if (!trace || !activeMaterialAgentStatuses.has(trace.status)) return false
  const messageCall = trace.messages.some(runtimeMessage =>
    runtimeMessage.id === replyId
    && !runtimeMessage.finished_at
    && runtimeMessage.content.some(block =>
      block.type === 'tool_call'
      && block.id === toolCallId
      && block.state === 'asking',
    ),
  )
  if (messageCall) return true
  return trace.subagentHitl.some(entry =>
    entry.reply_id === replyId
    && (entry.event.tool_calls || []).some(call =>
      call.id === toolCallId && call.state === 'asking',
    ),
  )
}

function hasPendingMaterialToolCall(replyId: string, toolCallId: string) {
  return materialAgentMessages.value.some(item =>
    traceHasPendingMaterialToolCall(item.runtimeTrace, replyId, toolCallId),
  )
}

function markMaterialAgentToolDecision(
  replyId: string,
  toolCallId: string,
  confirmed: boolean,
) {
  materialAgentMessages.value = materialAgentMessages.value.map((item) => {
    if (!item.runtimeTrace) return item
    const trace = cloneMaterialAgentTrace(item.runtimeTrace)
    let changed = false
    trace.subagentHitl = trace.subagentHitl.filter((entry) => {
      const matches = (
        entry.reply_id === replyId
        && (entry.event.tool_calls || []).some(call => call.id === toolCallId)
      )
      changed ||= matches
      return !matches
    })
    for (const runtimeMessage of trace.messages) {
      if (runtimeMessage.id !== replyId) continue
      const call = runtimeMessage.content.find(block =>
        block.type === 'tool_call' && block.id === toolCallId,
      )
      if (!call || call.type !== 'tool_call') continue
      call.state = confirmed ? 'allowed' : 'finished'
      changed = true
      if (
        !confirmed
        && !runtimeMessage.content.some(block =>
          block.type === 'tool_result' && block.id === toolCallId,
        )
      ) {
        runtimeMessage.content.push({
          type: 'tool_result',
          id: toolCallId,
          name: call.name,
          output: '已由用户拒绝。',
          state: 'denied',
        })
      }
    }
    if (!changed) return item
    trace.status = 'running'
    return { ...item, runtimeTrace: trace }
  })
}

function markActiveMaterialAgentMessagesInterrupted() {
  const interruptedAt = new Date().toISOString()
  materialAgentMessages.value = materialAgentMessages.value.map((item) => {
    if (
      !item.runtimeTrace
      || !activeMaterialAgentStatuses.has(item.runtimeTrace.status)
    ) return item
    const trace = cloneMaterialAgentTrace(item.runtimeTrace)
    trace.status = 'interrupted'
    trace.subagentHitl = []
    for (const runtimeMessage of trace.messages) {
      if (runtimeMessage.finished_at) continue
      runtimeMessage.finished_at = interruptedAt
      runtimeMessage.finished_reason = 'interrupted'
      const activeCalls = runtimeMessage.content.filter(block =>
        block.type === 'tool_call'
        && ['pending', 'asking', 'allowed', 'submitted'].includes(block.state),
      )
      for (const call of activeCalls) {
        if (call.type !== 'tool_call') continue
        call.state = 'finished'
        if (!runtimeMessage.content.some(block =>
          block.type === 'tool_result' && block.id === call.id,
        )) {
          runtimeMessage.content.push({
            type: 'tool_result',
            id: call.id,
            name: call.name,
            output: '任务已由用户停止。',
            state: 'interrupted',
          })
        }
      }
    }
    return { ...item, runtimeTrace: trace }
  })
}

async function stopMaterialAgentMessage() {
  const conversationId = materialAgentConversationId.value
  if (materialAgentStopping.value) return
  materialAgentStopping.value = true
  let reconciling = false
  try {
    if (!conversationId) {
      cancelMaterialAgentRequests()
      return
    }
    const refreshed = await loadMaterialAgentConversation()
    if (
      refreshed
      && !activeMaterialAgentStatuses.has(materialAgentConversationStatus.value)
    ) {
      cancelMaterialAgentRequests()
      materialAgentStreamingTrace.value = null
      message.info('该任务已经结束，页面已同步最新结果。')
      return
    }
    await api.post(
      `/agent-conversations/${conversationId}/interrupt`,
      undefined,
      { timeout: 30_000 },
    )
    materialAgentConversationStatus.value = 'interrupting'
    markActiveMaterialAgentMessagesInterrupted()
    cancelMaterialAgentRequests()
    message.info('停止请求已接收，正在同步中断前已生成的内容。')
    if (configProjectId.value) {
      reconciling = true
      void reconcileMaterialAgentAfterStop(
        configProjectId.value,
        conversationId,
      )
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '停止初始化助手失败。')
    await loadMaterialAgentConversation()
  } finally {
    if (!reconciling) materialAgentStopping.value = false
  }
}

async function confirmMaterialAgentToolCall(
  replyId: string,
  toolCall: AgentToolCallBlock,
  confirmed: boolean,
) {
  const conversationId = materialAgentConversationId.value
  if (
    !conversationId
    || materialAgentConfirming.value
    || materialAgentStopping.value
  ) return
  materialAgentConfirming.value = true
  materialAgentError.value = ''
  let controller: AbortController | null = null
  try {
    const refreshed = await loadMaterialAgentConversation()
    if (!refreshed) {
      message.error(materialAgentError.value || '无法读取最新任务状态。')
      return
    }
    if (!hasPendingMaterialToolCall(replyId, toolCall.id)) {
      message.info('该操作已经处理或所属回复已经结束，页面已同步最新状态。')
      return
    }
    controller = new AbortController()
    materialAgentConfirmAbortController = controller
    materialAgentStreamingTrace.value = createEmptyRuntimeTrace()
    message.info(
      confirmed
        ? `正在允许「${toolCall.name}」执行。`
        : `正在拒绝「${toolCall.name}」。`,
    )
    await streamAgentConversationConfirmation(
      conversationId,
      {
        reply_id: replyId,
        tool_call: toolCall,
        confirmed,
      },
      {
        onAccepted: payload => {
          materialAgentConversationStatus.value = payload.runtime_status
          markMaterialAgentToolDecision(replyId, toolCall.id, confirmed)
          message.success(
            payload.message
            || (
              confirmed
                ? `已允许「${toolCall.name}」，智能体正在继续执行。`
                : `已拒绝「${toolCall.name}」，智能体正在处理确认结果。`
            ),
          )
        },
        onEvents: async runtimeEvents => {
          materialAgentStreamingTrace.value = applyAgentRuntimeEvents(
            materialAgentStreamingTrace.value,
            runtimeEvents,
          )
          await scrollMaterialAgentToEnd()
        },
        onDone: payload => {
          materialAgentConversationStatus.value = payload.runtime_status
        },
      },
      controller.signal,
    )
    await Promise.all([
      loadMaterialAgentConversation(),
      loadInitializationDraft(),
    ])
    await scrollMaterialAgentToEnd('smooth')
  } catch (error: any) {
    if (!isMaterialAgentCancellation(error)) {
      materialAgentError.value = error?.response?.data?.detail || error?.message || '提交人工确认失败。'
      message.error(materialAgentError.value)
      await loadMaterialAgentConversation()
    }
  } finally {
    materialAgentStreamingTrace.value = null
    if (controller && materialAgentConfirmAbortController === controller) {
      materialAgentConfirmAbortController = null
    }
    materialAgentConfirming.value = false
  }
}

function cancelMaterialAgentRequests() {
  materialAgentStreamAbortController?.abort()
  materialAgentConfirmAbortController?.abort()
  materialAgentStreamAbortController = null
  materialAgentConfirmAbortController = null
}

function isMaterialAgentCancellation(error: any) {
  return (
    error?.name === 'AbortError'
    || error?.name === 'CanceledError'
    || error?.code === 'ERR_CANCELED'
  )
}

async function waitForMaterialAgentRefresh(delay: number) {
  if (!delay) return
  await new Promise<void>(resolve => window.setTimeout(resolve, delay))
}

async function reconcileMaterialAgentAfterStop(
  projectId: string,
  conversationId: number,
) {
  const sequence = ++materialAgentReconcileSequence
  const activeStatuses = new Set([
    'creating',
    'running',
    'interrupting',
    'awaiting_permission',
    'awaiting_external_result',
  ])
  let synchronized = false
  for (const delay of [0, 500, 1_000, 2_000, 4_000]) {
    await waitForMaterialAgentRefresh(delay)
    if (
      sequence !== materialAgentReconcileSequence
      || projectId !== configProjectId.value
    ) return
    try {
      await Promise.all([
        loadMaterialAgentConversation(projectId),
        loadInitializationDraft(projectId),
      ])
      const response = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
        `/projects/${projectId}/agent-conversations`,
        { params: { conversation_type: 'initialization' } },
      )
      const conversation = response.data.data.find(
        item => item.id === conversationId,
      )
      if (!conversation || !activeStatuses.has(conversation.status)) {
        synchronized = true
        break
      }
    } catch {
      // 下一轮继续回读；停止请求已经被后端接受。
    }
  }
  if (
    sequence !== materialAgentReconcileSequence
    || projectId !== configProjectId.value
  ) return
  materialAgentStopping.value = false
  if (synchronized) {
    message.success('初始化助手已停止，中断前内容已同步。')
  } else {
    message.info('停止请求仍在后台收尾，稍后重新进入页面即可同步结果。')
  }
}

onBeforeUnmount(() => {
  materialConversationLoadSequence += 1
  materialAgentConversationLoading.value = false
  materialAgentReconcileSequence += 1
  cancelMaterialAgentRequests()
})

function openMaterialAgentFilePicker() {
  materialAgentFileInput.value?.click()
}

function selectMaterialAgentFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const allowedSuffixes = new Set([
    '.xls',
    '.xlsx',
    '.csv',
    '.docx',
    '.pptx',
    '.pdf',
    '.txt',
    '.md',
    '.png',
    '.jpg',
    '.jpeg',
    '.bmp',
    '.webp',
    '.tif',
    '.tiff',
  ])
  const allSelected = Array.from(input.files || [])
  const selected = allSelected.filter((file) => {
    const suffix = file.name.includes('.')
      ? `.${file.name.split('.').pop()?.toLowerCase()}`
      : ''
    return allowedSuffixes.has(suffix) && file.size <= 30 * 1024 * 1024
  })
  if (selected.length !== allSelected.length) {
    message.warning('已忽略不支持的格式或超过 30 MB 的附件。')
  }
  if (!selected.length) {
    input.value = ''
    return
  }
  const existing = new Set(
    materialAgentFiles.value.map(file => `${file.name}:${file.size}:${file.lastModified}`),
  )
  const merged = [...materialAgentFiles.value]
  for (const file of selected) {
    const key = `${file.name}:${file.size}:${file.lastModified}`
    if (!existing.has(key)) {
      merged.push(file)
      existing.add(key)
    }
  }
  materialAgentFiles.value = merged.slice(0, 20)
  if (merged.length > 20) message.warning('一次最多发送 20 个初始化附件。')
  materialAgentError.value = ''
  input.value = ''
}

function removeMaterialAgentFile(index: number) {
  materialAgentFiles.value = materialAgentFiles.value.filter((_, fileIndex) => fileIndex !== index)
}

function clearMaterialAgentFiles() {
  materialAgentFiles.value = []
  if (materialAgentFileInput.value) materialAgentFileInput.value.value = ''
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function run(action: () => Promise<unknown>, success: string) {
  submitting.value = true
  try { await action(); await loadConfigProjectScope(); message.success(success) } catch (error: any) { message.error(error.response?.data?.detail || '保存失败，请检查权限和服务连接。') } finally { submitting.value = false }
}
function openProjectCreate() { projectCreateOpen.value = true }
function closeProjectCreate() { if (!submitting.value) projectCreateOpen.value = false }
function submitProject() {
  void run(async () => {
    const project = await store.createProject({ name: projectForm.name })
    configProjectId.value = project.id
    projectForm.name = ''
    projectCreateOpen.value = false
    if (projectRequiredNotice.value) await router.replace({ path: '/settings' })
  }, '项目已创建')
}
function submitMember() {
  void run(async () => {
    await store.saveMember({
      name: memberForm.name,
      username: memberForm.username || undefined,
      identityCardNo: memberForm.identityCardNo,
      password: memberForm.password,
      positionName: memberForm.positionName,
    }, configProjectId.value)
    Object.assign(memberForm, {
      name: '',
      username: '',
      identityCardNo: '',
      password: '',
      positionName: '',
    })
  }, '成员已添加')
}
function submitWbs() { void run(async () => { await store.createWbs(wbsForm, configProjectId.value); Object.assign(wbsForm, { code: '', name: '', planned_start: '', planned_finish: '' }) }, 'WBS 工序已添加') }
function submitRisk() { void run(async () => { const materials = riskForm.materials.split(/[、,，]/).map(item => item.trim()).filter(Boolean); await store.createRisk({ name: riskForm.name, level: riskForm.level, risk_type: riskForm.risk_type || '综合风险', material_requirements: materials }, configProjectId.value); Object.assign(riskForm, { name: '', level: 'medium', risk_type: '', materials: '' }) }, '风险源已添加') }
function submitQualityMetric() { void run(async () => { await store.createQualityMetric(qualityForm, configProjectId.value); Object.assign(qualityForm, { wbs_item_id: '', name: '', requirement: '', inspection_frequency: '' }) }, '质量指标已添加') }
function submitPlatformMapping() { void run(async () => { await store.createPlatformMapping({ ...mappingForm, enabled: true }, configProjectId.value); Object.assign(mappingForm, { platformName: '监管填报平台', sourceField: 'draft_content', targetField: '', required: false }) }, '平台字段映射已添加') }
function saveMonitoring() { void run(() => store.saveProjectSettings({ ...monitorForm, reminderRules: monitorRules.value }, configProjectId.value), '目录与预警规则已保存') }
function addReminderRule() { const index = monitorRules.value.findIndex(rule => rule.level === reminderForm.level); const next = { id: `rule-${reminderForm.level}`, level: reminderForm.level, days: Number(reminderForm.days) || 0, enabled: true }; if (index >= 0) monitorRules.value[index] = next; else monitorRules.value.push(next); message.info('规则已加入，请点击“保存配置”生效') }
function removeReminderRule(ruleId: string) { monitorRules.value = monitorRules.value.filter(rule => rule.id !== ruleId); message.info('规则已移除，请点击“保存配置”生效') }
function riskLabel(level: RiskLevel) { return ({ critical: '重大风险', high: '高风险', medium: '中风险', low: '低风险' } as Record<RiskLevel, string>)[level] }
function configWbsName(wbsId: string, wbsCode = '') {
  return configScope.wbsItems.find(item => wbsId && item.id === wbsId)?.name
    || configScope.wbsItems.find(item => wbsCode && item.code.trim() === wbsCode.trim())?.name
    || ''
}
function sourceFieldLabel(value: string) { return ({ draft_title: '草稿标题', draft_content: '草稿内容', source_refs: '来源资料' } as Record<string, string>)[value] || value }
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '刚刚' }
</script>

<style scoped>
.setup-page { box-sizing:border-box; display:flex; width:100%; min-width:0; height:100%; padding:18px; overflow:hidden; color:var(--text-primary); }
.panel-head p { margin:0; color:var(--text-muted); font-size:13px; }.primary { border:0; border-radius:6px; padding:9px 14px; color:#fff; background:var(--color-primary); cursor:pointer; font-weight:700; }.primary:disabled { opacity:.55; cursor:not-allowed; }
.setup-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-top:18px; }.setup-page > .setup-grid:first-of-type { margin-top:0; }.panel { background:#fff; border:1px solid var(--border-default); border-radius:10px; padding:20px; min-width:0; }.panel-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:16px; }.panel-head h2 { margin:0 0 5px; font-size:16px; }.projects-panel { grid-column:1 / -1; }.form-stack { display:grid; gap:12px; }.form-stack label { display:grid; gap:6px; font-size:12px; font-weight:700; color:var(--text-secondary); }.form-stack input,.form-stack textarea,.compact-form input,.compact-form select { border:1px solid var(--border-emphasis); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--text-primary); }.form-stack textarea { resize:vertical; }.compact-form { display:grid; grid-template-columns:1fr 1fr 1fr auto; gap:8px; }.wbs-form { grid-template-columns:.45fr 1.25fr 1fr 1fr auto; }.risk-form { grid-template-columns:1.1fr .55fr .9fr 1.35fr auto; }.quality-form { grid-template-columns:1fr 1fr 1.4fr .8fr auto; }.mapping-form { grid-template-columns:1.2fr .9fr 1fr auto auto; }.reminder-form { grid-template-columns:1fr 1fr auto; }.directory-pair,.monitor-controls { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.monitor-controls { align-items:end; grid-template-columns:1fr 1fr auto; }.check-label { display:flex !important; align-items:center; gap:7px; padding-bottom:9px; }.check-label input { width:15px; height:15px; }.link-button { border:0; padding:0; background:transparent; color:var(--color-primary); cursor:pointer; font:inherit; font-weight:700; }.item-list { display:grid; gap:0; margin-top:16px; border-top:1px solid var(--border-default); }.item-list>div { display:grid; grid-template-columns:1.2fr 1fr .8fr; gap:10px; align-items:center; padding:11px 0; border-bottom:1px solid var(--border-default); font-size:12px; }.item-list strong { font-size:13px; }.item-list span,.item-list small { color:var(--text-muted); }.empty { color:var(--text-muted); font-size:13px; padding:14px 0; }.project-row { display:flex; text-align:left; align-items:center; gap:10px; width:100%; padding:12px 4px; border:0; border-bottom:1px solid var(--border-default); background:transparent; cursor:pointer; }.project-row.active { color:var(--color-primary); }.project-row>span { width:8px; height:8px; border-radius:50%; background:var(--color-success); }.project-row div { flex:1; }.project-row strong,.project-row p { display:block; margin:0; }.project-row p,.project-row em { margin-top:3px; color:var(--text-muted); font-size: 12px; font-style:normal; }.config-summary { display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-top:18px; }.config-summary article { padding:16px; background:#f8faf9; border:1px solid var(--border-default); border-radius:9px; }.config-summary span,.config-summary p { display:block; color:var(--text-muted); font-size:12px; }.config-summary strong { display:block; margin:8px 0 3px; font-size:28px; }.config-summary p { margin:0; }
.setup-workspace { display:grid; flex:1 1 auto; min-height:0; grid-template-columns:300px minmax(0,1fr); align-items:stretch; gap:18px; }.project-navigator { min-height:0; overflow:hidden; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.project-navigator-head { display:flex; align-items:center; justify-content:space-between; min-height:64px; padding:0 18px; border-bottom:1px solid var(--border-default); }.project-navigator-head h2 { margin:0; font-size:16px; }.project-navigator-head .link-button { font-size:12px; }.project-nav-item { display:flex; align-items:flex-start; gap:10px; width:100%; min-width:0; padding:15px 16px; border:0; border-bottom:1px solid var(--border-default); border-left:3px solid transparent; background:transparent; color:var(--text-primary); font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,border-color .16s ease; }.project-nav-item:hover { background:#f8fbfa; }.project-nav-item.active { border-left-color:#0f8b7a; background:#eef7f4; }.project-status-dot { flex:0 0 auto; width:9px; height:9px; margin-top:5px; border-radius:50%; background:#aebcb9; }.project-nav-item.active .project-status-dot,.project-context .project-status-dot { background:#0f8b7a; }.project-nav-info { display:grid; flex:1 1 auto; min-width:0; gap:5px; }.project-nav-info strong { overflow:hidden; color:#25413e; font-size:13px; font-weight:750; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.project-nav-info small { overflow:hidden; color:var(--text-muted); font-size: 12px; line-height:1.3; text-overflow:ellipsis; white-space:nowrap; }.project-nav-item em { flex:0 0 auto; margin-top:3px; color:var(--text-muted); font-size: 12px; font-style:normal; white-space:nowrap; }.project-config-panel { display:grid; min-width:0; min-height:0; grid-template-rows:auto minmax(0,1fr); overflow:hidden; }.project-context { padding:20px 24px; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.project-context-title { display:flex; align-items:center; gap:10px; }.project-context-title .project-status-dot { margin-top:0; }.project-context-title h1 { margin:0; color:#203936; font-size:18px; line-height:1.35; }.project-context-meta { display:grid; grid-template-columns:minmax(210px,1.2fr) 150px minmax(250px,1fr); gap:16px 24px; margin:18px 0 0; }.project-context-meta div { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:10px; min-width:0; }.project-context-meta dt { color:var(--text-muted); font-size:12px; }.project-context-meta dd { display:flex; align-items:center; min-width:0; gap:7px; margin:0; overflow:hidden; color:#46635f; font-size:12px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.project-context-meta dd .project-status-dot { width:8px; height:8px; margin-top:0; }.configuration-progress { grid-template-columns:auto minmax(0,1fr) !important; }.progress-track { display:block; flex:1 1 auto; min-width:72px; max-width:120px; height:6px; overflow:hidden; border-radius:999px; background:#e4ece9; }.progress-track i { display:block; height:100%; border-radius:inherit; background:#0f8b7a; transition:width .2s ease; }.project-config-scroll { min-height:0; overflow-y:auto; padding-right:6px; }.project-config-scroll > .setup-grid:first-child { margin-top:18px; }
.project-nav-name { display:block; flex:1 1 auto; min-width:0; color:#25413e; font-size:13px; font-weight:750; line-height:1.55; overflow-wrap:anywhere; white-space:normal; }
.project-config-panel { grid-template-rows:minmax(0,1fr); }
.project-list-empty { display:grid; justify-items:start; gap:8px; margin:14px; padding:18px; border:1px dashed #c9d9d5; border-radius:9px; background:#f8fbfa; }
.project-list-empty > span { display:grid; width:34px; height:34px; place-items:center; border-radius:8px; color:#176d62; background:#e3f1ed; }
.project-list-empty strong { color:#294a45; font-size:13px; }
.project-list-empty p { margin:0; color:#778d88; font-size:12px; line-height:1.6; }
.project-list-empty button { display:inline-flex; align-items:center; gap:5px; margin-top:4px; border:0; padding:0; color:#0f766e; background:transparent; font:inherit; font-size:12px; font-weight:800; cursor:pointer; }
.project-list-empty button:hover { color:#0b5d56; text-decoration:underline; }
.project-list-empty button:focus-visible,.project-empty-primary:focus-visible { outline:3px solid rgba(15,118,110,.2); outline-offset:3px; }
.project-list-loading { display:grid; gap:9px; margin:18px; padding:6px 0; }
.project-list-loading i,.project-list-loading span,.project-list-loading small { display:block; height:10px; border-radius:4px; background:#edf2f0; animation:project-empty-pulse 1.3s ease-in-out infinite; }
.project-list-loading i { width:34px; height:34px; border-radius:8px; }.project-list-loading span { width:72%; }.project-list-loading small { width:48%; }
.project-empty-stage { position:relative; min-width:0; min-height:0; overflow:hidden; border:1px solid var(--border-default); border-radius:10px; background:radial-gradient(circle at 88% 12%,rgba(15,118,110,.10),transparent 30%),linear-gradient(145deg,#fff 0%,#f7faf8 66%,#edf5f2 100%); }
.project-empty-stage::before { position:absolute; right:-64px; bottom:-92px; width:310px; height:310px; border:1px solid rgba(15,118,110,.13); border-radius:50%; box-shadow:0 0 0 48px rgba(15,118,110,.035),0 0 0 96px rgba(15,118,110,.022); content:""; pointer-events:none; }
.project-empty-content { position:relative; z-index:1; display:grid; align-content:center; max-width:860px; min-height:100%; margin:0 auto; padding:clamp(48px,8vh,94px) clamp(42px,7vw,92px); }
.project-required-notice { display:flex; align-items:center; width:fit-content; max-width:100%; gap:9px; margin-bottom:30px; border:1px solid #ebcfb8; border-radius:8px; padding:10px 12px; color:#895022; background:#fff8f1; font-size:12px; line-height:1.45; }
.project-required-notice span { display:flex; flex-wrap:wrap; gap:4px 8px; }.project-required-notice strong { color:#703b16; }
.project-empty-kicker { color:#0f766e; font-size:12px; font-weight:850; letter-spacing:.12em; }
.project-empty-content h1 { max-width:760px; margin:13px 0 0; color:#173a35; font-size:clamp(28px,3vw,44px); font-weight:780; line-height:1.2; letter-spacing:-.025em; }
.project-empty-description { max-width:710px; margin:19px 0 0; color:#657d78; font-size:14px; line-height:1.9; }
.project-empty-primary { display:inline-flex; width:fit-content; align-items:center; justify-content:center; gap:8px; margin-top:28px; border:0; border-radius:8px; padding:11px 18px; color:#fff; background:#0f766e; box-shadow:0 8px 22px rgba(15,118,110,.16); font:inherit; font-size:13px; font-weight:800; cursor:pointer; transition:transform .16s ease,background .16s ease,box-shadow .16s ease; }
.project-empty-primary:hover { transform:translateY(-1px); background:#0b675f; box-shadow:0 11px 26px rgba(15,118,110,.22); }
.project-init-path { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0; margin:54px 0 0; padding:0; border-top:1px solid #dbe6e2; list-style:none; }
.project-init-path li { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:start; gap:11px; padding:18px 22px 0 0; }
.project-init-path li+li { padding-left:22px; border-left:1px solid #dbe6e2; }
.project-init-path li > span { color:#0f766e; font-size:12px; font-weight:850; font-variant-numeric:tabular-nums; letter-spacing:.08em; }
.project-init-path li div { display:grid; gap:5px; }.project-init-path strong { color:#31544e; font-size:13px; }.project-init-path small { color:#83938f; font-size:12px; line-height:1.45; }
.project-empty-loading { display:grid; align-content:center; width:min(70%,680px); min-height:100%; gap:16px; margin:0 auto; }
.project-empty-loading i,.project-empty-loading span,.project-empty-loading button { display:block; border:0; border-radius:7px; background:#eaf0ee; animation:project-empty-pulse 1.3s ease-in-out infinite; }
.project-empty-loading i { width:88px; height:13px; }.project-empty-loading span { width:100%; height:32px; }.project-empty-loading span:nth-of-type(2) { width:72%; height:13px; }.project-empty-loading button { width:148px; height:42px; margin-top:12px; }
@keyframes project-empty-pulse { 0%,100% { opacity:.58; } 50% { opacity:1; } }
.project-workspace-tabs { position:sticky; top:0; z-index:3; display:flex; gap:8px; padding:12px 0; background:var(--bg-base); }.project-workspace-tabs button { display:grid; flex:1 1 0; min-width:0; gap:2px; border:1px solid var(--border-default); border-radius:7px; padding:9px 12px; color:var(--text-secondary); background:#fff; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,border-color .16s ease,color .16s ease; }.project-workspace-tabs button:hover { border-color:#b8d2cc; background:#f7fbf9; }.project-workspace-tabs button.active { border-color:#0f8b7a; color:#174e47; background:#e8f4f0; }.project-workspace-tabs strong { overflow:hidden; font-size:12px; font-weight:800; text-overflow:ellipsis; white-space:nowrap; }.project-workspace-tabs span { overflow:hidden; color:var(--text-muted); font-size: 12px; text-overflow:ellipsis; white-space:nowrap; }.project-workspace-tabs button.active span { color:#4c7d75; }
.material-agent-workspace { display:grid; gap:16px; padding:20px; border:1px solid var(--border-default); border-radius:10px; background:#fff; }.material-workspace-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }.material-workspace-head>div:first-child { min-width:0; }.material-workspace-head span { display:block; margin-bottom:5px; color:#0f766e; font-size: 12px; font-weight:850; letter-spacing:.05em; }.material-workspace-head h2 { margin:0 0 6px; color:#1a3935; font-size:18px; line-height:1.35; }.material-workspace-head p { max-width:76ch; margin:0; color:var(--text-muted); font-size:12px; line-height:1.65; }.material-workspace-actions { display:flex; flex:0 0 auto; align-items:center; gap:8px; }.material-workspace-actions select { min-width:0; border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 9px; color:var(--text-secondary); background:#fff; font:inherit; font-size:12px; }.secondary-action { display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 11px; color:#315c56; background:#fff; font:inherit; font-size:12px; font-weight:750; text-decoration:none; white-space:nowrap; cursor:pointer; }.secondary-action:hover { border-color:#69a096; background:#f4faf8; }.agent-context-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.agent-context-summary article { padding:13px 14px; border:1px solid #e0ebe8; border-radius:8px; background:#f7fbfa; }.agent-context-summary span { display:block; color:#6a8581; font-size: 12px; font-weight:750; }.agent-context-summary strong { display:block; margin:5px 0 2px; color:#1b4943; font-size:23px; line-height:1.1; }.agent-context-summary p { margin:0; color:var(--text-muted); font-size: 12px; }.material-agent-chat { display:grid; min-height:390px; grid-template-rows:minmax(260px,1fr) auto auto; border:1px solid var(--border-default); border-radius:8px; overflow:hidden; background:#fbfcfc; }.material-agent-messages { display:grid; align-content:start; gap:14px; min-height:0; overflow-y:auto; padding:18px; }.material-agent-welcome { display:grid; gap:11px; align-self:center; max-width:700px; margin:auto; padding:8px; color:#315954; text-align:center; }.material-agent-welcome strong { color:#183d38; font-size:16px; }.material-agent-welcome p { margin:0; color:var(--text-muted); font-size:13px; line-height:1.7; }.material-agent-welcome>div { display:flex; justify-content:center; flex-wrap:wrap; gap:8px; }.material-agent-welcome button { border:1px solid #b9d6cf; border-radius:999px; padding:7px 11px; color:#21675d; background:#eef8f5; font:inherit; font-size:12px; cursor:pointer; }.material-agent-message { display:flex; align-items:flex-start; gap:9px; max-width:min(92%,760px); }.material-agent-message>span { display:grid; flex:0 0 auto; place-items:center; width:28px; height:28px; border-radius:50%; color:#fff; background:#0f766e; font-size:12px; font-weight:800; }.material-agent-message>div { min-width:0; padding:10px 12px; border:1px solid #dce9e5; border-radius:4px 10px 10px; background:#fff; }.material-agent-message small { display:block; margin-bottom:4px; color:#64817d; font-size: 12px; font-weight:800; }.material-agent-message p { margin:0; color:#355652; font-size:13px; line-height:1.65; white-space:pre-wrap; }.material-agent-message.user { justify-self:end; flex-direction:row-reverse; }.material-agent-message.user>span { background:#cd5b20; }.material-agent-message.user>div { border-color:#f0d8ca; border-radius:10px 4px 10px 10px; background:#fff9f5; }.material-agent-error { margin:0; padding:8px 14px; border-top:1px solid #f2ded5; color:#b64c1e; background:#fff7f3; font-size:12px; }.material-agent-composer { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; padding:12px; border-top:1px solid var(--border-default); background:#fff; }.material-agent-composer textarea { min-height:44px; max-height:120px; resize:vertical; border:1px solid var(--border-emphasis); border-radius:6px; padding:10px; color:var(--text-primary); font:inherit; font-size:13px; }.material-agent-composer textarea:focus { outline:2px solid rgba(15,118,110,.14); outline-offset:1px; border-color:#4f978a; }
.project-config-scroll > .setup-grid { grid-template-columns:1fr; gap:14px; }.project-config-scroll > .setup-grid .panel { padding:20px 22px; }.project-config-scroll > .setup-grid .panel-head { margin-bottom:15px; }.project-config-scroll > .setup-grid .item-list { margin-top:15px; }
.project-config-scroll { display:flex; flex-direction:column; }.project-workspace-tabs { flex:0 0 auto; }
.project-config-scroll > .project-connection-workspace { flex:1 1 auto; min-height:0; }
.project-connection-workspace { display:grid; min-height:0; grid-template-rows:auto minmax(0,1fr); gap:16px; padding:20px; border:1px solid var(--border-default); border-radius:10px; overflow:hidden; background:#fff; }
.project-connection-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding-bottom:16px; border-bottom:1px solid var(--border-default); }
.project-connection-head > div { min-width:0; }.project-connection-head span { display:block; margin-bottom:5px; color:#0f766e; font-size:12px; font-weight:850; letter-spacing:.05em; }.project-connection-head h2 { margin:0 0 6px; color:#1a3935; font-size:18px; line-height:1.35; }.project-connection-head p { margin:0; color:var(--text-muted); font-size:12px; line-height:1.65; }.project-connection-head em { flex:0 0 auto; border-radius:5px; padding:5px 8px; color:#53736d; background:#edf4f2; font-size:12px; font-style:normal; font-variant-numeric:tabular-nums; }
.project-connection-grid { display:grid; min-height:0; grid-template-columns:240px minmax(0,1fr); overflow:hidden; border:1px solid var(--border-default); border-radius:9px; }
.project-connector-list { display:grid; min-height:0; align-content:start; gap:4px; overflow-y:auto; padding:10px; border-right:1px solid var(--border-default); background:#f7faf8; }.project-connector-list button { display:grid; width:100%; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:9px; border:0; border-radius:7px; padding:10px; color:#55706b; background:transparent; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,color .16s ease; }.project-connector-list button:hover,.project-connector-list button.active { color:#204f49; background:#e7f1ee; }.project-connector-list button.active { box-shadow:inset 3px 0 #0f766e; }.project-connector-list button > span:nth-child(2) { display:grid; min-width:0; gap:2px; }.project-connector-list strong { overflow:hidden; color:#294d47; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }.project-connector-list small { color:#82938f; font-size:12px; }.project-connector-list button > i { width:7px; height:7px; border-radius:50%; background:#b7c2bf; }.project-connector-list button > i.configured { background:#10a079; }
.project-connector-icon { display:grid; width:32px; height:32px; place-items:center; border-radius:8px; color:#176b62; background:#dfeeea; }.project-connector-icon.large { width:40px; height:40px; }
.project-connector-editor { display:grid; min-height:0; align-content:start; gap:16px; overflow-y:auto; padding:22px; }.project-connector-editor > header { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:11px; padding-bottom:15px; border-bottom:1px solid var(--border-default); }.project-connector-editor h3 { margin:0 0 4px; color:#193b37; font-size:17px; }.project-connector-editor header p { margin:0; color:#6d817c; font-size:12px; line-height:1.55; }.project-connector-editor label { display:grid; gap:7px; color:#49645f; font-size:13px; font-weight:700; }.project-connector-editor input { box-sizing:border-box; width:100%; min-width:0; min-height:42px; border:1px solid #cad9d5; border-radius:7px; padding:9px 11px; color:#193b37; background:#fff; font:inherit; font-size:13px; outline:0; }.project-connector-editor input:focus { border-color:#4e9187; box-shadow:0 0 0 3px rgba(15,118,110,.1); }
.project-credential-note { display:grid; grid-template-columns:auto minmax(0,1fr); gap:9px; padding:11px; border-radius:8px; color:#0f766e; background:#eef6f3; }.project-credential-note p { display:grid; gap:3px; margin:0; }.project-credential-note strong { color:#315a54; font-size:12px; }.project-credential-note span { color:#70837f; font-size:12px; line-height:1.5; }
.project-connector-actions { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-top:4px; padding-top:18px; border-top:1px solid var(--border-default); }.project-connector-actions > span { color:#7a8d88; font-size:12px; }.project-connector-actions .primary { display:inline-flex; align-items:center; justify-content:center; gap:7px; white-space:nowrap; }
.setup-modal-backdrop { position:fixed; inset:0; z-index:30; display:grid; place-items:center; padding:24px; background:rgba(15,32,35,.42); backdrop-filter:blur(2px); }.setup-modal { width:min(100%,560px); max-height:calc(100dvh - 48px); overflow:auto; padding:20px; border:1px solid rgba(28,56,57,.18); border-radius:12px; background:#fff; box-shadow:0 22px 56px rgba(15,39,42,.26); }.setup-modal-head { display:flex; justify-content:space-between; align-items:center; gap:14px; min-width:0; margin-bottom:12px; }.setup-modal-head>div { display:flex; flex:1 1 auto; align-items:baseline; gap:10px; min-width:0; }.setup-modal-head span { flex:0 0 auto; color:var(--color-primary); font-size:12px; font-weight:800; letter-spacing:.04em; white-space:nowrap; }.setup-modal-head h2 { flex:0 1 auto; overflow:hidden; min-width:0; margin:0; color:#173235; font-size:17px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.setup-modal-head p { flex:1 1 14rem; overflow:hidden; min-width:5rem; max-width:none; margin:0; color:var(--text-muted); font-size:12px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }.setup-modal-head .modal-close { flex:0 0 auto; }.modal-close,.modal-secondary { border:1px solid var(--border-emphasis); border-radius:6px; padding:8px 12px; color:var(--text-secondary); background:#fff; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.modal-close:disabled,.modal-secondary:disabled { opacity:.55; cursor:not-allowed; }.project-create-form { gap:14px; }.setup-modal-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }.compact-form > * { min-width:0; }.compact-form input,.compact-form select { width:100%; min-width:0; }
.project-config-scroll > .manual-config-workspace { flex:1 1 auto; min-height:0; }
.project-config-scroll > .material-agent-workspace { display:grid; flex:1 1 auto; min-height:0; grid-template-rows:auto auto minmax(0,1fr); gap:10px; padding:14px 18px; }.material-agent-head { min-height:0; }.material-agent-head h2 { margin-bottom:3px; font-size:16px; }.material-agent-head p { max-width:none; font-size:12px; line-height:1.45; }.agent-context-summary { gap:0; overflow:hidden; border:1px solid #e0ebe8; border-radius:7px; background:#f8fbfa; }.agent-context-summary article { display:flex; align-items:baseline; gap:7px; min-width:0; padding:9px 13px; border:0; border-right:1px solid #e0ebe8; border-radius:0; background:transparent; }.agent-context-summary article:last-child { border-right:0; }.agent-context-summary span { flex:0 1 auto; overflow:hidden; color:#69847f; font-size: 12px; text-overflow:ellipsis; white-space:nowrap; }.agent-context-summary strong { flex:0 0 auto; margin:0; color:#1b4943; font-size:19px; font-variant-numeric:tabular-nums; }.agent-context-summary small { overflow:hidden; color:#7b918c; font-size: 12px; text-overflow:ellipsis; white-space:nowrap; }.material-agent-chat { min-height:0; height:100%; grid-template-rows:minmax(200px,1fr) auto auto; }.material-agent-chat.has-draft { grid-template-rows:minmax(200px,1fr) auto auto auto; }
.project-config-scroll > .material-agent-workspace { grid-template-rows:minmax(0,1fr); gap:0; }
.visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); clip-path:inset(50%); white-space:nowrap; }
.material-agent-messages.empty { place-content:center; }
.material-agent-history-loading { display:grid; place-items:center; gap:7px; margin:auto; padding:24px; color:#5f7873; text-align:center; }
.material-agent-history-loading > span { width:28px; height:28px; border:3px solid #d7e6e2; border-top-color:#0f766e; border-radius:50%; animation:material-agent-history-spin .8s linear infinite; }
.material-agent-history-loading strong { color:#244d46; font-size:14px; }
.material-agent-history-loading p { margin:0; color:#718783; font-size:12px; line-height:1.6; }
@keyframes material-agent-history-spin { to { transform:rotate(360deg); } }
.material-agent-welcome { display:grid; width:min(100%,650px); max-width:none; grid-template-columns:auto minmax(0,1fr); align-items:start; gap:16px; margin:auto; padding:28px 32px; color:#315954; text-align:left; }
.material-agent-welcome-mark { display:grid; width:46px; height:46px; place-items:center; border-radius:12px; color:#fff; background:#0f766e; box-shadow:0 9px 22px rgba(15,118,110,.18); font-size:18px; font-weight:850; }
.material-agent-welcome > div { display:grid; justify-content:stretch; gap:0; min-width:0; }
.material-agent-welcome small { margin:1px 0 6px; color:#0f766e; font-size:12px; font-weight:850; letter-spacing:.1em; }
.material-agent-welcome strong { color:#173d38; font-size:18px; line-height:1.35; letter-spacing:-.015em; text-wrap:balance; }
.material-agent-welcome p { max-width:62ch; margin:9px 0 0; color:#70837f; font-size:13px; line-height:1.75; text-wrap:pretty; }
.material-agent-composer { display:grid; grid-template-columns:minmax(0,1fr); gap:8px; padding:11px 12px 10px; }
.material-agent-composer-row { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:end; gap:9px; }
.material-agent-composer-row textarea { box-sizing:border-box; width:100%; min-height:42px; margin:0; }
.material-agent-attach { display:grid; width:42px; height:42px; place-items:center; border:1px solid var(--border-emphasis); border-radius:7px; color:#52706b; background:#fff; cursor:pointer; transition:border-color .16s ease,color .16s ease,background .16s ease,transform .16s ease; }
.material-agent-attach:hover:not(:disabled) { border-color:#68a096; color:#0f766e; background:#f2f8f6; }
.material-agent-attach:active:not(:disabled) { transform:translateY(1px); }
.material-agent-attach:disabled { opacity:.52; cursor:not-allowed; }
.material-agent-composer-row > .primary { min-height:42px; white-space:nowrap; }
.material-agent-stop { min-height:42px; border:0; border-radius:6px; padding:9px 14px; color:#fff; background:#3e5f5a; font:inherit; font-weight:750; white-space:nowrap; cursor:pointer; }
.material-agent-stop:hover { background:#304f4a; }
.material-agent-stop:disabled { opacity:.6; cursor:not-allowed; }
.material-agent-composer-hint { padding-left:51px; color:#8a9b97; font-size:12px; line-height:1.4; }
.material-agent-file-tray { display:grid; gap:7px; padding:9px 10px 10px; border:1px solid #dce8e5; border-radius:8px; background:#f7faf9; }
.material-agent-file-head { display:flex; align-items:center; justify-content:space-between; gap:12px; color:#617b76; font-size:12px; }
.material-agent-file-head button { border:0; padding:0; color:#2a7469; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }
.material-agent-file-head button:hover { text-decoration:underline; }
.material-agent-file-tray ul { display:flex; gap:7px; margin:0; padding:0; overflow-x:auto; list-style:none; scrollbar-width:thin; }
.material-agent-file-tray li { display:grid; flex:0 0 min(280px,72vw); grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; padding:8px 9px; border:1px solid #d9e5e2; border-radius:7px; color:#347166; background:#fff; }
.material-agent-file-tray li > span { display:grid; min-width:0; gap:2px; }
.material-agent-file-tray strong { overflow:hidden; color:#31534e; font-size:12px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
.material-agent-file-tray small { color:#8a9a97; font-size:12px; font-variant-numeric:tabular-nums; }
.material-agent-file-tray li > button { display:grid; width:26px; height:26px; place-items:center; border:0; border-radius:5px; color:#7f918d; background:transparent; cursor:pointer; transition:color .15s ease,background .15s ease; }
.material-agent-file-tray li > button:hover { color:#a8472b; background:#fff0eb; }
.material-agent-attach:focus-visible,.material-agent-file-tray button:focus-visible { outline:2px solid rgba(15,118,110,.24); outline-offset:2px; }
.material-agent-message-files { display:flex; flex-wrap:wrap; gap:6px; margin:9px 0 0; padding:0; list-style:none; }
.material-agent-message-files li { display:inline-flex; align-items:center; gap:5px; border:1px solid #ead8ce; border-radius:5px; padding:5px 7px; color:#66564f; background:#fff; font-size:12px; }
.material-agent-message-files li small { display:inline; margin:0 0 0 2px; color:#9a8880; font-size:12px; font-weight:600; }
.initialization-draft-dock { position:relative; z-index:2; min-width:0; border-top:1px solid #d5e4e0; background:#f6faf9; box-shadow:inset 3px 0 #0f766e; }
.initialization-draft-dock.status-collecting { border-top-color:#d7e4ee; background:#f5f9fc; box-shadow:inset 3px 0 #4b7f9f; }
.initialization-draft-dock.status-reviewing { border-top-color:#dfdceb; background:#f8f7fc; box-shadow:inset 3px 0 #7565a1; }
.initialization-draft-dock.status-invalid { border-top-color:#efd4c7; background:#fff8f4; box-shadow:inset 3px 0 #c85829; }
.initialization-draft-dock.status-applied { border-top-color:#d2e4da; background:#f5faf7; box-shadow:inset 3px 0 #28835b; }
.initialization-draft-dock.collapsed { box-shadow:none; }
.initialization-draft-content { display:grid; gap:8px; padding:10px 13px 9px 15px; }
.initialization-draft-head { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:16px; }
.initialization-draft-title { display:flex; min-width:0; align-items:center; gap:9px; }
.initialization-draft-title > div { display:flex; min-width:0; align-items:baseline; gap:8px; }
.initialization-draft-title small { flex:0 0 auto; color:#78908b; font-size:12px; letter-spacing:.04em; }
.initialization-draft-title strong { overflow:hidden; color:#234f48; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.initialization-draft-title em { flex:0 0 auto; border-radius:999px; padding:3px 7px; color:#1d6c60; background:#dceeea; font-size:12px; font-style:normal; font-weight:800; white-space:nowrap; }
.initialization-draft-dot { display:block; flex:0 0 auto; width:7px; height:7px; border-radius:50%; background:#15917f; box-shadow:0 0 0 3px rgba(21,145,127,.11); }
.status-collecting .initialization-draft-dot { background:#4b7f9f; box-shadow:0 0 0 3px rgba(75,127,159,.11); }
.status-reviewing .initialization-draft-dot { background:#7565a1; box-shadow:0 0 0 3px rgba(117,101,161,.11); }
.status-invalid .initialization-draft-dot { background:#c85829; box-shadow:0 0 0 3px rgba(200,88,41,.11); }
.status-applied .initialization-draft-dot { background:#28835b; box-shadow:0 0 0 3px rgba(40,131,91,.11); }
.initialization-draft-actions { display:flex; flex:0 0 auto; align-items:center; gap:7px; }
.initialization-draft-actions button,.initialization-draft-collapsed { border:0; font:inherit; cursor:pointer; transition:color .16s ease,background .16s ease,transform .16s ease; }
.initialization-draft-collapse { display:inline-flex; min-height:30px; align-items:center; gap:4px; border-radius:5px !important; padding:5px 8px; color:#657d78; background:transparent; font-size:12px !important; font-weight:700; }
.initialization-draft-collapse:hover { color:#275c54; background:#e7f1ee; }
.initialization-draft-review { min-height:30px; border-radius:5px !important; padding:6px 10px; color:#fff; background:#16796c; font-size:12px !important; font-weight:800; }
.initialization-draft-review:hover { background:#0d6b5f; }
.initialization-draft-actions button:active,.initialization-draft-collapsed:active { transform:translateY(1px); }
.initialization-draft-actions button:focus-visible,.initialization-draft-collapsed:focus-visible { outline:2px solid rgba(15,118,110,.26); outline-offset:-2px; }
.initialization-draft-summary { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); overflow:hidden; border:1px solid #dbe8e5; border-radius:6px; background:rgba(255,255,255,.82); }
.initialization-draft-summary span { display:flex; min-width:0; align-items:baseline; justify-content:center; gap:3px; padding:6px 5px; border-right:1px solid #e5eeec; color:#728681; font-size:12px; text-align:center; white-space:nowrap; }
.initialization-draft-summary span:last-child { border-right:0; }
.initialization-draft-summary strong { color:#245c54; font-size:13px; font-variant-numeric:tabular-nums; }
.initialization-draft-meta { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:16px; }
.initialization-draft-meta span { flex:0 0 auto; color:#58716c; font-size:12px; line-height:1.45; }
.initialization-draft-meta small { overflow:hidden; min-width:0; color:#81918e; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.initialization-draft-collapsed { display:flex; width:100%; min-height:40px; align-items:center; gap:9px; padding:0 14px 0 16px; color:#2d5b54; background:#f6faf9; text-align:left; }
.initialization-draft-collapsed:hover { color:#174f47; background:#edf6f3; }
.initialization-draft-collapsed strong { flex:1 1 auto; font-size:12px; font-weight:800; }
.initialization-draft-collapsed .n-icon { flex:0 0 auto; color:#67807a; }
.material-agent-plan-dock { position:relative; z-index:2; min-width:0; border-top:1px solid #d8e5e2; background:#f8fbfa; box-shadow:inset 3px 0 #32877a; }
.material-agent-plan-dock.completed { box-shadow:inset 3px 0 #4c8a68; }
.material-agent-plan-dock.interrupted { box-shadow:inset 3px 0 #b7792e; }
.material-agent-plan-dock.collapsed { box-shadow:none; }
.material-agent-plan-content { display:grid; gap:8px; padding:10px 13px 10px 16px; }
.material-agent-plan-content > header { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:14px; }
.material-agent-plan-content > header > div { display:flex; min-width:0; align-items:center; gap:8px; }
.material-agent-plan-content > header strong { color:#254f49; font-size:13px; }
.material-agent-plan-content > header em { border-radius:999px; padding:3px 7px; color:#287267; background:#e3f1ed; font-size:12px; font-style:normal; font-weight:750; }
.material-agent-plan-dock.completed .material-agent-plan-content > header em { color:#347153; background:#e6f2e9; }
.material-agent-plan-dock.interrupted .material-agent-plan-content > header em { color:#895a1f; background:#fff1dc; }
.material-agent-plan-content > header button { display:inline-flex; min-height:30px; align-items:center; gap:4px; border:0; border-radius:5px; padding:5px 8px; color:#657d78; background:transparent; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }
.material-agent-plan-content > header button:hover { color:#275c54; background:#e7f1ee; }
.material-agent-plan-dot { display:block; flex:0 0 auto; width:7px; height:7px; border-radius:50%; background:#238b7b; box-shadow:0 0 0 3px rgba(35,139,123,.11); }
.material-agent-plan-dock.completed .material-agent-plan-dot { background:#4c8a68; box-shadow:0 0 0 3px rgba(76,138,104,.11); }
.material-agent-plan-dock.interrupted .material-agent-plan-dot { background:#b7792e; box-shadow:0 0 0 3px rgba(183,121,46,.11); }
.material-agent-plan-progress { height:4px; overflow:hidden; border-radius:999px; background:#dfeae7; }
.material-agent-plan-progress i { display:block; height:100%; border-radius:inherit; background:#238b7b; transition:width .2s ease; }
.material-agent-plan-content ul { display:grid; max-height:142px; gap:4px; margin:0; padding:0; overflow-y:auto; list-style:none; }
.material-agent-plan-content li { display:grid; min-width:0; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; border-radius:5px; padding:5px 7px; color:#5f7772; background:rgba(255,255,255,.68); font-size:12px; line-height:1.45; }
.material-agent-plan-content li > i { width:8px; height:8px; border:2px solid #9bb5af; border-radius:50%; }
.material-agent-plan-content li.in_progress > i { border-color:#238b7b; border-top-color:transparent; animation:material-agent-history-spin .8s linear infinite; }
.material-agent-plan-content li.completed > i { border-color:#4c8a68; background:#4c8a68; box-shadow:inset 0 0 0 2px #fff; }
.material-agent-plan-content li > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.material-agent-plan-content li > small { color:#81928e; font-size:12px; white-space:nowrap; }
.material-agent-plan-content li.completed > span { color:#83948f; text-decoration:line-through; }
.material-agent-plan-collapsed { display:grid; width:100%; min-height:40px; grid-template-columns:auto auto auto minmax(0,1fr) auto; align-items:center; gap:9px; border:0; padding:0 14px 0 16px; color:#2d5b54; background:#f8fbfa; font:inherit; text-align:left; cursor:pointer; }
.material-agent-plan-collapsed:hover { color:#174f47; background:#eef6f3; }
.material-agent-plan-collapsed strong { font-size:12px; }
.material-agent-plan-collapsed > span:not(.material-agent-plan-dot) { color:#68807b; font-size:12px; font-variant-numeric:tabular-nums; }
.material-agent-plan-collapsed em { overflow:hidden; color:#6e817d; font-size:12px; font-style:normal; text-overflow:ellipsis; white-space:nowrap; }
.material-agent-plan-collapsed .n-icon { color:#67807a; }
.material-agent-plan-content > header button:focus-visible,.material-agent-plan-collapsed:focus-visible { outline:2px solid rgba(15,118,110,.26); outline-offset:-2px; }
.initialization-review-backdrop { z-index:36; }.initialization-review-modal { display:grid; width:min(100%,1380px); max-height:calc(100dvh - 48px); grid-template-rows:auto minmax(0,1fr) auto; overflow:hidden; padding:0; font-size:12px; }
.initialization-review-modal > .setup-modal-head { margin:0; padding:18px 20px 14px; border-bottom:1px solid var(--border-default); }
.initialization-review-body { display:flex; min-height:0; flex-direction:column; gap:13px; overflow-y:auto; padding:16px 20px; background:#fbfcfc; }
.initialization-review-body > * { flex:0 0 auto; }
.initialization-review-section { display:grid; gap:10px; border:1px solid #dce8e5; border-radius:8px; padding:13px 14px; background:#fff; }
.initialization-review-section > header { display:flex; align-items:center; justify-content:space-between; gap:12px; }.initialization-review-section h3 { margin:0; color:#284d47; font-size:14px; }.initialization-review-section header span { color:#80918e; font-size:12px; }
.initialization-project-section { gap:14px; overflow:hidden; padding:0; }
.initialization-project-head { align-items:flex-start !important; padding:14px 16px 0; }
.initialization-project-head > div { min-width:0; }
.initialization-project-head h3 { font-size:15px; letter-spacing:-.01em; }
.initialization-project-head p { margin:4px 0 0; color:#7b8e8a; font-size:12px; line-height:1.5; }
.initialization-project-head > span { flex:0 0 auto; border-radius:4px; padding:3px 6px; color:#52716b !important; background:#edf5f3; font-weight:750; }
.initialization-project-description { margin:0 14px; border-left:3px solid #5a988e; border-radius:2px 7px 7px 2px; padding:12px 14px 13px; background:#f3f8f6; }
.initialization-project-description span { display:block; margin-bottom:5px; color:#5e7873; font-size:12px; font-weight:800; }
.initialization-project-description p { max-width:100ch; margin:0; color:#264a44; font-size:13px; font-weight:650; line-height:1.7; text-wrap:pretty; }
.initialization-project-contract-grid { display:grid; grid-template-columns:1.05fr 1.05fr .8fr 1fr; gap:1px; overflow:hidden; margin:0 14px; border:1px solid #dfe9e7; border-radius:7px; background:#dfe9e7; }
.initialization-project-contract-grid article { display:grid; min-width:0; gap:5px; padding:11px 12px; background:#fff; }
.initialization-project-contract-grid span { color:#758985; font-size:12px; }
.initialization-project-contract-grid strong { overflow-wrap:anywhere; color:#244d46; font-size:13px; font-variant-numeric:tabular-nums; line-height:1.45; }
.initialization-project-units { display:grid; gap:8px; border-top:1px solid #e5eeec; padding:12px 14px 15px; }
.initialization-project-units h4 { margin:0; color:#486760; font-size:12px; font-weight:850; }
.initialization-project-units dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; margin:0; }
.initialization-project-units dl > div { display:grid; min-width:0; grid-template-columns:88px minmax(0,1fr); align-items:baseline; gap:9px; border-radius:5px; padding:9px 10px; background:#f7faf9; }
.initialization-project-units dl > div.primary { grid-column:1 / -1; border-left:2px solid #7aaaa2; background:#f0f7f5; }
.initialization-project-units dt,.initialization-project-units dd { margin:0; font-size:12px; line-height:1.55; }
.initialization-project-units dt { color:#758985; }
.initialization-project-units dd { min-width:0; color:#2e514b; font-weight:700; overflow-wrap:anywhere; }
.initialization-review-data-section { overflow:hidden; border:1px solid #dce8e5; border-radius:8px; background:#fff; }
.initialization-review-data-toggle { display:grid; width:100%; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:9px; border:0; padding:11px 13px; color:#32635b; background:#f8fbfa; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,color .16s ease; }
.initialization-review-data-toggle:hover { color:#1d5c52; background:#f0f7f5; }
.initialization-review-data-toggle:focus-visible { outline:2px solid rgba(15,118,110,.24); outline-offset:-2px; }
.initialization-review-data-toggle > .n-icon { color:#6f8984; transform:rotate(-90deg); transition:transform .18s ease; }
.initialization-review-data-toggle.expanded > .n-icon { transform:rotate(0deg); }
.initialization-review-data-toggle > span { display:flex; min-width:0; align-items:baseline; gap:9px; }
.initialization-review-data-toggle strong { flex:0 0 auto; color:#28564f; font-size:13px; }
.initialization-review-data-toggle small { overflow:hidden; color:#80928e; font-size:12px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.initialization-review-data-toggle em { flex:0 0 auto; color:#6b827d; font-size:12px; font-style:normal; font-variant-numeric:tabular-nums; font-weight:750; }
.initialization-personnel-list { display:grid; gap:10px; border-top:1px solid #e5eeec; padding:12px; background:#f6faf8; }
.initialization-personnel-card { display:grid; min-width:0; grid-template-columns:minmax(190px,.62fr) minmax(300px,1.25fr) minmax(330px,1.05fr); gap:0; overflow:hidden; border:1px solid #dce8e5; border-radius:7px; background:#fff; transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease; }
.initialization-personnel-card:hover { border-color:#c6dbd6; box-shadow:0 5px 16px rgba(31,83,73,.07); transform:translateY(-1px); }
.initialization-personnel-profile { display:grid; min-width:0; grid-template-columns:36px minmax(0,1fr); grid-template-rows:auto auto; align-content:center; align-items:center; gap:2px 10px; padding:14px; border-right:1px solid #e5eeec; background:#fbfdfc; }
.initialization-personnel-profile > span { display:grid; grid-row:1 / 3; width:36px; height:36px; place-items:center; border-radius:9px; color:#fff; background:#377f74; box-shadow:0 4px 10px rgba(55,127,116,.16); font-size:12px; font-variant-numeric:tabular-nums; font-weight:850; letter-spacing:.04em; }
.initialization-personnel-profile > div { min-width:0; }
.initialization-personnel-profile h4 { margin:0; color:#244c45; font-size:14px; line-height:1.35; overflow-wrap:anywhere; }
.initialization-personnel-profile p { margin:3px 0 0; color:#6d837e; font-size:12px; line-height:1.45; overflow-wrap:anywhere; }
.initialization-personnel-profile > em { grid-column:2; width:max-content; margin-top:5px; border-radius:4px; padding:2px 6px; color:#8a5a27; background:#fff1d9; font-size:12px; font-style:normal; font-weight:750; }
.initialization-personnel-profile > em.existing { color:#2f6f64; background:#e4f2ee; }
.initialization-personnel-profile > em.shared { color:#566f89; background:#eaf1f8; }
.initialization-personnel-facts { display:grid; min-width:0; grid-template-columns:repeat(2,minmax(0,1fr)); align-content:center; gap:10px 16px; margin:0; padding:13px 15px; }
.initialization-personnel-facts > div { min-width:0; }
.initialization-personnel-facts > div.responsibility { grid-column:1 / -1; padding-top:9px; border-top:1px solid #edf2f0; }
.initialization-personnel-facts dt,.initialization-personnel-facts dd { margin:0; font-size:12px; line-height:1.55; }
.initialization-personnel-facts dt { margin-bottom:3px; color:#7a8d89; font-weight:700; }
.initialization-personnel-facts dd { color:#31534d; font-variant-numeric:tabular-nums; font-weight:650; overflow-wrap:anywhere; text-wrap:pretty; }
.initialization-personnel-credential { display:grid; min-width:0; grid-template-columns:repeat(2,minmax(0,1fr)); align-content:center; gap:9px 10px; padding:12px 14px; border-left:1px solid #e5eeec; background:#f5faf8; }
.initialization-personnel-credential > div { display:flex; grid-column:1 / -1; align-items:baseline; justify-content:space-between; gap:12px; }
.initialization-personnel-credential > div strong { color:#31564f; font-size:12px; font-weight:850; }
.initialization-personnel-credential > div span { color:#81928e; font-size:12px; }
.initialization-personnel-credential label { display:grid; min-width:0; gap:5px; color:#607873; font-size:12px; font-weight:750; }
.initialization-personnel-credential input { min-width:0; width:100%; box-sizing:border-box; border:1px solid #cbded9; border-radius:5px; padding:8px 9px; color:#233f3b; background:#fff; font:inherit; font-size:12px; transition:border-color .16s ease,box-shadow .16s ease; }
.initialization-personnel-credential input:focus { border-color:#5f9f94; outline:0; box-shadow:0 0 0 3px rgba(36,128,113,.1); }
.initialization-generated-password { display:flex; min-width:0; gap:6px; }
.initialization-generated-password input { min-width:0; flex:1 1 auto; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing:.04em; }
.initialization-generated-password button { flex:0 0 auto; border:1px solid #cbded9; border-radius:5px; padding:0 9px; color:#38675f; background:#fff; font:inherit; font-size:12px; font-weight:750; cursor:pointer; white-space:nowrap; }
.initialization-generated-password button:hover { border-color:#8fb8b0; color:#1f5c52; background:#eff7f5; }
.initialization-generated-password button:focus-visible { outline:2px solid rgba(15,118,110,.22); outline-offset:1px; }
.initialization-personnel-credential > p { grid-column:1 / -1; margin:1px 0 0; color:#718681; font-size:12px; line-height:1.5; }
.initialization-personnel-account-ready { display:grid; align-content:center; gap:4px; padding:14px; border-left:1px solid #e5eeec; background:#f7faf9; }
.initialization-personnel-account-ready small { color:#718681; font-size:12px; font-weight:750; }
.initialization-personnel-account-ready strong { color:#2e5f56; font:800 15px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; overflow-wrap:anywhere; }
.initialization-personnel-account-ready span { color:#83938f; font-size:12px; line-height:1.5; }
.initialization-personnel-account-ready.existing { border-left-color:#cfe2de; background:#f2f8f6; }
.initialization-personnel-account-ready.shared { border-left-color:#d5e1ec; background:#f5f8fb; }
.initialization-wbs-content { border-top:1px solid #e5eeec; background:#fff; }
.initialization-wbs-toolbar { display:flex; min-height:44px; align-items:center; justify-content:space-between; gap:12px; padding:8px 12px; border-bottom:1px solid #e5eeec; background:#fbfdfc; }
.initialization-wbs-toolbar > div { display:flex; min-width:0; align-items:center; gap:10px; }
.initialization-wbs-toolbar strong { color:#28564f; font-size:12px; }
.initialization-wbs-toolbar span { color:#718783; font-size:12px; font-variant-numeric:tabular-nums; }
.initialization-wbs-toolbar em { display:inline-flex; align-items:center; gap:5px; border-radius:4px; padding:4px 7px; color:#8b5a24; background:#fff2d7; font-size:12px; font-style:normal; font-weight:750; white-space:nowrap; }
.initialization-wbs-toolbar em.sequence-warning { color:#a53f2c; background:#ffebe5; }
.initialization-wbs-toolbar button { border:0; border-radius:4px; padding:5px 7px; color:#287166; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; transition:color .16s ease,background .16s ease; }
.initialization-wbs-toolbar button:hover { color:#174f47; background:#eaf4f1; }
.initialization-wbs-toolbar button:active { transform:translateY(1px); }
.initialization-wbs-toolbar button:focus-visible { outline:2px solid rgba(15,118,110,.24); outline-offset:1px; }
.initialization-wbs-table-wrap { overflow-x:auto; overflow-y:hidden; background:#fff; }
.initialization-wbs-table { width:100%; min-width:1180px; border-spacing:0; border-collapse:separate; table-layout:fixed; color:#49635e; font-size:12px; }
.initialization-wbs-table th { padding:10px 11px; border-right:1px solid #e5eeec; border-bottom:1px solid #dce8e5; color:#5d7772; background:#f3f8f6; font-size:12px; font-weight:800; line-height:1.4; text-align:left; white-space:nowrap; }
.initialization-wbs-table th:last-child,.initialization-wbs-table td:last-child { border-right:0; }
.initialization-wbs-table td { padding:10px 11px; border-right:1px solid #edf2f0; border-bottom:1px solid #edf2f0; font-size:12px; line-height:1.55; vertical-align:top; }
.initialization-wbs-table tbody tr:last-child td { border-bottom:0; }
.initialization-wbs-table tbody tr { transition:background .16s ease; }
.initialization-wbs-table tbody tr:hover { background:#f3f9f7; }
.initialization-wbs-table tbody tr.is-wbs-group { background:#f9fcfb; }
.initialization-wbs-table tbody tr.has-dependency-warning { background:#fffaf0; }
.initialization-wbs-table tbody tr.has-dependency-warning:hover { background:#fff6e5; }
.initialization-wbs-table tbody tr.has-sequence-warning { background:#fff5f1; }
.initialization-wbs-table tbody tr.has-sequence-warning:hover { background:#ffebe5; }
.initialization-wbs-table th:nth-child(1),.initialization-wbs-table td:nth-child(1) { width:92px; }
.initialization-wbs-table th:nth-child(2),.initialization-wbs-table td:nth-child(2) { width:340px; }
.initialization-wbs-table th:nth-child(3),.initialization-wbs-table td:nth-child(3),.initialization-wbs-table th:nth-child(4),.initialization-wbs-table td:nth-child(4) { width:104px; }
.initialization-wbs-table th:nth-child(5),.initialization-wbs-table td:nth-child(5) { width:68px; }
.initialization-wbs-table th:nth-child(6),.initialization-wbs-table td:nth-child(6) { width:74px; }
.initialization-wbs-table th:nth-child(7),.initialization-wbs-table td:nth-child(7) { width:70px; }
.initialization-wbs-table th:nth-child(8),.initialization-wbs-table td:nth-child(8) { width:126px; }
.initialization-wbs-table th:nth-child(9),.initialization-wbs-table td:nth-child(9) { width:88px; }
.initialization-wbs-table td:not(.initialization-wbs-name):not(.initialization-wbs-dependencies) { white-space:nowrap; }
.initialization-wbs-table td strong { color:#28564f; font-size:12px; font-variant-numeric:tabular-nums; }
.initialization-wbs-name { padding-left:7px !important; color:#2f514b; overflow-wrap:anywhere; }
.initialization-wbs-tree-node { --wbs-depth:0; position:relative; display:flex; min-height:22px; align-items:flex-start; gap:7px; padding-left:calc(var(--wbs-depth) * 18px); }
.initialization-wbs-tree-node:not(.root)::before { content:""; position:absolute; top:-11px; bottom:-11px; left:calc((var(--wbs-depth) * 18px) - 9px); border-left:1px solid #cbded9; }
.initialization-wbs-tree-node:not(.root)::after { content:""; position:absolute; top:11px; left:calc((var(--wbs-depth) * 18px) - 9px); width:10px; border-top:1px solid #cbded9; }
.initialization-wbs-node-toggle { position:relative; z-index:1; display:grid; flex:0 0 20px; width:20px; height:20px; place-items:center; border:1px solid #c7ddd7; border-radius:4px; padding:0; color:#39776e; background:#edf6f3; cursor:pointer; transition:color .16s ease,background .16s ease,transform .16s ease; }
.initialization-wbs-node-toggle:hover { color:#174f47; background:#dfeeea; }
.initialization-wbs-node-toggle:focus-visible { outline:2px solid rgba(15,118,110,.24); outline-offset:1px; }
.initialization-wbs-node-toggle .n-icon { transition:transform .18s ease; }
.initialization-wbs-node-toggle.collapsed .n-icon { transform:rotate(-90deg); }
.initialization-wbs-leaf { position:relative; z-index:1; flex:0 0 20px; width:20px; height:20px; }
.initialization-wbs-leaf::after { content:""; position:absolute; top:8px; left:7px; width:5px; height:5px; border-radius:1px; background:#91afa8; }
.initialization-wbs-node-copy { display:flex; min-width:0; flex-wrap:wrap; align-items:baseline; gap:6px; padding-top:1px; }
.initialization-wbs-node-copy > strong { color:#2f514b !important; font-weight:700; overflow-wrap:anywhere; }
.initialization-wbs-node-copy > small { border-radius:3px; padding:1px 4px; color:#6c827e; background:#eef3f2; font-size:12px; font-weight:650; white-space:nowrap; }
.initialization-wbs-node-copy > em { border-radius:3px; padding:1px 5px; color:#a53f2c; background:#ffdfd5; font-size:12px; font-style:normal; font-weight:800; white-space:nowrap; }
.initialization-wbs-dependencies { display:flex; flex-wrap:wrap; gap:4px; white-space:normal; }
.initialization-wbs-dependencies span { border-radius:3px; padding:2px 5px; color:#456b64; background:#eaf3f1; font-size:12px; font-variant-numeric:tabular-nums; font-weight:750; }
.initialization-wbs-dependencies em { border-radius:3px; padding:2px 5px; color:#8b5a24; background:#fff0cf; font-size:12px; font-style:normal; font-weight:750; white-space:nowrap; }
.initialization-risk-list { display:grid; gap:10px; border-top:1px solid #e5eeec; padding:12px; background:#f8fbfa; }
.initialization-risk-card { overflow:hidden; border:1px solid #d9e7e3; border-left:3px solid #6d9f96; border-radius:7px; background:#fff; }
.initialization-risk-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding:12px 14px 11px; border-bottom:1px solid #e7efed; background:#fcfdfd; }
.initialization-risk-head > div { min-width:0; }
.initialization-risk-head span { display:block; margin-bottom:3px; color:#7c8f8b; font-size:12px; font-variant-numeric:tabular-nums; font-weight:700; }
.initialization-risk-head h4 { margin:0; color:#294f49; font-size:14px; line-height:1.45; overflow-wrap:anywhere; text-wrap:pretty; }
.initialization-risk-head > strong { flex:0 0 auto; border-radius:4px; padding:4px 8px; color:#935125; background:#fff0df; font-size:12px; font-weight:800; white-space:nowrap; }
.initialization-risk-facts { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(220px,.55fr); gap:1px; margin:0; border-bottom:1px solid #e7efed; background:#e7efed; }
.initialization-risk-facts > div { display:grid; min-width:0; grid-template-columns:78px minmax(0,1fr); align-items:baseline; gap:10px; padding:10px 14px; background:#f7faf9; }
.initialization-risk-facts dt,.initialization-risk-facts dd { margin:0; font-size:12px; line-height:1.55; }
.initialization-risk-facts dt { color:#718681; font-weight:700; }
.initialization-risk-facts dd { display:flex; min-width:0; flex-wrap:wrap; align-items:baseline; gap:7px; color:#31544e; font-weight:700; overflow-wrap:anywhere; }
.initialization-risk-facts code { border-radius:3px; padding:2px 5px; color:#35685f; background:#e5f1ee; font:700 12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; font-variant-numeric:tabular-nums; white-space:nowrap; }
.initialization-risk-window { color:#45645e !important; font-variant-numeric:tabular-nums; white-space:nowrap; }
.initialization-risk-window > span { color:#91a09d; font-weight:600; }
.initialization-risk-details { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; padding:12px 14px 14px; }
.initialization-risk-details section { min-width:0; }
.initialization-risk-details section + section { border-left:1px solid #e4ecea; padding-left:12px; }
.initialization-risk-details h5 { margin:0 0 5px; color:#667d78; font-size:12px; font-weight:800; }
.initialization-risk-details p { margin:0; color:#355650; font-size:12px; line-height:1.7; overflow-wrap:anywhere; text-wrap:pretty; }
.initialization-quality-table-wrap { overflow-x:auto; border-top:1px solid #e5eeec; background:#fff; }
.initialization-quality-table { width:100%; min-width:1160px; border-spacing:0; border-collapse:separate; table-layout:fixed; color:#45615b; font-size:12px; }
.initialization-quality-table th { padding:10px 12px; border-right:1px solid #e1ebe8; border-bottom:1px solid #d9e6e3; color:#58736d; background:#f1f7f5; font-size:12px; font-weight:800; line-height:1.45; text-align:left; }
.initialization-quality-table th:last-child,.initialization-quality-table td:last-child { border-right:0; }
.initialization-quality-table td { padding:11px 12px; border-right:1px solid #edf2f0; border-bottom:1px solid #edf2f0; font-size:12px; line-height:1.6; vertical-align:top; overflow-wrap:anywhere; text-wrap:pretty; }
.initialization-quality-table tbody tr:last-child td { border-bottom:0; }
.initialization-quality-table tbody tr { transition:background .16s ease; }
.initialization-quality-table tbody tr:hover { background:#f5faf8; }
.initialization-quality-table th:nth-child(1),.initialization-quality-table td:nth-child(1) { width:96px; }
.initialization-quality-table th:nth-child(2),.initialization-quality-table td:nth-child(2) { width:280px; }
.initialization-quality-table th:nth-child(3),.initialization-quality-table td:nth-child(3) { width:300px; }
.initialization-quality-table th:nth-child(4),.initialization-quality-table td:nth-child(4) { width:190px; }
.initialization-quality-table th:nth-child(5),.initialization-quality-table td:nth-child(5) { width:294px; }
.initialization-quality-table code { display:inline-flex; border-radius:4px; padding:3px 6px; color:#2f675e; background:#e6f1ee; font:750 12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; font-variant-numeric:tabular-nums; white-space:nowrap; }
.initialization-quality-table strong { color:#294f48; font-size:12px; font-weight:750; }
.draft-issues { gap:14px; padding:16px; background:#fbfcfc; }
.draft-issues > .draft-issues-heading { align-items:flex-start; }
.draft-issues-heading > div { min-width:0; }
.draft-issues-heading h3 { font-size:15px; line-height:1.4; }
.draft-issues-heading p { margin:4px 0 0; color:#6d817d; font-size:12px; line-height:1.55; }
.draft-issues-heading > span { flex:0 0 auto; border-radius:999px; padding:4px 9px; color:#5f7873 !important; background:#edf4f2; font-size:12px !important; font-weight:750; font-variant-numeric:tabular-nums; }
.draft-issues-summary { display:flex; flex-wrap:wrap; gap:8px; }
.draft-issues-summary span { display:inline-flex; align-items:baseline; gap:4px; border:1px solid transparent; border-radius:6px; padding:7px 10px; font-size:12px; font-weight:700; line-height:1.35; }
.draft-issues-summary span strong { font-size:15px; font-variant-numeric:tabular-nums; }
.draft-issues-summary .error { border-color:#efd7d0; color:#98442f; background:#fff5f2; }
.draft-issues-summary .warning { border-color:#eadfc8; color:#8b641f; background:#fffaf0; }
.draft-issue-groups { display:grid; gap:9px; }
.draft-issue-group { overflow:hidden; border:1px solid #dfe8e6; border-radius:8px; background:#fff; }
.draft-issue-group.error { border-left:3px solid #c96952; }
.draft-issue-group.warning { border-left:3px solid #d2a24b; }
.draft-issue-group-toggle { display:grid; width:100%; grid-template-columns:auto minmax(0,1fr) auto auto; align-items:center; gap:10px; border:0; padding:11px 12px; color:#294d47; background:#fff; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease; }
.draft-issue-group-toggle:hover { background:#f7faf9; }
.draft-issue-group-toggle:focus-visible { outline:2px solid rgba(15,118,110,.22); outline-offset:-2px; }
.draft-issue-group-icon { display:grid; width:30px; height:30px; place-items:center; border-radius:7px; color:#9a6c22; background:#fff5df; }
.draft-issue-group.error .draft-issue-group-icon { color:#a94e39; background:#fcece7; }
.draft-issue-group-copy { display:grid; min-width:0; gap:2px; }
.draft-issue-group-copy strong { color:#294d47; font-size:13px; font-weight:800; line-height:1.4; }
.draft-issue-group-copy small { color:#70837f; font-size:12px; line-height:1.45; }
.draft-issue-group-count { min-width:44px; color:#69807b !important; font-size:12px !important; font-weight:750; text-align:right; white-space:nowrap; }
.draft-issue-group-chevron { color:#738984; transition:transform .16s ease; }
.draft-issue-group-toggle[aria-expanded="true"] .draft-issue-group-chevron { transform:rotate(180deg); }
.draft-issue-group ul { display:grid; gap:0; margin:0; padding:0 12px 12px 52px; list-style:none; }
.draft-issue-group li { display:grid; gap:7px; border-top:1px solid #e8efed; padding:12px 0; font-size:12px; line-height:1.55; }
.draft-issue-group li:first-child { border-top-color:#dfe9e6; }
.draft-issue-group li > header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.draft-issue-group li > header > div { display:flex; min-width:0; flex-wrap:wrap; align-items:center; gap:7px; }
.draft-issue-group li > header strong { color:#31534d; font-size:13px; font-weight:800; line-height:1.45; }
.draft-issue-group li > header span { display:inline-flex; border-radius:4px; padding:2px 6px; color:#446b64; background:#eaf3f1; font:750 12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:nowrap; }
.draft-issue-group li > header em { flex:0 0 auto; border-radius:999px; padding:3px 7px; color:#93691f; background:#fff4dd; font-size:12px; font-style:normal; font-weight:750; line-height:1.35; white-space:nowrap; }
.draft-issue-group li.error > header em { color:#a24732; background:#fcebe6; }
.draft-issue-group li > p { margin:0; color:#516a65; font-size:12px; line-height:1.65; text-wrap:pretty; }
.draft-issue-guidance { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:start; gap:8px; border-radius:6px; padding:8px 10px; color:#58716c; background:#f4f8f7; font-size:12px; line-height:1.55; }
.draft-issue-guidance strong { color:#2f6259; font-size:12px; font-weight:800; white-space:nowrap; }
.draft-issue-guidance span { color:#58716c; font-size:12px; }
.initialization-partial-confirm { display:flex; align-items:flex-start; gap:7px; border-top:1px solid #e7eeec; padding-top:12px; color:#6f5d4d; font-size:12px; line-height:1.5; }.initialization-partial-confirm input { margin-top:2px; }
.initialization-review-actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:13px 20px; border-top:1px solid var(--border-default); background:#fff; }.initialization-review-actions > span { flex:1 1 auto; color:#738682; font-size:12px; line-height:1.5; }.initialization-review-actions .primary:disabled { opacity:.5; cursor:not-allowed; }
.project-navigator { display:grid; grid-template-rows:auto minmax(0,1fr); }.project-navigator-list { min-height:0; overflow-y:auto; }
.manual-config-workspace { display:grid; min-height:0; grid-template-columns:176px minmax(0,1fr); margin-top:8px; border:1px solid var(--border-default); border-radius:10px; overflow:hidden; background:#fff; }
.manual-config-tree { display:grid; align-content:start; min-width:0; padding:10px; border-right:1px solid var(--border-default); background:#fbfcfc; overflow-y:auto; }
.manual-config-tree-head { display:grid; gap:2px; padding:7px 8px 11px; color:#284b46; }
.manual-config-tree-head span { font-size:12px; font-weight:850; }
.manual-config-tree-head small { color:var(--text-muted); font-size: 12px; }
.manual-config-tree button { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; width:100%; border:0; border-radius:6px; padding:9px 8px; color:#4d6864; background:transparent; font:inherit; text-align:left; cursor:pointer; transition:background .16s ease,color .16s ease; }
.manual-config-tree button:hover { background:#f0f7f5; color:#22594f; }.manual-config-tree button.active { color:#17564d; background:#e3f2ee; }.manual-config-tree button strong { overflow:hidden; font-size:12px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }.manual-config-tree button em { min-width:18px; color:#78908b; font-size: 12px; font-style:normal; font-variant-numeric:tabular-nums; text-align:right; }.manual-config-tree button.active em { color:#2c7d70; }
.manual-config-list { display:grid; min-width:0; min-height:0; grid-template-rows:auto minmax(0,1fr); }.manual-list-head { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:17px 19px 15px; border-bottom:1px solid var(--border-default); }.manual-list-head>div:first-child { min-width:0; }.manual-list-head span { display:block; margin-bottom:4px; color:#0f766e; font-size: 12px; font-weight:850; letter-spacing:.05em; }.manual-list-head h2 { margin:0; color:#1a3935; font-size:17px; line-height:1.35; }.manual-list-head p { max-width:62ch; margin:4px 0 0; color:var(--text-muted); font-size:12px; line-height:1.55; }.manual-list-actions { display:flex; flex:0 0 auto; align-items:center; gap:8px; }.manual-search { display:flex; align-items:center; width:228px; gap:7px; border:1px solid var(--border-emphasis); border-radius:6px; padding:0 9px; color:#718782; background:#fff; }.manual-search input { min-width:0; width:100%; border:0; outline:0; padding:8px 0; color:var(--text-primary); background:transparent; font:inherit; font-size:12px; }.manual-list-actions .primary { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }.manual-table-wrap { min-height:0; overflow:auto; background:#fff; }.manual-table { width:100%; min-width:720px; border-collapse:collapse; color:#3f5d58; font-size:12px; }.manual-table th { position:sticky; top:0; z-index:1; padding:11px 15px; border-bottom:1px solid var(--border-default); color:#647d78; background:#f7faf9; font-size: 12px; font-weight:800; text-align:left; white-space:nowrap; }.manual-table td { padding:13px 15px; border-bottom:1px solid var(--border-subtle); vertical-align:middle; line-height:1.45; }.manual-table tbody tr { transition:background .14s ease; }.manual-table tbody tr:hover { background:#f8fbfa; }.manual-table strong { color:#294842; font-weight:750; }.manual-table small { display:block; max-width:42ch; margin-top:3px; overflow:hidden; color:var(--text-muted); font-size: 12px; text-overflow:ellipsis; white-space:nowrap; }.row-action { border:0; padding:4px 0; color:#197163; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; white-space:nowrap; }.row-action:hover { color:#0e5b50; text-decoration:underline; }.status-dot { display:inline-block; width:7px; height:7px; margin-right:6px; border-radius:50%; background:#abb9b6; }.status-dot.in_progress { background:#129f88; }.status-dot.done { background:#2278a5; }.status-dot.delayed { background:#d76835; }.risk-level { display:inline-flex; align-items:center; border-radius:4px; padding:2px 6px; font-size: 12px; white-space:nowrap; }.risk-level.critical { color:#9c351d; background:#fcebe5; }.risk-level.high { color:#a85d1c; background:#fff1dc; }.risk-level.medium { color:#3e716b; background:#e8f4f0; }.risk-level.low { color:#617f79; background:#eff5f3; }.manual-empty { display:grid; min-height:260px; place-content:center; justify-items:center; gap:8px; padding:24px; color:#78908b; text-align:center; }.manual-empty strong { color:#3a5a55; font-size:14px; }.manual-empty p { margin:0; color:var(--text-muted); font-size:12px; }.manual-editor-modal { width:min(100%,680px); }.manual-editor-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 16px; }.manual-editor-form label { display:grid; gap:6px; color:#4e6964; font-size:12px; font-weight:750; }.manual-editor-form input,.manual-editor-form select,.manual-editor-form textarea { min-width:0; border:1px solid var(--border-emphasis); border-radius:6px; padding:9px 10px; color:var(--text-primary); background:#fff; font:inherit; font-size:13px; }.manual-editor-form textarea { resize:vertical; }.manual-editor-form .full-span { grid-column:1 / -1; }.manual-editor-form .check-label { align-self:end; padding-bottom:0; font-weight:650; }.manual-rule-editor { display:grid; gap:10px; padding:12px; border:1px solid #e0ebe8; border-radius:8px; background:#f8fbfa; }.manual-rule-editor>div { display:flex; align-items:center; justify-content:space-between; gap:10px; }.manual-rule-editor strong,.manual-rule-editor small { display:block; }.manual-rule-editor strong { color:#31544f; font-size:12px; }.manual-rule-editor small { margin-top:3px; color:var(--text-muted); font-size: 12px; }.manual-rule-editor>div+div { justify-content:flex-start; }.manual-rule-editor select,.manual-rule-editor input { min-width:0; flex:1 1 0; padding:7px 8px; font-size:12px; }.manual-rule-editor .secondary-action { padding:7px 9px; }.manual-rule-editor ul { display:flex; flex-wrap:wrap; gap:7px; margin:0; padding:0; list-style:none; }.manual-rule-editor li { padding:4px 7px; border-radius:4px; color:#57746e; background:#eaf3f0; font-size: 12px; }.manual-editor-actions { display:flex; grid-column:1 / -1; justify-content:flex-end; gap:8px; padding-top:4px; }.manual-config-workspace button:focus-visible,.manual-table button:focus-visible,.manual-editor-form input:focus,.manual-editor-form select:focus,.manual-editor-form textarea:focus,.manual-search:focus-within { outline:2px solid rgba(15,118,110,.22); outline-offset:1px; }
.manual-member-table { min-width:980px; }.manual-member-table th:nth-child(1) { width:170px; }.manual-member-table th:nth-child(2) { width:190px; }.manual-member-table th:nth-child(3) { width:260px; }.manual-member-table th:last-child { width:78px; }.manual-position-cell { display:grid; gap:7px; }.manual-position-item { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:8px 10px; border:1px solid #e2ece9; border-radius:7px; background:#f7faf9; }.manual-position-item span { min-width:0; }.manual-position-item strong,.manual-position-item small { display:block; }.manual-responsibility { display:block; max-width:42ch; margin-bottom:7px; color:#58716c; font-size:12px; }.manual-responsibility:last-child { margin-bottom:0; }.manual-responsibility strong { margin-right:5px; }.manual-password-field { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:6px; }.manual-password-field button { border:1px solid var(--border-emphasis); border-radius:6px; padding:0 10px; color:#176f62; background:#f4faf8; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.manual-member-account-note { margin:0; border-left:3px solid #73b5aa; padding:9px 11px; color:#58736e; background:#f1f8f6; font-size:12px; line-height:1.65; }
.manual-data-loading { display:grid; min-height:360px; place-content:center; justify-items:center; gap:9px; }
.manual-data-loading i { width:30px; height:30px; border:3px solid #dce9e6; border-top-color:#218574; border-radius:50%; animation:setup-spin .8s linear infinite; }
.manual-data-loading span { width:180px; height:9px; border-radius:999px; background:#edf3f1; }
.manual-data-loading span:nth-child(3) { width:140px; }
.record-editor-modal { display:grid; width:min(100%,1080px); max-height:calc(100dvh - 48px); grid-template-rows:auto minmax(0,1fr); overflow:hidden; padding:0; }
.record-editor-modal > .setup-modal-head { margin:0; padding:17px 20px 15px; border-bottom:1px solid #dce7e4; background:#fff; }
.record-editor-modal > .setup-modal-head > div { align-items:baseline; }
.record-editor-modal > .setup-modal-head p { color:#6d827d; }
.record-editor-form { min-height:0; overflow-y:auto; padding:18px 20px 0; background:#f8fbfa; }
.record-editor-fieldset { min-width:0; margin:0; border:1px solid #dbe7e4; border-radius:9px; padding:0 15px 16px; background:#fff; }
.record-editor-fieldset legend { padding:0 8px; color:#315c55; font-size:13px; font-weight:800; }
.record-editor-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:13px 15px; padding-top:6px; }
.record-editor-grid label { align-content:start; }
.record-editor-grid label > small { color:#718681; font-size:12px; font-weight:500; line-height:1.55; }
.record-editor-grid select[size] { min-height:156px; padding:5px; line-height:1.5; }
.record-editor-grid select[size] option { padding:5px 7px; }
.record-editor-span-2 { grid-column:span 2; }
.record-editor-span-3 { grid-column:1 / -1; }
.wbs-source-fieldset dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; overflow:hidden; margin:6px 0 0; border:1px solid #e2ebe9; border-radius:7px; background:#e2ebe9; }
.wbs-source-fieldset dl > div { min-width:0; padding:10px 12px; background:#f9fbfa; }
.wbs-source-fieldset dt,.wbs-source-fieldset dd { margin:0; font-size:12px; line-height:1.55; }
.wbs-source-fieldset dt { margin-bottom:3px; color:#71847f; font-weight:700; }
.wbs-source-fieldset dd { color:#355650; overflow-wrap:anywhere; }
.wbs-source-fieldset .wbs-source-path { grid-column:1 / -1; }
.record-editor-form .manual-editor-actions { position:sticky; bottom:0; z-index:2; margin:0 -20px; border-top:1px solid #dce7e4; padding:13px 20px 16px; background:rgba(255,255,255,.96); backdrop-filter:blur(8px); }
.wbs-dependency-field { display:grid; gap:6px; color:#4e6964; font-size:12px; font-weight:750; }
.wbs-dependency-picker { overflow:hidden; border:1px solid #d6e2df; border-radius:7px; background:#fbfdfc; }
.wbs-dependency-search { display:flex !important; min-height:40px; grid-template-columns:auto minmax(0,1fr); align-items:center !important; gap:7px !important; border-bottom:1px solid #e0e9e7; padding:0 10px; color:#718681 !important; background:#fff; }
.wbs-dependency-search input { border:0 !important; padding:8px 0 !important; outline:0 !important; box-shadow:none !important; }
.wbs-dependency-selected { display:flex; flex-wrap:wrap; gap:6px; border-bottom:1px solid #e5ecea; padding:8px 10px; }
.wbs-dependency-selected button { display:inline-flex; align-items:center; max-width:100%; gap:5px; border:1px solid #cfe0dc; border-radius:5px; padding:4px 6px; color:#41645e; background:#edf5f3; font:inherit; font-size:12px; cursor:pointer; transition:background .16s ease,border-color .16s ease; }
.wbs-dependency-selected button:hover { border-color:#9fc6bd; background:#e3f0ed; }
.wbs-dependency-selected strong { color:#24685d; font-size:12px; font-variant-numeric:tabular-nums; }
.wbs-dependency-selected span { overflow:hidden; max-width:25ch; text-overflow:ellipsis; white-space:nowrap; }
.wbs-dependency-picker > p,.wbs-dependency-options > p { margin:0; padding:9px 10px; color:#7b8f8a; font-size:12px; font-weight:500; }
.wbs-dependency-options { display:grid; max-height:210px; overflow-y:auto; padding:5px; }
.wbs-dependency-options label { display:grid; min-height:34px; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:8px; border-radius:5px; padding:5px 7px; color:#49665f; font-weight:600; cursor:pointer; }
.wbs-dependency-options label:hover { background:#eef5f3; }
.wbs-dependency-options input { width:15px; height:15px; margin:0; padding:0; }
.wbs-dependency-options span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wbs-dependency-options strong { margin-right:8px; color:#256a5f; font-size:12px; font-variant-numeric:tabular-nums; }
.manual-data-loading span:nth-child(4) { width:100px; }
.manual-data-panel { display:grid; min-width:0; align-content:start; background:#f7faf9; }
.personnel-card-list { display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr)); grid-auto-rows:1fr; align-items:stretch; gap:14px; padding:14px; }
.personnel-card { display:grid; height:100%; min-height:216px; grid-template-rows:auto minmax(0,1fr) auto; overflow:hidden; border:1px solid #d7e4e0; border-radius:10px; background:#fff; box-shadow:0 4px 14px rgba(40,80,72,.06); transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease; }
.personnel-card:hover { border-color:#b8d0ca; box-shadow:0 8px 22px rgba(40,80,72,.10); transform:translateY(-1px); }
.personnel-profile { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:11px; padding:13px 15px; border-bottom:1px solid #e6eeec; background:#fbfdfc; }
.personnel-avatar { display:grid; width:38px; height:38px; place-items:center; border-radius:9px; color:#fff; background:#397f73; font-size:15px; font-weight:850; }
.personnel-profile h3,.personnel-profile p { margin:0; }
.personnel-profile h3 { color:#244b44; font-size:15px; line-height:1.4; }
.personnel-profile p { margin-top:2px; color:#778a86; font-size:12px; font-variant-numeric:tabular-nums; }
.personnel-profile > em { border-radius:4px; padding:4px 7px; color:#4d716a; background:#e9f2f0; font-size:12px; font-style:normal; font-weight:750; white-space:nowrap; }
.personnel-card-content { display:grid; min-height:0; align-content:start; gap:9px; padding:14px 15px 16px; background:#fff; }
.personnel-card-content > span { color:#738783; font-size:12px; font-weight:750; }
.personnel-card-content > p { margin:0; color:#7d8f8b; font-size:12px; line-height:1.6; }
.personnel-card-content > small { color:#8b9b97; font-size:12px; line-height:1.5; }
.personnel-position-tags { display:flex; flex-wrap:wrap; align-content:flex-start; gap:7px; }
.personnel-position-tags button { border:1px solid #c8ddd7; border-radius:5px; padding:5px 8px; color:#28685e; background:#edf6f3; font:inherit; font-size:12px; font-weight:750; line-height:1.35; cursor:pointer; transition:border-color .16s ease,background .16s ease,color .16s ease,transform .16s ease; }
.personnel-position-tags button:hover { border-color:#8db9af; color:#15594e; background:#e0f0ec; transform:translateY(-1px); }
.personnel-position-tags button:active { transform:translateY(0); }
.personnel-card > footer { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:9px 15px; border-top:1px solid #e7eeec; color:#80918d; background:#fbfdfc; font-size:12px; }
.personnel-detail-link { border:0; padding:4px 0; color:#536f69; background:transparent; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }
.personnel-detail-link:hover { color:#176f62; text-decoration:underline; }
.personnel-detail-modal { width:min(100%,760px); padding:0; }
.personnel-detail-modal > .setup-modal-head { padding:18px 20px 15px; }
.personnel-detail-list { display:grid; max-height:min(58dvh,560px); gap:10px; overflow-y:auto; padding:15px 20px 18px; background:#f7faf9; }
.personnel-detail-list > article { overflow:hidden; border:1px solid #dbe7e4; border-radius:8px; background:#fff; transition:border-color .16s ease,box-shadow .16s ease; }
.personnel-detail-list > article.selected { border-color:#8fbeb4; box-shadow:0 0 0 2px rgba(31,128,111,.08); }
.personnel-detail-list article > header { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:start; gap:10px; padding:12px 14px; border-bottom:1px solid #e7eeec; background:#fbfdfc; }
.personnel-detail-list article > header > span { display:grid; width:29px; height:29px; place-items:center; border-radius:6px; color:#39756c; background:#e8f3f0; font-size:12px; font-weight:800; font-variant-numeric:tabular-nums; }
.personnel-detail-list h3,.personnel-detail-list p { margin:0; }
.personnel-detail-list h3 { color:#315750; font-size:14px; line-height:1.4; }
.personnel-detail-list header p { margin-top:2px; color:#7d8f8b; font-size:12px; line-height:1.5; }
.personnel-detail-list article > div { padding:12px 14px 14px; }
.personnel-detail-list article > div strong { display:block; margin-bottom:5px; color:#738783; font-size:12px; }
.personnel-detail-list article > div p { color:#46635d; font-size:12px; line-height:1.75; text-wrap:pretty; }
.personnel-detail-empty { padding:40px 20px; color:#7d8f8b; background:#fff; font-size:12px; text-align:center; }
.personnel-detail-actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:12px 20px; border-top:1px solid #dfe8e6; background:#fff; }
.personnel-detail-actions > span { margin-right:auto; color:#7b8e89; font-size:12px; }
.personnel-detail-actions .primary { display:inline-flex; align-items:center; gap:5px; }
.wbs-browser-toolbar { position:sticky; top:0; left:0; z-index:3; box-sizing:border-box; display:flex; height:48px; align-items:center; justify-content:space-between; gap:14px; padding:10px 14px; border-bottom:1px solid #d7e4e0; color:#687e79; background:#f5f9f8; box-shadow:0 3px 8px rgba(39,76,69,.06); font-size:12px; }
.wbs-browser-toolbar > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wbs-browser-toolbar > div { display:flex; gap:7px; margin-left:auto; }
.wbs-browser-toolbar button { border:1px solid #cdded9; border-radius:5px; padding:5px 8px; color:#356a61; background:#fff; font:inherit; font-size:12px; font-weight:700; line-height:1.35; cursor:pointer; }
.wbs-browser-toolbar button:hover { border-color:#9fc2ba; background:#edf6f3; }
.wbs-tree-table-wrap { overflow:visible; background:#fff; }
.wbs-tree-table { min-width:1160px; table-layout:fixed; }
.wbs-tree-table th { top:48px; z-index:2; }
.wbs-tree-table th:nth-child(1) { width:300px; }
.wbs-tree-table th:nth-child(2) { width:145px; }
.wbs-tree-table th:nth-child(3) { width:145px; }
.wbs-tree-table th:nth-child(4) { width:145px; }
.wbs-tree-table th:nth-child(5) { width:130px; }
.wbs-tree-table th:nth-child(6) { width:120px; }
.wbs-tree-table th:nth-child(7) { width:90px; }
.wbs-tree-table td { padding:10px 12px; }
.wbs-tree-table .wbs-group-row { background:#fbfdfc; }
.wbs-tree-node { --wbs-depth:0; position:relative; display:grid; grid-template-columns:22px minmax(0,1fr); align-items:start; gap:6px; padding-left:calc(var(--wbs-depth) * 17px); }
.wbs-tree-node::before { content:""; position:absolute; top:-11px; bottom:-11px; left:calc((var(--wbs-depth) * 17px) + 10px); border-left:1px solid #d6e3df; }
.wbs-tree-node.root::before { display:none; }
.wbs-tree-node > i { width:22px; height:22px; }
.wbs-tree-node > i::after { content:""; display:block; width:6px; height:6px; margin:8px; border-radius:2px; background:#9ab1ac; }
.wbs-tree-toggle { display:grid; width:22px; height:22px; place-items:center; border:1px solid #c9dcd7; border-radius:5px; padding:0; color:#347268; background:#edf6f3; cursor:pointer; }
.wbs-tree-toggle .n-icon { transition:transform .16s ease; }
.wbs-tree-toggle.collapsed .n-icon { transform:rotate(-90deg); }
.wbs-tree-node > span { min-width:0; }
.wbs-tree-node em,.wbs-tree-node strong,.wbs-tree-node small { display:block; }
.wbs-tree-node em { margin-bottom:2px; color:#237468; font:800 12px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace; font-variant-numeric:tabular-nums; }
.wbs-tree-node strong { overflow:hidden; color:#2b4e48; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.wbs-tree-node small { margin-top:2px; color:#82938f; font-size:12px; }
.wbs-progress { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:8px; }
.wbs-progress > div { overflow:hidden; height:7px; border-radius:999px; background:#e5edeb; }
.wbs-progress > div i { display:block; height:100%; border-radius:inherit; background:#2c8b7a; }
.wbs-progress span { min-width:38px; color:#41645e; font-size:12px; font-weight:750; font-variant-numeric:tabular-nums; text-align:right; }
.wbs-status-chip { display:inline-flex; align-items:center; gap:6px; max-width:110px; overflow:hidden; border-radius:999px; padding:3px 7px; color:#607772; background:#edf2f1; font-size:12px; font-weight:750; text-overflow:ellipsis; white-space:nowrap; }
.wbs-status-chip i { flex:0 0 6px; width:6px; height:6px; border-radius:50%; background:#9aaca8; }
.wbs-status-chip.in_progress { color:#226c61; background:#e4f2ef; }.wbs-status-chip.in_progress i { background:#218b79; }
.wbs-status-chip.done { color:#376c82; background:#e6f1f5; }.wbs-status-chip.done i { background:#387f9c; }
.wbs-status-chip.delayed { color:#9a4c2f; background:#fbece6; }.wbs-status-chip.delayed i { background:#ce6742; }
.wbs-predecessors { display:flex; flex-wrap:wrap; gap:4px; }
.wbs-predecessors span { border-radius:4px; padding:2px 5px; color:#416c64; background:#e9f2f0; font:750 12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; }
.manual-muted { color:#91a09d; font-size:12px; }
.quality-data-table-wrap { overflow:visible; background:#fff; }
.quality-data-table { min-width:1260px; table-layout:fixed; }
.quality-data-table th:nth-child(1) { width:190px; }.quality-data-table th:nth-child(2) { width:220px; }.quality-data-table th:nth-child(3) { width:280px; }.quality-data-table th:nth-child(4) { width:150px; }.quality-data-table th:nth-child(5) { width:290px; }.quality-data-table th:nth-child(6) { width:90px; }
.quality-data-table td { vertical-align:top; line-height:1.65; overflow-wrap:anywhere; text-wrap:pretty; }
.quality-data-table td:first-child code,.quality-data-table td:first-child strong { display:block; }
.quality-data-table td:first-child code { width:max-content; max-width:100%; margin-bottom:5px; border-radius:4px; padding:2px 5px; color:#276f64; background:#e7f2ef; font:800 12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:nowrap; }
.quality-data-table td:first-child strong { font-size:12px; line-height:1.5; }
.risk-card-list { display:grid; gap:11px; padding:14px; }
.risk-record-card { overflow:hidden; border:1px solid #dce6e3; border-left:3px solid #6f9c94; border-radius:8px; background:#fff; }
.risk-record-card > header { display:grid; grid-template-columns:auto minmax(0,1fr) auto auto; align-items:start; gap:11px; padding:12px 14px; border-bottom:1px solid #e6eeec; background:#fbfdfc; }
.risk-serial { display:grid; min-width:37px; height:28px; place-items:center; border-radius:6px; color:#376e65; background:#e7f1ef; font-size:12px; font-weight:850; font-variant-numeric:tabular-nums; }
.risk-record-card h3,.risk-record-card p { margin:0; }
.risk-record-card h3 { color:#2f514b; font-size:14px; line-height:1.45; }
.risk-record-card header p { margin-top:2px; color:#778b86; font-size:12px; }
.risk-context { display:grid; grid-template-columns:1fr 1fr; gap:1px; border-bottom:1px solid #e8efed; background:#e8efed; }
.risk-context.single { grid-template-columns:1fr; }
.risk-context > span { padding:9px 14px; color:#41625c; background:#f7faf9; font-size:12px; line-height:1.55; }
.risk-context strong { margin-right:9px; color:#748783; font-size:12px; }
.risk-record-card dl { display:grid; grid-template-columns:1.2fr 1fr; gap:1px; margin:0; background:#e8efed; }
.risk-record-card dl > div { min-width:0; padding:11px 14px; background:#fff; }
.risk-record-card dt,.risk-record-card dd { margin:0; font-size:12px; line-height:1.7; }
.risk-record-card dt { margin-bottom:4px; color:#758984; font-weight:750; }
.risk-record-card dd { color:#3d5d57; overflow-wrap:anywhere; text-wrap:pretty; }
@media (max-width:760px) {
  .personnel-card-list { grid-template-columns:1fr; padding:10px; }
  .personnel-profile { grid-template-columns:auto minmax(0,1fr); }.personnel-profile > em { grid-column:2; justify-self:start; }
  .personnel-detail-actions { align-items:stretch; flex-wrap:wrap; }.personnel-detail-actions > span { flex-basis:100%; }.personnel-detail-actions button { flex:1 1 auto; }
  .risk-context,.risk-record-card dl { grid-template-columns:1fr; }
  .risk-record-card > header { grid-template-columns:auto minmax(0,1fr) auto; }.risk-record-card > header .row-action { grid-column:2; justify-self:start; }
}
@media (max-width:1100px) {
  .initialization-personnel-card { grid-template-columns:minmax(190px,.65fr) minmax(0,1.35fr); }
  .initialization-personnel-credential,.initialization-personnel-account-ready { grid-column:1 / -1; border-top:1px solid #e5eeec; border-left:0; }
}
@media (max-width:1380px) and (min-width:1001px) { .project-config-scroll > .setup-grid { grid-template-columns:1fr; } }
@media (max-width:1000px) { .setup-page { display:block; height:auto; min-height:100%; overflow:visible; }.setup-workspace { display:block; min-height:0; }.project-navigator { min-height:0; margin-bottom:18px; }.project-config-panel { display:block; min-width:0; overflow:visible; }.project-config-scroll { overflow:visible; padding-right:0; }.project-workspace-tabs { position:static; overflow-x:auto; }.project-workspace-tabs button { flex:0 0 155px; }.project-config-scroll > .material-agent-workspace,.project-connection-workspace { min-height:520px; }.project-connection-grid { grid-template-columns:210px minmax(0,1fr); }.manual-config-workspace { min-height:520px; grid-template-columns:1fr; }.manual-config-tree { grid-template-columns:repeat(3,minmax(150px,1fr)); grid-auto-rows:min-content; border-right:0; border-bottom:1px solid var(--border-default); overflow:auto; }.manual-config-tree-head { grid-column:1 / -1; }.setup-grid { grid-template-columns:1fr; }.config-summary { grid-template-columns:repeat(2,1fr); }.compact-form,.wbs-form,.risk-form { grid-template-columns:1fr 1fr; }.compact-form button { grid-column:span 2; } } @media (max-width:600px) { .setup-page { padding:18px; }.project-context { padding:16px; }.project-context-title h1 { font-size:16px; }.project-context-meta { grid-template-columns:1fr; gap:9px; margin-top:15px; }.project-context-meta div { grid-template-columns:60px minmax(0,1fr); }.project-nav-item { padding:13px 14px; }.material-agent-workspace,.project-connection-workspace { min-height:0; padding:15px; }.material-workspace-head,.project-connection-head { display:grid; gap:12px; }.material-workspace-actions { justify-content:space-between; }.agent-context-summary { grid-template-columns:1fr; }.project-config-scroll > .material-agent-workspace { min-height:500px; padding:14px; }.agent-context-summary article { border-right:0; border-bottom:1px solid #e0ebe8; }.agent-context-summary article:last-child { border-bottom:0; }.material-agent-chat { min-height:340px; }.material-agent-composer { grid-template-columns:1fr; }.project-connection-grid { grid-template-columns:1fr; overflow:visible; }.project-connector-list { grid-template-columns:repeat(3,minmax(0,1fr)); overflow:visible; border-right:0; border-bottom:1px solid var(--border-default); }.project-connector-list button { grid-template-columns:auto minmax(0,1fr); }.project-connector-list button > i { display:none; }.project-connector-editor { overflow:visible; padding:16px; }.project-connector-actions { align-items:stretch; flex-direction:column; }.project-connector-actions .primary { width:100%; }.manual-config-workspace { min-height:500px; }.manual-config-tree { display:flex; gap:3px; padding:7px; overflow-x:auto; }.manual-config-tree-head { display:none; }.manual-config-tree button { flex:0 0 auto; grid-template-columns:auto minmax(0,1fr); width:auto; }.manual-config-tree button em { display:none; }.manual-list-head { display:grid; padding:15px; }.manual-list-actions { width:100%; }.manual-search { width:auto; flex:1 1 auto; }.manual-editor-form { grid-template-columns:1fr; }.manual-editor-form .full-span,.manual-editor-actions { grid-column:auto; }.manual-rule-editor>div { display:grid; }.manual-editor-actions { justify-content:stretch; }.manual-editor-actions button { flex:1 1 auto; }.config-summary { grid-template-columns:1fr 1fr; }.item-list>div { grid-template-columns:1fr; gap:3px; }.panel-head { gap:10px; }.setup-modal-backdrop { padding:12px; }.setup-modal { max-height:calc(100dvh - 24px); padding:16px; border-radius:10px; }.setup-modal-head { gap:12px; }.setup-modal-actions { justify-content:stretch; }.setup-modal-actions button { flex:1 1 auto; } }
@media (max-width:600px) { .setup-modal-head span,.setup-modal-head p { display:none; } }
@media (max-width:1000px) {
  .project-empty-stage,.project-empty-content { min-height:560px; }
  .project-empty-content { box-sizing:border-box; }
}
@media (max-width:600px) {
  .project-empty-stage,.project-empty-content { min-height:520px; }
  .project-empty-content { padding:38px 24px; }
  .project-empty-content h1 { font-size:28px; }
  .project-empty-description { font-size:13px; }
  .project-required-notice { align-items:flex-start; margin-bottom:24px; }
  .project-init-path { grid-template-columns:1fr; gap:0; margin-top:38px; }
  .project-init-path li { padding:14px 0; }
  .project-init-path li+li { padding-left:0; border-top:1px solid #dbe6e2; border-left:0; }
  .project-empty-stage::before { opacity:.6; }
  .initialization-draft-summary { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .initialization-draft-summary span { border-right:0; border-bottom:1px solid #e4efec; }
  .initialization-project-contract-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .initialization-project-units dl { grid-template-columns:1fr; }
  .initialization-personnel-card { grid-template-columns:1fr; }
  .initialization-personnel-profile { border-right:0; border-bottom:1px solid #e5eeec; }
  .initialization-personnel-facts { grid-template-columns:1fr; }
  .initialization-personnel-facts > div.responsibility { grid-column:auto; }
  .initialization-personnel-credential { grid-template-columns:1fr; }
  .initialization-personnel-credential > div { grid-column:auto; }
  .initialization-risk-facts,.initialization-risk-details { grid-template-columns:1fr; }
  .initialization-risk-details section + section { border-top:1px solid #e4ecea; border-left:0; padding-top:12px; padding-left:0; }
  .initialization-project-units dl > div.primary { grid-column:auto; }
  .initialization-review-actions { align-items:stretch; flex-wrap:wrap; }
  .initialization-review-actions > span { flex-basis:100%; }
}
@media (max-width:1000px) {
  .record-editor-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .record-editor-span-3 { grid-column:1 / -1; }
}
@media (max-width:600px) {
  .record-editor-modal { padding:0; }
  .record-editor-modal > .setup-modal-head { padding:15px 16px 13px; }
  .record-editor-form { padding:16px 14px 0; }
  .record-editor-grid { grid-template-columns:1fr; }
  .record-editor-span-2,.record-editor-span-3 { grid-column:auto; }
  .wbs-source-fieldset dl { grid-template-columns:1fr; }
  .wbs-source-fieldset .wbs-source-path { grid-column:auto; }
  .record-editor-form .manual-editor-actions { margin:0 -14px; padding:12px 14px 14px; }
}
</style>
