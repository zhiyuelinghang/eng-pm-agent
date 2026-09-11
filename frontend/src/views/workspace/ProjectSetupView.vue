<template>
  <div class="setup-page">
    <div class="setup-workspace">
      <main v-if="configProjectId" class="project-config-panel">
      <div class="project-config-scroll">
      <nav class="project-workspace-tabs" aria-label="项目资料工作台" role="tablist">
        <button v-for="tab in workspaceTabs" :key="tab.key" type="button" role="tab" :aria-selected="activeWorkspaceTab === tab.key" :class="{ active: activeWorkspaceTab === tab.key }" @click="selectWorkspaceTab(tab.key)"><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <section v-if="activeWorkspaceTab === 'agent'" class="material-agent-workspace">
        <aside class="material-conversation-sidebar" aria-label="配置助手会话">
          <button
            type="button"
            class="material-conversation-new"
            :disabled="materialAgentLoading || materialAgentStopping"
            @click="startNewMaterialAgentConversation"
          >
            <n-icon :size="18"><Plus /></n-icon>
            <span>新会话</span>
          </button>
          <label class="material-conversation-search">
            <n-icon :size="16"><Search /></n-icon>
            <input v-model.trim="materialAgentConversationSearch" type="search" aria-label="搜索配置助手会话" placeholder="搜索会话">
          </label>
          <div class="material-conversation-list" aria-live="polite">
            <div v-if="materialAgentConversationListLoading" class="material-conversation-skeleton" aria-label="正在加载会话">
              <i v-for="index in 4" :key="index"></i>
            </div>
            <template v-else>
              <button
                v-for="conversation in filteredMaterialAgentConversations"
                :key="conversation.id"
                type="button"
                class="material-conversation-item"
                :class="{ active: materialAgentConversationId === conversation.id }"
                :aria-current="materialAgentConversationId === conversation.id ? 'true' : undefined"
                :disabled="materialAgentLoading || materialAgentStopping"
                @click="selectMaterialAgentConversation(conversation.id)"
              >
                <strong :title="conversation.title">{{ conversation.title }}</strong>
                <time>{{ formatMaterialAgentConversationTime(conversation.updated_at || conversation.created_at) }}</time>
              </button>
              <div v-if="!filteredMaterialAgentConversations.length" class="material-conversation-empty">
                <n-icon :size="22"><MessageCircle /></n-icon>
                <strong>{{ materialAgentConversations.length ? '没有匹配的会话' : '还没有会话' }}</strong>
                <p>{{ materialAgentConversations.length ? '换一个关键词试试。' : '发送第一条消息后，会话会保存在这里。' }}</p>
              </div>
            </template>
          </div>
        </aside>
        <div class="material-agent-chat">
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
                <small>项目资料助手</small>
                <strong>从现有资料开始完善项目</strong>
                <p>直接说明已知信息，或添加工程说明、人员表、WBS、风险清单和质量指标文件。整理结果会先交给你核对，确认后再写入项目。</p>
              </div>
            </div>
            <article v-for="item in materialAgentMessages" :key="item.id" :class="['material-agent-message', item.role]">
              <span aria-hidden="true">
                <n-icon v-if="item.role === 'assistant'" :size="16"><Robot /></n-icon>
                <template v-else>我</template>
              </span>
              <div>
                <AgentMessageContent
                  v-if="item.role === 'assistant'"
                  :show-task-plan="false"
                  :content="item.content"
                  :runtime-trace="item.runtimeTrace"
                  :confirmation-busy="materialAgentLoading || materialAgentStopping"
                  @confirm="confirmMaterialAgentToolCall"
                />
                <p v-else>{{ item.content }}</p>
                <ul v-if="item.attachments?.length" class="material-agent-message-files">
                  <li v-for="file in item.attachments" :key="file.id"><n-icon :size="14"><Paperclip /></n-icon>{{ file.name }}<small>{{ formatFileSize(file.size) }}</small></li>
                </ul>
              </div>
            </article>
            <article v-if="materialAgentPreparation" class="material-agent-message assistant material-agent-preparation">
              <span aria-hidden="true"><n-icon :size="16"><Robot /></n-icon></span>
              <div role="status" aria-live="polite">
                <strong>{{ materialAgentPreparationTitle }}</strong>
                <p>{{ materialAgentPreparationDetail }}</p>
                <div v-if="materialAgentPreparation.total" class="material-agent-preparation-progress" aria-hidden="true">
                  <i :style="{ width: `${materialAgentPreparationProgress}%` }"></i>
                </div>
              </div>
            </article>
            <article v-if="materialAgentStreamingTrace" class="material-agent-message assistant">
              <span aria-hidden="true"><n-icon :size="16"><Robot /></n-icon></span>
              <div>
                <AgentMessageContent
                  :runtime-trace="materialAgentStreamingTrace"
                  :show-task-plan="false"
                  :confirmation-busy="materialAgentLoading || materialAgentStopping"
                  streaming
                  @confirm="confirmMaterialAgentToolCall"
                />
              </div>
            </article>
          </div>
          <div v-if="materialAgentError" class="material-agent-error" role="alert"><span>{{ materialAgentError }}</span><button v-if="materialAgentConversationId" type="button" :disabled="materialAgentLoading || materialAgentStopping || materialAgentConversationLoading" @click="resyncMaterialAgentConversation">重新同步会话</button></div>
          <section
            v-if="materialAgentDraftDockVisible && materialAgentDraft"
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
                    <small>资料草稿</small>
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
                  <button type="button" class="initialization-draft-review" :disabled="initializationDraftReviewLoading" :aria-busy="initializationDraftReviewLoading" @click="openInitializationDraftReview">
                    <n-icon v-if="initializationDraftReviewLoading" :size="15" class="project-action-spinner" aria-hidden="true"><Loader /></n-icon>
                    {{ initializationDraftReviewLoading ? '正在加载…' : materialAgentDraft.status === 'applied' ? '查看内容' : '核对草稿' }}
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
                <span v-if="materialAgentDraft.status === 'applied'">本次确认内容已写入项目，可查看提交记录</span>
                <span v-else-if="materialAgentDraft.workflow && materialAgentDraft.workflow.stage !== 'completed'">
                  已完成 {{ materialAgentDraft.workflow.completed_sections.length }}/{{ materialAgentDraft.workflow.expected_sections.length }} 个专项分区
                  <template v-if="materialAgentDraft.workflow.pending_sections.length">，等待：{{ initializationSectionLabels(materialAgentDraft.workflow.pending_sections) }}</template>
                </span>
                <span v-else-if="materialAgentDraft.validation?.status === 'failed'">核验未完成，请重新执行规则核验</span>
                <span v-else-if="materialAgentDraft.status === 'collecting'">专业智能体仍在整理草稿</span>
                <span v-else-if="materialAgentDraft.status === 'reviewing'">平台正在运行规则核验</span>
                <span v-else>{{ materialAgentDraft.validation_issues.length ? initializationDraftIssueSummary : '结构校验已通过，确认前不会写入项目' }}</span>
                <small v-if="materialAgentDraft.validation?.status === 'completed'">
                  核验规则 {{ materialAgentDraft.validation.package_version ? `v${materialAgentDraft.validation.package_version}` : '' }}
                  · {{ formatValidationDuration(materialAgentDraft.validation.duration_ms) }}
                </small>
                <small v-if="initializationDraftSourceNames.length">来源：{{ initializationDraftSourceNames.join('、') }}</small>
                <small v-else>来源：本次问答</small>
              </footer>
            </div>
          </section>
          <form class="material-agent-composer" @submit.prevent="sendMaterialAgentMessage">
            <input ref="materialAgentFileInput" class="visually-hidden" type="file" multiple accept=".xls,.xlsx,.csv,.docx,.pptx,.pdf,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp,.tif,.tiff" @change="selectMaterialAgentFiles">
            <ChatComposerSurface :busy="materialAgentWorking || materialAgentStopping" contained>
              <template v-if="materialAgentFiles.length" #attachments>
                <div class="material-agent-file-head">
                  <span>已选择 {{ materialAgentFiles.length }} 个附件</span>
                  <button type="button" @click="clearMaterialAgentFiles">清空</button>
                </div>
                <ul class="chat-composer-files">
                  <li v-for="(file, index) in materialAgentFiles" :key="`${file.name}-${file.size}-${file.lastModified}`" class="chat-composer-file">
                    <n-icon :size="17"><Paperclip /></n-icon>
                    <strong :title="file.name">{{ file.name }}</strong>
                    <small>{{ formatFileSize(file.size) }}</small>
                    <button type="button" class="chat-composer-file-remove" :aria-label="`移除附件 ${file.name}`" @click="removeMaterialAgentFile(index)"><n-icon :size="15"><X /></n-icon></button>
                  </li>
                </ul>
              </template>

              <textarea
                v-model="materialAgentPrompt"
                class="chat-composer-input"
                rows="1"
                :disabled="materialAgentWorking"
                placeholder="描述需要补充的工程信息，或添加附件"
                @keydown.enter.exact.prevent="sendMaterialAgentMessage"
              ></textarea>

              <template #tools>
                <button type="button" class="chat-composer-tool" :disabled="materialAgentWorking" @click="openMaterialAgentFilePicker">
                  <n-icon :size="17"><Paperclip /></n-icon>
                  <span>附件</span>
                </button>
              </template>

              <template #action>
                <button v-if="materialAgentWorking || materialAgentStopping" type="button" class="chat-composer-action is-stop" :disabled="materialAgentStopping" :aria-busy="materialAgentStopping" @click="stopMaterialAgentMessage"><n-icon v-if="materialAgentStopping" :size="17" class="project-action-spinner"><Loader /></n-icon><n-icon v-else :size="17"><PlayerStop /></n-icon>{{ materialAgentStopping ? '正在停止…' : '停止分析' }}</button>
                <button v-else type="submit" class="chat-composer-action" :disabled="materialAgentConversationLoading || (!materialAgentPrompt.trim() && !materialAgentFiles.length)"><n-icon :size="17"><Send /></n-icon>发送</button>
              </template>
            </ChatComposerSurface>
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
          <aside class="manual-config-tree" aria-label="项目配置目录">
            <div class="manual-config-tree-head"><span>项目配置</span><small>基础信息与业务规则</small></div>
            <button v-for="section in manualSections" :key="section.key" type="button" :aria-current="manualSection === section.key ? 'page' : undefined" :class="{ active: manualSection === section.key }" @click="selectManualSection(section.key)"><n-icon :size="17"><component :is="section.icon" /></n-icon><strong>{{ section.label }}</strong><em>{{ section.count }}</em></button>
          </aside>

          <section class="manual-config-list">
            <div class="manual-table-wrap" :class="{ 'permission-table-wrap': manualSection === 'documentPermissions' }">
              <div v-if="!['overview', 'documentPermissions', 'platforms', 'wecom', 'feishu', 'dingtalk'].includes(manualSection)" class="manual-list-actions manual-inline-actions">
                <label class="manual-search">
                  <n-icon :size="16"><Search /></n-icon>
                  <input v-model.trim="manualSearch" :placeholder="`搜索${activeManualSection.label}`">
                </label>
                <button v-if="manualSection !== 'monitor'" type="button" class="primary" :disabled="submitting" @click="openManualEditor(manualSection)">
                  <n-icon :size="16"><Plus /></n-icon>新建
                </button>
                <button v-else type="button" class="primary" :disabled="submitting" @click="openManualEditor('monitor')">
                  <n-icon :size="16"><Pencil /></n-icon>维护配置
                </button>
              </div>
              <div v-if="configScopeLoading" class="manual-data-loading" aria-label="正在加载正式项目数据"><i></i><span></span><span></span><span></span></div>

              <section v-else-if="manualSection === 'overview'" class="project-base-info-panel">
                <form class="project-base-info-form" @submit.prevent="saveProjectBaseInfo">
                  <fieldset>
                    <legend>项目概况</legend>
                    <div class="project-base-info-grid">
                      <label class="project-base-info-wide">项目名称<span>用于项目切换、任务归属和资料关联。</span><input v-model.trim="projectBaseInfoForm.name" required maxlength="200" placeholder="请输入项目名称"></label>
                      <label class="project-base-info-wide">工程类型及概况<span>简要说明工程类别、范围和主要建设内容。</span><textarea v-model.trim="projectBaseInfoForm.engineeringTypeDescription" maxlength="5000" rows="4" placeholder="例如：社区卫生服务中心异地扩建，包含地下结构、主体结构及安装工程"></textarea></label>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend>合同信息</legend>
                    <div class="project-base-info-grid contract">
                      <label>合同开工日期<input v-model="projectBaseInfoForm.contractStartDate" type="date"></label>
                      <label>合同结束日期<input v-model="projectBaseInfoForm.contractEndDate" type="date"></label>
                      <label>合同工期（天）<input v-model.number="projectBaseInfoForm.contractDurationDays" type="number" min="1" step="1" placeholder="请输入天数"></label>
                      <label>合同金额（万元）<input v-model.number="projectBaseInfoForm.contractAmountWanYuan" type="number" min="0" step="0.01" placeholder="请输入金额"></label>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend>参建单位</legend>
                    <div class="project-base-info-grid units">
                      <label>建设单位<input v-model.trim="projectBaseInfoForm.constructionUnitName" maxlength="300" placeholder="请输入建设单位名称"></label>
                      <label>施工总承包单位<input v-model.trim="projectBaseInfoForm.generalContractorUnitName" maxlength="300" placeholder="请输入总承包单位名称"></label>
                      <label>监理单位<input v-model.trim="projectBaseInfoForm.supervisionUnitName" maxlength="300" placeholder="请输入监理单位名称"></label>
                      <label>设计单位<input v-model.trim="projectBaseInfoForm.designUnitName" maxlength="300" placeholder="请输入设计单位名称"></label>
                      <label>勘察单位<input v-model.trim="projectBaseInfoForm.surveyUnitName" maxlength="300" placeholder="请输入勘察单位名称"></label>
                    </div>
                  </fieldset>
                  <footer class="project-base-info-actions"><span>保存后立即更新当前项目，已有业务数据和知识库绑定不会改变。</span><button type="submit" class="primary" :disabled="submitting || !projectBaseInfoForm.name.trim()">{{ submitting ? '正在保存…' : '保存基础信息' }}</button></footer>
                </form>
              </section>

              <ProjectPlatformPanel v-else-if="manualSection === 'platforms'" :project-id="configProjectId" manage />
              <section v-else-if="['wecom', 'feishu', 'dingtalk'].includes(manualSection)" class="project-connector-direct">
                <form v-if="activeProjectConnector" class="project-connector-editor" @submit.prevent="saveProjectConnector">
                  <label>{{ activeProjectConnector.connectionLabel }}<input v-model.trim="activeProjectConnector.connectionId" maxlength="500" :disabled="projectConnectorBusy" :placeholder="activeProjectConnector.connectionPlaceholder"></label>
                  <label>{{ activeProjectConnector.secretLabel }}<input v-model="activeProjectConnector.secret" type="password" autocomplete="new-password" :disabled="projectConnectorBusy" :placeholder="activeProjectConnector.hasSecret ? '留空则继续使用已保存的凭据' : activeProjectConnector.secretPlaceholder"></label>
                  <div class="project-credential-note"><n-icon :size="17"><ShieldLock /></n-icon><p><strong>凭据保护</strong><span>{{ activeProjectConnector.key === 'wecom' ? '群机器人 Webhook 仅以服务端密文保存，页面和接口均不会回显。' : '连接标识保存在项目配置表，密钥仅以服务端密文保存，页面不会回显。' }}</span></p></div>
                  <footer class="project-connector-actions"><span>{{ activeProjectConnector.updatedAt ? `更新于 ${activeProjectConnector.updatedAt}` : '尚未保存连接信息' }}</span><div><button v-if="activeProjectConnector.key === 'wecom' && activeProjectConnector.configured" type="button" class="secondary" :disabled="projectConnectorBusy" @click="testProjectConnector"><n-icon v-if="projectConnectorTesting" :size="16" class="project-action-spinner"><Loader /></n-icon>{{ projectConnectorTesting ? '正在测试…' : '测试发送' }}</button><button v-if="activeProjectConnector.configured" type="button" class="secondary danger" :disabled="projectConnectorBusy" @click="clearProjectConnector"><n-icon v-if="projectConnectorClearing" :size="16" class="project-action-spinner"><Loader /></n-icon>{{ projectConnectorClearing ? '正在清除…' : '清除配置' }}</button><button type="submit" class="primary" :disabled="projectConnectorBusy"><n-icon :size="17" :class="{ 'project-action-spinner': projectConnectorSaving }"><Loader v-if="projectConnectorSaving" /><Link v-else /></n-icon>{{ projectConnectorSaving ? '正在保存…' : `保存${activeProjectConnector.label}配置` }}</button></div></footer>
                </form>
              </section>

              <section v-else-if="manualSection === 'members'" class="manual-data-panel personnel-browser">
                <div v-if="filteredMembers.length" class="personnel-card-list">
                  <article v-for="item in filteredMembers" :key="item.id" class="personnel-card" :data-config-record-id="item.id" tabindex="-1">
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

              <ProjectDocumentPermissionPanel
                v-else-if="manualSection === 'documentPermissions'"
                :project-id="configProjectId"
                :members="configScope.members"
              />

              <section v-else-if="manualSection === 'wbs'" class="manual-data-panel wbs-browser">
                <div class="wbs-browser-toolbar"><span v-if="manualSearch">找到 {{ visibleManualWbsRows.length }} 个相关节点，已保留上级路径</span><div><button type="button" @click="expandAllManualWbs">全部展开</button><button type="button" @click="collapseAllManualWbs">收起任务组</button></div></div>
                <div v-if="visibleManualWbsRows.length" class="wbs-tree-table-wrap">
                  <table class="manual-table wbs-tree-table">
                    <thead><tr><th>计划层级（WBS）</th><th>计划区间</th><th>工期与负责人</th><th>完成进度</th><th>状态与优先级</th><th>前置工序</th><th>操作</th></tr></thead>
                    <tbody>
                      <tr v-for="row in visibleManualWbsRows" :key="row.item.id" :data-config-record-id="row.item.id" tabindex="-1" :class="{ 'wbs-group-row': row.hasChildren }">
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
                    <tbody><tr v-for="item in filteredQualityMetrics" :key="item.id" :data-config-record-id="item.id" tabindex="-1"><td><code>{{ item.wbsCode || '—' }}</code><strong>{{ item.wbsName || configWbsName(item.wbsId || '', item.wbsCode) || '未匹配工序' }}</strong></td><td>{{ item.acceptanceItem || '未填写' }}</td><td>{{ item.controlIndicator || '未填写' }}</td><td>{{ item.inspectionFrequency || '未设置' }}</td><td>{{ item.relatedDocuments || item.requiredMaterials.join('、') || '未设置' }}</td><td><button type="button" class="row-action" @click="openManualEditor('quality', item)">查看 / 修改</button></td></tr></tbody>
                  </table>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><Shield /></n-icon><strong>{{ manualSearch ? '没有匹配的质量要求' : '还没有质量要求' }}</strong><p>{{ manualSearch ? '可按 WBS 编码、验收项、控制指标或资料名称搜索。' : '点击右上角“新建”，为 WBS 工序配置验收要求。' }}</p></div>
              </section>

              <section v-else-if="manualSection === 'risks'" class="manual-data-panel risk-browser">
                <div v-if="filteredRisks.length" class="risk-card-list">
                  <article v-for="item in filteredRisks" :key="item.id" class="risk-record-card" :data-config-record-id="item.id" tabindex="-1">
                    <header><span class="risk-serial">第 {{ String(item.serialNo || 0).padStart(2, '0') }} 项</span><div><h3>{{ item.riskPart || item.name }}</h3><p>{{ item.relatedProcessName || item.type || '未注明相关工序' }}</p></div><span class="risk-level" :class="item.level">{{ formalRiskLevelLabel(item) }}</span><button type="button" class="row-action" @click="openManualEditor('risks', item)">查看 / 修改</button></header>
                    <div class="risk-context single"><span><strong>风险窗口</strong>{{ formatRiskWindow(item) }}</span></div>
                    <dl><div><dt>评价条件</dt><dd>{{ item.evaluationCondition || item.controlMeasures || '未填写' }}</dd></div><div><dt>风险摘要</dt><dd>{{ item.summary || '未填写' }}</dd></div></dl>
                  </article>
                </div>
                <div v-else class="manual-empty"><n-icon :size="28"><Shield /></n-icon><strong>{{ manualSearch ? '没有匹配的风险源' : '还没有风险源' }}</strong><p>{{ manualSearch ? '可按风险部位、相关工序、等级或评价条件搜索。' : '点击右上角“新建”，补充项目风险清单。' }}</p></div>
              </section>

              <section v-else-if="manualSection === 'mappings'" class="manual-data-panel mapping-browser">
                <table v-if="filteredMappings.length" class="manual-table"><thead><tr><th>平台</th><th>来源字段</th><th>目标字段</th><th>填报要求</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredMappings" :key="item.id" :data-config-record-id="item.id" tabindex="-1"><td><strong>{{ item.platformName }}</strong></td><td>{{ sourceFieldLabel(item.sourceField) }}</td><td>{{ item.targetField }}</td><td>{{ item.required ? '必填' : '选填' }} · {{ item.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('mappings', item)">查看 / 修改</button></td></tr></tbody></table>
                <div v-else class="manual-empty"><n-icon :size="28"><ArrowsLeftRight /></n-icon><strong>{{ manualSearch ? '没有匹配的字段映射' : '还没有字段映射' }}</strong><p>{{ manualSearch ? '可按平台、来源字段或目标字段搜索。' : '点击右上角“新建”，补充外部平台字段映射规则。' }}</p></div>
              </section>
              <table v-else-if="manualSection === 'monitor'" class="manual-table"><thead><tr><th>配置项</th><th>当前值</th><th>说明</th><th>操作</th></tr></thead><tbody><tr><td><strong>资料目录监控</strong></td><td>{{ monitorForm.enabled ? '已启用' : '未启用' }}</td><td>{{ monitorForm.mainDir || '尚未设置资料接收目录' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">查看 / 修改</button></td></tr><tr v-for="rule in monitorRules" :key="rule.id"><td><strong>{{ riskLabel(rule.level) }}预警</strong></td><td>提前 {{ rule.days }} 天</td><td>{{ rule.enabled ? '已启用' : '已停用' }}</td><td><button type="button" class="row-action" @click="openManualEditor('monitor')">维护规则</button></td></tr></tbody></table>
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
            <footer class="personnel-detail-actions"><span>{{ personnelDetailMember.systemRole === 'admin' ? '管理人员' : '普通用户' }}</span><button type="button" class="modal-secondary" @click="closePersonnelDetail">关闭</button><button type="button" class="primary" @click="addPersonnelDetailPosition(personnelDetailMember)"><n-icon :size="16"><Plus /></n-icon>添加兼任岗位</button></footer>
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
                <label>岗位<select v-model="editorMemberForm.positionName" required><option disabled value="">请选择固定岗位</option><option v-for="position in PROJECT_POSITION_OPTIONS" :key="position.code" :value="position.name">{{ position.name }}</option></select></label>
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
            <label>项目名称<input v-model.trim="projectForm.name" required maxlength="200" autofocus :disabled="submitting" placeholder="请输入项目名称"></label>
            <div class="setup-modal-actions"><button type="button" class="modal-secondary" :disabled="submitting" @click="closeProjectCreate">取消</button><button type="submit" class="primary" :disabled="submitting || !projectForm.name.trim()" :aria-busy="submitting"><n-icon v-if="submitting" :size="16" class="project-action-spinner"><Loader /></n-icon>{{ submitting ? '正在创建…' : '创建项目' }}</button></div>
          </form>
        </section>
      </div>

      <InitializationChangeReview
        :open="initializationDraftReviewOpen"
        :draft="materialAgentDraft"
        :project-id="configProjectId"
        :name="configProjectName"
        :admin="isPlatformAdmin"
        @loading-change="initializationDraftReviewLoading = $event"
        @close="initializationDraftReviewOpen = false"
        @applied="handleInitializationChangesApplied"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowsLeftRight, ChevronDown, ChevronUp, Link, ListDetails, Loader, MessageCircle, Paperclip, Pencil, PlayerStop, Plus, Robot, Search, Send, Shield, ShieldLock, Users, X } from '@vicons/tabler'
import api, { type ApiEnvelope } from '@/api/client'
import {
  streamAgentConversationConfirmation,
  streamAgentConversationMessage,
} from '@/api/agentStream'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import ProjectDocumentPermissionPanel from '@/components/admin/ProjectDocumentPermissionPanel.vue'
import ProjectPlatformPanel from '@/components/business/ProjectPlatformPanel.vue'
import ChatComposerSurface from '@/components/chat/ChatComposerSurface.vue'
import InitializationChangeReview from '@/components/initialization/InitializationChangeReview.vue'
import { useProjectSetupConfiguration } from '@/composables/useProjectSetupConfiguration'
import { useInitializationDraftSync } from '@/composables/useInitializationDraftSync'
import { showInitializationDraftDock } from '@/utils/initializationDraftDock'
import { useAppStore, type ProjectConfigScope } from '@/stores/app'
import type { DirConfig, Member, MemberPosition, PlatformFieldMapping, QualityMetric, RemindRule, RiskLevel, RiskSource, WbsItem } from '@/types'
import {
  applyAgentRuntimeEvents,
  createEmptyRuntimeTrace,
  type AgentRuntimeTrace,
  type AgentToolCallBlock,
  type ApiAgentMessage,
} from '@/types/agentRuntime'
import {
  PROJECT_POSITION_OPTIONS,
  type ApiAgentConversation,
  type ApiInitializationDraft,
  type ApiInitializationFile,
  type InitializationAttachment,
  type ManualSection,
  type MaterialAgentMessage,
  type MaterialAgentPreparation,
  type ProjectConnectorKey,
  type WorkspaceTab,
} from './project-setup/types'
import {
  ACTIVE_MATERIAL_AGENT_STATUSES,
  buildManualWbsTree,
  cloneMaterialAgentTrace,
  formalRiskLevelLabel,
  formalWbsItemType,
  formalWbsPriorityLabel,
  formalWbsStatusLabel,
  formatFileSize,
  formatFormalDate,
  formatProgress,
  formatRiskWindow,
  formatSourceDateTime,
  formatTime,
  formatValidationDuration,
  formatWbsDuration,
  generateInitializationPassword,
  initializationDraftCollapsedLabel,
  initializationDraftStageHint,
  initializationDraftStatusLabel,
  initializationSectionLabels,
  mapMaterialAgentMessage,
  maskedIdentityCard,
  riskLabel,
  sourceFieldLabel,
  traceHasPendingMaterialToolCall,
  wbsStatusLabel,
} from './project-setup/presentation'
const store = useAppStore()
const message = useMessage()
const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const configScopeLoading = ref(false)
const configProjectId = ref('')
const {
  projectBaseInfoForm, projectBaseInfoCompletedCount, projectConnectorLoading, projectConnectorSaving, projectConnectorTesting, projectConnectorClearing,
  activeProjectConnectorKey, projectConnectors, activeProjectConnector, projectConnectorBusy, syncProjectBaseInfo, saveProjectBaseInfo, loadProjectConnectorSettings, saveProjectConnector, testProjectConnector, clearProjectConnector,
} = useProjectSetupConfiguration({ store, message, configProjectId, run })
const isPlatformAdmin = computed(() => sessionStorage.getItem('user_role') === 'admin')
const configProjectName = computed(() => store.projects.find(project => project.id === configProjectId.value)?.name || '当前项目')
const projectRequiredNotice = computed(() => route.query.projectRequired === '1')
const configScope = reactive<ProjectConfigScope>({ members: [], wbsItems: [], riskSources: [], qualityMetrics: [], platformMappings: [], dirConfig: { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false }, remindRules: [] })
const activeWorkspaceTab = ref<WorkspaceTab>('agent')
const workspaceTabs: Array<{ key: WorkspaceTab; label: string; hint: string }> = [
  { key: 'agent', label: 'Dobby 配置助手', hint: '资料补充与更新' },
  { key: 'manual', label: '项目配置', hint: '基础信息与业务规则' },
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
const manualSection = ref<ManualSection>('overview')
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
const materialAgentConversations = ref<ApiAgentConversation[]>([])
const materialAgentConversationSearch = ref('')
const materialAgentConversationListLoading = ref(false)
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
const materialAgentPreparation = ref<MaterialAgentPreparation | null>(null)
const materialAgentStreamingTrace = shallowRef<AgentRuntimeTrace | null>(null)
let materialAgentStreamAbortController: AbortController | null = null
let materialAgentConfirmAbortController: AbortController | null = null
let materialAgentReconcileSequence = 0
let materialConversationLoadSequence = 0
const filteredMaterialAgentConversations = computed(() => {
  const keyword = materialAgentConversationSearch.value.trim().toLowerCase()
  if (!keyword) return materialAgentConversations.value
  return materialAgentConversations.value.filter(conversation => (
    `${conversation.title} ${conversation.agent_name}`.toLowerCase().includes(keyword)
  ))
})
const materialAgentPreparationProgress = computed(() => {
  const preparation = materialAgentPreparation.value
  if (!preparation?.total) return 0
  return Math.round(preparation.completed * 100 / preparation.total)
})
const materialAgentPreparationTitle = computed(() => {
  if (materialAgentPreparation.value?.stage === 'uploading') {
    return '正在上传并解析附件'
  }
  if (materialAgentPreparation.value?.stage === 'starting_agent') {
    return '附件解析完成，正在处理初始化请求'
  }
  return '正在处理项目初始化请求'
})
const materialAgentPreparationDetail = computed(() => {
  const preparation = materialAgentPreparation.value
  if (!preparation) return ''
  if (preparation.stage === 'uploading') {
    const current = preparation.currentFile
      ? `，当前：${preparation.currentFile}`
      : ''
    return `${preparation.completed}/${preparation.total} 个附件已完成${current}`
  }
  if (preparation.stage === 'starting_agent') {
    return `${preparation.total} 个附件已经保存为可引用的解析资料，正在交给 Dobby 处理。`
  }
  return '你的消息已经进入对话，正在准备本次初始化任务。'
})
const initializationDraftCollapsed = ref(false)
const initializationDraftReviewOpen = ref(false)
const initializationDraftReviewLoading = ref(false)
const materialDraftSyncRunning = computed(() => materialAgentLoading.value || ACTIVE_MATERIAL_AGENT_STATUSES.has(materialAgentConversationStatus.value))
const materialAgentWorking = computed(() => materialAgentLoading.value || (
  materialAgentConversationStatus.value !== 'interrupting'
  && ACTIVE_MATERIAL_AGENT_STATUSES.has(materialAgentConversationStatus.value)
))
const { draft: materialAgentDraft, refresh: refreshInitializationDraft } = useInitializationDraftSync<ApiInitializationDraft>({
  projectId: configProjectId,
  conversationId: materialAgentConversationId,
  running: materialDraftSyncRunning,
  onChange: (next, previous) => {
    if (!next) initializationDraftReviewOpen.value = false
    if (next && (!previous || next.id !== previous.id || next.revision !== previous.revision)) initializationDraftCollapsed.value = false
    // After a reload there is no local SSE request. Keep both the reply and
    // its terminal status in sync while the server still owns this turn.
    if (!materialAgentLoading.value && !materialAgentConversationLoading.value
      && ACTIVE_MATERIAL_AGENT_STATUSES.has(materialAgentConversationStatus.value)) {
      void loadMaterialAgentConversation(configProjectId.value, materialAgentConversationId.value ?? undefined)
    }
  },
  onError: detail => { materialAgentError.value = detail },
})
const initializationDraftSourceNames = computed(() => {
  const names = (materialAgentDraft.value?.source_files || [])
    .map((source) => {
      if (typeof source === 'string') return source.trim()
      const fileName = source.file_name || source.name || source.original_name
      if (fileName?.trim()) return fileName.trim()
      return source.file_id === null || source.file_id === undefined
        ? ''
        : `附件 #${source.file_id}`
    })
    .filter(name => name.length > 0)
  return [...new Set(names)]
})
const materialAgentDraftDockVisible = computed(() => showInitializationDraftDock(
  materialAgentDraft.value, materialDraftSyncRunning.value,
))
watch([materialAgentDraftDockVisible, initializationDraftCollapsed], () => {
  // Capture the user's follow preference before the dock changes viewport size.
  if (materialAgentFollowOutput.value) void scrollMaterialAgentToEnd('auto', true)
}, { flush: 'pre' })

const projectPositionCount = computed(() => new Set(
  configScope.members.flatMap(member => member.positions.map(position => position.positionId)),
).size)
const manualSections = computed(() => {
  const sections = [
    { key: 'overview' as ManualSection, label: '基础信息', description: '修改项目名称、工程概况、合同信息与参建单位。', count: `${projectBaseInfoCompletedCount.value}/11`, icon: ListDetails },
    { key: 'members' as ManualSection, label: '项目成员', description: '维护成员账号、岗位与协作责任。', count: configScope.members.length, icon: Users },
    { key: 'wbs' as ManualSection, label: 'WBS进度管理', description: '维护工序基线，供进度、日报和预警匹配。', count: configScope.wbsItems.length, icon: ListDetails },
    { key: 'quality' as ManualSection, label: '质量指标', description: '维护验收要求、检查频次与关联工序。', count: configScope.qualityMetrics.length, icon: Shield },
    { key: 'risks' as ManualSection, label: '风险源', description: '维护风险等级、控制要求和资料要求。', count: configScope.riskSources.length, icon: Shield },
    { key: 'mappings' as ManualSection, label: '字段映射', description: '维护外部平台填报字段的映射规则。', count: configScope.platformMappings.length, icon: ArrowsLeftRight },
    { key: 'platforms' as ManualSection, label: '工程平台', description: '维护工程平台名称、类型与访问地址。', count: '配置', icon: ArrowsLeftRight },
    { key: 'monitor' as ManualSection, label: '监控与预警', description: '维护资料目录监控与风险预警提前量。', count: monitorRules.value.length + 1, icon: ListDetails },
    { key: 'wecom' as ManualSection, label: '企业微信配置', description: '维护任务通知使用的项目群机器人。', count: projectConnectors[0].configured ? 1 : 0, icon: MessageCircle },
    { key: 'feishu' as ManualSection, label: '飞书配置', description: '维护当前项目使用的飞书应用或项目群机器人。', count: projectConnectors[1].configured ? 1 : 0, icon: MessageCircle },
    { key: 'dingtalk' as ManualSection, label: '钉钉配置', description: '维护当前项目使用的钉钉应用或项目群机器人。', count: projectConnectors[2].configured ? 1 : 0, icon: MessageCircle },
  ]
  if (isPlatformAdmin.value) {
    sections.splice(2, 0, {
      key: 'documentPermissions',
      label: '岗位权限',
      description: '按项目岗位分配工程资料目录与文件的访问范围。',
      count: projectPositionCount.value,
      icon: ShieldLock,
    })
  }
  return sections
})
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
const manualWbsTree = computed(() => buildManualWbsTree([
  ...configScope.wbsItems,
]))
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
function setupQueryValue(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function replaceSetupRouteQuery(patch: Record<string, string | undefined>) {
  const query = { ...route.query }
  Object.entries(patch).forEach(([key, value]) => {
    if (value) query[key] = value
    else delete query[key]
  })
  void router.replace({ path: '/settings', query })
}

async function focusConfigRecordFromRoute() {
  const recordId = setupQueryValue(route.query.recordId)
  if (!recordId) return
  await nextTick()
  const element = document.querySelector<HTMLElement>(`[data-config-record-id="${CSS.escape(recordId)}"]`)
  element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  element?.focus({ preventScroll: true })
}

function syncProjectSetupFromRoute() {
  const tab = setupQueryValue(route.query.tab)
  const requestedSection = setupQueryValue(route.query.section) as ManualSection
  const requestedConversationId = Number(setupQueryValue(route.query.conversationId))
  const availableSections = new Set(manualSections.value.map(item => item.key))
  if (setupQueryValue(route.query.createProject) === '1') projectCreateOpen.value = true
  if (tab === 'manual' || tab === 'project' || availableSections.has(requestedSection)) {
    activeWorkspaceTab.value = 'manual'
  } else if (tab === 'agent') {
    activeWorkspaceTab.value = 'agent'
  }
  if (availableSections.has(requestedSection)) {
    manualSection.value = requestedSection
    if (['wecom', 'feishu', 'dingtalk'].includes(requestedSection)) activeProjectConnectorKey.value = requestedSection as ProjectConnectorKey
  }
  if (
    activeWorkspaceTab.value === 'agent'
    && configProjectId.value
    && Number.isInteger(requestedConversationId)
    && requestedConversationId > 0
    && requestedConversationId !== materialAgentConversationId.value
  ) {
    void loadMaterialAgentConversation(configProjectId.value, requestedConversationId)
  }
  void focusConfigRecordFromRoute()
}

function selectManualSection(section: ManualSection, syncRoute = true) {
  activeWorkspaceTab.value = 'manual'
  manualSection.value = section
  manualSearch.value = ''
  if (section === 'wecom' || section === 'feishu' || section === 'dingtalk') activeProjectConnectorKey.value = section
  if (syncRoute) replaceSetupRouteQuery({ tab: 'manual', section, recordId: undefined })
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
    await focusConfigRecordFromRoute()
  } catch (error: any) {
    if (sequence === configLoadSequence) message.error(error.response?.data?.detail || '项目配置加载失败。')
  } finally {
    if (sequence === configLoadSequence) configScopeLoading.value = false
  }
}

function selectWorkspaceTab(tab: WorkspaceTab, syncRoute = true) {
  activeWorkspaceTab.value = tab
  if (syncRoute) replaceSetupRouteQuery({ tab, section: tab === 'manual' ? manualSection.value : undefined, recordId: undefined })
  if (tab !== 'agent' || !configProjectId.value) return
  void loadMaterialAgentConversation(configProjectId.value)
  void loadInitializationDraft(configProjectId.value)
}

watch(() => [store.currentProjectId, store.projects.length] as const, () => {
  const preferredProjectId = store.currentProjectId || store.projects[0]?.id || ''
  if (preferredProjectId && preferredProjectId !== configProjectId.value) {
    configProjectId.value = preferredProjectId
  }
}, { immediate: true })

watch(configProjectId, projectId => {
  cancelMaterialAgentRequests()
  materialAgentReconcileSequence += 1
  materialAgentSending.value = false
  materialAgentConfirming.value = false
  materialAgentStopping.value = false
  activeWorkspaceTab.value = 'agent'
  manualSection.value = 'overview'
  manualSearch.value = ''
  materialAgentConversations.value = []
  materialAgentConversationSearch.value = ''
  materialAgentMessages.value = []
  materialAgentError.value = ''
  materialAgentConversationId.value = null
  materialAgentConversationStatus.value = ''
  materialAgentPreparation.value = null
  materialAgentStreamingTrace.value = null
  materialAgentFollowOutput.value = true
  materialAgentDraft.value = null
  initializationDraftCollapsed.value = false
  initializationDraftReviewOpen.value = false
  clearMaterialAgentFiles()
  activeProjectConnectorKey.value = 'wecom'
  syncProjectBaseInfo(projectId)
  configScope.members = []
  configScope.wbsItems = []
  configScope.riskSources = []
  configScope.qualityMetrics = []
  configScope.platformMappings = []
  collapsedManualWbsIds.value = new Set()
  closePersonnelDetail()
  Object.assign(monitorForm, { mainDir: '', archiveDir: '', tempDir: '', failedDir: '', backupDir: '', scanInterval: 30, enabled: false })
  monitorRules.value = []
  void loadProjectConnectorSettings()
  void loadConfigProjectScope(projectId)
  void loadMaterialAgentConversation(projectId)
  void loadInitializationDraft(projectId)
  syncProjectSetupFromRoute()
}, { immediate: true })

watch(
  () => [route.query.tab, route.query.section, route.query.recordId, route.query.conversationId, route.query.createProject] as const,
  syncProjectSetupFromRoute,
  { immediate: true },
)

watch(() => store.projectSetupRefreshVersion, () => {
  if (!configProjectId.value) return
  activeWorkspaceTab.value = 'agent'
  void loadMaterialAgentConversation(configProjectId.value)
  void loadInitializationDraft(configProjectId.value)
})

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
  requestedConversationId?: number,
): Promise<boolean> {
  if (!projectId) return false
  const sequence = ++materialConversationLoadSequence
  materialAgentConversationListLoading.value = true
  materialAgentConversationLoading.value = true
  materialAgentError.value = ''
  try {
    const response = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
      `/projects/${projectId}/agent-conversations`,
      { params: { conversation_type: 'initialization' } },
    )
    if (sequence !== materialConversationLoadSequence || projectId !== configProjectId.value) return false
    materialAgentConversations.value = response.data.data
    const routeConversationId = Number(setupQueryValue(route.query.conversationId))
    const preferredConversationId = requestedConversationId
      || materialAgentConversationId.value
      || (Number.isInteger(routeConversationId) && routeConversationId > 0 ? routeConversationId : null)
    const requestedConversation = response.data.data.find(item => item.id === preferredConversationId)
    if (requestedConversationId && !requestedConversation) {
      materialAgentError.value = '该会话已不可用，请从会话列表选择其他会话。'
      return false
    }
    const conversation = requestedConversation || response.data.data[0]
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
    const mappedMessages = messages.data.data.map(mapMaterialAgentMessage)
    const firstUserMessage = mappedMessages.find(item => item.role === 'user')
    const firstUserTitle = firstUserMessage
      ? materialAgentConversationTitle(firstUserMessage.content)
      : ''
    materialAgentMessages.value = mappedMessages
    materialAgentConversations.value = refreshedConversations.data.data.map(item => (
      item.id === conversation.id && firstUserTitle
        ? { ...item, title: firstUserTitle }
        : item
    ))
    const refreshedConversation = refreshedConversations.data.data.find(item => item.id === conversation.id)
    materialAgentConversationStatus.value = refreshedConversation?.status || conversation.status
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
      materialAgentConversationListLoading.value = false
      materialAgentConversationLoading.value = false
    }
  }
}

function formatMaterialAgentConversationTime(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function materialAgentConversationTitle(content: string) {
  const firstLine = content
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(Boolean) || ''
  const normalized = firstLine.replace(/\s+/g, ' ').trim()
  const firstSentence = normalized.match(/^.*?[。！？!?]|^.*?\.(?=\s|$)/)?.[0] || normalized
  if (!firstSentence) return '新对话'
  return firstSentence.length > 300
    ? `${firstSentence.slice(0, 299).trimEnd()}…`
    : firstSentence
}

function syncMaterialAgentConversationRoute(conversationId?: number) {
  replaceSetupRouteQuery({
    tab: 'agent',
    section: undefined,
    recordId: undefined,
    conversationId: conversationId ? String(conversationId) : undefined,
  })
}

function resetMaterialAgentConversationView() {
  cancelMaterialAgentRequests()
  materialConversationLoadSequence += 1
  materialAgentConversationListLoading.value = false
  materialAgentConversationLoading.value = false
  materialAgentReconcileSequence += 1
  materialAgentConversationId.value = null
  materialAgentConversationStatus.value = ''
  materialAgentMessages.value = []
  materialAgentPrompt.value = ''
  materialAgentError.value = ''
  materialAgentPreparation.value = null
  materialAgentStreamingTrace.value = null
  materialAgentFollowOutput.value = true
  clearMaterialAgentFiles()
}

function startNewMaterialAgentConversation() {
  if (materialAgentLoading.value || materialAgentStopping.value) return
  resetMaterialAgentConversationView()
  syncMaterialAgentConversationRoute()
}

async function selectMaterialAgentConversation(conversationId: number) {
  if (
    conversationId === materialAgentConversationId.value
    || materialAgentLoading.value
    || materialAgentStopping.value
  ) return
  resetMaterialAgentConversationView()
  materialAgentConversationId.value = conversationId
  syncMaterialAgentConversationRoute(conversationId)
  await loadMaterialAgentConversation(configProjectId.value, conversationId)
}

async function resyncMaterialAgentConversation() {
  if (materialAgentLoading.value || materialAgentStopping.value || materialAgentConversationLoading.value) return
  const projectId = configProjectId.value
  const conversationId = materialAgentConversationId.value
  if (!projectId || !conversationId) return
  await loadMaterialAgentConversation(projectId, conversationId)
}

async function loadInitializationDraft(projectId = configProjectId.value) {
  if (projectId === configProjectId.value) await refreshInitializationDraft()
}
function openInitializationDraftReview() {
  if (materialAgentDraft.value && !initializationDraftReviewLoading.value) {
    initializationDraftReviewLoading.value = true
    initializationDraftReviewOpen.value = true
  }
}

async function handleInitializationChangesApplied() {
  await Promise.all([loadInitializationDraft(), loadConfigProjectScope()])
  message.success('所选项目资料已更新。')
}
async function ensureMaterialAgentConversation(signal?: AbortSignal): Promise<number> {
  if (materialAgentConversationId.value) return materialAgentConversationId.value
  const response = await api.post<ApiEnvelope<ApiAgentConversation>>(
    `/projects/${configProjectId.value}/agent-conversations`,
    { conversation_type: 'initialization' },
    { signal },
  )
  const conversation = response.data.data
  materialAgentConversationId.value = conversation.id
  materialAgentConversationStatus.value = conversation.status
  materialAgentConversations.value = [
    conversation,
    ...materialAgentConversations.value.filter(item => item.id !== conversation.id),
  ]
  syncMaterialAgentConversationRoute(conversation.id)
  return conversation.id
}

async function uploadMaterialAgentFiles(
  conversationId: number,
  files: File[],
  signal?: AbortSignal,
  onProgress?: (progress: MaterialAgentPreparation) => void,
): Promise<ApiInitializationFile[]> {
  const uploaded: ApiInitializationFile[] = []
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index]
    onProgress?.({
      stage: 'uploading',
      completed: index,
      total: files.length,
      currentFile: file.name,
    })
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<ApiEnvelope<ApiInitializationFile>>(
      `/projects/${configProjectId.value}/agent-conversations/${conversationId}/initialization-files`,
      form,
      { timeout: 60_000, signal },
    )
    uploaded.push(response.data.data)
    onProgress?.({
      stage: 'uploading',
      completed: index + 1,
      total: files.length,
      currentFile: file.name,
    })
  }
  return uploaded
}

async function sendMaterialAgentMessage() {
  const requestedContent = materialAgentPrompt.value.trim()
  if (!configProjectId.value || materialAgentWorking.value || materialAgentStopping.value || materialAgentConversationLoading.value) return
  const selectedFiles = [...materialAgentFiles.value]
  if (!requestedContent && !selectedFiles.length) return
  const controller = new AbortController()
  materialAgentStreamAbortController = controller
  materialAgentSending.value = true
  materialAgentError.value = ''
  const content = requestedContent || '请读取并分析这些项目初始化附件，整理需要我核对的初始化信息。'
  const localMessageId = `user-${Date.now()}`
  materialAgentMessages.value = [
    ...materialAgentMessages.value,
    {
      id: localMessageId,
      role: 'user',
      content,
      attachments: selectedFiles.length
        ? selectedFiles.map((file, index) => ({
            id: `pending-${localMessageId}-${index}`,
            name: file.name,
            size: file.size,
          }))
        : undefined,
    },
  ]
  materialAgentPrompt.value = ''
  clearMaterialAgentFiles()
  materialAgentPreparation.value = {
    stage: 'creating_conversation',
    completed: 0,
    total: selectedFiles.length,
    currentFile: '',
  }
  await scrollMaterialAgentToEnd()
  try {
    const creatingConversation = materialAgentConversationId.value === null
    const conversationId = await ensureMaterialAgentConversation(controller.signal)
    const activeConversation = materialAgentConversations.value.find(conversation => conversation.id === conversationId)
    if (activeConversation) {
      materialAgentConversations.value = [
        {
          ...activeConversation,
          title: creatingConversation
            ? materialAgentConversationTitle(content)
            : activeConversation.title,
          updated_at: new Date().toISOString(),
        },
        ...materialAgentConversations.value.filter(conversation => conversation.id !== conversationId),
      ]
    }
    const uploadedFiles = await uploadMaterialAgentFiles(
      conversationId,
      selectedFiles,
      controller.signal,
      progress => {
        materialAgentPreparation.value = progress
        void scrollMaterialAgentToEnd()
      },
    )
    const attachments = uploadedFiles.map(file => ({
      id: String(file.id),
      name: file.file_name,
      size: file.file_size,
    }))
    materialAgentMessages.value = materialAgentMessages.value.map(item => (
      item.id === localMessageId
        ? { ...item, attachments: attachments.length ? attachments : undefined }
        : item
    ))
    materialAgentPreparation.value = {
      stage: 'starting_agent',
      completed: uploadedFiles.length,
      total: uploadedFiles.length,
      currentFile: '',
    }
    materialAgentStreamingTrace.value = createEmptyRuntimeTrace()
    await scrollMaterialAgentToEnd()
    const completion: { message: ApiAgentMessage | null } = { message: null }
    await streamAgentConversationMessage(
      conversationId,
      content,
      {
        onAccepted: payload => {
          materialAgentConversationStatus.value = payload.runtime_status
          materialAgentPreparation.value = null
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
    materialAgentPreparation.value = null
    if (materialAgentStreamAbortController === controller) {
      materialAgentStreamAbortController = null
    }
    materialAgentSending.value = false
  }
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
      || !ACTIVE_MATERIAL_AGENT_STATUSES.has(item.runtimeTrace.status)
    ) return item
    const trace = cloneMaterialAgentTrace(item.runtimeTrace)
    trace.status = 'interrupted'
    trace.turnFinishedAt = interruptedAt
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
  try {
    if (materialAgentPreparation.value) {
      cancelMaterialAgentRequests()
      materialAgentPreparation.value = null
      materialAgentStreamingTrace.value = null
      message.info('附件上传与解析已停止。')
      return
    }
    if (!conversationId) {
      cancelMaterialAgentRequests()
      return
    }
    // Stopping must not wait for history, catalogue or attachment reads.
    if (materialAgentStreamingTrace.value?.messages.length) {
      materialAgentMessages.value.push({
        id: `stopped-${Date.now()}`, role: 'assistant', content: '',
        runtimeTrace: cloneMaterialAgentTrace(materialAgentStreamingTrace.value),
      })
    }
    cancelMaterialAgentRequests()
    await api.post(
      `/agent-conversations/${conversationId}/interrupt`,
      undefined,
      { timeout: 10_000 },
    )
    materialAgentConversationStatus.value = 'interrupting'
    markActiveMaterialAgentMessagesInterrupted()
    message.info('停止请求已接收，正在同步中断前已生成的内容。')
    if (configProjectId.value) {
      void reconcileMaterialAgentAfterStop(
        configProjectId.value,
        conversationId,
      )
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '停止初始化助手失败。')
    void loadMaterialAgentConversation()
  } finally {
    materialAgentStopping.value = false
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
  materialAgentPreparation.value = null
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
  materialAgentConversationListLoading.value = false
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
  materialAgentFiles.value = merged
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

async function run(action: () => Promise<unknown>, success: string) {
  if (submitting.value) return
  submitting.value = true
  try { await action(); await loadConfigProjectScope(); message.success(success) } catch (error: any) { message.error(error.response?.data?.detail || '保存失败，请检查权限和服务连接。') } finally { submitting.value = false }
}
function openProjectCreate() { projectCreateOpen.value = true }
function closeProjectCreate() {
  if (submitting.value) return
  projectCreateOpen.value = false
  if (setupQueryValue(route.query.createProject) === '1') {
    replaceSetupRouteQuery({ createProject: undefined })
  }
}
function submitProject() {
  void run(async () => {
    const project = await store.createProject({ name: projectForm.name })
    configProjectId.value = project.id
    projectForm.name = ''
    projectCreateOpen.value = false
    if (projectRequiredNotice.value || setupQueryValue(route.query.createProject) === '1') {
      await router.replace({ path: '/settings', query: { tab: 'agent' } })
    }
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
function configWbsName(wbsId: string, wbsCode = '') {
  return configScope.wbsItems.find(item => wbsId && item.id === wbsId)?.name
    || configScope.wbsItems.find(item => wbsCode && item.code.trim() === wbsCode.trim())?.name
    || ''
}
</script>

<style scoped src="./styles/ProjectSetupView.css"></style>
