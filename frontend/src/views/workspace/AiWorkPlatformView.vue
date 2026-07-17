<template>
  <div class="ai-platform">
    <section v-if="section === 'home'" class="home-console">
      <main class="home-workspace">
        <div class="home-titlebar">
          <div class="home-mode-tabs">
            <button
              v-for="mode in homeModeTabs"
              :key="mode.key"
              :class="{ active: homeMode === mode.key }"
              @click="homeMode = mode.key"
            >
              {{ mode.label }}
            </button>
          </div>
          <div class="home-actions">
            <router-link :to="homePrimaryAction.to" class="home-primary-button">
              <n-icon :size="17"><component :is="homePrimaryAction.icon" /></n-icon>
              {{ homePrimaryAction.label }}
            </router-link>
          </div>
        </div>

        <div v-if="homeMode === 'work'" class="home-controlbar">
          <div class="home-filter-tabs">
            <button
              v-for="tab in homeFilterTabs"
              :key="tab.key"
              :class="{ active: homeFilter === tab.key }"
              @click="homeFilter = tab.key"
            >
              {{ tab.label }}
              <span>{{ tab.count }}</span>
            </button>
          </div>
          <div class="home-pager">
            <span class="home-page-state">{{ homePageRangeText }}</span>
            <button class="home-page-arrow" :disabled="homePageIndex === 0" @click="goHomePage(-1)">
              <n-icon :size="18"><ChevronLeft /></n-icon>
            </button>
            <button class="home-page-arrow" :disabled="homePageIndex >= homePageCount - 1" @click="goHomePage(1)">
              <n-icon :size="18"><ChevronRight /></n-icon>
            </button>
          </div>
        </div>

        <div v-if="homeMode === 'work'" ref="homeQueueViewport" class="home-queue-list">
          <article v-for="item in pagedHomeWorkItems" :key="item.id" class="home-queue-card">
            <div class="home-rank" :class="item.tone">{{ item.rank }}</div>
            <div class="home-work-icon" :class="item.tone">
              <n-icon :size="25"><component :is="item.icon" /></n-icon>
            </div>
            <div class="home-work-main">
              <div class="home-chip-row">
                <span class="home-chip" :class="item.tone">{{ item.label }}</span>
              </div>
              <h2>{{ item.title }}</h2>
              <p>{{ item.reason }}</p>
              <div class="home-tag-row">
                <span v-for="tag in item.tags" :key="tag">{{ tag }}</span>
              </div>
            </div>
            <div class="home-owner">
              <div class="home-owner-name">
                <n-icon :size="17"><User /></n-icon>
                <strong>{{ item.owner }}</strong>
              </div>
              <span>{{ item.role }}</span>
              <time>{{ item.deadline }}</time>
            </div>
            <div class="home-card-actions">
              <router-link :to="item.to" :class="['home-card-primary', item.tone]">{{ item.action }}</router-link>
            </div>
          </article>
        </div>
        <button v-if="homeMode === 'work'" class="home-expand-button">展开已完成工作（12）</button>

        <section v-else class="home-chat-panel">
          <div class="chat-head home-chat-head" :class="{ 'is-empty': !homeQuickSession }">
            <div v-if="homeQuickSession" class="chat-title-block">
              <h1 :title="homeQuickSessionTitle">{{ homeQuickSessionTitle }}</h1>
              <div class="chat-subline">
                <span>{{ homeQuickSessionTime }}</span>
              </div>
            </div>
          </div>
          <div :class="['messages', 'home-chat-messages', { 'is-empty': !homeQuickChatMessages.length }]">
            <div v-if="!homeQuickChatMessages.length" class="home-chat-guide">
              <div class="home-chat-guide-copy">
                <strong>从这里开始协同处理</strong>
                <p>可以围绕当前项目的任务、资料、风险和人员关系展开处理；对话中形成的新工作会同步到智能协同，后续继续跟踪责任人、截止时间和处理进度。</p>
              </div>
              <div class="home-chat-guide-items">
                <span><b>查资料缺口</b>核对日报、监测报告、风险草稿和填报附件</span>
                <span><b>拆解处理动作</b>生成责任人、截止时间、依赖关系和下一步</span>
                <span><b>发起多人协同</b>把需要配合的人和事项沉淀到同一会话</span>
                <span><b>跟踪闭环结果</b>会话产生的工作进入任务管理持续推进</span>
              </div>
            </div>
            <article
              v-for="message in homeQuickChatMessages"
              :key="message.id"
              :class="['message-row', message.role, { 'has-generated': message.generatedTaskIds?.length }]"
            >
              <div class="message-avatar" aria-hidden="true">
                {{ message.role === 'assistant' ? '管' : '我' }}
              </div>
              <div class="message-stack">
                <div v-if="message.role === 'assistant'" class="message-role">Dobby</div>
                <div class="message-bubble">
                  <p>{{ message.content }}</p>
                  <div v-if="message.generatedTaskIds?.length" class="generated-work">
                    <div class="generated-work-head">
                      <span>已生成工作</span>
                      <strong>{{ tasksByIds(message.generatedTaskIds).length }} 项</strong>
                    </div>
                    <article v-for="task in tasksByIds(message.generatedTaskIds)" :key="task.id" class="generated-task-card">
                      <div class="generated-task-main">
                        <strong :title="task.title">{{ task.title }}</strong>
                        <p>{{ taskSourceLabel(task.type) }} · {{ store.getMemberName(task.responsibleId) }} · 截止 {{ formatDateTime(task.deadline, 'end') }}</p>
                      </div>
                      <span class="status-pill">{{ statusLabel(task.status) }}</span>
                      <div class="mini-track"><i :style="{ width: `${taskProgress(task.status)}%` }"></i></div>
                      <router-link to="/tasks">跟踪</router-link>
                    </article>
                  </div>
                </div>
              </div>
            </article>
          </div>
          <form class="chat-composer home-chat-composer" @submit.prevent="dispatchQuickCommand">
            <textarea
              v-model="quickCommand"
              placeholder="输入消息"
              @keydown.enter.prevent="dispatchQuickCommand"
            ></textarea>
            <button type="submit">
              <n-icon :size="17"><Send /></n-icon>
              发送
            </button>
          </form>
        </section>
      </main>

      <aside class="home-side">
        <section class="home-side-panel collaborators">
          <div class="home-side-head">
            <h2>待协同对象 <span>（{{ homeCollaborators.length }} 人）</span></h2>
            <router-link to="/ai">查看全部</router-link>
          </div>
          <div class="home-collaborator-list">
            <article v-for="person in homeCollaborators" :key="person.name" class="home-collaborator">
              <div class="home-avatar">{{ person.name.slice(0, 1) }}</div>
              <div>
                <strong>{{ person.name }}</strong>
                <p>{{ person.role }} · 协同事项：{{ person.task }}</p>
              </div>
              <span>在线</span>
            </article>
          </div>
        </section>

        <section class="home-side-panel">
          <div class="home-side-head">
            <h2>建议处理顺序</h2>
            <button class="home-regenerate" @click="openHomePriorityRegenerate">
              <n-icon :size="15"><Refresh /></n-icon>
              重新生成
            </button>
          </div>
          <form v-if="showHomePriorityBasisInput" class="home-priority-basis-form" @submit.prevent="submitHomePriorityBasis">
            <input
              v-model="homePriorityBasisInput"
              type="text"
              placeholder="输入建议依据，如风险等级、资料缺口、截止时间"
            />
            <button type="submit">生成</button>
            <button type="button" @click="cancelHomePriorityBasis">取消</button>
          </form>
          <ol class="home-priority-list">
            <li v-for="item in homePriorityItems" :key="item.rank">
              <b :class="item.tone">{{ item.rank }}</b>
              <div>
                <strong>{{ item.title }}</strong>
                <p>影响：{{ item.effect }}</p>
              </div>
              <em :class="item.tone">{{ item.tag }}</em>
            </li>
          </ol>
        </section>

        <section class="home-side-panel home-activity-panel">
          <div class="home-side-head home-activity-head">
            <h2>协同动态</h2>
            <router-link to="/ai">更多</router-link>
          </div>
          <ol class="home-ai-feed">
            <li v-for="item in homeActivityFeed" :key="item.text">
              <span></span>
              <p>{{ item.text }}</p>
              <time>{{ item.time }}</time>
            </li>
          </ol>
          <div class="home-activity-foot">
            <span>更新于 2026-06-10 09:42:30</span>
            <b>自动刷新中</b>
          </div>
        </section>
      </aside>
    </section>

    <section v-else-if="section === 'ai'" class="chat-layout collaboration-screen">
      <aside class="conversation-list collab-sessions">
        <div class="conversation-head">
          <h2>会话列表</h2>
          <button class="new-session" @click="startNewSession">
            <n-icon :size="16"><Plus /></n-icon>
            新建会话
          </button>
        </div>

        <div class="session-groups">
          <section v-for="group in sessionGroups" :key="group.label" class="session-group">
            <h3>{{ group.label }}</h3>
            <article
              v-for="session in group.items"
              :key="session.id"
              :class="['session-item', { active: activeSessionId === session.id }]"
              @click="activeSessionId = session.id"
            >
              <div class="session-title-row">
                <strong :title="session.title">{{ session.title }}</strong>
                <n-icon v-if="group.pinned" :size="14"><Pin /></n-icon>
              </div>
              <time>{{ session.time }}</time>
              <span class="session-desc">{{ session.desc }}</span>
              <div class="session-meta">
                <span>{{ session.participantIds.length }} 人参与</span>
                <span>{{ session.taskIds.length }} 项工作</span>
              </div>
            </article>
          </section>
        </div>

        <div class="conversation-tools">
          <button title="会话设置"><n-icon :size="18"><Settings /></n-icon></button>
          <button title="搜索会话"><n-icon :size="18"><Search /></n-icon></button>
          <button title="筛选会话"><n-icon :size="18"><AdjustmentsHorizontal /></n-icon></button>
        </div>
      </aside>

      <main class="chat-panel collab-chat-panel">
        <div class="chat-head collab-chat-head">
          <div class="chat-title-block">
            <div class="collab-title-row">
              <h1 :title="activeSession?.title">{{ activeSession?.title }}</h1>
              <button class="title-chevron" title="切换会话信息">
                <n-icon :size="16"><ChevronDown /></n-icon>
              </button>
            </div>
            <div class="chat-subline">
              <span>创建于 {{ activeSession?.time }}</span>
              <span>{{ activeSession?.desc }}</span>
            </div>
          </div>
          <div class="chat-head-actions">
            <button title="生成会议纪要" :disabled="!activeSessionId" @click="createMeetingMinute">纪要</button>
            <button title="邀请参与人">
              <n-icon :size="18"><UserPlus /></n-icon>
            </button>
            <button title="更多">
              <n-icon :size="18"><Dots /></n-icon>
            </button>
          </div>
        </div>
        <div v-if="meetingMinute" class="meeting-minute"><strong>{{ meetingMinute.title }}</strong><p>{{ meetingMinute.summary }}</p><span>行动项 {{ meetingMinute.action_items?.length || 0 }} 项</span></div>

        <div class="messages collab-messages">
          <article
            v-for="message in activeChatMessages"
            :key="message.id"
            :class="['message-row', message.role, { 'has-generated': message.generatedTaskIds?.length }]"
          >
            <div class="message-avatar" aria-hidden="true">
              {{ message.role === 'assistant' ? '管' : '我' }}
            </div>
            <div class="message-stack">
              <div v-if="message.role === 'assistant'" class="message-role">
                <span>Dobby</span>
                <time>{{ message.role === 'assistant' ? '09:43' : '' }}</time>
              </div>
              <div class="message-bubble">
                <p>{{ message.content }}</p>
                <div v-if="message.generatedTaskIds?.length" class="generated-work">
                  <div class="generated-work-head">
                    <span>已生成工作（{{ tasksByIds(message.generatedTaskIds).length }}）</span>
                    <button>收起</button>
                  </div>
                  <div class="generated-task-grid">
                    <article v-for="task in tasksByIds(message.generatedTaskIds)" :key="task.id" class="generated-task-card">
                      <div class="generated-task-main">
                        <div class="generated-task-title">
                          <strong :title="task.title">{{ task.title }}</strong>
                          <em>{{ taskSourceLabel(task.type) }}</em>
                        </div>
                        <div class="generated-task-meta">
                          <span>责任人：{{ store.getMemberName(task.responsibleId) }}</span>
                          <span>截止：{{ formatDateTime(task.deadline, 'end') }}</span>
                        </div>
                        <div class="mini-track"><i :style="{ width: `${taskProgress(task.status)}%` }"></i></div>
                      </div>
                      <div class="generated-task-foot">
                        <span class="status-pill">{{ statusLabel(task.status) }}</span>
                        <router-link to="/tasks">跟踪</router-link>
                      </div>
                    </article>
                  </div>
                </div>
              </div>
            </div>
          </article>
        </div>

        <div v-if="chatSuggestionsOpen" class="suggestion-list chat-suggestion-panel">
          <button v-for="item in activeChatSuggestions" :key="item.label" type="button" @click="applyChatSuggestion(item.prompt)">
            <strong>{{ item.label }}</strong>
            <span>{{ item.desc }}</span>
          </button>
        </div>

        <div class="chat-input-toolbar">
          <div class="chat-input-tools">
            <button type="button" title="上传附件"><n-icon :size="18"><Paperclip /></n-icon></button>
            <button type="button" title="提及人员"><n-icon :size="18"><At /></n-icon></button>
            <button type="button" title="插入时间"><n-icon :size="18"><CalendarEvent /></n-icon></button>
          </div>
          <button class="suggestion-toggle" type="button" @click="toggleChatSuggestions">
            <n-icon :class="['suggestion-arrow', { open: chatSuggestionsOpen }]" :size="16"><ChevronDown /></n-icon>
            <span>{{ chatSuggestionsOpen ? '收起建议' : '查看建议' }}</span>
          </button>
        </div>

        <form class="chat-composer collab-composer" @submit.prevent="sendPrompt">
          <textarea v-model="prompt" placeholder="输入要查询的项目问题，或描述需要下发的任务..." @keydown.enter.prevent="sendPrompt"></textarea>
          <button class="send-button" type="submit">
            <n-icon :size="17"><Send /></n-icon>
            发送
          </button>
        </form>
      </main>

      <aside class="realtime-panel collab-side">
        <section class="panel flush collab-side-panel generated-side-panel">
          <div class="panel-head">
            <div>
              <h2>已生成任务</h2>
              <p>来自当前会话的跟踪任务</p>
            </div>
            <router-link to="/tasks">查看全部（{{ activeSessionTasks.length }}）</router-link>
          </div>
          <div class="session-task-list">
            <article v-for="task in activeSessionTasks" :key="task.id" class="session-task">
              <div class="session-task-head">
                <strong :title="task.title">{{ task.title }}</strong>
                <span>{{ statusLabel(task.status) }}</span>
              </div>
              <p>{{ store.getMemberName(task.responsibleId) }} · 截止 {{ formatDateTime(task.deadline, 'end') }}</p>
              <div class="task-progress-row">
                <div class="mini-track"><i :style="{ width: `${taskProgress(task.status)}%` }"></i></div>
                <em>{{ taskProgress(task.status) }}%</em>
              </div>
            </article>
          </div>
        </section>

        <section class="panel flush collab-side-panel">
          <div class="panel-head">
            <div>
              <h2>参与人</h2>
              <p>{{ activeSessionPeople.length }} 人参与本会话</p>
            </div>
            <button class="panel-text-button">管理</button>
          </div>
          <div class="participant-list">
            <article v-for="person in activeSessionPeople" :key="person.id" class="participant-row">
              <div class="avatar">{{ person.name.slice(0, 1) }}</div>
              <div>
                <strong>{{ person.name }} <span v-if="person.id === currentUserId">我</span></strong>
                <small>{{ person.title }}</small>
              </div>
            </article>
          </div>
        </section>

        <section class="panel flush collab-side-panel material-side-panel">
          <div class="panel-head">
            <div>
              <h2>资料缺项</h2>
              <p>已识别 {{ activeSessionMissingItems.length }} 类缺项</p>
            </div>
            <router-link to="/docs">查看详情</router-link>
          </div>
          <ul class="missing-material-list">
            <li v-for="item in activeSessionMissingItems" :key="item.name">
              <strong>{{ item.name }}</strong>
              <span>{{ item.source }}</span>
            </li>
          </ul>
        </section>

        <section class="panel flush collab-side-panel action-side-panel">
          <div class="panel-head">
            <div>
              <h2>处理动作</h2>
              <p>会话内可直接生成任务或资料动作</p>
            </div>
          </div>
          <div class="action-stack">
            <button v-for="item in sideActionItems" :key="item.label" @click="seedPrompt(item.prompt)">{{ item.label }}</button>
          </div>
        </section>
      </aside>
    </section>

    <section v-else-if="section === 'tasks'" class="page-stack task-page">
      <div class="task-filterbar">
        <span>当前显示 {{ filteredTasks.length }} / {{ store.tasks.length }} 条</span>
        <div class="filter-tabs">
          <button v-for="tab in taskTabs" :key="tab.key" :class="{ active: taskFilter === tab.key }" @click="taskFilter = tab.key">
            <span>{{ tab.label }}</span><b class="task-filter-count">{{ taskTabCounts[tab.key] }}</b>
          </button>
        </div>
        <button class="task-create-button" type="button" @click="taskCreateOpen = true">新建任务</button>
      </div>
      <div v-if="taskCreateOpen" class="workflow-modal-backdrop" @click.self="taskCreateOpen = false">
        <section class="workflow-modal task-flow-modal" role="dialog" aria-modal="true" aria-labelledby="task-create-title">
          <div class="workflow-modal-head">
            <div><h2 id="task-create-title">新建任务流</h2></div>
            <button type="button" class="modal-close" aria-label="关闭新建任务窗口" @click="taskCreateOpen = false">关闭</button>
          </div>
          <form class="task-flow-form" @submit.prevent="createManualTask">
            <section class="task-flow-global-settings">
              <div class="task-flow-global-head">
                <div class="task-flow-global-copy"><div><span>任务全局配置</span><strong>执行与触发设置</strong></div><p>以下设置作用于整个任务流，不属于任何单个节点。</p></div>
                <output class="task-flow-trigger-preview" aria-live="polite"><span>触发说明</span><strong>{{ taskTriggerSummary }}</strong></output>
              </div>
              <div class="task-flow-trigger-grid">
                <label class="form-field">执行方式<select v-model="taskCreateForm.run_mode"><option value="single">单次执行</option><option value="scheduled">定时执行</option></select></label>
                <label class="form-field">{{ taskCreateForm.run_mode === 'single' ? '执行日期与时间' : '首次触发日期与时间' }}<input v-model="taskExecutionAt" type="datetime-local" required></label>
                <label v-if="taskCreateForm.run_mode === 'scheduled'" class="form-field task-flow-interval-field">触发间隔<span><input v-model.number="taskCreateForm.trigger_interval_value" type="number" min="1" max="365" required><select v-model="taskCreateForm.trigger_interval_unit"><option value="hour">小时</option><option value="day">天</option><option value="week">周</option><option value="month">个月</option></select></span></label>
                <label class="form-field task-flow-cc-field">抄送人<input v-model.trim="taskCreateForm.cc" placeholder="输入姓名，多个用逗号分隔"></label>
              </div>
            </section>
            <div class="task-flow-body">
              <aside class="task-flow-brief">
                <div class="task-flow-mode-switch" aria-label="任务流生成方式">
                  <button type="button" :class="{ active: taskCreateMode === 'dobby' }" @click="taskCreateMode = 'dobby'">Dobby 生成</button>
                  <button type="button" :class="{ active: taskCreateMode === 'template' }" @click="taskCreateMode = 'template'">模板生成</button>
                </div>
                <section v-if="taskCreateMode === 'dobby'" class="task-flow-generator dobby-generator">
                  <div class="task-flow-section-title"><div><span>Dobby 任务流助手</span><strong>描述你想完成的工作</strong></div><em>自动解析</em></div>
                  <textarea v-model.trim="taskFlowRequirement" placeholder="例如：每周一检查基坑监测数据；接近预警值时由监测员复核，项目负责人确认，最后归档监测报告。"></textarea>
                  <div class="task-flow-examples"><button v-for="example in taskFlowExamples" :key="example" type="button" @click="taskFlowRequirement = example">{{ example }}</button></div>
                  <button type="button" class="task-flow-generate-button" :disabled="taskFlowGenerating || taskFlowRequirement.length < 4" @click="generateTaskFlowWithDobby">{{ taskFlowGenerating ? 'Dobby 正在设计流程…' : '让 Dobby 生成任务流' }}</button>
                  <p v-if="taskFlowGenerationNote" class="task-flow-generation-note">{{ taskFlowGenerationNote }}</p>
                </section>
                <section v-else class="task-flow-generator template-generator">
                  <div class="task-flow-section-title"><div><span>标准流程模板</span><strong>选择场景并生成基础节点</strong></div><em>可编辑</em></div>
                  <label class="form-field">任务场景<select v-model="taskTemplateType"><option v-for="item in taskTemplateOptions" :key="item" :value="item">{{ item }}</option></select></label>
                  <label class="form-field">任务主题<input v-model.trim="taskTemplateTopic" placeholder="例如：整改现场隐患并完成复核闭环"></label>
                  <button type="button" class="task-flow-generate-button" @click="generateTemplateTaskFlow">按模板生成流程</button>
                </section>
              </aside>
              <main class="task-flow-canvas">
                <div class="task-flow-canvas-head"><div><span>流程画布</span><h3>{{ taskCreateForm.title || '未命名任务流' }}</h3></div><p>{{ taskFlowSteps.length }} 个节点 · {{ taskCreateForm.run_mode === 'scheduled' ? '定时执行' : '单次执行' }}</p></div>
                <div class="task-flow-canvas-body">
                  <section class="task-flow-editor-panel">
                    <div class="task-flow-editor-head"><div><span>节点配置</span><strong>维护责任人、时间与交付物</strong></div><div class="task-flow-editor-actions"><em>使用上下按钮调整顺序</em><button type="button" class="task-flow-add-button" @click="addTaskFlowStep">＋ 添加节点</button></div></div>
                    <div class="task-flow-node-grid">
                      <article v-for="(step, index) in taskFlowSteps" :key="step.id" class="task-flow-node-card" :class="{ active: selectedTaskFlowStepIndex === index }" @click="selectedTaskFlowStepIndex = index">
                        <header><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ step.name || `节点 ${index + 1}` }}</strong><div><button type="button" :disabled="index === 0" title="上移" @click.stop="moveTaskFlowStep(index, -1)">↑</button><button type="button" :disabled="index === taskFlowSteps.length - 1" title="下移" @click.stop="moveTaskFlowStep(index, 1)">↓</button><button type="button" class="danger" :disabled="taskFlowSteps.length <= 2" title="删除" @click.stop="removeTaskFlowStep(index)">删除</button></div></header>
                        <div class="task-flow-node-fields"><label class="form-field">节点名称<input v-model.trim="step.name" required></label><label class="form-field">负责人<select v-model="step.owner_user_id"><option value="">待指定</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }}</option></select></label><label class="form-field">截止日期<input v-model="step.due_at" type="date"></label><label class="form-field">所需资料<input v-model.trim="step.material" placeholder="该节点的交付物或依据"></label></div>
                      </article>
                    </div>
                  </section>
                  <aside class="task-flow-preview-panel">
                    <div class="task-flow-preview-head"><span>节点预览</span><strong>流转顺序</strong><em>点击节点可定位配置</em></div>
                    <div class="task-flow-strip" aria-label="任务流转顺序">
                      <template v-for="(step, index) in taskFlowSteps" :key="step.id"><button type="button" class="task-flow-node" :class="{ active: selectedTaskFlowStepIndex === index }" @click="selectedTaskFlowStepIndex = index"><span>{{ index + 1 }}</span><strong>{{ step.name || `节点 ${index + 1}` }}</strong><em>{{ memberNameById(step.owner_user_id) }}</em></button><span v-if="index < taskFlowSteps.length - 1" class="task-flow-arrow" aria-hidden="true">↓</span></template>
                      <div v-if="!taskFlowSteps.length" class="task-flow-empty">从左侧生成任务流，或点击“添加节点”手动开始。</div>
                    </div>
                  </aside>
                </div>
              </main>
            </div>
            <div class="task-flow-footer"><p><strong>{{ taskFlowSteps.length }}</strong> 个流程节点，将按当前顺序依次执行并留痕。</p><div class="workflow-modal-actions"><button type="button" class="modal-secondary" @click="taskCreateOpen = false">取消</button><button type="submit" class="modal-primary" :disabled="!taskCreateForm.title || taskFlowSteps.length < 2">创建任务流</button></div></div>
          </form>
        </section>
      </div>
      <div class="task-board">
        <article v-for="task in filteredTasks" :key="task.id" class="task-card">
          <div class="task-top">
            <span :class="['level-tag', task.riskLevel]">{{ riskLabel(task.riskLevel) }}</span>
            <span class="status-pill">{{ statusLabel(task.status) }}</span>
          </div>
          <h2>{{ task.title }}</h2>
          <div class="task-source">来源：{{ taskSourceLabel(task.type) }}</div>
          <p>{{ task.triggerReason }}</p>
          <div class="task-meta">
            <span>负责人：{{ store.getMemberName(task.responsibleId) }}</span>
            <span>截止：{{ formatDateTime(task.deadline, 'end') }}</span>
            <span>缺项：{{ task.missingCount }}</span>
          </div>
          <ol v-if="task.workflowSteps.length" class="task-step-list">
            <li v-for="(step, index) in task.workflowSteps" :key="`${task.id}-${index}`" :class="step.status">
              <span>{{ index + 1 }}</span><strong>{{ step.name }}</strong><em>{{ taskStepLabel(step.status) }}</em>
              <button v-if="task.status === 'processing' && step.status !== 'completed'" type="button" @click="store.updateTaskStep(task.id, index, 'completed')">完成步骤</button>
            </li>
          </ol>
          <div class="task-actions">
            <router-link to="/ai">协同处理</router-link>
            <button type="button" @click="openTaskHistory(task.id)">处理记录</button>
            <button v-if="task.status === 'pending' || task.status === 'overdue'" @click="store.updateTaskStatus(task.id, 'processing')">开始处理</button>
            <button v-if="task.status === 'processing'" @click="store.updateTaskStatus(task.id, 'waiting_confirm')">提交确认</button>
            <button v-if="task.status === 'processing'" @click="store.updateTaskStatus(task.id, 'need_more_info')">需要补充</button>
            <button v-if="task.status === 'waiting_confirm'" @click="store.updateTaskStatus(task.id, 'processing')">退回处理</button>
            <button v-if="task.status === 'waiting_confirm'" class="done" @click="store.updateTaskStatus(task.id, 'done')">确认完成</button>
            <button v-if="task.status === 'need_more_info'" @click="store.updateTaskStatus(task.id, 'processing')">已补充，继续处理</button>
          </div>
        </article>
      </div>
      <div v-if="taskHistoryOpenId && selectedTaskHistoryTask" class="workflow-modal-backdrop" @click.self="closeTaskHistory">
        <section class="workflow-modal task-history-modal" role="dialog" aria-modal="true" aria-labelledby="task-history-title">
          <div class="workflow-modal-head">
            <div><h2 id="task-history-title">任务记录 - {{ selectedTaskHistoryTask.title }}</h2></div>
            <button type="button" class="modal-close" aria-label="关闭处理记录" @click="closeTaskHistory">关闭</button>
          </div>
          <div class="task-history-summary">
            <div><span>当前状态</span><strong>{{ statusLabel(selectedTaskHistoryTask.status) }}</strong></div>
            <div><span>负责人</span><strong>{{ store.getMemberName(selectedTaskHistoryTask.responsibleId) }}</strong></div>
            <div><span>截止时间</span><strong>{{ formatDateTime(selectedTaskHistoryTask.deadline, 'end') }}</strong></div>
          </div>
          <div class="task-history-body">
            <div v-if="taskHistoryLoading" class="task-history-loading">正在加载处理记录…</div>
            <ol v-else-if="(taskHistories[taskHistoryOpenId] || []).length" class="task-history-timeline">
              <li v-for="item in taskHistories[taskHistoryOpenId] || []" :key="item.id">
                <i aria-hidden="true"></i>
                <div><header><strong>{{ item.from_status ? `${statusLabel(item.from_status)} → ` : '' }}{{ statusLabel(item.to_status) }}</strong><time>{{ formatDateTime(item.created_at) }}</time></header><p>{{ item.note || '状态更新' }}</p></div>
              </li>
            </ol>
            <div v-else class="task-history-empty"><strong>暂无处理记录</strong><p>开始处理或更新任务状态后，系统会在这里自动留痕。</p></div>
          </div>
          <div class="workflow-modal-actions task-history-actions"><button type="button" class="modal-primary" @click="closeTaskHistory">完成查看</button></div>
        </section>
      </div>
    </section>

    <section v-else-if="section === 'project'" class="page-stack project-page project-status-view">
      <section class="project-kpi-strip" aria-label="项目状态指标">
        <article v-for="metric in projectStatusMetrics" :key="metric.label" :class="metric.tone">
          <div class="project-kpi-icon"><n-icon :size="22"><component :is="metric.icon" /></n-icon></div>
          <div><span>{{ metric.label }}</span><strong>{{ metric.value }}</strong><small>{{ metric.hint }}</small></div>
        </article>
      </section>

      <section class="project-health-band" aria-label="项目健康度概览">
        <article class="project-health-summary">
          <div class="project-health-gauge" :style="{ '--health-progress': `${projectHealth.actual}%` }"><div><strong>{{ projectHealthGrade }}</strong><small>项目健康度</small></div></div>
          <div class="project-health-copy"><span>项目健康度评估</span><p>{{ projectHealth.conclusion }}</p><small>根据进度、风险、质量和任务闭环状态综合判断。</small></div>
        </article>
        <dl class="project-health-data">
          <div class="project-progress-compare"><dt>进度对比</dt><div class="progress-compare-values"><span><small>计划</small><b>{{ projectHealth.planned }}%</b></span><span><small>实际</small><b>{{ projectHealth.actual }}%</b></span></div><dd :class="projectHealth.delta >= 0 ? 'positive' : 'negative'"><small>差异</small><strong>{{ projectHealth.delta >= 0 ? '+' : '' }}{{ projectHealth.delta }}%</strong></dd></div>
          <div><dt>任务完成率</dt><dd>{{ projectHealth.taskCompletion }}%</dd><div class="project-health-progress"><i><em :style="{ width: `${projectHealth.taskCompletion}%` }" /></i><small>已完成 {{ projectHealth.doneTasks }} / {{ projectHealth.totalTasks }}</small></div></div>
          <div class="project-health-conclusion"><dt>关键结论</dt><dd>{{ projectHealth.label }}</dd><small>{{ projectHealth.summary }}</small></div>
        </dl>
      </section>

      <nav class="project-status-tabs" aria-label="项目状态视图">
        <button v-for="tab in projectStatusTabs" :key="tab.key" type="button" :class="{ active: projectStatusTab === tab.key }" @click="projectStatusTab = tab.key"><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <section class="project-status-content">
        <main class="project-status-main">
          <section v-if="projectStatusTab === 'latest'" class="status-workspace status-latest-workspace">
            <header class="status-workspace-head"><div><span>最新动态</span><h2>项目多源信息</h2><p>汇集群消息、日报、照片、平台导出、会议纪要和工程文件；待确认信息在此完成处置。</p></div><small>{{ statusLatestItems.length }} 条</small></header>
            <div v-if="statusLatestItems.length" class="status-latest-list"><article v-for="item in statusLatestItems" :key="item.id"><i :class="['status-event-dot', item.tone]" /><div><strong>{{ item.title }}</strong><p>{{ item.sourceType }} · {{ item.content }}</p></div><em :class="item.tone">{{ item.status }}</em><time>{{ item.time }}</time><button v-if="item.canDispose" type="button" class="status-row-action" @click="openInformationDisposition(item.recordId)">处置</button><span v-else class="status-row-placeholder" /></article></div><p v-else class="status-empty">当前还没有项目最新信息。接入群消息、日报、照片或平台导出后，将在此等待核验和处置。</p>
          </section>

          <section v-else-if="projectStatusTab === 'process'" class="status-workspace status-process-workspace">
            <header class="status-workspace-head"><div><span>过程监管</span><h2>当前工序过程监管</h2><p>逐项核对今日进度、质量验收数据、关联风险和现场关注点。</p></div><small>{{ processSupervisionRows.length }} 项</small></header>
            <div v-if="processSupervisionRows.length" class="process-supervision-table"><div class="process-supervision-head"><span>工序</span><span>状态</span><span>今日进度</span><span>质量验收</span><span>关联风险</span><span>关注点</span></div><article v-for="item in processSupervisionRows" :key="item.id"><div><small>{{ item.code }}</small><strong>{{ item.name }}</strong></div><div class="process-progress"><b>{{ item.progressStatus }}</b><i><em :style="{ width: `${item.progress}%` }" /></i><small>{{ item.progress }}% · 昨日：{{ item.yesterday }}</small></div><div>{{ item.today }}</div><div>{{ item.quality }}</div><div :class="['process-risk', item.riskTone]">{{ item.risk }}</div><div>{{ item.focus }}</div></article></div><p v-else class="status-empty">尚未维护 WBS 工序。可在“工程配置 → 人工配置”中补充项目工序。</p>
          </section>

          <section v-else-if="projectStatusTab === 'execution'" class="status-workspace status-execution-workspace">
            <header class="status-workspace-head"><div><span>任务执行</span><h2>项目任务执行状态</h2><p>聚焦项目任务的当前阶段、关联 WBS 或风险、负责人和计划闭环节点。</p></div><small>{{ projectExecutionTasks.length }} 项</small></header>
            <div v-if="projectExecutionTasks.length" class="status-execution-table"><div class="status-execution-head"><span>状态</span><span>任务标题</span><span>关联 WBS / 风险</span><span>负责人</span><span>计划完成</span><span>闭环阶段</span></div><article v-for="task in projectExecutionTasks" :key="task.id"><div><span :class="['execution-status', task.status]">{{ projectTaskStatusLabel(task.status) }}</span></div><div><strong>{{ task.title }}</strong><small>{{ taskPhaseLabel(task) }} · 所需材料：{{ taskMaterialLabel(task) }}</small></div><div>{{ taskRelationLabel(task) }}</div><div>{{ store.getMemberName(task.responsibleId) }}</div><div><strong :class="{ overdue: task.status === 'overdue' }">{{ task.deadline }}</strong><small>{{ task.status === 'overdue' ? '已逾期，需优先处理' : task.triggerReason || '按计划推进' }}</small></div><div><span :class="['closure-status', taskClosureTone(task)]">{{ taskClosureLabel(task) }}</span></div></article></div><p v-else class="status-empty">当前没有项目任务。</p>
          </section>

          <section v-else class="status-workspace status-change-workspace">
            <header class="status-workspace-head"><div><span>工程变更</span><h2>工程变更记录</h2><p>保留项目已记录变更及其对应的证据文件，便于快速追溯。</p></div><small>{{ store.projectChanges.length }} 条</small></header>
            <div v-if="store.projectChanges.length" class="status-change-list"><article v-for="item in store.projectChanges" :key="item.id"><div><span>{{ item.category }}</span><strong>{{ item.title }}</strong><p>{{ item.content }}</p></div><em>{{ item.source_refs?.join('、') || '未关联证据' }}</em><time>{{ statusTimeLabel(item.created_at) }}</time></article></div><p v-else class="status-empty">当前没有工程变更记录。</p>
          </section>
        </main>
      </section>

      <div v-if="informationDispositionOpen && selectedInformationRecord" class="workflow-modal-backdrop" @click.self="closeInformationDisposition">
        <section class="workflow-modal information-disposition-modal" role="dialog" aria-modal="true" aria-labelledby="information-disposition-title">
          <div class="workflow-modal-head"><div><h2 id="information-disposition-title">信息处置</h2></div><button type="button" class="modal-close" aria-label="关闭信息处置窗口" @click="closeInformationDisposition">关闭</button></div>
          <div class="information-disposition-content"><strong>{{ selectedInformationRecord.sourceName }}</strong><div class="information-disposition-meta"><span>{{ selectedInformationRecord.sourceType }}</span><span>{{ selectedInformationRecord.status }}</span><span>置信度 {{ selectedInformationRecord.confidence }}</span><span>{{ selectedInformationRecord.author || '来源待补充' }}</span></div><p>{{ selectedInformationRecord.content }}</p><label class="form-field">修订信息<textarea v-model.trim="informationRevision" placeholder="修订信息，例如：S3测斜位移需以监测单位原始记录为准"></textarea></label></div>
          <div class="workflow-modal-actions"><button type="button" class="modal-secondary" @click="disposeInformation('confirm')">确认</button><button type="button" class="modal-secondary" @click="disposeInformation('deny')">否认</button><button type="button" class="modal-primary" :disabled="!informationRevision" @click="disposeInformation('revise')">修订</button></div>
        </section>
      </div>
    </section>

    <section v-else class="page-stack docs-page">
      <section class="document-intake-panel">
        <div>
          <span>资料入库</span>
          <h2>上传工程资料</h2>
          <p>文件会归属当前项目，自动识别资料类别；同名文件将保留版本记录和上传留痕。</p>
        </div>
        <label class="document-upload-button" :class="{ disabled: documentUploading }">
          <input type="file" :disabled="documentUploading" @change="uploadDocument">
          {{ documentUploading ? '正在入库…' : '选择并上传文件' }}
        </label>
      </section>
      <form class="document-search-panel" @submit.prevent="searchDocuments">
        <input v-model.trim="documentSearchKeyword" placeholder="检索文件名或已提取的文本内容，例如：基坑、监测、验收">
        <button type="submit" :disabled="documentSearching">{{ documentSearching ? '检索中…' : '检索资料' }}</button>
      </form>
      <section v-if="documentSearchKeyword" class="panel document-search-results">
        <div class="panel-head"><div><h2>资料检索结果</h2><p>{{ documentSearchResults.length }} 条匹配；结果包含文件信息与文本命中片段。</p></div></div>
        <div class="document-list"><article v-for="item in documentSearchResults" :key="item.id"><span>{{ item.category }}</span><strong>{{ item.fileName }}</strong><p>{{ item.snippet || `版本 V${item.version} · 未提取文本或仅匹配文件名` }}</p><em>V{{ item.version }}</em></article><p v-if="!documentSearching && !documentSearchResults.length" class="empty-document-note">未找到匹配资料。</p></div>
      </section>
      <div class="docs-work-grid">
        <article v-for="item in docWorkItems" :key="item.label" class="doc-work-card">
          <div>
            <span>{{ item.label }}</span>
            <strong>{{ item.title }}</strong>
            <p>{{ item.desc }}</p>
          </div>
          <router-link :to="item.to">{{ item.action }}</router-link>
        </article>
      </div>
      <div class="doc-grid">
        <article v-for="doc in documentCards" :key="doc.title" class="doc-card">
          <div class="doc-icon">
            <n-icon :size="20"><component :is="doc.icon" /></n-icon>
          </div>
          <div>
            <h2>{{ doc.title }}</h2>
            <p>{{ doc.desc }}</p>
          </div>
          <strong>{{ doc.count }}</strong>
        </article>
      </div>
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>最近资料流</h2>
            <p>日报、草稿和填报包的最近记录</p>
          </div>
        </div>
        <div class="document-list">
          <article v-for="item in recentDocuments" :key="item.name">
            <span>{{ item.type }}</span>
            <strong>{{ item.name }}</strong>
            <p>{{ item.desc }}</p>
            <em>{{ item.state }}</em>
          </article>
        </div>
      </section>
      <section class="panel document-storage-panel">
        <div class="panel-head">
          <div><h2>已入库资料</h2><p>当前项目的文件、类别和版本</p></div>
          <strong>{{ store.attachments.length }} 个文件</strong>
        </div>
        <div class="document-list">
          <article v-for="item in store.attachments.slice(0, 8)" :key="item.id">
            <span>{{ item.category }}</span>
            <strong>{{ item.fileName }}</strong>
            <p>版本 V{{ item.version }} · {{ formatFileSize(item.fileSize) }}</p>
            <em>{{ formatDateTime(item.createdAt, 'end') }}</em>
            <button v-if="item.category === '日报'" type="button" class="document-action" @click="store.parseDailyAttachment(item.id)">登记日报</button>
          </article>
          <p v-if="!store.attachments.length" class="empty-document-note">暂无已入库资料，可上传日报、监测记录、现场照片或工程文件。</p>
        </div>
      </section>
      <section class="panel document-review-panel">
        <div class="panel-head">
          <div><h2>日报确认队列</h2><p>确认后日报将正式进入项目资料流；任务中心同步保留处理记录。</p></div>
          <strong>{{ store.pendingDailyReports.length }} 待确认</strong>
        </div>
        <div class="document-list">
          <article v-for="report in store.pendingDailyReports" :key="report.id">
            <span>日报</span>
            <strong>{{ report.fileName }}</strong>
            <p>{{ report.constructionContent || '待补充施工内容' }}</p>
            <em>匹配置信度 {{ Math.round(report.confidence * 100) }}%</em>
            <button type="button" class="document-action confirm" @click="store.confirmDailyReport(report.id)">确认入库</button>
          </article>
          <p v-if="!store.pendingDailyReports.length" class="empty-document-note">暂无待确认日报。上传后点击“登记日报”即可生成确认任务。</p>
        </div>
      </section>
      <section class="panel document-review-panel">
        <div class="panel-head">
          <div><h2>风险草稿与填报</h2><p>将风险材料整理为可审核草稿，确认后生成平台填报包并留存状态。</p></div>
          <button type="button" class="document-action confirm" @click="draftCreateOpen = true">新建草稿</button>
        </div>
        <div class="document-list">
          <article v-for="draft in store.riskDrafts" :key="draft.id">
            <span>草稿</span>
            <strong>{{ draft.title }}</strong>
            <p>{{ draft.content }}</p>
            <em>{{ draftStatusLabel(draft.status) }}</em>
            <div class="document-actions">
              <button v-if="draft.status === 'draft' || draft.status === 'rejected'" type="button" class="document-action" @click="store.submitDraftReview(draft.id)">提交审核</button>
              <template v-else-if="draft.status === 'reviewing'">
                <button type="button" class="document-action confirm" @click="store.confirmDraft(draft.id)">确认</button>
                <button type="button" class="document-action" @click="store.rejectDraft(draft.id, '请补充材料后重新提交')">退回</button>
              </template>
              <button v-else-if="draft.status === 'confirmed'" type="button" class="document-action confirm" @click="createDefaultFillPackage(draft.id, draft.title, draft.content)">生成填报包</button>
            </div>
          </article>
          <p v-if="!store.riskDrafts.length" class="empty-document-note">暂无风险草稿。请先在工程配置中建立风险源，或直接新建草稿。</p>
        </div>
        <div v-if="draftCreateOpen" class="workflow-modal-backdrop" @click.self="draftCreateOpen = false">
          <section class="workflow-modal draft-create-modal" role="dialog" aria-modal="true" aria-labelledby="draft-create-title">
            <div class="workflow-modal-head">
              <div><h2 id="draft-create-title">新建风险草稿</h2></div>
              <button type="button" class="modal-close" aria-label="关闭新建风险草稿窗口" @click="draftCreateOpen = false">关闭</button>
            </div>
            <form class="draft-create-form" @submit.prevent="createRiskDraft">
              <label class="form-field">关联风险源<select v-model="draftCreateForm.risk_source_id" required><option value="">请选择风险源</option><option v-for="risk in store.riskSources" :key="risk.id" :value="risk.id">{{ risk.name }}</option></select></label>
              <label class="form-field">草稿标题<input v-model.trim="draftCreateForm.title" required placeholder="例如：深基坑支护施工风险上报"></label>
              <label class="form-field draft-form-content">草稿内容<textarea v-model.trim="draftCreateForm.content" required placeholder="填写风险说明、处置建议和资料依据"></textarea></label>
              <div class="workflow-modal-actions"><button type="button" class="modal-secondary" @click="draftCreateOpen = false">取消</button><button type="button" class="modal-assist" :disabled="!draftCreateForm.risk_source_id" @click="assistRiskDraft">智能生成</button><button type="submit" class="modal-primary">保存草稿</button></div>
            </form>
          </section>
        </div>
        <div v-if="store.fillPackages.length" class="document-list fill-package-list">
          <article v-for="item in store.fillPackages" :key="item.id">
            <span>填报</span>
            <strong>{{ item.processName }}</strong>
            <p>{{ item.platformName }} · {{ item.fields.length }} 个映射字段</p>
            <em>{{ fillStatusLabel(item.status) }}</em>
            <div class="document-actions">
              <button v-if="item.status === 'pending'" type="button" class="document-action" @click="store.startFilling(item.id)">开始填报</button>
              <button v-if="item.status === 'filling'" type="button" class="document-action confirm" @click="store.markFillDone(item.id)">标记已提交</button>
            </div>
          </article>
        </div>
      </section>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NIcon, useMessage } from 'naive-ui'
import {
  AdjustmentsHorizontal, At, CalendarEvent, ChartBar, ChevronDown, ChevronLeft, ChevronRight,
  Dots, FileText, Folder, ListCheck, Notes, Paperclip, Pin, Plus, Refresh, Robot,
  Search, Send, Settings, Table, User, UserPlus,
} from '@vicons/tabler'
import { useAppStore, type AttachmentRecord } from '@/stores/app'
import api, { type ApiEnvelope } from '@/api/client'
import type { DraftStatus, FillStatus, Member, RiskLevel, Task, TaskStatus } from '@/types'

type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  generatedTaskIds?: string[]
}

type CollaborationSession = { id: string; title: string; desc: string; time: string; participantIds: string[]; taskIds: string[] }
type ApiCollaborationSession = { id: number; title: string; summary?: string; participant_ids: number[]; task_ids: number[]; created_at: string; updated_at: string }
type ApiCollaborationMessage = { id: number; role: 'assistant' | 'user'; content: string; generated_task_ids: number[]; created_at: string }
type TaskFlowStepDraft = { id: string; name: string; owner_user_id: string; due_at: string; material: string }
type TriggerIntervalUnit = 'hour' | 'day' | 'week' | 'month'
type GeneratedTaskFlow = {
  title: string
  task_type: Task['type']
  risk_level: RiskLevel
  assignee_user_id?: number | null
  confirmer_user_id?: number | null
  wbs_item_id?: number | null
  risk_source_id?: number | null
  run_mode: 'single' | 'scheduled'
  trigger_date: string
  trigger_time: string
  trigger_rule: string
  trigger_interval_value: number
  trigger_interval_unit: TriggerIntervalUnit
  cc: string
  steps: Array<{ name: string; owner_user_id?: number | null; due_at?: string; material?: string }>
  generated_by: 'ai' | 'rules'
  generation_note: string
}

type ChatSuggestion = {
  label: string
  desc: string
  prompt: string
}
type ProjectStatusTab = 'latest' | 'process' | 'execution' | 'changes'
type ProjectStatusEvent = { id: string; recordId: string; tone: 'teal' | 'orange' | 'red' | 'blue'; sourceType: string; status: string; confidence: string; title: string; content: string; time: string; canDispose: boolean }

const route = useRoute()
const store = useAppStore()
const message = useMessage()

const section = computed(() => {
  const name = String(route.name || '')
  if (name === 'AiWorkspace') return 'ai'
  if (name === 'TaskManagement') return 'tasks'
  if (name === 'ProjectStatus') return 'project'
  if (name === 'EngineeringDocs') return 'docs'
  return 'home'
})

const currentProject = computed(() => store.currentProject)
const currentUserId = 'm1'
const projectProgress = computed(() => {
  if (!store.wbsItems.length) return 0
  return Math.round(store.wbsItems.reduce((sum, item) => sum + item.progress, 0) / store.wbsItems.length)
})
const focusTasks = computed(() => store.tasks.filter(task => ['overdue', 'pending', 'processing', 'waiting_confirm'].includes(task.status)))
const importantWbs = computed(() => store.wbsItems.filter(item => item.level <= 2).slice(0, 5))
const activeWbs = computed(() => store.wbsItems.find(item => item.status === 'in_progress' && item.level > 1) ?? store.wbsItems.find(item => item.status === 'in_progress') ?? importantWbs.value[0])
const criticalRisks = computed(() => store.riskSources.filter(risk => risk.level === 'critical' || risk.level === 'high'))
const projectStatusTab = ref<ProjectStatusTab>('execution')
const projectStatusTabs: Array<{ key: ProjectStatusTab; label: string; hint: string }> = [
  { key: 'latest', label: '最新信息', hint: '采集记录与处理' },
  { key: 'process', label: '过程监管', hint: '工序、质量与风险' },
  { key: 'execution', label: '任务执行', hint: '阶段、材料与闭环' },
  { key: 'changes', label: '工程变更', hint: '变更留痕' },
]
const actualProgress = computed(() => store.dashboard?.progress_rate ?? projectProgress.value)
const plannedProgress = computed(() => {
  const planned = store.wbsItems.filter(item => item.planStart && item.planEnd).map(item => {
    const start = Date.parse(item.planStart)
    const end = Date.parse(item.planEnd)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return item.progress
    return Math.max(0, Math.min(100, Math.round(((Date.now() - start) / (end - start)) * 100)))
  })
  return planned.length ? Math.round(planned.reduce((sum, value) => sum + value, 0) / planned.length) : actualProgress.value
})
const projectHealth = computed(() => {
  const totalTasks = store.tasks.length
  const doneTasks = store.tasks.filter(task => task.status === 'done').length
  const taskCompletion = store.dashboard?.task_completion_rate ?? (totalTasks ? Math.round((doneTasks / totalTasks) * 100) : 0)
  const delta = actualProgress.value - plannedProgress.value
  const needsAttention = store.tasks.some(task => task.status === 'overdue') || criticalRisks.value.some(risk => risk.level === 'critical')
  const label = store.dashboard?.overall || (needsAttention ? '需重点跟进' : criticalRisks.value.length ? '风险可控' : '整体平稳')
  const safetyIssues = store.dashboard?.safety_issues ?? 0
  const qualityIssues = store.dashboard?.quality_issues ?? store.qualityMetrics.filter(item => item.status === 'failed').length
  const mainRisk = store.dashboard?.main_risk || criticalRisks.value[0]?.name || '暂无新增风险预警'
  const mainSafety = store.dashboard?.main_safety || (safetyIssues ? `有 ${safetyIssues} 项安全事项待核查` : '暂无新增安全隐患')
  const mainQuality = store.dashboard?.main_quality || (qualityIssues ? `有 ${qualityIssues} 项质量事项待复核` : '暂无待复核质量问题')
  const plannedDelta = store.dashboard?.planned_delta || (delta >= 0 ? `超前 ${delta}%` : `滞后 ${Math.abs(delta)}%`)
  const summary = `目前进度 ${actualProgress.value}%，与周计划进度相比${plannedDelta}。主要风险关注：${mainRisk}。主要安全问题：${mainSafety}。存在的质量问题：${mainQuality}。任务完成率 ${taskCompletion}%，总体评价：${label}。`
  const conclusion = criticalRisks.value.length
    ? `重点关注 ${criticalRisks.value.slice(0, 2).map(item => item.name).join('、')}。`
    : focusTasks.value.length
      ? `当前有 ${focusTasks.value.length} 项待办需要持续推进。`
      : '暂无未闭环的重点事项。'
  return { label, summary, planned: plannedProgress.value, actual: actualProgress.value, delta, taskCompletion, doneTasks, totalTasks, conclusion }
})
const projectHealthGrade = computed(() => {
  if (criticalRisks.value.some(item => item.level === 'critical') || store.tasks.some(task => task.status === 'overdue')) return '关注'
  if (criticalRisks.value.length || (store.dashboard?.safety_issues ?? 0) || (store.dashboard?.quality_issues ?? 0)) return '可控'
  return '良好'
})
const projectStatusMetrics = computed(() => [
  { label: '进度完成率', value: `${actualProgress.value}%`, hint: `计划 ${plannedProgress.value}%`, icon: ChartBar, tone: actualProgress.value >= plannedProgress.value ? 'teal' : 'orange' },
  { label: '风险预警数', value: store.dashboard?.risk_warnings ?? criticalRisks.value.length, hint: criticalRisks.value.length ? '当前存在重点风险' : '当前无重点风险', icon: Pin, tone: criticalRisks.value.length ? 'orange' : 'teal' },
  { label: '安全隐患数', value: store.dashboard?.safety_issues ?? 0, hint: (store.dashboard?.safety_issues ?? 0) ? '待核查安全事项' : '暂无新增安全隐患', icon: UserPlus, tone: (store.dashboard?.safety_issues ?? 0) ? 'orange' : 'teal' },
  { label: '质量问题数', value: store.dashboard?.quality_issues ?? store.qualityMetrics.filter(item => item.status === 'failed').length, hint: (store.dashboard?.quality_issues ?? 0) ? '待复核质量事项' : '暂无待复核质量问题', icon: Notes, tone: (store.dashboard?.quality_issues ?? 0) ? 'orange' : 'teal' },
  { label: '待办任务数', value: focusTasks.value.length, hint: focusTasks.value.length ? '未完成事项' : '暂无待办事项', icon: ListCheck, tone: focusTasks.value.length ? 'blue' : 'teal' },
  { label: '逾期任务', value: store.tasks.filter(task => task.status === 'overdue').length, hint: store.tasks.some(task => task.status === 'overdue') ? '需要优先处置' : '当前无逾期任务', icon: CalendarEvent, tone: store.tasks.some(task => task.status === 'overdue') ? 'red' : 'teal' },
])
const statusLatestItems = computed<ProjectStatusEvent[]>(() => {
  const records = store.informationRecords || []
  return records.map(item => ({
    id: `information-${item.id}`,
    recordId: item.id,
    tone: item.status === '待确认' || item.status === '待复核' ? 'orange' : item.status === '已否认' ? 'red' : item.sourceType === '平台导出' ? 'blue' : 'teal',
    sourceType: item.sourceType,
    status: item.status,
    confidence: item.confidence,
    title: item.sourceName,
    content: item.content,
    time: item.recordedAt,
    canDispose: item.status === '待确认' || item.status === '待复核',
  }))
})
const processSupervisionRows = computed(() => store.wbsItems.slice().sort((a, b) => a.code.localeCompare(b.code, 'zh-CN')).slice(0, 12).map(item => {
  const metric = store.qualityMetrics.find(candidate => candidate.wbsId === item.id)
  const link = store.wbsRiskLinks.find(candidate => candidate.wbsId === item.id)
  const risk = link ? store.riskSources.find(candidate => candidate.id === link.riskId) : undefined
  const task = store.tasks.find(candidate => candidate.linkedWbsIds.includes(item.id) && candidate.status !== 'done')
  const supervision = item.supervision
  const quality = supervision?.quality || (metric ? `${metric.name}：${metric.requirement || qualityStatusLabel(metric.status)}` : '暂未配置质量验收数据')
  const riskText = supervision?.risk || (risk ? `${riskLabel(risk.level)}风险：${risk.name}${risk.controlMeasures ? `；${risk.controlMeasures}` : ''}` : '暂无关联风险数据')
  const key = supervision?.key ?? (Boolean(risk && ['critical', 'high'].includes(risk.level)) || task?.status === 'overdue' || item.status === 'delayed')
  return { id: item.id, code: item.code, name: item.name, progress: item.progress, yesterday: supervision?.yesterday || (item.actualStart ? `已于 ${item.actualStart} 开工，累计完成 ${item.progress}%` : '暂无昨日日报记录'), today: supervision?.today || (item.status === 'in_progress' ? `按计划推进，当前累计完成 ${item.progress}%` : item.status === 'done' ? '工序已完成，等待资料归档或复核' : item.status === 'delayed' ? '当前进度滞后，需核对计划与处置措施' : '尚未启动，待满足开工条件'), quality, risk: riskText, focus: supervision?.focus || task?.title || '暂无待办事项', riskTone: risk?.level || (item.status === 'delayed' ? 'high' : 'low'), progressStatus: item.status === 'delayed' ? '滞后' : item.status === 'done' ? '已完成' : item.status === 'in_progress' ? '正常' : '待启动', key }
}))
const projectExecutionTasks = computed(() => {
  const rank: Record<string, number> = { overdue: 0, need_more_info: 1, pending: 2, processing: 3, waiting_confirm: 4, done: 5, cancelled: 6 }
  return store.tasks.slice().sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || a.deadline.localeCompare(b.deadline)).slice(0, 20)
})

const myAttentionTasks = computed(() =>
  focusTasks.value.filter(task =>
    task.responsibleId === currentUserId ||
    task.confirmatorId === currentUserId ||
    task.status === 'overdue'
  ).slice(0, 4)
)

const myWorkQueue = computed(() =>
  myAttentionTasks.value.map(task => ({
    id: task.id,
    tag: taskTypeLabel(task.type),
    title: task.title,
    desc: task.triggerReason,
    owner: `责任人：${store.getMemberName(task.responsibleId)}`,
    deadline: `截止：${formatDateTime(task.deadline, 'end')}`,
    state: statusLabel(task.status),
    action: task.missingCount > 0 ? '补充资料' : task.status === 'waiting_confirm' ? '进入确认' : '进入会话',
    to: task.missingCount > 0 ? '/docs' : '/ai',
  }))
)

const homeMode = ref<'work' | 'quick'>('work')
const homeModeTabs = [
  { key: 'work' as const, label: '待处理工作' },
  { key: 'quick' as const, label: '快捷协同' },
]
const homeFilter = ref<'all' | 'decision' | 'upload' | 'generated'>('all')
const homePageIndex = ref(0)
const homePageSize = ref(5)
const homeQueueViewport = ref<HTMLElement | null>(null)
const homeWorkItems = computed(() => [
  {
    id: 'home-1',
    rank: 1,
    category: 'decision',
    label: '需我决策',
    title: '深基坑风险草稿审核',
    reason: '原因：已生成风险草稿，需要你确认关键结论与管控措施。',
    tags: ['风险等级 重大', '关联 WBS', '基坑开挖'],
    owner: '王芳',
    role: '资料与填报负责人',
    deadline: '截止 2026-06-10 18:00:00',
    action: '协同处理',
    to: '/ai',
    tone: 'danger',
    icon: Notes,
  },
  {
    id: 'home-2',
    rank: 2,
    category: 'upload',
    label: '需我上传资料',
    title: '地面沉降监测材料缺项',
    reason: '原因：检测到风险草稿缺少关键监测报告，请尽快补充。',
    tags: ['缺项资料', '地表沉降监测报告'],
    owner: '李明',
    role: '项目执行人',
    deadline: '截止 2026-06-10 18:00:00',
    action: '上传关键资料',
    to: '/docs',
    tone: 'upload',
    icon: Folder,
  },
  {
    id: 'home-3',
    rank: 3,
    category: 'generated',
    label: '需我协同',
    title: '日报解析确认（2026-06-09 施工日报）',
    reason: '原因：已解析日报，需确认关键进度与风险引用是否正确。',
    tags: ['关联 WBS', '基坑开挖', '置信度 85%'],
    owner: '王芳',
    role: '资料与填报负责人',
    deadline: '截止 2026-06-10 18:00:00',
    action: '协同处理',
    to: '/ai',
    tone: 'warning',
    icon: FileText,
  },
  {
    id: 'home-4',
    rank: 4,
    category: 'upload',
    label: '需我上传资料',
    title: '顶管推进偏差预警相关资料',
    reason: '原因：检测到预警阈值需佐证资料，请补充测量记录。',
    tags: ['缺项资料', '顶管测量记录', '纠偏记录'],
    owner: '李明',
    role: '项目执行人',
    deadline: '截止 2026-06-11 09:00:00',
    action: '上传关键资料',
    to: '/docs',
    tone: 'upload',
    icon: Folder,
  },
  {
    id: 'home-5',
    rank: 5,
    category: 'generated',
    label: '需我协同',
    title: '重大风险动态管控月报填报启动',
    reason: '原因：已生成填报包草案，需要你确认范围与责任人。',
    tags: ['填报包', '2026 年 6 月', '周期 月报'],
    owner: '张伟',
    role: '项目现场负责人',
    deadline: '截止 2026-06-12 18:00:00',
    action: '协同处理',
    to: '/ai',
    tone: 'warning',
    icon: FileText,
  },
  {
    id: 'home-6',
    rank: 6,
    category: 'decision',
    label: '需我协调',
    title: '接收井施工验收准备会',
    reason: '原因：建议召开准备会，协调参与人并确认时间。',
    tags: ['建议时间', '2026-06-11 14:00'],
    owner: '涉及 3 人',
    role: '张伟、李明、王芳',
    deadline: '建议 2026-06-11 14:00',
    action: '发起协调',
    to: '/ai',
    tone: 'info',
    icon: ListCheck,
  },
])
const filteredHomeWorkItems = computed(() =>
  homeFilter.value === 'all'
    ? homeWorkItems.value
    : homeWorkItems.value.filter(item => item.category === homeFilter.value)
)
const homePageCount = computed(() =>
  Math.max(1, Math.ceil(filteredHomeWorkItems.value.length / homePageSize.value))
)
const pagedHomeWorkItems = computed(() => {
  const start = homePageIndex.value * homePageSize.value
  return filteredHomeWorkItems.value.slice(start, start + homePageSize.value)
})
const homePageRangeText = computed(() => {
  const total = filteredHomeWorkItems.value.length
  if (!total) return '0 / 0'
  const start = homePageIndex.value * homePageSize.value + 1
  const end = Math.min(start + homePageSize.value - 1, total)
  return `${start}-${end} / ${total}`
})
const homeFilterTabs = computed(() => [
  { key: 'all' as const, label: '全部', count: homeWorkItems.value.length },
  { key: 'decision' as const, label: '需我决策', count: homeWorkItems.value.filter(item => item.category === 'decision').length },
  { key: 'upload' as const, label: '需我上传资料', count: homeWorkItems.value.filter(item => item.category === 'upload').length },
  { key: 'generated' as const, label: '需我协同', count: homeWorkItems.value.filter(item => item.category === 'generated').length },
])
const homePrimaryAction = computed(() =>
  homeMode.value === 'work'
    ? { label: '进入任务管理', to: '/tasks', icon: ListCheck }
    : { label: '进入智能协同', to: '/ai', icon: Send }
)

function clampHomePageIndex() {
  homePageIndex.value = Math.min(homePageIndex.value, homePageCount.value - 1)
}

function goHomePage(direction: number) {
  homePageIndex.value = Math.min(Math.max(homePageIndex.value + direction, 0), homePageCount.value - 1)
}

function updateHomePageSize() {
  const measuredHeight = homeQueueViewport.value?.clientHeight ?? 0
  const fallbackHeight = typeof window === 'undefined' ? 560 : Math.max(320, window.innerHeight - 340)
  const availableHeight = measuredHeight > 0 ? measuredHeight : fallbackHeight
  homePageSize.value = Math.max(2, Math.min(6, Math.floor(availableHeight / 112)))
  clampHomePageIndex()
}

watch(homeFilter, () => {
  homePageIndex.value = 0
  nextTick(updateHomePageSize)
})

watch(homePageCount, clampHomePageIndex)

watch(homeMode, () => {
  nextTick(updateHomePageSize)
})

watch(section, () => {
  nextTick(updateHomePageSize)
})

onMounted(() => {
  nextTick(updateHomePageSize)
  window.addEventListener('resize', updateHomePageSize, { passive: true })
  void loadCollaborationSessions()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateHomePageSize)
})
watch(() => store.currentProjectId, () => { void loadCollaborationSessions() })
const currentUserName = computed(() => store.getMemberName(currentUserId))
const homeCollaborators = computed(() =>
  [
    { name: '李明', role: '项目执行人', task: '补齐沉降监测与顶管测量资料' },
    { name: '王芳', role: '资料与填报负责人', task: '确认风险草稿与日报解析' },
  ].filter(person => person.name !== currentUserName.value)
)
const showHomePriorityBasisInput = ref(false)
const homePriorityBasisInput = ref('')
const homePriorityBasis = ref('')
const baseHomePriorityItems = [
  { title: '深基坑风险草稿审核', effect: '风险管控闭环', tag: '重大风险', tone: 'danger', group: 'risk' },
  { title: '地面沉降监测材料缺项', effect: '草稿确认前置条件', tag: '资料缺项', tone: 'upload', group: 'material' },
  { title: '日报解析确认（2026-06-09）', effect: '进度同步与风险引用', tag: '进度同步', tone: 'warning', group: 'progress' },
  { title: '顶管偏差预警资料补充', effect: '预警有效性', tag: '安全预警', tone: 'info', group: 'risk' },
  { title: '月报填报启动', effect: '合规填报时效', tag: '合规要求', tone: 'info', group: 'deadline' },
]
const homePriorityItems = computed(() => {
  const basis = homePriorityBasis.value.trim()
  const preferredGroup = basis.includes('资料') || basis.includes('缺项') || basis.includes('附件')
    ? 'material'
    : basis.includes('截止') || basis.includes('时间') || basis.includes('工期') || basis.includes('合规')
      ? 'deadline'
      : basis.includes('进度') || basis.includes('日报') || basis.includes('同步')
        ? 'progress'
        : basis.includes('风险') || basis.includes('安全') || basis.includes('重大')
          ? 'risk'
          : ''

  const orderedItems = preferredGroup
    ? [...baseHomePriorityItems].sort((a, b) => Number(b.group === preferredGroup) - Number(a.group === preferredGroup))
    : baseHomePriorityItems

  return orderedItems.map((item, index) => ({ ...item, rank: index + 1 }))
})

function openHomePriorityRegenerate() {
  homePriorityBasisInput.value = homePriorityBasis.value
  showHomePriorityBasisInput.value = true
}

function submitHomePriorityBasis() {
  homePriorityBasis.value = homePriorityBasisInput.value.trim()
  showHomePriorityBasisInput.value = false
}

function cancelHomePriorityBasis() {
  showHomePriorityBasisInput.value = false
  homePriorityBasisInput.value = homePriorityBasis.value
}
const homeActivityFeed = [
  { text: '解析完成：2026-06-09 施工日报', time: '09:42' },
  { text: '生成任务：深基坑风险草稿审核', time: '09:42' },
  { text: '检测到资料缺项：地表沉降监测报告', time: '09:41' },
  { text: '更新：4 项工作已同步到你的队列', time: '09:41' },
]

const aiBriefItems = computed(() => [
  { title: '先补齐地面沉降监测报告', reason: '已逾期，且会阻塞深基坑风险上报。' },
  { title: '确认深基坑风险草稿', reason: '草稿确认后才能生成填报包并启动平台填报。' },
  { title: '核对 2026-06-09 施工日报', reason: '日报内容会影响 WBS 进度和风险材料引用。' },
])

const collaborationPeople = computed(() =>
  store.members.slice(0, 5).map(member => ({
    ...member,
    taskCount: store.tasks.filter(task => task.responsibleId === member.id || task.confirmatorId === member.id).length,
    nextAction: store.tasks.find(task => task.responsibleId === member.id || task.confirmatorId === member.id)?.title ?? '暂无新的跟进事项',
  })).sort((a, b) => b.taskCount - a.taskCount)
)

const quickCommand = ref('')
function dispatchQuickCommand() {
  const content = quickCommand.value.trim()
  if (!content) return
  syncHomeQuickCommand(content)
  store.addLog({
    id: `log${Date.now()}`,
    time: nowStr(),
    operator: '张伟',
    action: '任务下发',
    detail: content,
    level: 'info',
  })
  quickCommand.value = ''
}

const sessions = ref<CollaborationSession[]>([])
const activeSessionId = ref('')
const activeSession = computed(() => sessions.value.find(item => item.id === activeSessionId.value))
const activeSessionTasks = computed(() => {
  const ids = activeSession.value?.taskIds ?? []
  return ids.map(id => store.tasks.find(task => task.id === id)).filter((task): task is Task => Boolean(task))
})
const activeSessionPeople = computed(() => {
  const ids = activeSession.value?.participantIds ?? []
  return ids
    .map(id => store.members.find(member => member.id === id))
    .filter((member): member is Member => Boolean(member))
})
const activeSessionProgress = computed(() => {
  if (!activeSessionTasks.value.length) return 0
  return Math.round(activeSessionTasks.value.reduce((sum, task) => sum + taskProgress(task.status), 0) / activeSessionTasks.value.length)
})
const sessionGroups = computed(() => {
  const pinned = sessions.value.slice(0, 1)
  const today = sessions.value.slice(1, 3)
  const earlier = sessions.value.slice(3)
  return [
    { label: '置顶会话', pinned: true, items: pinned },
    { label: '今天', pinned: false, items: today },
    { label: '更早', pinned: false, items: earlier },
  ].filter(group => group.items.length)
})
const activeSessionMissingItems = computed(() => {
  const items = store.riskDrafts
    .flatMap(draft => draft.missingItems.map(name => ({ name, source: draft.title })))
    .slice(0, 3)

  return items.length
    ? items
    : [
      { name: '地表沉降监测报告', source: '深基坑风险草稿' },
      { name: '基坑支护变形监测图', source: '风险进展上报' },
      { name: '降雨记录与排水日志', source: '填报附件' },
    ]
})
const sideActionItems = [
  { label: '创建协办任务', prompt: '根据当前会话创建协办任务' },
  { label: '生成项目周报', prompt: '根据当前会话和项目状态生成项目周报' },
  { label: '检查资料缺口', prompt: '检查当前风险草稿和填报包还缺哪些资料' },
  { label: '生成填报包', prompt: '根据已确认内容生成平台填报包' },
]
const prompt = ref('')
const chatSuggestionsOpen = ref(false)
const generatedChatSuggestions = ref<Record<string, ChatSuggestion[]>>({})
const sessionMessages = ref<Record<string, ChatMessage[]>>({})
const homeQuickSessionId = ref<string | null>(null)
const homeQuickSession = computed(() =>
  homeQuickSessionId.value
    ? sessions.value.find(session => session.id === homeQuickSessionId.value)
    : undefined
)
const homeQuickSessionTitle = computed(() => homeQuickSession.value?.title ?? '')
const homeQuickSessionTime = computed(() => homeQuickSession.value?.time ?? '')
const homeQuickChatMessages = computed<ChatMessage[]>(() =>
  homeQuickSessionId.value ? sessionMessages.value[homeQuickSessionId.value] ?? [] : []
)
const activeChatMessages = computed(() => sessionMessages.value[activeSessionId.value] ?? [])
const activeChatSuggestions = computed(() => generatedChatSuggestions.value[activeSessionId.value] ?? [])
const meetingMinute = ref<{ title: string; summary: string; action_items?: unknown[] } | null>(null)

function mapSession(row: ApiCollaborationSession): CollaborationSession { return { id: String(row.id), title: row.title, desc: row.summary || '暂无会话摘要', time: row.updated_at || row.created_at, participantIds: (row.participant_ids || []).map(String), taskIds: (row.task_ids || []).map(String) } }
function mapMessage(row: ApiCollaborationMessage): ChatMessage { return { id: String(row.id), role: row.role, content: row.content, generatedTaskIds: (row.generated_task_ids || []).map(String) } }
async function loadSessionMessages(sessionId: string) {
  if (!sessionId) return
  const response = await api.get<ApiEnvelope<ApiCollaborationMessage[]>>(`/collaboration-sessions/${sessionId}/messages`)
  sessionMessages.value = { ...sessionMessages.value, [sessionId]: response.data.data.map(mapMessage) }
}
async function loadCollaborationSessions() {
  if (!store.currentProjectId) return
  const response = await api.get<ApiEnvelope<ApiCollaborationSession[]>>(`/projects/${store.currentProjectId}/collaboration-sessions`)
  sessions.value = response.data.data.map(mapSession)
  if (!activeSessionId.value || !sessions.value.some(item => item.id === activeSessionId.value)) activeSessionId.value = sessions.value[0]?.id || ''
  if (activeSessionId.value) await loadSessionMessages(activeSessionId.value)
}
async function createMeetingMinute() {
  if (!activeSessionId.value) return
  const response = await api.post<ApiEnvelope<{ title: string; summary: string; action_items?: unknown[] }>>(`/collaboration-sessions/${activeSessionId.value}/minutes`)
  meetingMinute.value = response.data.data
}

watch(activeSessionId, () => {
  chatSuggestionsOpen.value = false
  void loadSessionMessages(activeSessionId.value)
})

function seedPrompt(text: string) {
  prompt.value = text
}

function buildChatSuggestions(): ChatSuggestion[] {
  const tasks = activeSessionTasks.value
  const suggestions: ChatSuggestion[] = []
  const overdueTask = tasks.find(task => task.status === 'overdue')
  const waitingTask = tasks.find(task => task.status === 'waiting_confirm')
  const missingItem = activeSessionMissingItems.value[0]
  const collaborator = activeSessionPeople.value.find(member => member.id !== currentUserId)

  if (overdueTask) {
    suggestions.push({
      label: '先处理逾期项',
      desc: overdueTask.title,
      prompt: `请先梳理「${overdueTask.title}」逾期原因，并给出今天可以完成的处理步骤。`,
    })
  }

  if (missingItem) {
    suggestions.push({
      label: '补齐资料缺口',
      desc: missingItem.name,
      prompt: `请围绕「${missingItem.name}」列出需要补齐的资料、责任人和提交时间。`,
    })
  }

  if (waitingTask) {
    suggestions.push({
      label: '推动确认',
      desc: waitingTask.title,
      prompt: `请为「${waitingTask.title}」整理确认要点，并生成给确认人的沟通内容。`,
    })
  }

  if (collaborator) {
    suggestions.push({
      label: `找${collaborator.name}协同`,
      desc: collaborator.title,
      prompt: `请判断当前会话中哪些事项需要${collaborator.name}协同，并生成协同说明。`,
    })
  }

  suggestions.push({
    label: '重排处理顺序',
    desc: '按风险、截止时间和资料阻塞关系排序',
    prompt: '请按风险等级、截止时间和资料阻塞关系，重新给出当前会话工作的处理顺序。',
  })

  const unique = suggestions.filter((item, index, array) =>
    array.findIndex(next => next.label === item.label) === index
  )
  return unique.slice(0, Math.max(2, Math.min(4, unique.length)))
}

function toggleChatSuggestions() {
  if (chatSuggestionsOpen.value) {
    chatSuggestionsOpen.value = false
    return
  }
  generatedChatSuggestions.value = {
    ...generatedChatSuggestions.value,
    [activeSessionId.value]: buildChatSuggestions(),
  }
  chatSuggestionsOpen.value = true
}

function applyChatSuggestion(text: string) {
  seedPrompt(text)
  chatSuggestionsOpen.value = false
}

function generatedTaskIdsFromPrompt(content: string) {
  if (content.includes('资料') || content.includes('缺项') || content.includes('附件')) return ['t2', 't4']
  if (content.includes('日报') || content.includes('WBS') || content.includes('进度')) return ['t3']
  if (content.includes('填报') || content.includes('月报')) return ['t6']
  if (content.includes('风险') || content.includes('拆') || content.includes('任务')) return ['t4', 't2', 't3', 't6']
  return []
}

async function sendPrompt() {
  const content = prompt.value.trim()
  if (!content || !activeSessionId.value) return
  const response = await api.post<ApiEnvelope<{ session: ApiCollaborationSession; message: ApiCollaborationMessage }>>(`/collaboration-sessions/${activeSessionId.value}/messages`, { content })
  const session = mapSession(response.data.data.session)
  sessions.value = sessions.value.map(item => item.id === session.id ? session : item)
  await loadSessionMessages(activeSessionId.value)
  store.addLog({ id: `log${Date.now()}`, time: nowStr(), operator: '系统', action: '会话处理', detail: content, level: 'success' })
  prompt.value = ''
}

function sessionTitleFromFirstMessage(content: string) {
  return content.trim().split(/[。！？!?；;\n]/)[0]?.trim() || content.trim()
}

function ensureHomeQuickSession(content: string) {
  if (homeQuickSessionId.value && sessions.value.some(session => session.id === homeQuickSessionId.value)) {
    return homeQuickSessionId.value
  }
  const id = `home-${Date.now()}`
  const title = sessionTitleFromFirstMessage(content)
  homeQuickSessionId.value = id
  sessions.value.unshift({
    id,
    title,
    desc: content.slice(0, 22),
    time: nowStr(),
    participantIds: ['m1'],
    taskIds: [],
  })
  sessionMessages.value[id] = []
  return id
}

function syncHomeQuickCommand(content: string) {
  const id = ensureHomeQuickSession(content)
  const now = nowStr()
  const messages = sessionMessages.value[id] ?? []
  const generatedTaskIds = content.includes('资料') || content.includes('缺项')
    ? ['t2', 't4']
    : content.includes('风险')
      ? ['t4', 't6']
      : []
  messages.push({ id: `hq-u-${Date.now()}`, role: 'user', content })
  messages.push({
    id: `hq-a-${Date.now() + 1}`,
    role: 'assistant',
    content: generatedTaskIds.length
      ? `已根据当前任务、资料缺口和风险状态生成相关工作：${content}`
      : `已进入当前项目协同：${content}`,
    generatedTaskIds: generatedTaskIds.length ? generatedTaskIds : undefined,
  })
  sessionMessages.value[id] = messages
  const targetSession = sessions.value.find(session => session.id === id)
  if (targetSession) {
    targetSession.desc = content.slice(0, 22)
    targetSession.time = now
    if (generatedTaskIds.length) targetSession.taskIds = Array.from(new Set([...targetSession.taskIds, ...generatedTaskIds]))
  }
  activeSessionId.value = id
}

async function startNewSession() {
  if (!store.currentProjectId) return
  const response = await api.post<ApiEnvelope<ApiCollaborationSession>>(`/projects/${store.currentProjectId}/collaboration-sessions`, { title: '新的工程协同' })
  const session = mapSession(response.data.data)
  sessions.value.unshift(session)
  sessionMessages.value = { ...sessionMessages.value, [session.id]: [] }
  activeSessionId.value = session.id
}

const taskFilter = ref<'all' | TaskStatus>('all')
const informationDispositionOpen = ref(false)
const selectedInformationRecordId = ref('')
const informationRevision = ref('')
const selectedInformationRecord = computed(() => (store.informationRecords || []).find(item => item.id === selectedInformationRecordId.value))
const taskHistoryOpenId = ref('')
const taskHistories = ref<Record<string, Array<{ id: number; from_status?: string; to_status: string; note?: string; created_at: string }>>>({})
const taskHistoryLoading = ref(false)
const selectedTaskHistoryTask = computed(() => store.tasks.find(task => task.id === taskHistoryOpenId.value))
const taskCreateOpen = ref(false)
const taskCreateMode = ref<'dobby' | 'template'>('template')
const taskFlowRequirement = ref('')
const taskFlowGenerating = ref(false)
const taskFlowGenerationNote = ref('')
const taskTemplateOptions = ['条件核查', '隐患整改', '资料补全', '风险处置', '报告审核', '自定义'] as const
const taskTemplateType = ref<(typeof taskTemplateOptions)[number]>('隐患整改')
const taskTemplateTopic = ref('整改现场隐患并完成复核闭环')
const selectedTaskFlowStepIndex = ref(0)
const taskFlowExamples = ['每周核查基坑监测数据并完成复核归档', '发现临边防护缺失后发起整改并闭环', '补齐日报缺失资料并由资料员复核']
const taskCreateForm = ref({ title: taskTemplateTopic.value, task_type: 'risk_alert' as Task['type'], run_mode: 'single' as 'single' | 'scheduled', trigger_date: todayDateString(), trigger_time: '09:00', trigger_interval_value: 1, trigger_interval_unit: 'week' as TriggerIntervalUnit, cc: '项目经理' })
const taskExecutionAt = computed({
  get: () => `${taskCreateForm.value.trigger_date}T${taskCreateForm.value.trigger_time}`,
  set: (value: string) => {
    const [triggerDate, triggerTime] = value.split('T')
    taskCreateForm.value.trigger_date = triggerDate || todayDateString()
    taskCreateForm.value.trigger_time = triggerTime || '09:00'
  },
})
const triggerIntervalUnitLabel = computed(() => ({ hour: '小时', day: '天', week: '周', month: '个月' })[taskCreateForm.value.trigger_interval_unit])
const taskTriggerSummary = computed(() => taskCreateForm.value.run_mode === 'single'
  ? `${taskCreateForm.value.trigger_date} ${taskCreateForm.value.trigger_time} 单次执行`
  : `${taskCreateForm.value.trigger_date} ${taskCreateForm.value.trigger_time} 首次执行，之后每 ${taskCreateForm.value.trigger_interval_value} ${triggerIntervalUnitLabel.value}执行一次`)
const taskFlowSteps = ref<TaskFlowStepDraft[]>(createTemplateFlowSteps('隐患整改'))
const taskTabs: Array<{ key: 'all' | TaskStatus, label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'overdue', label: '逾期' },
  { key: 'pending', label: '待处理' },
  { key: 'processing', label: '处理中' },
  { key: 'need_more_info', label: '待补充' },
  { key: 'waiting_confirm', label: '待确认' },
  { key: 'done', label: '已完成' },
]
const taskTabCounts = computed<Record<'all' | TaskStatus, number>>(() => ({
  all: store.tasks.length,
  overdue: store.tasks.filter(task => task.status === 'overdue').length,
  pending: store.tasks.filter(task => task.status === 'pending').length,
  processing: store.tasks.filter(task => task.status === 'processing').length,
  need_more_info: store.tasks.filter(task => task.status === 'need_more_info').length,
  waiting_confirm: store.tasks.filter(task => task.status === 'waiting_confirm').length,
  done: store.tasks.filter(task => task.status === 'done').length,
  cancelled: store.tasks.filter(task => task.status === 'cancelled').length,
}))
const filteredTasks = computed(() => taskFilter.value === 'all' ? store.tasks : store.tasks.filter(task => task.status === taskFilter.value))

async function openTaskHistory(taskId: string) {
  taskHistoryOpenId.value = taskId
  taskHistoryLoading.value = true
  try {
    taskHistories.value = { ...taskHistories.value, [taskId]: await store.getTaskHistory(taskId) }
  } catch (error: any) {
    message.error(error.response?.data?.detail || '处理记录加载失败，请检查后端服务后重试。')
    taskHistoryOpenId.value = ''
  } finally {
    taskHistoryLoading.value = false
  }
}

function closeTaskHistory() {
  taskHistoryOpenId.value = ''
}
function openInformationDisposition(recordId: string) {
  selectedInformationRecordId.value = recordId
  informationRevision.value = selectedInformationRecord.value?.content || ''
  informationDispositionOpen.value = true
}

function closeInformationDisposition() {
  informationDispositionOpen.value = false
  selectedInformationRecordId.value = ''
  informationRevision.value = ''
}

async function disposeInformation(action: 'confirm' | 'deny' | 'revise') {
  const record = selectedInformationRecord.value
  if (!record || (action === 'revise' && !informationRevision.value.trim())) return
  try {
    await store.disposeInformationRecord(record.id, action, action === 'revise' ? informationRevision.value.trim() : undefined)
    message.success(action === 'confirm' ? '信息已确认' : action === 'deny' ? '信息已否认' : '信息已修订')
    closeInformationDisposition()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '信息处置失败，请检查服务连接后重试。')
  }
}

function todayDateString(offsetDays = 0) {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function createTemplateFlowSteps(type: (typeof taskTemplateOptions)[number]): TaskFlowStepDraft[] {
  const templates: Record<(typeof taskTemplateOptions)[number], Array<[string, string]>> = {
    条件核查: [['发起核查', '核查清单'], ['现场复核', '现场记录与照片'], ['负责人确认', '复核意见'], ['资料归档', '闭环资料']],
    隐患整改: [['发现隐患', '隐患记录'], ['派单整改', '整改方案与照片'], ['安全员复核', '复核记录'], ['闭环归档', '闭环证明']],
    资料补全: [['识别缺失', '缺失项清单'], ['补齐资料', '待补资料'], ['复核资料', '复核意见'], ['资料归档', '完整资料包']],
    风险处置: [['风险触发', '风险依据'], ['数据复核', '监测或核验数据'], ['处置确认', '处置记录'], ['风险关闭', '关闭依据']],
    报告审核: [['提交报告', '报告文件'], ['依据审核', '审核意见'], ['问题修订', '修订稿'], ['审核通过', '定稿文件']],
    自定义: [['发起任务', '任务依据'], ['执行处理', '过程资料'], ['复核确认', '复核意见'], ['闭环归档', '闭环资料']],
  }
  return templates[type].map(([name, material], index) => ({ id: `flow-${Date.now()}-${index}`, name, owner_user_id: store.members[index % Math.max(store.members.length, 1)]?.id || '', due_at: todayDateString(index + 1), material }))
}

function taskTypeFromTemplate(type: (typeof taskTemplateOptions)[number]): Task['type'] {
  if (type === '资料补全') return 'material_missing'
  if (type === '报告审核') return 'draft_review'
  return 'risk_alert'
}

function memberNameById(memberId: string) {
  return store.members.find(member => member.id === memberId)?.name || '待指定'
}

function generateTemplateTaskFlow() {
  taskCreateForm.value.title = taskTemplateTopic.value || `${taskTemplateType.value}任务`
  taskCreateForm.value.task_type = taskTypeFromTemplate(taskTemplateType.value)
  taskFlowSteps.value = createTemplateFlowSteps(taskTemplateType.value)
  selectedTaskFlowStepIndex.value = 0
  taskFlowGenerationNote.value = `已按“${taskTemplateType.value}”模板生成 ${taskFlowSteps.value.length} 个可编辑节点。`
}

function applyGeneratedTaskFlow(flow: GeneratedTaskFlow) {
  taskCreateForm.value.title = flow.title
  taskCreateForm.value.task_type = flow.task_type
  taskFlowSteps.value = flow.steps.map((step, index) => ({ id: `generated-${Date.now()}-${index}`, name: step.name, owner_user_id: step.owner_user_id ? String(step.owner_user_id) : '', due_at: step.due_at?.slice(0, 10) || todayDateString(index + 1), material: step.material || '' }))
  selectedTaskFlowStepIndex.value = 0
  taskFlowGenerationNote.value = flow.generation_note
}

async function generateTaskFlowWithDobby() {
  if (!store.currentProjectId || taskFlowRequirement.value.length < 4) return
  taskFlowGenerating.value = true
  taskFlowGenerationNote.value = ''
  try {
    const response = await api.post<ApiEnvelope<GeneratedTaskFlow>>(`/projects/${store.currentProjectId}/tasks/generate-flow`, { requirement: taskFlowRequirement.value }, { timeout: 35_000 })
    applyGeneratedTaskFlow(response.data.data)
    message.success(response.data.data.generated_by === 'ai' ? 'Dobby 已生成任务流' : '已生成可编辑的模板任务流')
  } catch (error: any) {
    taskFlowGenerationNote.value = error.response?.data?.detail || '生成失败，请检查后端服务或模型配置后重试。'
    message.error(taskFlowGenerationNote.value)
  } finally {
    taskFlowGenerating.value = false
  }
}

function addTaskFlowStep() {
  taskFlowSteps.value.push({ id: `manual-${Date.now()}`, name: `新节点 ${taskFlowSteps.value.length + 1}`, owner_user_id: '', due_at: todayDateString(taskFlowSteps.value.length + 1), material: '' })
  selectedTaskFlowStepIndex.value = taskFlowSteps.value.length - 1
}

function moveTaskFlowStep(index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= taskFlowSteps.value.length) return
  const [step] = taskFlowSteps.value.splice(index, 1)
  taskFlowSteps.value.splice(nextIndex, 0, step)
  selectedTaskFlowStepIndex.value = nextIndex
}

function removeTaskFlowStep(index: number) {
  if (taskFlowSteps.value.length <= 2) return
  taskFlowSteps.value.splice(index, 1)
  selectedTaskFlowStepIndex.value = Math.min(selectedTaskFlowStepIndex.value, taskFlowSteps.value.length - 1)
}

function resetTaskFlowCreator() {
  taskCreateMode.value = 'template'
  taskFlowRequirement.value = ''
  taskFlowGenerationNote.value = ''
  taskTemplateType.value = '隐患整改'
  taskTemplateTopic.value = '整改现场隐患并完成复核闭环'
  taskCreateForm.value = { title: taskTemplateTopic.value, task_type: 'risk_alert', run_mode: 'single', trigger_date: todayDateString(), trigger_time: '09:00', trigger_interval_value: 1, trigger_interval_unit: 'week', cc: '项目经理' }
  taskFlowSteps.value = createTemplateFlowSteps('隐患整改')
  selectedTaskFlowStepIndex.value = 0
}

async function createManualTask() {
  if (!taskCreateForm.value.title || taskFlowSteps.value.length < 2) return
  const form = taskCreateForm.value
  const requiredMaterials = Array.from(new Set(taskFlowSteps.value.map(step => step.material.trim()).filter(Boolean)))
  const workflow_steps = taskFlowSteps.value.map((step, index) => ({ name: step.name.trim(), owner: memberNameById(step.owner_user_id), owner_user_id: step.owner_user_id || undefined, due_at: step.due_at || undefined, material: step.material.trim(), order: index + 1, next_step: index < taskFlowSteps.value.length - 1 ? index + 2 : undefined, status: 'pending' as const })) as Task['workflowSteps']
  const triggerParts = [taskTriggerSummary.value, form.cc ? `抄送：${form.cc}` : ''].filter(Boolean)
  try {
    await store.createTask({ title: form.title, task_type: form.task_type, risk_level: 'medium', assignee_user_id: taskFlowSteps.value[0]?.owner_user_id, due_at: taskFlowSteps.value[taskFlowSteps.value.length - 1]?.due_at, trigger_reason: triggerParts.join(' · '), required_materials: requiredMaterials, workflow_steps })
    message.success('任务流已创建并进入任务看板')
    taskCreateOpen.value = false
    resetTaskFlowCreator()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '任务流创建失败，请检查填写内容后重试。')
  }
}

const documentCards = computed(() => [
  { title: '日报解析', desc: '施工内容、风险和进度记录', count: store.dailyReports.length, icon: FileText },
  { title: '风险草稿', desc: '待审核的风险上报内容', count: store.riskDrafts.length, icon: Notes },
  { title: '填报包', desc: '字段与附件映射到平台', count: store.fillPackages.length, icon: Table },
  { title: '目录监控', desc: store.dirConfig.enabled ? '文件目录监听中' : '目录监听未启用', count: `${store.dirConfig.scanInterval}m`, icon: Folder },
])
const documentUploading = ref(false)
const documentSearchKeyword = ref('')
const documentSearchResults = ref<AttachmentRecord[]>([])
const documentSearching = ref(false)
const draftCreateOpen = ref(false)
const draftCreateForm = ref({ risk_source_id: '', title: '', content: '' })
async function uploadDocument(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  documentUploading.value = true
  try { await store.uploadAttachment(file) } finally { documentUploading.value = false; input.value = '' }
}
async function searchDocuments() {
  documentSearching.value = true
  try { documentSearchResults.value = await store.searchDocuments(documentSearchKeyword.value) } finally { documentSearching.value = false }
}
async function createRiskDraft() {
  if (!draftCreateForm.value.risk_source_id || !draftCreateForm.value.title || !draftCreateForm.value.content) return
  await store.createRiskDraft(draftCreateForm.value)
  draftCreateForm.value = { risk_source_id: '', title: '', content: '' }
  draftCreateOpen.value = false
}
async function assistRiskDraft() {
  if (!draftCreateForm.value.risk_source_id) return
  await store.assistRiskDraft(draftCreateForm.value.risk_source_id)
  draftCreateOpen.value = false
}
function createDefaultFillPackage(draftId: string, title: string, content: string) {
  return store.createFillPackage(draftId, { platform_name: '监管填报平台', process_name: title, fields: [{ name: '风险说明', value: content }], attachments: [] })
}
function formatFileSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
const totalMissingItems = computed(() => store.riskDrafts.reduce((sum, item) => sum + item.missingItems.length, 0))
const docWorkItems = computed(() => {
  const daily = store.pendingDailyReports[0]
  const draft = store.pendingDrafts[0]
  const fill = store.pendingFills[0]
  const missingDraft = store.riskDrafts.find(item => item.missingItems.length > 0)
  return [
    {
      label: '日报待确认',
      title: daily ? daily.fileName : '暂无待确认日报',
      desc: daily ? `匹配 WBS：${store.getWbsName(daily.matchedWbsId ?? '')}，置信度 ${Math.round(daily.confidence * 100)}%。` : '新的日报解析完成后会出现在这里。',
      action: daily ? '处理任务' : '查看任务',
      to: '/tasks',
    },
    {
      label: '草稿待审核',
      title: draft ? draft.title : '暂无待审核草稿',
      desc: draft ? `上报类型：${draft.hazardType}，截止 ${draft.deadline}。` : '风险草稿生成后需要资料负责人确认。',
      action: draft ? '去审核' : '查看草稿',
      to: '/tasks',
    },
    {
      label: '材料缺项',
      title: totalMissingItems.value ? `${totalMissingItems.value} 项资料未齐` : '当前材料齐全',
      desc: missingDraft ? `${missingDraft.title}：${missingDraft.missingItems.slice(0, 2).join('、')}` : '后续缺项会按草稿和填报包自动归集。',
      action: '补充资料',
      to: '/ai',
    },
    {
      label: '待填报包',
      title: fill ? fill.processName : '暂无待填报包',
      desc: fill ? `${fill.platformName}，截止 ${fill.deadline}。` : '草稿确认后会生成平台填报包。',
      action: fill ? '启动填报' : '查看填报',
      to: '/tasks',
    },
  ]
})
const recentDocuments = computed(() => [
  ...store.dailyReports.map(item => ({ type: '日报', name: item.fileName, desc: item.constructionContent, state: statusLabel(item.status as TaskStatus) })),
  ...store.riskDrafts.map(item => ({ type: '草稿', name: item.title, desc: item.hazardType, state: draftStatusLabel(item.status) })),
  ...store.fillPackages.map(item => ({ type: '填报', name: item.processName, desc: item.platformName, state: fillStatusLabel(item.status) })),
].slice(0, 6))

function riskLabel(level: RiskLevel) {
  return ({ critical: '重大', high: '高', medium: '中', low: '低' } as Record<RiskLevel, string>)[level]
}

function wbsStatusLabel(status: string) {
  return ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' } as Record<string, string>)[status] || status
}

function qualityStatusLabel(status: string) {
  return ({ pending: '待配置', processing: '进行中', passed: '已通过', failed: '未通过' } as Record<string, string>)[status] || status
}

function dailyStatusLabel(status: string) {
  return ({ pending_confirm: '待确认', confirmed: '已确认', failed: '解析失败', reparse: '待重新解析' } as Record<string, string>)[status] || status
}

function projectTaskStatusLabel(status: TaskStatus) {
  return ({ pending: '待处理', processing: '进行中', need_more_info: '待补充', waiting_confirm: '待确认', done: '已完成', overdue: '逾期', cancelled: '已取消' } as Record<TaskStatus, string>)[status]
}

function taskClosureLabel(task: Task) {
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed') ?? task.workflowSteps[task.workflowSteps.length - 1]
  return currentStep?.closure || ({ pending: '未闭环', processing: '未闭环', need_more_info: '待补充', waiting_confirm: '待复核', done: '已闭环', overdue: '待复核', cancelled: '已取消' } as Record<TaskStatus, string>)[task.status]
}

function taskClosureTone(task: Task) {
  const label = taskClosureLabel(task)
  if (label === '已闭环') return 'closed'
  if (label.includes('复核')) return 'review'
  if (label.includes('补充')) return 'supplement'
  if (label.includes('取消')) return 'cancelled'
  return 'open'
}

function taskPhaseLabel(task: Task) {
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  return currentStep?.phase || task.workflowSteps[0]?.phase || (task.status === 'done' ? '归档' : '处理中')
}

function taskMaterialLabel(task: Task) {
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  const material = currentStep?.material || currentStep?.note || task.workflowSteps[task.workflowSteps.length - 1]?.material
  return material || (task.missingCount > 0 ? `待补齐 ${task.missingCount} 项资料` : '暂无待补充材料')
}

function taskRelationLabel(task: Task) {
  const wbsNames = task.linkedWbsIds.map(id => store.getWbsName(id)).filter(Boolean)
  const riskName = task.linkedRiskId ? store.getRiskName(task.linkedRiskId) : ''
  return [wbsNames.join('、'), riskName].filter(Boolean).join(' · ') || '未关联'
}

function statusTimeLabel(value: string) {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value || '刚刚'
  const delta = Date.now() - timestamp
  if (delta >= 0 && delta < 86400000) return '今天 ' + new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  return new Date(timestamp).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function taskTypeLabel(type: Task['type']) {
  return ({
    risk_alert: '风险预警',
    material_missing: '资料缺项',
    daily_confirm: '日报确认',
    draft_review: '草稿审核',
    fill_platform: '平台填报',
  } as Record<Task['type'], string>)[type]
}

function taskStepLabel(status: Task['workflowSteps'][number]['status']) {
  return ({ pending: '待处理', processing: '处理中', completed: '已完成', blocked: '受阻' } as Record<Task['workflowSteps'][number]['status'], string>)[status]
}

function taskSourceLabel(type: Task['type']) {
  return ({
    risk_alert: 'WBS 风险规则自动触发',
    material_missing: '风险草稿资料校验',
    daily_confirm: '日报目录解析',
    draft_review: '风险草稿生成',
    fill_platform: '填报包生成',
  } as Record<Task['type'], string>)[type]
}

function tasksByIds(ids: string[]) {
  return ids
    .map(id => store.tasks.find(task => task.id === id))
    .filter((task): task is Task => Boolean(task))
}

function taskProgress(status: TaskStatus) {
  return ({
    overdue: 20,
    pending: 30,
    processing: 58,
    need_more_info: 45,
    waiting_confirm: 78,
    done: 100,
    cancelled: 0,
  } as Record<TaskStatus, number>)[status]
}

function formatDateTime(date: string, mode: 'start' | 'end' = 'start') {
  if (date.includes(':')) return date.length === 16 ? `${date}:00` : date
  return `${date} ${mode === 'end' ? '18:00:00' : '00:00:00'}`
}

function statusLabel(status: TaskStatus | string) {
  return ({
    pending: '待处理',
    processing: '处理中',
    need_more_info: '待补充资料',
    waiting_confirm: '待确认',
    done: '已完成',
    overdue: '已逾期',
    cancelled: '已取消',
    pending_confirm: '待确认',
    confirmed: '已确认',
  } as Record<string, string>)[status] ?? status
}

function draftStatusLabel(status: DraftStatus) {
  return ({
    draft: '草稿',
    reviewing: '审核中',
    confirmed: '已确认',
    rejected: '已退回',
    packaged: '已生成填报包',
  } as Record<DraftStatus, string>)[status]
}

function fillStatusLabel(status: FillStatus) {
  return ({
    pending: '待填报',
    filling: '填报中',
    submitted: '已提交',
    failed: '填报失败',
  } as Record<FillStatus, string>)[status]
}

function nowStr() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
}
</script>

<style scoped>
.ai-platform {
  min-height: 100%;
  padding: 18px;
  background:
    radial-gradient(circle at 18% 0%, rgba(21, 94, 117, 0.08), transparent 28rem),
    linear-gradient(180deg, #f6f7f3 0%, #edf1ee 100%);
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  padding: 4px 8px;
  border: 1px solid rgba(205, 91, 32, 0.2);
  border-radius: 6px;
  background: rgba(247, 236, 228, 0.86);
  color: var(--color-primary-dark);
  font-size: 11px;
  font-weight: 760;
  line-height: 1;
}

.home-console {
  display: grid;
  grid-template-columns: minmax(760px, 1fr) 330px;
  gap: 16px;
  align-items: start;
  height: calc(100dvh - var(--header-height, 56px) - 36px);
  min-height: 600px;
}

.home-workspace,
.home-side-panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(20, 45, 54, 0.1);
  border-radius: 8px;
  box-shadow: 0 18px 42px rgba(28, 48, 44, 0.06);
}

.home-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  overflow: hidden;
}

.home-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 22px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.home-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 132px;
}

.home-primary-button,
.home-card-primary,
.home-expand-button,
.home-regenerate {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid rgba(20, 45, 54, 0.14);
  border-radius: 6px;
  background: #fff;
  color: #152d34;
  font: inherit;
  font-size: 13px;
  font-weight: 760;
  text-decoration: none;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease, background .18s ease;
}

.home-primary-button {
  height: 40px;
  min-width: 100px;
  padding: 0 16px;
}

.home-primary-button {
  border-color: #cd5b20;
  background: linear-gradient(180deg, #e46722, #c84e12);
  color: #fff;
  box-shadow: 0 10px 20px rgba(205, 91, 32, 0.18);
}

.home-primary-button:hover,
.home-card-primary:hover,
.home-expand-button:hover,
.home-regenerate:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.34);
  box-shadow: 0 12px 24px rgba(28, 48, 44, 0.11);
}

.home-mode-tabs {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(120px, 1fr));
  gap: 4px;
  min-width: 286px;
  padding: 4px;
  border: 1px solid rgba(20, 45, 54, 0.1);
  border-radius: 8px;
  background: #f4f7f6;
}

.home-mode-tabs button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #5d717a;
  font: inherit;
  font-size: 14px;
  font-weight: 760;
  cursor: pointer;
  padding: 0 18px;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease, background .18s ease;
}

.home-mode-tabs button.active {
  border-color: rgba(8, 56, 62, 0.18);
  background: #fff;
  color: #10242a;
  box-shadow: 0 8px 18px rgba(28, 48, 44, 0.08);
}

.home-mode-tabs button:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.28);
}

.home-controlbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 22px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.home-filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}

.home-filter-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(20, 45, 54, 0.12);
  border-radius: 6px;
  background: #fff;
  color: #455b63;
  font: inherit;
  font-size: 13px;
  font-weight: 780;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(255, 255, 255, .7) inset;
}

.home-filter-tabs button span {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: #edf4f3;
  color: #466169;
  font-size: 12px;
  line-height: 20px;
  font-variant-numeric: tabular-nums;
}

.home-filter-tabs button.active {
  border-color: #08383e;
  background: #08383e;
  color: #fff;
  box-shadow: 0 10px 22px rgba(8, 56, 62, 0.18);
}

.home-filter-tabs button.active span {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.home-pager {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.home-page-state {
  display: inline-flex;
  align-items: center;
  min-width: 70px;
  height: 32px;
  justify-content: center;
  color: #647783;
  font-size: 12px;
  font-weight: 760;
  font-variant-numeric: tabular-nums;
}

.home-page-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(20, 45, 54, 0.13);
  border-radius: 6px;
  background: #fff;
  color: #153138;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease, background .18s ease, opacity .18s ease;
}

.home-page-arrow:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.34);
  box-shadow: 0 10px 20px rgba(28, 48, 44, 0.1);
}

.home-page-arrow:disabled {
  cursor: not-allowed;
  opacity: .36;
}

.home-queue-list {
  display: grid;
  flex: 1 1 auto;
  align-content: start;
  min-height: 0;
  overflow: hidden;
  padding: 0 22px;
}

.home-queue-card {
  display: grid;
  grid-template-columns: 34px 62px minmax(0, 1fr) 190px 116px;
  gap: 16px;
  align-items: center;
  min-height: 112px;
  padding: 16px 0;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
}

.home-queue-card:first-child {
  border-top-color: rgba(205, 91, 32, 0.16);
}

.home-rank {
  display: grid;
  place-items: center;
  width: 34px;
  height: 52px;
  border-radius: 0 8px 8px 0;
  font-size: 18px;
  font-weight: 860;
  font-variant-numeric: tabular-nums;
}

.home-rank.danger,
.home-rank.warning {
  background: #fff2e7;
  color: #d95c16;
}

.home-rank.upload {
  background: #e8f8f5;
  color: #007f78;
}

.home-rank.info {
  background: #eaf2ff;
  color: #2563eb;
}

.home-work-icon {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  border-radius: 8px;
  border: 1px solid transparent;
}

.home-work-icon.danger {
  border-color: rgba(205, 91, 32, 0.14);
  background: #fff0ec;
  color: #df4f2f;
}

.home-work-icon.upload {
  border-color: rgba(0, 127, 120, 0.14);
  background: #e9faf7;
  color: #00877f;
}

.home-work-icon.warning {
  border-color: rgba(217, 142, 22, 0.16);
  background: #fff7e8;
  color: #e28a09;
}

.home-work-icon.info {
  border-color: rgba(37, 99, 235, 0.14);
  background: #eef5ff;
  color: #2563eb;
}

.home-work-main {
  min-width: 0;
}

.home-chip-row {
  display: flex;
  margin-bottom: 5px;
}

.home-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 7px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 820;
}

.home-chip.danger {
  background: #ffe7e1;
  color: #df4f2f;
}

.home-chip.upload {
  background: #daf6f0;
  color: #00877f;
}

.home-chip.warning {
  background: #fff0cf;
  color: #cf7600;
}

.home-chip.info {
  background: #e6efff;
  color: #2563eb;
}

.home-work-main h2 {
  overflow: hidden;
  margin: 0 0 5px;
  color: #122933;
  font-size: 16px;
  line-height: 1.28;
  font-weight: 820;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-work-main p {
  overflow: hidden;
  margin: 0;
  color: #6a7d88;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}

.home-tag-row span {
  display: inline-flex;
  align-items: center;
  height: 19px;
  padding: 0 6px;
  border-radius: 4px;
  background: #edf2f4;
  color: #71818b;
  font-size: 11px;
  font-weight: 680;
}

.home-owner {
  min-width: 0;
  padding-left: 18px;
  border-left: 1px solid rgba(20, 45, 54, 0.13);
}

.home-owner-name {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 4px;
  color: #0d242a;
}

.home-owner-name strong {
  overflow: hidden;
  font-size: 14px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-owner span,
.home-owner time {
  display: block;
  overflow: hidden;
  color: #6f7f89;
  font-size: 12px;
  line-height: 1.65;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
}

.home-card-primary {
  width: 112px;
  height: 38px;
  padding: 0 14px;
}

.home-card-primary.danger,
.home-card-primary.warning {
  border-color: #cd5b20;
  background: linear-gradient(180deg, #e46722, #c84e12);
  color: #fff;
}

.home-card-primary.upload {
  border-color: #00877f;
  background: linear-gradient(180deg, #009f96, #007f78);
  color: #fff;
}

.home-card-primary.info {
  border-color: #2563eb;
  background: linear-gradient(180deg, #3b82f6, #2563eb);
  color: #fff;
}

.home-expand-button {
  width: calc(100% - 44px);
  height: 38px;
  margin: 8px 22px 18px;
  color: #728491;
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}

.home-chat-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.chat-head.home-chat-head {
  padding: 16px 22px 12px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.chat-head.home-chat-head.is-empty {
  min-height: 0;
  padding: 0;
  border-bottom: 0;
}

.home-chat-head .chat-title-block {
  width: 100%;
}

.chat-head.home-chat-head h1 {
  overflow: hidden;
  max-width: min(760px, 100%);
  color: #10242a;
  font-size: 20px;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.messages.home-chat-messages {
  min-height: 0;
  padding: 16px 22px;
  background:
    radial-gradient(circle at 8% 0, rgba(15, 118, 110, 0.08), transparent 16rem),
    linear-gradient(180deg, rgba(248, 250, 249, 0.74), rgba(255, 255, 255, 0.2));
}

.messages.home-chat-messages.is-empty {
  align-items: center;
  justify-content: center;
}

.home-chat-guide {
  display: grid;
  gap: 14px;
  width: min(820px, 92%);
  padding: 20px 22px;
  border: 1px solid rgba(20, 45, 54, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 18px 42px rgba(28, 48, 44, 0.08);
}

.home-chat-guide-copy {
  display: grid;
  gap: 7px;
}

.home-chat-guide strong {
  color: #10242a;
  font-size: 17px;
  line-height: 1.35;
  font-weight: 820;
}

.home-chat-guide p {
  max-width: 720px;
  margin: 0;
  color: #637782;
  font-size: 13px;
  line-height: 1.65;
}

.home-chat-guide-items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.home-chat-guide-items span {
  display: grid;
  gap: 3px;
  min-height: 58px;
  padding: 10px 12px;
  border-radius: 7px;
  background: #f4f8f7;
  color: #5f737d;
  font-size: 12px;
  line-height: 1.45;
}

.home-chat-guide-items b {
  display: block;
  color: #153238;
  font-size: 12px;
  line-height: 1.35;
  font-weight: 820;
}

.home-chat-messages .message-row {
  max-width: min(760px, 92%);
}

.home-chat-messages .message-row.has-generated {
  max-width: min(760px, 96%);
}

.chat-composer.home-chat-composer {
  grid-template-columns: minmax(0, 1fr) 92px;
  padding: 14px 22px 18px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
  background: rgba(255, 255, 255, 0.84);
}

.home-chat-composer textarea {
  min-height: 58px;
  max-height: 104px;
}

.home-chat-composer button {
  min-width: 92px;
}

.home-side {
  display: grid;
  grid-template-rows: minmax(178px, .82fr) minmax(284px, 1.32fr) minmax(216px, 1fr);
  gap: 12px;
  height: 100%;
  min-height: 0;
  align-content: stretch;
  overflow: hidden;
}

.home-side-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

.home-side-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.home-side-head h2 {
  min-width: 0;
  margin: 0;
  color: #10242a;
  font-size: 17px;
  line-height: 1.25;
  font-weight: 830;
  letter-spacing: 0;
}

.home-side-head h2::before {
  content: "";
  display: inline-block;
  width: 4px;
  height: 18px;
  margin-right: 8px;
  border-radius: 999px;
  background: #cd5b20;
  vertical-align: -3px;
}

.home-side-head h2 span,
.home-side-head > span,
.home-side-head a {
  color: #778996;
  font-size: 12px;
  font-weight: 680;
  text-decoration: none;
}

.home-side-head > div {
  min-width: 0;
}

.home-activity-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.home-activity-head a {
  justify-self: end;
  white-space: nowrap;
}

.home-activity-foot {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px 9px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
  color: #7c8b95;
  font-size: 12px;
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
}

.home-activity-foot span {
  white-space: nowrap;
}

.home-activity-foot b {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px 0 17px;
  border-radius: 5px;
  background: #edf8f4;
  color: #278464;
  font-weight: 720;
  white-space: nowrap;
}

.home-activity-foot b::before {
  content: "";
  position: absolute;
  left: 7px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10a76e;
}

.home-collaborator-list {
  display: grid;
  flex: 1 1 auto;
  grid-template-rows: repeat(auto-fit, minmax(68px, 1fr));
  gap: 10px;
  min-height: 0;
}

.home-collaborator {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 0;
  padding: 10px 0;
  border-top: 1px solid rgba(20, 45, 54, 0.07);
}

.home-collaborator:first-child {
  border-top: 0;
}

.home-avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 18%, #1b7f86, #062f36 68%);
  color: #fff;
  font-size: 18px;
  font-weight: 820;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.13), 0 10px 18px rgba(6, 47, 54, .14);
}

.home-collaborator strong {
  display: block;
  color: #132930;
  font-size: 14px;
  font-weight: 820;
}

.home-collaborator p {
  overflow: hidden;
  margin: 3px 0 0;
  color: #6d7f89;
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-collaborator > span {
  color: #11a56b;
  font-size: 12px;
  font-weight: 760;
}

.home-priority-list,
.home-ai-feed {
  display: grid;
  min-height: 0;
  gap: 11px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.home-priority-list {
  flex: 1 1 auto;
  align-content: space-between;
}

.home-ai-feed {
  flex: 1 1 auto;
  align-content: start;
}

.home-priority-list li {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.home-priority-list b {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: #fff;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.home-priority-list b.danger,
.home-priority-list b.warning {
  background: linear-gradient(180deg, #e46722, #c84e12);
}

.home-priority-list b.upload {
  background: linear-gradient(180deg, #009f96, #007f78);
}

.home-priority-list b.info {
  background: linear-gradient(180deg, #3b82f6, #2563eb);
}

.home-priority-list strong {
  display: block;
  overflow: hidden;
  color: #152d34;
  font-size: 13px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-priority-list p {
  overflow: hidden;
  margin: 2px 0 0;
  color: #70818b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-priority-list em {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 7px;
  border-radius: 5px;
  font-size: 12px;
  font-style: normal;
  font-weight: 780;
  white-space: nowrap;
}

.home-priority-list em.danger {
  background: #ffe7e1;
  color: #df4f2f;
}

.home-priority-list em.upload {
  background: #daf6f0;
  color: #00877f;
}

.home-priority-list em.warning {
  background: #fff0cf;
  color: #cf7600;
}

.home-priority-list em.info {
  background: #e6efff;
  color: #2563eb;
}

.home-regenerate {
  height: 30px;
  margin: 0 0 0 auto;
  padding: 0 8px;
  border-color: rgba(20, 45, 54, 0.1);
  background: #f8faf9;
  color: #526872;
  box-shadow: none;
}

.home-priority-basis-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px 44px;
  gap: 6px;
  margin: -4px 0 13px;
}

.home-priority-basis-form input {
  min-width: 0;
  height: 34px;
  border: 1px solid rgba(20, 45, 54, 0.13);
  border-radius: 6px;
  background: #fff;
  color: #153138;
  font: inherit;
  font-size: 12px;
  outline: none;
  padding: 0 9px;
  transition: border-color .18s ease, box-shadow .18s ease;
}

.home-priority-basis-form input:focus {
  border-color: rgba(15, 118, 110, 0.42);
  box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.09);
}

.home-priority-basis-form button {
  height: 34px;
  border: 1px solid rgba(20, 45, 54, 0.13);
  border-radius: 6px;
  background: #fff;
  color: #153138;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  cursor: pointer;
}

.home-priority-basis-form button[type="submit"] {
  border-color: #08383e;
  background: #08383e;
  color: #fff;
}

.home-ai-feed li {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.home-ai-feed li span {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: #0b4a50;
}

.home-ai-feed li span::after {
  content: "";
  width: 6px;
  height: 6px;
  border: 1px solid rgba(255, 255, 255, 0.85);
  border-radius: 50%;
}

.home-ai-feed p {
  overflow: hidden;
  margin: 0;
  color: #425962;
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-ai-feed time {
  color: #7a8b96;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 14px;
}

.work-hero,
.panel,
.metric-card,
.task-card,
.doc-card,
.chat-panel,
.conversation-list,
.realtime-panel {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(42, 52, 62, 0.09);
  border-radius: 8px;
  box-shadow: 0 18px 45px rgba(29, 47, 42, 0.07);
  transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease, background .22s ease;
}

.work-hero {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 172px;
  padding: 22px 24px;
  background:
    radial-gradient(circle at 88% 18%, rgba(205, 91, 32, 0.28), transparent 18rem),
    linear-gradient(135deg, rgba(9, 31, 38, 0.97), rgba(31, 49, 45, 0.9)),
    url('https://picsum.photos/seed/engineering-control-room/1600/900');
  background-size: cover;
  background-blend-mode: multiply;
  color: #fff;
  overflow: hidden;
  position: relative;
}

.work-hero::after {
  content: "";
  position: absolute;
  inset: auto 0 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .38), transparent);
}

.hero-copy {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 10px;
}

.hero-copy .eyebrow {
  background: rgba(255,255,255,0.1);
  border-color: rgba(255,255,255,0.18);
  color: rgba(255,255,255,0.82);
}

.hero-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-meta span {
  padding: 5px 8px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.hero-copy h1,
.chat-head h1 {
  margin: 0;
  font-size: clamp(24px, 2.4vw, 34px);
  line-height: 1.12;
  letter-spacing: 0;
  font-weight: 820;
  text-wrap: balance;
}

.hero-copy p {
  max-width: 720px;
  margin: 0;
  color: rgba(255, 255, 255, 0.72);
  line-height: 1.6;
  font-size: 13px;
}

.hero-actions,
.task-actions,
.quick-chips,
.filter-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.command-btn,
.quick-input button,
.chat-composer button,
.task-actions button,
.task-actions a,
.new-session,
.action-stack button,
.quick-chips button,
.filter-tabs button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid rgba(27, 36, 48, 0.12);
  border-radius: 6px;
  background: #fff;
  color: var(--text-primary);
  padding: 9px 13px;
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(255,255,255,.72) inset;
  transition: transform .2s ease, border-color .2s ease, background .2s ease, box-shadow .2s ease;
}

.command-btn:hover,
.quick-input button:hover,
.chat-composer button:hover,
.task-actions button:hover,
.task-actions a:hover,
.new-session:hover,
.action-stack button:hover,
.quick-chips button:hover,
.filter-tabs button:hover {
  transform: translateY(-1px);
  border-color: var(--color-primary);
  box-shadow: 0 10px 24px rgba(29, 47, 42, .11);
}

.command-btn:active,
.quick-input button:active,
.chat-composer button:active,
.task-actions button:active,
.task-actions a:active,
.new-session:active,
.action-stack button:active,
.quick-chips button:active,
.filter-tabs button:active {
  transform: translateY(0) scale(.98);
}

.command-btn.primary,
.quick-input button,
.chat-composer button,
.task-actions a,
.task-actions .done {
  background: var(--color-primary);
  color: #fff;
  border-color: var(--color-primary);
}

.command-btn.compact { padding: 7px 10px; font-size: 12px; }

.metric-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  padding: 16px;
  position: relative;
  overflow: hidden;
}

.metric-card:hover,
.panel:hover,
.task-card:hover,
.doc-card:hover {
  border-color: rgba(15, 118, 110, 0.22);
  box-shadow: 0 20px 45px rgba(29, 47, 42, 0.1);
}

.metric-card::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, #0f766e, var(--color-primary));
  opacity: .75;
}
.metric-card span,
.metric-card em {
  display: block;
  color: var(--text-muted);
  font-style: normal;
}
.metric-card span {
  font-size: 12px;
  font-weight: 720;
}
.metric-card strong {
  display: block;
  margin: 10px 0 4px;
  color: #102528;
  font-size: 30px;
  line-height: 1;
  font-weight: 820;
  font-variant-numeric: tabular-nums;
}

.panel { padding: 16px; min-width: 0; }
.panel.flush { box-shadow: none; }
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.panel-head h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 5px;
  color: #102528;
  font-size: 16px;
  line-height: 1.25;
  font-weight: 800;
}
.panel-head h2::before {
  content: "";
  width: 4px;
  height: 15px;
  border-radius: 999px;
  background: var(--color-primary);
}
.panel-head p { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.45; }
.panel-head a { color: var(--color-primary); text-decoration: none; font-weight: 700; font-size: 12px; }

.people-list,
.stage-list,
.context-stack,
.action-stack,
.risk-list,
.document-list,
.work-queue,
.priority-list,
.session-task-list,
.participant-list {
  display: grid;
  gap: 10px;
}

.person-row,
.stage-row,
.context-item,
.risk-list article,
.document-list article,
.participant-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 7px;
  background: rgba(247, 249, 247, 0.86);
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: #173235;
  color: #fff;
  font-weight: 800;
}

.person-main { flex: 1; display: grid; gap: 2px; }
.person-main span,
.person-main em,
.person-meta span,
.task-meta span { color: var(--text-muted); font-size: 12px; }
.person-main em { font-style: normal; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 360px; }
.person-meta { text-align: right; }
.person-meta b { display: block; font-size: 18px; }

.my-work-panel {
  min-height: 394px;
}

.work-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 14px;
  border-radius: 8px;
  background: #f8faf8;
  border: 1px solid rgba(42, 52, 62, .08);
}

.work-item-main {
  min-width: 0;
}

.work-item-main > span {
  display: inline-flex;
  width: fit-content;
  margin-bottom: 8px;
  padding: 3px 7px;
  border-radius: 4px;
  background: #eef4f1;
  color: #0f766e;
  font-size: 11px;
  font-weight: 780;
}

.work-item-main strong {
  display: block;
  color: #102528;
  font-size: 16px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.work-item-main p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.work-item-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.work-item-action {
  display: grid;
  justify-items: end;
  gap: 10px;
  min-width: 102px;
}

.work-item-action b {
  color: #102528;
  font-size: 12px;
}

.work-item-action a {
  padding: 7px 10px;
  border-radius: 6px;
  background: #173235;
  color: #fff;
  font-size: 12px;
  font-weight: 760;
  text-decoration: none;
}

.priority-list {
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: priority;
}

.priority-list li {
  counter-increment: priority;
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 10px;
  align-items: start;
  padding: 11px;
  border-radius: 8px;
  background: #f8faf8;
}

.priority-list li::before {
  content: counter(priority);
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: #173235;
  color: #fff;
  font-weight: 820;
  font-variant-numeric: tabular-nums;
}

.priority-list strong,
.priority-list span {
  grid-column: 2;
}

.priority-list strong {
  color: #102528;
  font-size: 14px;
  line-height: 1.35;
}

.priority-list span {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.progress-total {
  color: var(--color-primary);
  font-size: 30px;
  font-variant-numeric: tabular-nums;
}
.progress-track,
.mini-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #dfe6e1;
}
.progress-track span,
.mini-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0f766e, var(--color-primary));
}
.stage-row span { flex: 1; min-width: 0; }
.stage-row .mini-track { width: 120px; height: 6px; }

.quick-panel,
.activity-panel { align-self: start; }
.quick-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}
.quick-input input,
.chat-composer textarea {
  width: 100%;
  border: 1px solid var(--border-emphasis);
  border-radius: 6px;
  background: #fff;
  color: var(--text-primary);
  font: inherit;
  outline: none;
}
.quick-input input { height: 40px; padding: 0 12px; }
.quick-input input:focus,
.chat-composer textarea:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(205, 91, 32, 0.12);
}
.quick-chips { margin-top: 10px; }
.quick-chips button { padding: 7px 10px; font-size: 12px; color: var(--text-secondary); }

.activity-list {
  display: grid;
  gap: 10px;
  list-style: none;
}
.activity-list li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 9px;
  align-items: start;
}
.activity-list p,
.document-list p,
.task-card p,
.session-item span {
  margin: 3px 0 0;
  color: var(--text-muted);
  line-height: 1.55;
}
.activity-list time,
.session-item time { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.log-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; background: var(--color-info); }
.log-dot.success { background: var(--color-success); }
.log-dot.warning { background: var(--color-warning); }
.log-dot.error { background: var(--color-danger); }

.chat-layout {
  height: calc(100dvh - var(--header-height) - 36px);
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 300px;
  gap: 12px;
}
.conversation-list,
.realtime-panel {
  padding: 12px;
  overflow: auto;
}
.new-session { width: 100%; margin-bottom: 10px; }
.session-item {
  display: grid;
  gap: 7px;
  padding: 12px;
  border-radius: 7px;
  cursor: pointer;
  border: 1px solid transparent;
}
.session-item.active {
  background: #eef4f1;
  border-color: rgba(15, 118, 110, .22);
}

.session-title-row {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.session-title-row strong,
.chat-head h1,
.session-task-head strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-title-row strong {
  color: #102528;
  font-size: 14px;
  line-height: 1.35;
  font-weight: 820;
}

.session-desc {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.session-meta span {
  padding: 3px 6px;
  border-radius: 4px;
  background: rgba(15, 118, 110, .08);
  color: #0f766e;
  font-size: 11px;
  font-weight: 760;
}

.chat-panel {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-width: 0;
  overflow: hidden;
}
.chat-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 18px 10px;
}

.chat-title-block {
  min-width: 0;
}

.chat-head h1 {
  max-width: 100%;
  font-size: 20px;
  line-height: 1.25;
  letter-spacing: 0;
  font-weight: 820;
}

.chat-subline {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 7px;
  color: var(--text-muted);
  font-size: 12px;
}

.messages {
  overflow: auto;
  padding: 10px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.message-row {
  display: grid;
  grid-template-columns: 28px minmax(0, max-content);
  align-items: start;
  gap: 9px;
  max-width: min(720px, 92%);
}

.message-row.user {
  grid-template-columns: minmax(0, max-content);
  justify-content: end;
  align-self: flex-end;
}

.message-row.has-generated {
  max-width: min(720px, 94%);
}

.message-avatar {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: #173235;
  color: #fff;
  font-size: 12px;
  font-weight: 820;
}

.message-row.user .message-avatar {
  display: none;
}

.message-stack {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.message-row.user .message-stack {
  justify-items: end;
}

.message-role {
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 800;
}

.message-bubble {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f3f6f4;
  color: var(--text-primary);
  box-shadow: 0 1px 0 rgba(255,255,255,.82) inset;
}

.message-row.user .message-bubble {
  background: #153336;
  color: #fff;
  border-top-right-radius: 4px;
}

.message-row.assistant .message-bubble {
  border-top-left-radius: 4px;
}

.message-bubble p { margin: 0; line-height: 1.65; }

.generated-work {
  display: grid;
  gap: 9px;
  margin-top: 12px;
  padding: 11px;
  border-radius: 8px;
  background: rgba(255, 255, 255, .74);
  border: 1px solid rgba(15, 118, 110, .14);
}

.generated-work-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.generated-work-head span {
  color: #0f766e;
  font-size: 12px;
  font-weight: 820;
}

.generated-work-head strong {
  color: #102528;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.generated-task-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 10px;
  align-items: center;
  padding: 10px;
  border-radius: 7px;
  background: #fff;
  border: 1px solid rgba(42, 52, 62, .08);
}

.generated-task-main {
  min-width: 0;
}

.generated-task-main strong {
  display: block;
  color: #102528;
  font-size: 13px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.generated-task-main p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.generated-task-card .mini-track {
  grid-column: 1 / -1;
  width: 100%;
  height: 5px;
}

.generated-task-card a {
  width: fit-content;
  padding: 5px 8px;
  border-radius: 5px;
  background: #173235;
  color: #fff;
  font-size: 12px;
  font-weight: 760;
  text-decoration: none;
}
.chat-composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  padding: 14px;
  border-top: 1px solid var(--border-default);
}
.chat-composer textarea {
  min-height: 58px;
  resize: none;
  padding: 10px 12px;
}

.session-task {
  display: grid;
  gap: 8px;
  padding: 11px;
  border-radius: 8px;
  background: #f8faf8;
  border: 1px solid rgba(42, 52, 62, .08);
}

.session-task-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.session-task-head strong {
  color: #102528;
  font-size: 13px;
  line-height: 1.35;
}

.session-task-head span {
  padding: 2px 6px;
  border-radius: 4px;
  background: #eef4f1;
  color: #173235;
  font-size: 11px;
  font-weight: 760;
}

.session-task p,
.participant-row span {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.participant-row {
  background: #f8faf8;
}

.participant-row > div:last-child {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.participant-row strong {
  color: #102528;
  font-size: 13px;
}

.collaboration-screen {
  grid-template-columns: 280px minmax(0, 1fr) 340px;
  gap: 12px;
  height: calc(100dvh - var(--header-height) - 24px);
}

.collab-sessions,
.collab-chat-panel,
.collab-side {
  border-color: rgba(20, 45, 54, 0.1);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 20px 46px rgba(28, 48, 44, 0.07);
}

.collab-sessions {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  padding: 0;
  overflow: hidden;
}

.conversation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 16px 12px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.conversation-head h2 {
  margin: 0;
  color: #10242a;
  font-size: 17px;
  line-height: 1.25;
  font-weight: 830;
}

.conversation-head .new-session {
  width: auto;
  height: 36px;
  margin: 0;
  padding: 0 12px;
  font-size: 13px;
}

.session-groups {
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.session-group {
  display: grid;
  gap: 8px;
  margin-bottom: 18px;
}

.session-group h3 {
  margin: 0 0 2px;
  color: #6e8089;
  font-size: 12px;
  line-height: 1.3;
  font-weight: 760;
}

.collab-sessions .session-item {
  gap: 7px;
  padding: 13px 14px;
  border: 1px solid rgba(20, 45, 54, 0.1);
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 0 rgba(255,255,255,.8) inset;
}

.collab-sessions .session-item.active {
  border-color: rgba(15, 118, 110, 0.42);
  background: #eef9f7;
  box-shadow: inset 3px 0 0 #0f766e, 0 10px 24px rgba(15, 118, 110, 0.08);
}

.collab-sessions .session-title-row {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
}

.collab-sessions .session-item time {
  color: #627781;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.conversation-tools {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 12px 16px 14px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
}

.conversation-tools button,
.chat-head-actions button,
.title-chevron,
.composer-tools button {
  display: inline-grid;
  place-items: center;
  border: 1px solid rgba(20, 45, 54, 0.11);
  border-radius: 7px;
  background: #fff;
  color: #425961;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.conversation-tools button {
  height: 34px;
}

.conversation-tools button:hover,
.chat-head-actions button:hover,
.title-chevron:hover,
.composer-tools button:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.28);
  box-shadow: 0 10px 20px rgba(28, 48, 44, 0.08);
}

.collab-chat-panel {
  grid-template-rows: auto minmax(0, 1fr) auto auto;
}

.collab-chat-head {
  align-items: center;
  padding: 20px 24px 14px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.collab-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.collab-title-row h1 {
  max-width: 100%;
  font-size: 21px;
  line-height: 1.25;
}

.title-chevron {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
}

.chat-head-actions {
  display: flex;
  gap: 8px;
}

.chat-head-actions button {
  width: 38px;
  height: 38px;
}

.collab-messages {
  padding: 18px 26px 16px;
  gap: 14px;
  background:
    radial-gradient(circle at 8% 0, rgba(15, 118, 110, 0.06), transparent 16rem),
    linear-gradient(180deg, rgba(255,255,255,.92), rgba(248,250,249,.65));
}

.collab-messages .message-role {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #153238;
}

.collab-messages .message-role span {
  color: #153238;
}

.collab-messages .message-role time {
  color: #7b8c95;
  font-size: 12px;
  font-weight: 620;
}

.collab-messages .message-bubble {
  max-width: 560px;
  border: 1px solid rgba(20, 45, 54, 0.08);
  background: #fff;
  box-shadow: 0 10px 22px rgba(28, 48, 44, 0.05);
}

.collab-messages .message-row.user .message-bubble {
  border-color: rgba(8, 56, 62, 0.28);
  background: linear-gradient(135deg, #073940, #0a4b50);
  box-shadow: 0 16px 32px rgba(8, 56, 62, 0.18);
}

.collab-messages .message-row.has-generated {
  max-width: min(720px, 96%);
}

.collab-messages .generated-work {
  width: min(660px, 100%);
  padding: 14px;
  background: #fff;
}

.generated-work-head button {
  border: 0;
  background: transparent;
  color: #0f766e;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  cursor: pointer;
}

.collab-messages .generated-task-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.generated-task-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.generated-task-title em {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 7px;
  border-radius: 5px;
  background: #eef8f6;
  color: #0f766e;
  font-size: 12px;
  font-style: normal;
  font-weight: 760;
  white-space: nowrap;
}

.generated-task-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  grid-column: 1 / -1;
}

.collab-messages .generated-task-card {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  align-content: start;
  gap: 12px;
  min-height: 0;
  padding: 10px 11px;
}

.collab-messages .generated-task-main {
  min-width: 0;
}

.collab-messages .generated-task-title strong {
  min-width: 0;
  color: #102528;
  font-size: 13px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collab-messages .generated-task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 6px;
  color: #6f8089;
  font-size: 12px;
  line-height: 1.45;
}

.collab-messages .generated-task-card .mini-track {
  grid-column: auto;
  margin-top: 8px;
}

.collab-messages .generated-task-foot {
  grid-column: auto;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  min-width: 54px;
}

.collab-messages .generated-task-foot a {
  width: 48px;
  text-align: center;
}

.chat-suggestion-panel {
  display: grid;
  gap: 8px;
  padding: 10px 24px 4px;
  border-top: 1px solid rgba(20, 45, 54, 0.07);
  background: linear-gradient(180deg, rgba(255,255,255,.84), rgba(248,250,249,.96));
}

.suggestion-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(15, 118, 110, 0.2);
  border-radius: 7px;
  background: #f5fbf9;
  color: #0f5f5a;
  font: inherit;
  font-size: 12px;
  font-weight: 780;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(15, 118, 110, .06);
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}

.suggestion-toggle:hover {
  border-color: rgba(15, 118, 110, 0.34);
  background: #eef8f6;
}

.suggestion-toggle:active {
  transform: translateY(1px);
}

.suggestion-toggle:focus {
  outline: none;
}

.suggestion-toggle:focus-visible {
  outline: 2px solid rgba(15, 118, 110, .24);
  outline-offset: 2px;
}

.suggestion-arrow {
  transform: rotate(180deg);
  transition: transform .18s ease;
}

.suggestion-arrow.open {
  transform: rotate(0deg);
}

.suggestion-list {
  display: grid;
  gap: 7px;
}

.suggestion-list button {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid rgba(15, 118, 110, .14);
  border-radius: 7px;
  background: #fff;
  color: #234047;
  text-align: left;
  cursor: pointer;
}

.suggestion-list strong {
  color: #0f766e;
  font-size: 12px;
}

.suggestion-list span {
  min-width: 0;
  overflow: hidden;
  color: #667880;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 24px 8px;
  border-top: 1px solid rgba(20, 45, 54, 0.07);
  background: rgba(248,250,249,.96);
}

.chat-suggestion-panel + .chat-input-toolbar {
  border-top: 0;
}

.chat-input-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-input-tools button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(20, 45, 54, 0.12);
  border-radius: 7px;
  background: #fff;
  color: #425961;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}

.chat-input-tools button:hover {
  border-color: rgba(15, 118, 110, 0.24);
  background: #f7fbfa;
}

.chat-input-tools button:active {
  transform: translateY(1px);
}

.chat-input-tools button:focus {
  outline: none;
}

.chat-input-tools button:focus-visible {
  outline: 2px solid rgba(15, 118, 110, .2);
  outline-offset: 2px;
}

.collab-composer {
  grid-template-columns: minmax(0, 1fr) 88px;
  align-items: center;
  padding: 0 14px 14px;
  border-top: 0;
}

.collab-composer textarea {
  min-height: 66px;
  max-height: 110px;
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 4px;
}

.collab-composer .composer-tools button {
  width: 34px;
  height: 34px;
  padding: 0;
  box-shadow: none;
}

.collab-composer .send-button {
  height: 46px;
  padding: 0 16px;
  border-color: #073940;
  background: linear-gradient(135deg, #073940, #0b5155);
  color: #fff;
  box-shadow: 0 14px 26px rgba(8, 56, 62, 0.18);
}

.collab-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0;
  overflow: auto;
  background: transparent;
  border: 0;
  box-shadow: none;
}

.collab-side-panel {
  padding: 14px;
  background: rgba(255, 255, 255, 0.94);
}

.collab-side .panel-head {
  align-items: center;
  margin-bottom: 12px;
}

.collab-side .panel-head a,
.panel-text-button {
  border: 0;
  background: transparent;
  color: #0f766e;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  text-decoration: none;
  cursor: pointer;
}

.task-progress-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 34px;
  gap: 8px;
  align-items: center;
}

.task-progress-row em {
  color: #7d8c94;
  font-size: 12px;
  font-style: normal;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.collab-side .participant-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid rgba(20, 45, 54, 0.07);
  border-radius: 8px;
}

.collab-side .participant-row strong span {
  margin-left: 4px;
  padding: 1px 5px;
  border-radius: 4px;
  background: #eef8f6;
  color: #0f766e;
  font-size: 11px;
}

.collab-side .participant-row small {
  color: #75858e;
  font-size: 12px;
}

.missing-material-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.missing-material-list li {
  display: grid;
  gap: 3px;
  padding-left: 12px;
  position: relative;
}

.missing-material-list li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #0f766e;
}

.missing-material-list strong {
  color: #263d45;
  font-size: 12px;
  line-height: 1.4;
}

.missing-material-list span {
  color: #778891;
  font-size: 12px;
}

.action-side-panel .action-stack {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.action-side-panel .action-stack button {
  min-height: 38px;
  padding: 0 10px;
  color: #173235;
}

.page-stack {
  display: grid;
  gap: 14px;
}

.task-page {
  gap: 12px;
}

.task-hero {
  padding: 12px;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(255,255,255,.98), rgba(244, 248, 246, .94)),
    radial-gradient(circle at 96% 12%, rgba(15, 118, 110, .12), transparent 20rem);
  border: 1px solid rgba(42, 52, 62, 0.09);
  box-shadow: 0 18px 45px rgba(29, 47, 42, 0.07);
  position: relative;
  overflow: hidden;
}

.task-hero::before {
  content: "";
  position: absolute;
  left: 0;
  top: 18px;
  bottom: 18px;
  width: 4px;
  border-radius: 0 999px 999px 0;
  background: linear-gradient(180deg, #0f766e, var(--color-primary));
}

.task-summary-strip {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.task-summary-strip article {
  display: grid;
  align-content: center;
  gap: 8px;
  min-height: 86px;
  padding: 12px;
  border-radius: 7px;
  background: rgba(255, 255, 255, .74);
  border: 1px solid rgba(42, 52, 62, .08);
  box-shadow: 0 1px 0 rgba(255,255,255,.8) inset;
}

.task-summary-strip span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.task-summary-strip strong {
  color: #102528;
  font-size: 26px;
  line-height: 1;
  font-weight: 840;
  font-variant-numeric: tabular-nums;
}

.task-filterbar {
  position: sticky;
  top: 0;
  z-index: 12;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid rgba(42, 52, 62, 0.09);
  box-shadow: 0 8px 20px rgba(24, 54, 51, .07);
}

.task-filterbar > span {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 760;
  white-space: nowrap;
}
.task-filterbar .filter-tabs {
  flex: 0 1 auto;
  flex-wrap: nowrap;
  margin-left: auto;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
}
.task-filterbar .filter-tabs::-webkit-scrollbar { display: none; }
.task-filterbar .filter-tabs button { flex: 0 0 auto; gap: 7px; }
.task-filter-count {
  display: inline-grid;
  min-width: 20px;
  height: 20px;
  box-sizing: border-box;
  place-items: center;
  padding: 0 6px;
  border-radius: 999px;
  background: #edf3f1;
  color: #48635d;
  font-size: 11px;
  font-weight: 820;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.task-filterbar .filter-tabs button.active .task-filter-count {
  background: rgba(255, 255, 255, .16);
  color: #fff;
}
.task-create-button {
  flex: 0 0 auto;
  margin-left: 0;
  padding: 7px 11px;
  border: 1px solid var(--border-emphasis);
  border-radius: 6px;
  color: var(--color-primary);
  background: #fff;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.workflow-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 32, 35, .42);
  backdrop-filter: blur(2px);
}
.workflow-modal {
  width: min(100%, 760px);
  max-height: calc(100dvh - 48px);
  overflow: auto;
  padding: 20px;
  border: 1px solid rgba(28, 56, 57, .18);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 22px 56px rgba(15, 39, 42, .26);
}
.workflow-modal-head { display:flex; justify-content:space-between; align-items:center; gap:14px; min-width:0; margin-bottom:12px; }
.workflow-modal-head > div { display:flex; flex:1 1 auto; align-items:baseline; gap:10px; min-width:0; }
.workflow-modal-head span { flex:0 0 auto; color:var(--color-primary); font-size:12px; font-weight:800; letter-spacing:.04em; white-space:nowrap; }
.workflow-modal-head h2 { flex:0 1 auto; overflow:hidden; min-width:0; margin:0; color:#173235; font-size:17px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }
.workflow-modal-head p { flex:1 1 18rem; overflow:hidden; min-width:6rem; max-width:none; margin:0; color:var(--text-muted); font-size:12px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }
.workflow-modal-head .modal-close { flex:0 0 auto; }
.information-disposition-modal { width: min(560px, 100%); }
.information-disposition-content { display: grid; gap: 10px; padding: 2px 0 8px; }
.information-disposition-content > strong { color: #173235; font-size: 14px; line-height: 1.45; }
.information-disposition-meta { display:flex; flex-wrap:wrap; align-items:center; gap:5px; color:var(--text-muted); font-size:12px; line-height:1.4; }
.information-disposition-meta span+span::before { margin-right:5px; color:#9baca8; content:'·'; }
.information-disposition-content > p { margin: 0; padding: 11px 12px; border: 1px solid #e2ebe8; border-radius: 7px; color: #385b56; background: #f7faf9; font-size: 13px; line-height: 1.65; }
.modal-close,.modal-secondary,.modal-assist,.modal-primary { border: 0; border-radius: 6px; padding: 8px 12px; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; transition: transform .16s ease, box-shadow .16s ease, background .16s ease; }
.modal-close,.modal-secondary { border: 1px solid var(--border-emphasis); color: var(--text-secondary); background: #fff; }
.modal-primary { color: #fff; background: var(--color-primary); box-shadow: 0 4px 10px rgba(205, 91, 32, .18); }
.modal-assist { color: #0c5d58; background: #e7f4f0; }
.modal-assist:disabled { opacity: .5; cursor: not-allowed; }
.modal-close:hover,.modal-secondary:hover,.modal-assist:hover,.modal-primary:hover { transform: translateY(-1px); }
.modal-close:active,.modal-secondary:active,.modal-assist:active,.modal-primary:active { transform: translateY(0); }
.form-field { display: grid; gap: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 750; }
.form-field input,.form-field select,.form-field textarea { width: 100%; min-width: 0; box-sizing: border-box; padding: 9px 10px; border: 1px solid var(--border-emphasis); border-radius: 6px; background: #fff; color: var(--text-primary); font: inherit; font-size: 13px; }
.form-field textarea { min-height: 106px; resize: vertical; line-height: 1.55; }
.form-field input:focus,.form-field select:focus,.form-field textarea:focus { outline: 2px solid rgba(205, 91, 32, .2); outline-offset: 1px; border-color: var(--color-primary); }
.workflow-modal-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.task-create-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 13px 12px;
}
.task-form-title,.task-form-workflow { grid-column: 1 / -1; }
.task-flow-modal {
  display: flex;
  flex-direction: column;
  width: 90vw;
  max-width: none;
  height: 90dvh;
  max-height: 90dvh;
  padding: 0;
  overflow: hidden;
}
.task-flow-modal > .workflow-modal-head {
  flex: 0 0 auto;
  align-items: center;
  margin: 0;
  padding: 10px 18px;
  border-bottom: 1px solid #e1e9e7;
}
.task-flow-form { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; }
.task-flow-global-settings { display:grid; flex:0 0 auto; gap:11px; padding:12px 18px 14px; border-bottom:1px solid #dfe8e6; background:#f8faf9; }
.task-flow-global-head { display:flex; align-items:center; justify-content:space-between; gap:24px; }
.task-flow-global-copy { display:flex; min-width:0; align-items:center; gap:16px; }
.task-flow-global-copy>div { display:flex; flex:0 0 auto; align-items:baseline; gap:10px; }
.task-flow-global-head span { color:#0f766e; font-size:12px; font-weight:850; letter-spacing:.04em; }
.task-flow-global-head strong { color:#173235; font-size:14px; }
.task-flow-global-copy p { overflow:hidden; margin:0; color:#6c827e; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.task-flow-global-settings .form-field { gap:5px; font-size:12px; }
.task-flow-global-settings .form-field input,.task-flow-global-settings .form-field select { min-height:36px; padding:7px 9px; font-size:12px; }
.task-flow-trigger-grid { display:flex; align-items:end; gap:9px; }
.task-flow-trigger-grid>.form-field { flex:0 1 190px; }
.task-flow-trigger-grid>.form-field:nth-child(2) { flex-basis:230px; }
.task-flow-trigger-grid>.task-flow-cc-field { flex:1 1 240px; }
.task-flow-interval-field { flex-basis:230px !important; }
.task-flow-interval-field>span { display:grid; grid-template-columns:minmax(72px,.65fr) minmax(100px,1fr); gap:6px; }
.task-flow-trigger-preview { display:flex; flex:0 1 auto; min-width:0; align-items:center; gap:8px; padding:6px 10px; border-left:2px solid #58a698; background:#eef6f3; }
.task-flow-trigger-preview span { flex:0 0 auto; color:#64817b; font-size:12px; }
.task-flow-trigger-preview strong { overflow:hidden; color:#164a43; font-size:12px; font-variant-numeric:tabular-nums; text-overflow:ellipsis; white-space:nowrap; }
.task-flow-body { display: grid; flex: 1 1 auto; min-height: 0; grid-template-columns: minmax(330px, 31%) minmax(0, 1fr); }
.task-flow-brief { min-height: 0; overflow-y: auto; padding: 16px; border-right: 1px solid #e1e9e7; background: #f7faf9; }
.task-flow-mode-switch { display: grid; grid-template-columns: 1fr 1fr; padding: 3px; border: 1px solid #dbe6e2; border-radius: 8px; background: #eaf1ef; }
.task-flow-mode-switch button { border: 0; border-radius: 6px; padding: 9px 12px; color: #5b716e; background: transparent; font: inherit; font-size: 13px; font-weight: 750; cursor: pointer; }
.task-flow-mode-switch button.active { color: #fff; background: #173f3e; box-shadow: 0 3px 8px rgba(23,63,62,.17); }
.task-flow-generator { margin-top: 12px; padding: 14px; border: 1px solid #dde8e5; border-radius: 9px; background: #fff; }
.dobby-generator { border-color: rgba(15,118,110,.26); background: linear-gradient(145deg, #f2fbf8, #fff 58%); }
.task-flow-section-title,.task-flow-editor-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.task-flow-section-title > div,.task-flow-editor-head > div { display: grid; gap: 3px; }
.task-flow-section-title span,.task-flow-editor-head span,.task-flow-canvas-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }
.task-flow-section-title strong,.task-flow-editor-head strong { color: #173235; font-size: 14px; }
.task-flow-section-title em,.task-flow-editor-head em { color: #76908b; font-size: 12px; font-style: normal; white-space: nowrap; }
.task-flow-generator textarea { width: 100%; min-height: 100px; box-sizing: border-box; padding: 10px 11px; border: 1px solid #cadbd6; border-radius: 7px; color: #173235; background: #fff; font: inherit; font-size: 13px; line-height: 1.6; resize: vertical; }
.task-flow-generator textarea:focus { outline: 2px solid rgba(15,118,110,.18); border-color: #0f766e; }
.task-flow-examples { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.task-flow-examples button { max-width: 100%; overflow: hidden; border: 1px solid #d7e7e2; border-radius: 999px; padding: 6px 9px; color: #54706b; background: #fff; font: inherit; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.task-flow-examples button:hover { border-color: #7eb5aa; color: #0f766e; }
.task-flow-generate-button { width: 100%; margin-top: 10px; border: 0; border-radius: 7px; padding: 10px 12px; color: #fff; background: #0f766e; font: inherit; font-size: 13px; font-weight: 800; cursor: pointer; box-shadow: 0 5px 12px rgba(15,118,110,.16); }
.task-flow-generate-button:disabled { opacity: .52; cursor: not-allowed; box-shadow: none; }
.task-flow-generation-note { margin: 9px 0 0; color: #52706b; font-size: 12px; line-height: 1.55; }
.template-generator { display: grid; gap: 10px; }
.template-generator .task-flow-section-title { margin-bottom: 0; }
.task-flow-canvas { display: flex; min-width: 0; min-height: 0; flex-direction: column; padding: 16px 18px 0; overflow: hidden; background: #fff; }
.task-flow-canvas-head { display: flex; flex: 0 0 auto; min-width:0; align-items:center; justify-content:space-between; gap:16px; padding-bottom:9px; border-bottom:1px solid #e5ecea; }
.task-flow-canvas-head>div { display:flex; min-width:0; align-items:baseline; gap:10px; }
.task-flow-canvas-head h3 { overflow:hidden; margin:0; color:#173235; font-size:15px; text-overflow:ellipsis; white-space:nowrap; }
.task-flow-canvas-head p { flex:0 0 auto; margin:0; color:#748984; font-size:12px; white-space:nowrap; }
.task-flow-add-button { flex: 0 0 auto; border: 1px solid #bbd5cf; border-radius: 6px; padding: 8px 10px; color: #0f766e; background: #f6fbf9; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
.task-flow-canvas-body { display:grid; flex:1 1 auto; min-height:0; grid-template-columns:minmax(0,1fr) minmax(190px,.42fr); gap:14px; padding-top:10px; }
.task-flow-editor-panel { display:flex; min-width:0; min-height:0; flex-direction:column; }
.task-flow-preview-panel { display:flex; min-width:0; min-height:0; flex-direction:column; padding-left:14px; border-left:1px solid #e1e9e7; }
.task-flow-preview-head { display:grid; flex:0 0 auto; gap:2px; }
.task-flow-preview-head span { color:#0f766e; font-size:12px; font-weight:850; letter-spacing:.04em; }
.task-flow-preview-head strong { color:#173235; font-size:14px; }
.task-flow-preview-head em { color:#76908b; font-size:12px; font-style:normal; }
.task-flow-strip { display: flex; flex:1 1 auto; min-height:0; flex-direction:column; align-items:stretch; gap:6px; margin:10px 0 16px; padding:12px; overflow-y:auto; border: 1px solid #dfe8e6; border-radius: 9px; background: linear-gradient(180deg, #f7faf9, #fbfcfc); }
.task-flow-node { position: relative; display: grid; flex:0 0 auto; width:100%; min-height:70px; box-sizing:border-box; align-content: center; gap: 3px; border: 1px solid #cfdedb; border-radius: 8px; padding: 11px 10px 10px 39px; color: #173235; background: #fff; text-align: left; cursor: pointer; box-shadow: 0 3px 9px rgba(23,50,53,.05); }
.task-flow-node > span { position: absolute; top: 10px; left: 10px; display: grid; width: 22px; height: 22px; place-items: center; border-radius: 50%; color: #fff; background: #7d9792; font-size: 12px; font-weight: 850; }
.task-flow-node strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-node em { overflow: hidden; color: #657d78; font-size: 12px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-node.active { border-color: #0f766e; background: #eff9f6; box-shadow: 0 0 0 2px rgba(15,118,110,.1); }
.task-flow-node.active > span { background: #0f766e; }
.task-flow-arrow { flex: 0 0 auto; height:16px; color: #8da29e; font-size: 17px; line-height:16px; text-align:center; }
.task-flow-empty { display: grid; width: 100%; min-height: 80px; place-items: center; color: #82938f; font-size: 12px; }
.task-flow-editor-head { flex: 0 0 auto; margin: 0 0 10px; padding-top: 1px; }
.task-flow-editor-actions { display:flex; align-items:center; gap:9px; }
.task-flow-editor-actions .task-flow-add-button { padding:6px 9px; }
.task-flow-node-grid { display: grid; min-height: 0; flex: 1 1 auto; grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr)); grid-auto-rows:max-content; align-content: start; gap: 10px; padding: 0 5px 16px 0; overflow-y: auto; }
.task-flow-node-card { border: 1px solid #dce6e3; border-radius: 9px; padding: 12px; background: #fff; transition: border-color .16s ease, box-shadow .16s ease; }
.task-flow-node-card.active { border-color: #8fbab2; box-shadow: 0 4px 14px rgba(15,118,110,.09); }
.task-flow-node-card header { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; align-items: center; gap: 8px; margin-bottom: 10px; }
.task-flow-node-card header > span { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 6px; color: #0f766e; background: #e6f3ef; font-size: 12px; font-weight: 850; }
.task-flow-node-card header > strong { overflow: hidden; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-node-card header > div { display: flex; gap: 4px; }
.task-flow-node-card header button { border: 1px solid #d8e3e0; border-radius: 5px; padding: 5px 7px; color: #48645f; background: #f8faf9; font: inherit; font-size: 12px; cursor: pointer; }
.task-flow-node-card header button.danger { color: #b24b2b; }
.task-flow-node-card header button:disabled { opacity: .35; cursor: not-allowed; }
.task-flow-node-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.task-flow-node-fields .form-field { font-size: 12px; }
.task-flow-node-fields .form-field input,.task-flow-node-fields .form-field select { padding: 8px 9px; font-size: 12px; }
.task-flow-footer { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 16px; padding: 11px 18px; border-top: 1px solid #dfe8e6; background: #f8faf9; }
.task-flow-footer p { margin: 0; color: #647c77; font-size: 12px; }
.task-flow-footer p strong { color: #0f766e; font-size: 15px; }
.task-flow-footer .workflow-modal-actions { margin: 0; }
.task-flow-footer .modal-primary:disabled { opacity: .45; cursor: not-allowed; transform: none; }
.task-step-list { display: grid; gap: 6px; margin: 12px 0 0; padding: 0; list-style: none; }
.task-step-list li { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto auto; align-items: center; gap: 7px; padding: 7px 8px; border-radius: 5px; background: #f6f8f7; color: var(--text-secondary); font-size: 12px; }
.task-step-list li > span { display: grid; width: 19px; height: 19px; place-items: center; border-radius: 50%; background: #dce6e2; color: #48625e; font-size: 10px; font-weight: 800; }.task-step-list li.completed > span { background: #0f766e; color: #fff; }.task-step-list li.blocked { background: #fff5ed; }.task-step-list em { font-style: normal; color: var(--text-muted); }.task-step-list button { border: 0; border-radius: 4px; padding: 4px 6px; background: #e9f3f0; color: #0f766e; font-size: 11px; font-weight: 700; cursor: pointer; }
.task-history-modal { width:min(720px,100%); max-height:min(82dvh,760px); overflow:hidden; }
.task-history-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; overflow:hidden; margin-bottom:16px; border:1px solid #dfe8e5; border-radius:8px; background:#dfe8e5; }
.task-history-summary>div { display:grid; gap:5px; padding:12px 14px; background:#f7faf9; }
.task-history-summary span { color:var(--text-muted); font-size:11px; }
.task-history-summary strong { overflow:hidden; color:#173235; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.task-history-body { min-height:250px; max-height:46dvh; overflow-y:auto; padding:2px 4px 2px 0; }
.task-history-timeline { display:grid; gap:0; margin:0; padding:0; list-style:none; }
.task-history-timeline li { position:relative; display:grid; grid-template-columns:24px minmax(0,1fr); gap:10px; min-height:72px; }
.task-history-timeline li:not(:last-child)::after { position:absolute; top:20px; bottom:-2px; left:8px; width:1px; content:''; background:#cbdcd7; }
.task-history-timeline i { position:relative; z-index:1; display:block; width:17px; height:17px; margin-top:2px; border:4px solid #dff0eb; border-radius:50%; background:#0f766e; box-sizing:border-box; }
.task-history-timeline li>div { padding:0 2px 15px 0; }
.task-history-timeline header { display:flex; align-items:center; justify-content:space-between; gap:14px; }
.task-history-timeline header strong { color:#173235; font-size:13px; }
.task-history-timeline time { flex:0 0 auto; color:var(--text-muted); font-size:11px; font-variant-numeric:tabular-nums; }
.task-history-timeline p { margin:7px 0 0; padding:9px 11px; border-radius:6px; color:#506b66; background:#f5f8f7; font-size:12px; line-height:1.55; }
.task-history-loading,.task-history-empty { display:grid; min-height:250px; place-content:center; justify-items:center; color:var(--text-muted); font-size:12px; text-align:center; }
.task-history-empty strong { color:#294945; font-size:14px; }
.task-history-empty p { margin:6px 0 0; }
.task-history-actions { padding-top:14px; border-top:1px solid #e3ebe9; }
.meeting-minute { margin: 0 16px 12px; padding: 11px 13px; border: 1px solid rgba(15,118,110,.18); border-radius: 7px; background: #f3faf7; color: var(--text-secondary); font-size: 12px; }.meeting-minute strong { color: #173235; }.meeting-minute p { margin: 5px 0; line-height: 1.55; }.meeting-minute span { color: #0f766e; font-weight: 700; }
.change-create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 12px; }.change-form-content { grid-column: 1 / -1; }

.filter-tabs button.active {
  background: #173235;
  color: #fff;
}

.project-focus-strip,
.docs-work-grid {
  display: grid;
  gap: 14px;
}
.document-intake-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 20px;
  border: 1px solid rgba(205,91,32,.24);
  border-radius: 10px;
  background: linear-gradient(100deg, rgba(255,247,242,.96), #fff);
}
.document-intake-panel span { color: var(--color-primary); font-size: 11px; font-weight: 800; letter-spacing: .06em; }
.document-intake-panel h2 { margin: 4px 0; font-size: 16px; }
.document-intake-panel p { margin: 0; color: var(--text-muted); font-size: 12px; }
.document-upload-button { flex: 0 0 auto; padding: 9px 13px; border-radius: 6px; color: #fff; background: var(--color-primary); font-size: 12px; font-weight: 750; cursor: pointer; }
.document-upload-button input { display: none; }.document-upload-button.disabled { opacity: .6; cursor: wait; }
.document-search-panel { display: flex; gap: 8px; margin-top: 12px; }.document-search-panel input { flex: 1; min-width: 0; padding: 9px 11px; border: 1px solid var(--border-emphasis); border-radius: 6px; background: #fff; font: inherit; font-size: 12px; }.document-search-panel button { border: 0; border-radius: 6px; padding: 0 13px; background: #173235; color: #fff; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }.document-search-panel button:disabled { opacity: .6; cursor: wait; }.document-search-results { margin-top: 12px; }
.document-storage-panel, .document-review-panel { margin-top: 18px; }.empty-document-note { padding: 14px 0; color: var(--text-muted); font-size: 13px; }
.draft-create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 12px; }.draft-form-content { grid-column: 1 / -1; }

.project-focus-strip {
  grid-template-columns: minmax(0, 1.2fr) minmax(240px, .62fr) minmax(240px, .62fr);
}

.docs-work-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.focus-card,
.doc-work-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 14px;
  min-height: 142px;
  padding: 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, .9);
  border: 1px solid rgba(42, 52, 62, .09);
  box-shadow: 0 18px 45px rgba(29, 47, 42, 0.07);
  position: relative;
  overflow: hidden;
  transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
}

.focus-card::before,
.doc-work-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: linear-gradient(180deg, #0f766e, var(--color-primary));
}

.focus-card:hover,
.doc-work-card:hover {
  transform: translateY(-2px);
  border-color: rgba(15, 118, 110, 0.22);
  box-shadow: 0 24px 52px rgba(29, 47, 42, 0.11);
}

.focus-card span,
.doc-work-card span {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 760;
}

.focus-card strong,
.doc-work-card strong {
  display: block;
  margin-top: 8px;
  color: #102528;
  font-size: 17px;
  line-height: 1.35;
  font-weight: 820;
}

.focus-card-main strong {
  font-size: 20px;
}

.focus-card p,
.doc-work-card p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.progress-track.compact {
  height: 7px;
}

.doc-work-card a {
  width: fit-content;
  padding: 7px 10px;
  border-radius: 6px;
  background: #102528;
  color: #fff;
  font-size: 12px;
  font-weight: 760;
  text-decoration: none;
  transition: transform .2s ease, background .2s ease;
}

.doc-work-card a:hover {
  transform: translateY(-1px);
  background: var(--color-primary);
}

.task-board {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  grid-auto-rows: minmax(360px, auto);
  align-items: stretch;
  gap: 12px;
}
.task-card { display: flex; min-width: 0; height: 100%; box-sizing: border-box; flex-direction: column; padding: 16px; }
.task-top,
.task-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.task-card h2 { display: -webkit-box; min-height: 48px; overflow: hidden; -webkit-box-orient: vertical; margin: 12px 0 6px; font-size: 17px; line-height: 1.4; -webkit-line-clamp: 2; }
.task-source {
  width: fit-content;
  margin-bottom: 8px;
  padding: 3px 7px;
  border-radius: 4px;
  background: rgba(15, 118, 110, .08);
  color: #0f766e;
  font-size: 11px;
  font-weight: 760;
}
.status-pill {
  padding: 2px 8px;
  border-radius: 4px;
  background: #eef4f1;
  color: #173235;
  font-size: 11px;
  font-weight: 750;
}
.task-actions { margin-top: auto; padding-top: 14px; }
.task-actions button { padding: 7px 10px; font-size: 12px; }

.status-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, .65fr);
  gap: 14px;
}
.span-2 { min-height: 520px; }
.wbs-table { display: grid; gap: 8px; }
.wbs-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1.2fr) 90px minmax(90px, .5fr) 44px;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 7px;
  background: #f8faf8;
}
.wbs-code { color: var(--text-muted); font-family: var(--font-mono, monospace); }
.risk-list article { align-items: flex-start; }

.doc-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.doc-card {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 16px;
}
.doc-icon {
  width: 40px;
  height: 40px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: #eef4f1;
  color: #0f766e;
}
.doc-card h2 { margin: 0 0 4px; font-size: 15px; }
.doc-card p { margin: 0; color: var(--text-muted); font-size: 12px; }
.doc-card strong { font-size: 24px; font-variant-numeric: tabular-nums; }
.document-list article {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) minmax(180px, 1fr) 100px auto;
}
.document-list em { color: var(--color-primary); font-style: normal; font-weight: 700; }
.document-action { padding: 6px 9px; border: 1px solid rgba(21, 94, 117, .2); border-radius: 5px; background: #fff; color: var(--color-primary-dark); font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }
.document-action.confirm { border-color: transparent; background: var(--color-primary); color: #fff; }
.document-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 6px; }.fill-package-list { margin-top: 10px; }

/* Project status — operating dashboard layout */
.project-status-view {
  min-height: calc(100dvh - var(--header-height, 56px) - 36px);
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: 12px;
}
.project-status-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 1px 2px 0; }
.project-status-heading > div { min-width: 0; }
.project-status-heading span,
.status-workspace-head > div > span,
.status-side-panel header span { display: block; color: #0f766e; font-size: 11px; font-weight: 800; letter-spacing: .05em; }
.project-status-heading h1 { margin: 4px 0; color: #173235; font-size: 21px; line-height: 1.25; }
.project-status-heading p { max-width: 68ch; margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.project-status-heading > small { flex: 0 0 auto; margin-bottom: 3px; color: var(--text-muted); font-size: 11px; }

.project-kpi-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.project-kpi-strip article { position: relative; min-width: 0; padding: 14px 15px 13px; border-right: 1px solid #edf1ef; }
.project-kpi-strip article:last-child { border-right: 0; }
.project-kpi-strip article::before { content: ''; position: absolute; top: 13px; bottom: 13px; left: 0; width: 3px; border-radius: 0 999px 999px 0; background: #0f766e; opacity: .9; }
.project-kpi-strip article.orange::before { background: #d97706; }
.project-kpi-strip article.red::before { background: #c2410c; }
.project-kpi-strip article.blue::before { background: #2563eb; }
.project-kpi-strip span { display: block; overflow: hidden; color: var(--text-secondary); font-size: 11px; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
.project-kpi-strip strong { display: block; margin: 7px 0 3px; color: #173235; font-size: 23px; line-height: 1; font-variant-numeric: tabular-nums; }
.project-kpi-strip small { display: block; overflow: hidden; color: var(--text-muted); font-size: 11px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }

.project-health-band { display: grid; grid-template-columns: minmax(250px, .78fr) minmax(0, 2.22fr); overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; }
.project-health-summary { padding: 15px 17px; border-right: 1px solid #edf1ef; background: #f8fbfa; }
.project-health-summary span { display: block; color: #0f766e; font-size: 11px; font-weight: 800; letter-spacing: .04em; }
.project-health-summary strong { display: block; margin: 6px 0 5px; color: #173235; font-size: 17px; }
.project-health-summary p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.project-health-data { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; }
.project-health-data > div { min-width: 0; padding: 15px 17px; border-right: 1px solid #edf1ef; }
.project-health-data > div:last-child { border-right: 0; }
.project-health-data dt { overflow: hidden; color: var(--text-secondary); font-size: 11px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.project-health-data dd { margin: 7px 0 4px; color: #173235; font-size: 20px; font-weight: 830; font-variant-numeric: tabular-nums; }
.project-health-data dd.positive { color: #0f766e; }.project-health-data dd.negative { color: #c2410c; }
.project-health-data small { display: block; color: var(--text-muted); font-size: 11px; line-height: 1.45; }
.project-health-data .project-health-conclusion { overflow: hidden; min-height: 24px; margin-top: 5px; color: #0f4c49; font-size: 13px; line-height: 1.45; }

.project-status-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.project-status-tabs button { min-width: 0; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: #fff; color: var(--text-secondary); font: inherit; text-align: left; cursor: pointer; transition: border-color .16s ease, background .16s ease, color .16s ease, transform .16s ease; }
.project-status-tabs button:hover { border-color: rgba(15, 118, 110, .42); transform: translateY(-1px); }
.project-status-tabs button.active { border-color: #0f766e; background: #f0faf7; color: #0c615b; box-shadow: inset 0 0 0 1px rgba(15, 118, 110, .08); }
.project-status-tabs strong { display: block; overflow: hidden; font-size: 12px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.project-status-tabs span { display: block; overflow: hidden; margin-top: 3px; color: var(--text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }

.project-status-content { display: grid; grid-template-columns: minmax(0, 1.72fr) minmax(286px, .72fr); min-height: 0; gap: 12px; align-items: stretch; }
.project-status-main, .project-status-aside { min-width: 0; min-height: 0; }
.project-status-aside { display: grid; gap: 12px; }
.status-workspace, .status-side-panel { overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.status-workspace { min-height: 0; }
.status-workspace-head, .status-side-panel header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 15px 17px 13px; border-bottom: 1px solid #edf1ef; }
.status-workspace-head h2, .status-side-panel h2 { margin: 5px 0 3px; color: #173235; font-size: 16px; line-height: 1.25; }
.status-workspace-head p { max-width: 60ch; margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
.status-link-action, .status-side-panel header a, .status-side-panel header button, .status-row-action { flex: 0 0 auto; border: 1px solid rgba(15, 118, 110, .25); border-radius: 5px; padding: 6px 9px; background: #fff; color: #0e675f; font: inherit; font-size: 11px; font-weight: 780; line-height: 1.2; text-decoration: none; cursor: pointer; }
.status-link-action:hover, .status-side-panel header a:hover, .status-side-panel header button:hover, .status-row-action:hover { border-color: #0f766e; background: #f1faf8; }
.status-empty { display: grid; min-height: 290px; place-items: center; box-sizing: border-box; margin: 0; padding: 34px; color: var(--text-muted); font-size: 13px; line-height: 1.65; text-align: center; }

.status-execution-table, .process-supervision-table { overflow-x: auto; }
.status-execution-head, .status-execution-table article { display: grid; grid-template-columns: 82px minmax(180px, 1.45fr) minmax(150px, 1.05fr) 92px 96px 92px; min-width: 770px; align-items: center; gap: 13px; padding: 11px 17px; }
.status-execution-head { color: var(--text-muted); font-size: 11px; font-weight: 760; background: #f8faf9; border-bottom: 1px solid #edf1ef; }
.status-execution-table article { min-height: 59px; border-bottom: 1px solid #edf1ef; color: var(--text-secondary); font-size: 12px; }
.status-execution-table article:last-child { border-bottom: 0; }
.status-execution-table article > div { min-width: 0; }.status-execution-table article strong { display: block; overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-execution-table article small { display: block; margin-top: 3px; color: var(--text-muted); font-size: 10px; }
.execution-status { width: fit-content; border-radius: 999px; padding: 4px 7px; background: #f0f3f2; color: #536964; font-size: 10px; font-weight: 780; white-space: nowrap; }.execution-status.overdue { background: #fff0e7; color: #b84e18; }.execution-status.processing { background: #e8f6f2; color: #0f766e; }.execution-status.waiting_confirm { background: #eef5ff; color: #2563a8; }.execution-status.done { background: #edf7ef; color: #39834c; }.execution-status.need_more_info { background: #fff8df; color: #9a6700; }.status-execution-table .overdue { color: #bd4d17; font-weight: 750; }

.status-latest-list { padding: 3px 17px; }
.status-latest-list article { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto; align-items: center; gap: 10px; min-height: 61px; border-bottom: 1px solid #edf1ef; }
.status-latest-list article:last-of-type { border-bottom: 0; }.status-event-dot { width: 7px; height: 7px; border-radius: 50%; background: #0f766e; }.status-event-dot.orange { background: #d97706; }.status-event-dot.red { background: #c2410c; }.status-event-dot.blue { background: #2563eb; }
.status-latest-list article > div { min-width: 0; }.status-latest-list strong { display: block; overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-latest-list p { overflow: hidden; max-width: 56ch; margin: 3px 0 0; color: var(--text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.status-latest-list time { color: var(--text-muted); font-size: 11px; white-space: nowrap; }

.process-supervision-head, .process-supervision-table article { display: grid; grid-template-columns: minmax(185px, 1.18fr) 150px minmax(118px, .82fr) minmax(125px, .9fr) minmax(120px, .88fr) minmax(130px, 1fr); min-width: 920px; gap: 12px; align-items: center; padding: 11px 17px; }
.process-supervision-head { border-bottom: 1px solid #edf1ef; background: #f8faf9; color: var(--text-muted); font-size: 11px; font-weight: 760; }.process-supervision-table article { min-height: 60px; border-bottom: 1px solid #edf1ef; color: var(--text-secondary); font-size: 11px; }.process-supervision-table article:last-child { border-bottom: 0; }.process-supervision-table article > div { min-width: 0; }.process-supervision-table article strong { display: block; overflow: hidden; margin-top: 2px; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.process-supervision-table article > div:first-child small { color: var(--text-muted); font-family: var(--font-mono, monospace); font-size: 10px; }
.process-progress { display: grid; grid-template-columns: auto minmax(35px, 1fr); gap: 4px 7px; align-items: center; }.process-progress b { font-size: 12px; color: #173235; }.process-progress i { display: block; height: 5px; overflow: hidden; border-radius: 999px; background: #e6ece9; }.process-progress i em { display: block; height: 100%; border-radius: inherit; background: #0f766e; }.process-progress small { grid-column: 1 / -1; color: var(--text-muted); font-size: 10px; }.process-risk { color: #4e6964; }.process-risk.critical,.process-risk.high { color: #b94b18; font-weight: 760; }.process-risk.medium { color: #b77800; }

.status-change-list { padding: 2px 17px; }.status-change-list article { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 12px; min-height: 71px; border-bottom: 1px solid #edf1ef; }.status-change-list article:last-child { border-bottom: 0; }.status-change-list article > div { min-width: 0; }.status-change-list span { display: block; color: #0f766e; font-size: 10px; font-weight: 780; }.status-change-list strong { display: block; overflow: hidden; margin-top: 3px; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.status-change-list p { overflow: hidden; max-width: 58ch; margin: 3px 0 0; color: var(--text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.status-change-list time { color: var(--text-muted); font-size: 11px; white-space: nowrap; }.status-change-list em { border-radius: 999px; padding: 4px 7px; background: #f0f5f3; color: #41615b; font-size: 10px; font-style: normal; font-weight: 760; white-space: nowrap; }

.status-side-panel header { padding: 14px 15px 11px; }.status-side-panel h2 { font-size: 14px; }.status-side-panel header a, .status-side-panel header button { padding: 5px 7px; font-size: 10px; }.risk-window-list { padding: 0 15px 8px; }.risk-window-list article { padding: 12px 0; border-bottom: 1px solid #edf1ef; }.risk-window-list article:last-child { border-bottom: 0; }.risk-window-list article > div { display: flex; align-items: center; gap: 7px; }.risk-indicator { width: 7px; height: 7px; border-radius: 50%; background: #84958f; }.risk-indicator.critical { background: #bd4c1a; }.risk-indicator.high { background: #e08416; }.risk-indicator.medium { background: #d1a000; }.risk-window-list strong { overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.risk-window-list dl { display: grid; gap: 4px; margin: 8px 0; }.risk-window-list dl div { display: grid; grid-template-columns: 55px minmax(0, 1fr); gap: 7px; }.risk-window-list dt { color: var(--text-muted); font-size: 10px; }.risk-window-list dd { overflow: hidden; margin: 0; color: var(--text-secondary); font-size: 11px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }.risk-window-list .status-row-action { display: inline-block; padding: 4px 7px; font-size: 10px; }
.status-side-empty { margin: 0; padding: 24px 15px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }.change-preview-list { padding: 0 15px 8px; }.change-preview-list article { display: grid; gap: 3px; padding: 10px 0; border-bottom: 1px solid #edf1ef; }.change-preview-list article:last-child { border-bottom: 0; }.change-preview-list span { color: #0f766e; font-size: 10px; font-weight: 780; }.change-preview-list strong { overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.change-preview-list small { color: var(--text-muted); font-size: 10px; }

/* 原型项目状态的内容结构：摘要 + 四个完整业务视图 */
.project-summary-panel { padding: 14px 17px; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.project-summary-panel header { display: flex; align-items: center; gap: 9px; }.project-summary-panel header span { color: #0f766e; font-size: 11px; font-weight: 800; letter-spacing: .05em; }.project-summary-panel header strong { color: #173235; font-size: 13px; }.project-summary-panel p { margin: 8px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
.project-status-content { display: flex; min-height: 0; }.project-status-main { display: flex; width: 100%; min-height: 0; }.project-status-main > .status-workspace { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.status-latest-card-grid, .process-grid, .status-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px; padding: 14px 16px 16px; }
.status-info-card, .process-card, .task-execution-card { min-width: 0; padding: 13px; border: 1px solid #e4ece9; border-radius: 7px; background: #fbfcfb; }
.status-info-card { display: flex; flex-direction: column; align-items: flex-start; }.status-info-meta { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 8px; }.status-info-meta > span { overflow: hidden; color: #0f766e; font-size: 11px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }.status-info-meta em { flex: 0 0 auto; border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #127265; font-size: 10px; font-style: normal; font-weight: 780; }.status-info-meta em.orange { background: #fff5df; color: #a66a00; }.status-info-meta em.red { background: #fff0e9; color: #bf4a1b; }.status-info-meta em.blue { background: #edf5ff; color: #2563a8; }.status-info-meta em.pending { background: #f0f3f2; color: #536964; }.status-info-meta em.processing { background: #e8f6f2; color: #0f766e; }.status-info-meta em.overdue { background: #fff0e7; color: #b84e18; }.status-info-meta em.waiting_confirm { background: #eef5ff; color: #2563a8; }.status-info-meta em.done { background: #edf7ef; color: #39834c; }.status-info-card > small { display: block; margin-top: 8px; color: var(--text-muted); font-size: 10px; }.status-info-card > strong, .task-execution-card > strong { display: block; overflow: hidden; width: 100%; margin-top: 7px; color: #173235; font-size: 13px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.status-info-card > p, .task-execution-card > p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin: 6px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.55; -webkit-line-clamp: 2; }.status-info-card .status-row-action, .task-execution-card .status-row-action { margin-top: 11px; }
.process-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.process-card { border-left: 3px solid #b8d8d1; }.process-card.key-process { border-color: #d97706; background: #fffdf8; }.process-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; margin-bottom: 9px; }.process-card-head > div { min-width: 0; }.process-card-head small { display: block; color: var(--text-muted); font-size: 10px; font-family: var(--font-mono, monospace); }.process-card-head strong { display: block; overflow: hidden; margin-top: 2px; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.process-card-head > span { flex: 0 0 auto; border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #0f766e; font-size: 10px; font-weight: 780; }.process-card-head > span.high, .process-card-head > span.critical { background: #fff0e9; color: #b84e18; }.process-card-head > span.medium { background: #fff5df; color: #9a6700; }.process-card p { margin: 5px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.52; }.process-card p b { color: #45635d; font-weight: 780; }.process-card-note { display: block; margin-top: 9px; color: #0f766e; font-size: 10px; font-weight: 750; }
.task-execution-card { border-top: 3px solid #0f766e; }.task-execution-card > p b { color: #45635d; }.status-source-ref { color: #0f766e !important; font-weight: 700; }
.status-workspace > .status-latest-card-grid, .status-workspace > .process-grid, .status-workspace > .status-card-grid, .status-workspace > .status-empty { flex: 1; min-height: 0; overflow-y: auto; }

/* 项目状态沿用已确认的「指标—健康度—执行主表＋风险侧栏」信息架构 */
.project-status-view {
  height: calc(100dvh - var(--header-height, 56px) - 36px);
  min-height: 680px;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: 12px;
}
.project-kpi-strip { border-radius: 8px; box-shadow: 0 8px 24px rgba(24, 54, 51, .045); }
.project-kpi-strip article { display: flex; align-items: center; gap: 13px; padding: 15px 16px; }
.project-kpi-strip article::before { display: none; }
.project-kpi-icon { display: grid; flex: 0 0 46px; width: 46px; height: 46px; place-items: center; border-radius: 50%; background: #e8f7f4; color: #0f8c82; }
.project-kpi-strip article.orange .project-kpi-icon { background: #fff1e9; color: #ec6b21; }
.project-kpi-strip article.red .project-kpi-icon { background: #ffefef; color: #d83232; }
.project-kpi-strip article.blue .project-kpi-icon { background: #edf4ff; color: #3182ce; }
.project-kpi-strip article > div { min-width: 0; }
.project-kpi-strip span { font-size: 11px; font-weight: 720; }
.project-kpi-strip strong { margin: 4px 0 3px; font-size: 24px; letter-spacing: -.03em; }
.project-kpi-strip small { font-size: 10px; }

.project-health-band { grid-template-columns: minmax(320px, 1.1fr) minmax(0, 2.55fr); border-radius: 8px; box-shadow: 0 8px 24px rgba(24, 54, 51, .045); }
.project-health-summary { display: grid; grid-template-columns: 112px minmax(0, 1fr); align-items: center; gap: 15px; padding: 18px; background: #fff; }
.project-health-gauge { position: relative; display: grid; width: 104px; height: 104px; place-items: center; border-radius: 50%; background: conic-gradient(#0f9d92 var(--health-progress), #e5eeeb 0); }
.project-health-gauge::after { position: absolute; inset: 11px; border-radius: inherit; background: #fff; content: ''; }
.project-health-gauge > div { position: relative; z-index: 1; display: grid; gap: 3px; place-items: center; text-align: center; }
.project-health-gauge strong { margin: 0; color: #0b786f; font-size: 16px; line-height: 1.15; }
.project-health-gauge small { color: var(--text-muted); font-size: 10px; white-space: nowrap; }
.project-health-copy span { color: #193b39; font-size: 14px; font-weight: 800; }
.project-health-copy p { margin: 9px 0 6px; color: var(--text-secondary); font-size: 12px; line-height: 1.65; }
.project-health-copy small { display: block; color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.project-health-data > div { display: flex; min-height: 134px; flex-direction: column; justify-content: center; padding: 17px 20px; }
.project-health-data dt { font-size: 12px; }
.project-health-data dd { margin: 9px 0 5px; font-size: 25px; letter-spacing: -.035em; }
.project-health-data small { line-height: 1.6; }
.project-health-progress { display: grid; gap: 7px; }
.project-health-progress i { display: block; height: 7px; overflow: hidden; border-radius: 999px; background: #e8efed; }
.project-health-progress i em { display: block; height: 100%; border-radius: inherit; background: #0f9d92; }
.project-health-conclusion dd { margin: 8px 0 6px; color: #173235; font-size: 15px; line-height: 1.35; letter-spacing: 0; }
.project-health-conclusion small { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; max-width: 42ch; -webkit-line-clamp: 3; }

.project-status-tabs { gap: 0; overflow: hidden; border: 1px solid var(--border-default); border-radius: 8px; background: #fff; box-shadow: 0 7px 18px rgba(24, 54, 51, .03); }
.project-status-tabs button { position: relative; padding: 12px 16px; border: 0; border-right: 1px solid #edf1ef; border-radius: 0; background: transparent; text-align: left; }
.project-status-tabs button:last-child { border-right: 0; }
.project-status-tabs button::after { position: absolute; right: 16px; bottom: 0; left: 16px; height: 3px; border-radius: 999px 999px 0 0; background: transparent; content: ''; }
.project-status-tabs button:hover { border-color: #edf1ef; transform: none; background: #f8fbfa; }
.project-status-tabs button.active { border-color: #edf1ef; background: #fff; box-shadow: none; color: #0d766e; }
.project-status-tabs button.active::after { background: #0f9d92; }
.project-status-tabs strong { font-size: 13px; }.project-status-tabs span { margin-top: 2px; font-size: 10px; }

.project-status-content { display: grid; grid-template-columns: minmax(0, 1.82fr) minmax(300px, .78fr); min-height: 0; gap: 12px; }
.project-status-main { display: flex; width: auto; min-width: 0; min-height: 0; }
.project-status-main > .status-workspace { display: flex; flex: 1; min-height: 0; flex-direction: column; }
.project-status-aside { display: grid; grid-template-rows: minmax(0, 1fr) minmax(160px, .52fr); min-height: 0; gap: 12px; }
.status-workspace, .status-side-panel { border-radius: 8px; box-shadow: 0 8px 22px rgba(24, 54, 51, .04); }
.status-workspace-head, .status-side-panel header { align-items: center; padding: 15px 17px 13px; }
.status-workspace-head > div, .status-side-panel header > div { min-width: 0; }
.status-workspace-head h2, .status-side-panel h2 { margin: 3px 0 2px; font-size: 16px; }
.status-workspace-head p { max-width: 72ch; font-size: 11px; }
.status-workspace-head > small, .status-side-panel header > small { flex: 0 0 auto; color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.status-execution-table, .process-supervision-table, .status-latest-list, .status-change-list { flex: 1; min-height: 0; overflow: auto; }
.status-execution-head, .status-execution-table article { grid-template-columns: 76px minmax(195px, 1.46fr) minmax(155px, 1fr) 82px 118px 98px; min-width: 820px; padding: 11px 16px; }
.status-execution-table article { min-height: 66px; }
.status-execution-table article:hover, .process-supervision-table article:hover, .status-latest-list article:hover, .status-change-list article:hover { background: #fbfdfc; }
.status-execution-table article > div { overflow: hidden; }
.status-execution-table article > div:not(:nth-child(2)):not(:nth-child(5)) { display: -webkit-box; -webkit-box-orient: vertical; color: #5b706b; font-size: 11px; line-height: 1.5; -webkit-line-clamp: 2; }
.status-execution-table article > div:nth-child(4) { color: #173235; font-weight: 700; }
.status-execution-table article > div:last-child { color: #46645e; }
.status-execution-table article small { line-height: 1.4; }
.execution-status { padding: 4px 8px; }
.status-latest-list { padding: 2px 17px; }
.status-latest-list article { grid-template-columns: 10px minmax(0, 1fr) auto auto 42px; gap: 10px; min-height: 64px; }
.status-latest-list p { max-width: 54ch; }
.status-latest-list em { border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #127265; font-size: 10px; font-style: normal; font-weight: 780; white-space: nowrap; }
.status-latest-list em.orange { background: #fff5df; color: #a66a00; }.status-latest-list em.red { background: #fff0e9; color: #bf4a1b; }.status-latest-list em.blue { background: #edf5ff; color: #2563a8; }
.status-row-placeholder { width: 42px; }
.status-row-action { padding: 5px 7px; font-size: 10px; }
.process-supervision-head, .process-supervision-table article { grid-template-columns: minmax(175px, 1.12fr) minmax(165px, 1.06fr) minmax(145px, 1fr) minmax(150px, 1fr) minmax(135px, .92fr) minmax(145px, 1fr); min-width: 1000px; padding: 11px 16px; }
.process-supervision-table article > div:not(:first-child) { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; line-height: 1.5; -webkit-line-clamp: 3; }
.process-progress { display: grid !important; -webkit-line-clamp: unset !important; }
.process-progress small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-change-list { padding: 2px 17px; }
.status-change-list article { min-height: 73px; }
.status-side-panel { display: flex; min-height: 0; flex-direction: column; }
.status-side-panel header { flex: 0 0 auto; }.risk-window-list, .change-preview-list { flex: 1; min-height: 0; overflow-y: auto; }
.risk-window-list article { padding: 12px 0; }.risk-window-list p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin: 0; color: #5c726d; font-size: 10px; line-height: 1.5; -webkit-line-clamp: 2; }
.risk-window-list dl { margin: 7px 0; }.risk-window-list dl div { grid-template-columns: 54px minmax(0, 1fr); }.risk-window-list dd { white-space: normal; }
.change-preview-list article { padding: 11px 0; }

/* 可读性优先：页面允许纵向展开，业务表格保持正常字号与行高。 */
.project-status-view {
  height: auto;
  min-height: 920px;
  grid-template-rows: auto auto auto minmax(600px, 1fr);
  gap: 16px;
}

.project-kpi-strip article { gap: 14px; min-height: 88px; padding: 17px 18px; }
.project-kpi-icon { flex-basis: 50px; width: 50px; height: 50px; }
.project-kpi-strip span { font-size: 13px; }
.project-kpi-strip strong { margin: 5px 0 4px; font-size: 27px; }
.project-kpi-strip small { font-size: 12px; }

.project-health-summary { grid-template-columns: 122px minmax(0, 1fr); gap: 18px; min-height: 158px; padding: 20px; }
.project-health-gauge { width: 114px; height: 114px; }
.project-health-gauge strong { font-size: 18px; }
.project-health-gauge small { font-size: 12px; }
.project-health-copy span { font-size: 16px; }
.project-health-copy p { margin: 10px 0 7px; font-size: 14px; }
.project-health-copy small { font-size: 12px; }
.project-health-data { grid-template-columns: 206px 206px minmax(0, 1fr); }
.project-health-data > div { min-height: 158px; padding: 20px 22px; }
.project-health-data > div:nth-child(-n + 2) { padding-right: 20px; padding-left: 20px; }
.project-health-data dt { overflow: visible; font-size: 13px; line-height: 1.35; text-overflow: clip; white-space: normal; }
.project-progress-compare { display: grid !important; width: 100%; grid-template-rows: auto auto auto; align-content: center; justify-items: stretch; padding-top: 18px !important; padding-bottom: 16px !important; }
.project-progress-compare dt { width: 100%; color: #496761; font-weight: 800; letter-spacing: .01em; text-align: left; }
.progress-compare-values { position: relative; display: grid; width: 100%; box-sizing: border-box; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 28px; margin-top: 13px; padding: 0 2px 13px; border-bottom: 1px solid #bcd1ca; }
.progress-compare-values span { display: grid; min-width: 0; gap: 4px; justify-items: center; text-align: center; }
.progress-compare-values small { color: #78908a; font-size: 12px; font-weight: 720; line-height: 1.25; }
.progress-compare-values b { color: #27433f; font-size: 24px; font-variant-numeric: tabular-nums; line-height: 1.1; letter-spacing: -.035em; }
.progress-compare-values span:last-child b { color: #0d8278; }
.project-progress-compare dd { position: relative; display: grid; gap: 2px; justify-self: center; justify-items: center; margin: 12px 0 0; padding: 0; line-height: 1; }
.project-progress-compare dd::before { position: absolute; top: -13px; left: 50%; width: 1px; height: 10px; background: #83aaa0; content: ''; }
.project-progress-compare dd small { color: #78908a; font-size: 10px; font-weight: 740; line-height: 1; }
.project-progress-compare dd strong { color: currentColor; font-size: 22px; font-variant-numeric: tabular-nums; line-height: 1; letter-spacing: -.03em; }
.project-health-data dd { margin: 10px 0 6px; font-size: 28px; }
.project-progress-compare dd { margin: 12px 0 0; font-size: inherit; }
.project-health-data small { font-size: 12px; }
.project-health-conclusion dd { font-size: 17px; }

.project-status-tabs button { min-height: 70px; padding: 14px 18px; }
.project-status-tabs strong { font-size: 14px; }
.project-status-tabs span { margin-top: 3px; font-size: 12px; }

.project-status-content { grid-template-columns: minmax(0, 1fr); min-height: 600px; gap: 16px; }
.project-status-aside { grid-template-rows: minmax(360px, 1fr) minmax(220px, .58fr); min-height: 600px; gap: 16px; }
.status-workspace-head, .status-side-panel header { padding: 18px 20px 16px; }
.status-workspace-head h2, .status-side-panel h2 { margin: 4px 0 3px; font-size: 18px; }
.status-workspace-head p { font-size: 13px; }
.status-workspace-head > small, .status-side-panel header > small { font-size: 12px; }

.status-execution-head, .status-execution-table article {
  grid-template-columns: 82px minmax(205px, 1.46fr) minmax(170px, 1fr) 90px 128px 106px;
  min-width: 885px;
  padding: 14px 18px;
}
.status-execution-head { font-size: 12px; }
.status-execution-table article { min-height: 78px; font-size: 13px; }
.status-execution-table article strong { font-size: 14px; }
.status-execution-table article small { font-size: 12px; }
.status-execution-table article > div:not(:nth-child(2)):not(:nth-child(5)) { font-size: 12px; }
.execution-status { padding: 5px 9px; font-size: 11px; }
.closure-status { display: inline-flex; align-items: center; width: fit-content; border: 1px solid transparent; border-radius: 5px; padding: 5px 9px; background: #f2f5f4; color: #557069; font-size: 11px; font-weight: 780; line-height: 1.2; white-space: nowrap; }
.closure-status.open { border-color: #dce5e2; background: #f3f6f5; color: #62746f; }
.closure-status.review { border-color: #f1d6ad; background: #fff7e8; color: #a46600; }
.closure-status.supplement { border-color: #e7d7a6; background: #fff9e8; color: #927100; }
.closure-status.closed { border-color: #b9e2cd; background: #ecf8f0; color: #247449; }
.closure-status.cancelled { border-color: #e0e3e2; background: #f4f5f5; color: #78837f; }

.status-latest-list article { grid-template-columns: 10px minmax(0, 1fr) auto auto 48px; gap: 12px; min-height: 74px; }
.status-latest-list strong { font-size: 14px; }
.status-latest-list p, .status-latest-list time { font-size: 12px; }
.status-latest-list em { padding: 4px 8px; font-size: 11px; }
.status-row-placeholder { width: 48px; }
.status-row-action { padding: 6px 9px; font-size: 11px; }

.process-supervision-head, .process-supervision-table article {
  grid-template-columns: minmax(195px, 1.12fr) minmax(180px, 1.06fr) minmax(155px, 1fr) minmax(165px, 1fr) minmax(150px, .92fr) minmax(160px, 1fr);
  min-width: 1100px;
  padding: 14px 18px;
}
.process-supervision-head { font-size: 12px; }
.process-supervision-table article { min-height: 76px; font-size: 13px; }
.process-supervision-table article strong, .process-progress b { font-size: 14px; }
.process-supervision-table article > div:first-child small { color: #5f7771; font-size: 13px; font-weight: 720; line-height: 1.4; letter-spacing: .01em; }
.process-progress small { font-size: 11px; }

.status-change-list article { min-height: 82px; }
.status-change-list span { font-size: 11px; }
.status-change-list strong { font-size: 14px; }
.status-change-list p, .status-change-list time, .status-change-list em { font-size: 12px; }

.risk-window-list article { padding: 15px 0; }
.risk-window-list p { font-size: 12px; line-height: 1.55; }
.risk-window-list strong { font-size: 14px; }
.risk-window-list dl { margin: 8px 0; }
.risk-window-list dl div { grid-template-columns: 60px minmax(0, 1fr); }
.risk-window-list dt { font-size: 11px; }
.risk-window-list dd { font-size: 12px; white-space: normal; }
.change-preview-list article { padding: 13px 0; }
.change-preview-list strong { font-size: 13px; }
.change-preview-list span, .change-preview-list small { font-size: 11px; }

/* 信息类页签沿用原型的固定宽度卡片栅格，空间不足时自动换行。 */
.status-latest-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  grid-auto-rows: minmax(176px, auto);
  align-content: start;
  gap: 14px;
  padding: 16px 18px 20px;
}
.status-latest-list article {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  grid-template-rows: auto 1fr auto;
  align-items: start;
  min-height: 0;
  padding: 16px;
  border: 1px solid #e0eae6;
  border-radius: 8px;
  background: #fbfdfc;
  gap: 0 10px;
}
.status-latest-list article:hover { border-color: rgba(15, 118, 110, .32); background: #f7fbf9; }
.status-latest-list .status-event-dot { grid-column: 1; grid-row: 1; margin-top: 6px; }
.status-latest-list article > div { grid-column: 2; grid-row: 1 / span 2; }
.status-latest-list strong { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; font-size: 14px; line-height: 1.45; text-overflow: clip; white-space: normal; -webkit-line-clamp: 2; }
.status-latest-list p { display: -webkit-box; overflow: hidden; max-width: none; -webkit-box-orient: vertical; margin-top: 8px; font-size: 12px; line-height: 1.65; text-overflow: clip; white-space: normal; -webkit-line-clamp: 4; }
.status-latest-list em { grid-column: 3; grid-row: 1; margin-left: 4px; }
.status-latest-list time { grid-column: 2; grid-row: 3; align-self: end; margin-top: 12px; }
.status-latest-list .status-row-action, .status-latest-list .status-row-placeholder { grid-column: 3; grid-row: 3; align-self: end; }

.status-change-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  grid-auto-rows: minmax(168px, auto);
  align-content: start;
  gap: 14px;
  padding: 16px 18px 20px;
}
.status-change-list article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  padding: 17px;
  border: 1px solid #e0eae6;
  border-radius: 8px;
  background: #fbfdfc;
}
.status-change-list article:hover { border-color: rgba(15, 118, 110, .32); background: #f7fbf9; }
.status-change-list article > div { grid-column: 1 / -1; grid-row: 1; }
.status-change-list strong { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin-top: 7px; font-size: 15px; line-height: 1.4; text-overflow: clip; white-space: normal; -webkit-line-clamp: 2; }
.status-change-list p { display: -webkit-box; overflow: hidden; max-width: 60ch; -webkit-box-orient: vertical; margin-top: 8px; font-size: 13px; line-height: 1.7; text-overflow: clip; white-space: normal; -webkit-line-clamp: 4; }
.status-change-list em { grid-column: 1; grid-row: 2; align-self: end; margin-top: 14px; }
.status-change-list time { grid-column: 2; grid-row: 2; align-self: end; margin-left: 12px; }

@media (max-width: 1180px) {
  .workspace-grid,
  .chat-layout,
  .status-grid {
    grid-template-columns: 1fr;
  }
  .task-hero {
    grid-template-columns: 1fr;
  }
  .project-focus-strip,
  .docs-work-grid {
    grid-template-columns: 1fr;
  }
  .project-kpi-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .project-kpi-strip article:nth-child(3n) { border-right: 0; }
  .project-kpi-strip article:nth-child(-n + 3) { border-bottom: 1px solid #edf1ef; }
  .project-health-band { grid-template-columns: 1fr; }
  .project-health-summary { border-right: 0; border-bottom: 1px solid #edf1ef; }
  .project-status-content { grid-template-columns: 1fr; }
  .project-status-aside { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .status-latest-card-grid, .process-grid, .status-card-grid { grid-template-columns: 1fr; }
  .task-create-form { grid-template-columns: 1fr 1fr; }
  .task-flow-trigger-grid { flex-wrap:wrap; }
  .task-flow-trigger-preview { min-width:280px; }
  .task-flow-body { grid-template-columns: minmax(300px, 34%) minmax(0, 1fr); }
  .chat-layout { height: auto; }
  .conversation-list,
  .realtime-panel { max-height: none; }
  .doc-grid,
  .metric-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .ai-platform { padding: 12px; }
  .work-hero,
  .chat-head,
  .chat-composer {
    display: grid;
  }
  .metric-row,
  .doc-grid,
  .task-board { grid-template-columns: 1fr; }
  .task-summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .project-status-heading { align-items: flex-start; flex-direction: column; gap: 5px; }
  .project-status-heading > small { margin: 0; }
  .project-kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .project-kpi-strip article { border-bottom: 1px solid #edf1ef; }
  .project-kpi-strip article:nth-child(2n) { border-right: 0; }
  .project-kpi-strip article:nth-last-child(-n + 2) { border-bottom: 0; }
  .project-health-data { grid-template-columns: 1fr; }
  .project-health-data > div { border-right: 0; border-bottom: 1px solid #edf1ef; }
  .project-health-data > div:last-child { border-bottom: 0; }
  .project-status-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .project-status-aside { grid-template-columns: 1fr; }
  .status-latest-card-grid, .process-grid, .status-card-grid { padding: 12px; }
  .status-workspace-head { align-items: flex-start; }
  .status-latest-list { grid-template-columns: 1fr; grid-auto-rows: minmax(165px, auto); padding: 12px; }
  .status-latest-list article { grid-template-columns: 8px minmax(0, 1fr) auto; gap: 0 8px; padding: 14px; }
  .status-latest-list article .status-row-action { grid-column: 3; width: fit-content; }
  .status-latest-list p { max-width: none; }
  .status-change-list { grid-template-columns: 1fr; grid-template-rows: none; padding: 12px; }
  .status-change-list article, .status-change-list article:first-child { grid-row: auto; padding: 16px; }
  .status-change-list em { grid-column: 1; grid-row: 2; }
  .task-filterbar {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 10px;
  }
  .task-filterbar > span { flex-basis: 100%; }
  .task-create-button { margin-left: 0; }
  .task-filterbar .filter-tabs { order: 3; flex: 1 1 100%; margin-left: 0; }
  .workflow-modal-backdrop { padding: 12px; }
  .workflow-modal { max-height: calc(100dvh - 24px); padding: 16px; border-radius: 10px; }
  .task-flow-modal { width: calc(100vw - 24px); height: calc(100dvh - 24px); max-height: calc(100dvh - 24px); padding: 0; }
  .task-flow-modal > .workflow-modal-head { margin: 0; padding: 10px 14px; }
  .task-flow-modal > .workflow-modal-head span,.task-flow-modal > .workflow-modal-head p { display:none; }
  .task-flow-form { overflow-y:auto; }
  .task-flow-global-head { align-items:flex-start; flex-direction:column; gap:4px; }
  .task-flow-global-copy { width:100%; align-items:flex-start; flex-direction:column; gap:4px; }
  .task-flow-global-copy p { white-space:normal; }
  .task-flow-trigger-preview { width:100%; min-width:0; box-sizing:border-box; }
  .task-flow-trigger-grid { display:grid; grid-template-columns:1fr; }
  .task-flow-trigger-grid>.form-field,.task-flow-trigger-grid>.form-field:nth-child(2),.task-flow-trigger-grid>.task-flow-cc-field,.task-flow-interval-field { width:100%; min-width:0; }
  .task-flow-body { display: block; overflow-y: auto; }
  .task-flow-brief { overflow: visible; border-right: 0; border-bottom: 1px solid #e1e9e7; }
  .task-flow-canvas { min-height: 720px; overflow: visible; }
  .task-flow-canvas-body { grid-template-columns:1fr; }
  .task-flow-preview-panel { padding:14px 0 0; border-top:1px solid #e1e9e7; border-left:0; }
  .task-flow-strip { max-height:none; overflow:visible; }
  .task-flow-node-grid { overflow: visible; }
  .task-flow-footer { padding: 10px 14px; }
  .task-flow-footer > p { display: none; }
  .workflow-modal-head { gap:12px; margin-bottom:10px; }
  .workflow-modal-head span,.workflow-modal-head p { display:none; }
  .workflow-modal-head h2 { font-size: 17px; }
  .workflow-modal-actions { justify-content: stretch; }
  .workflow-modal-actions button { flex: 1 1 auto; }
  .task-history-summary { grid-template-columns:1fr; }
  .task-history-body { max-height:50dvh; }
  .task-history-timeline header { align-items:flex-start; flex-direction:column; gap:4px; }
  .work-hero { min-height: 260px; align-items: end; }
  .wbs-row,
  .document-list article {
    grid-template-columns: 1fr;
  }
  .task-create-form,.change-create-form,.draft-create-form { grid-template-columns: 1fr; }
  .task-form-title,.task-form-workflow,.change-form-content,.draft-form-content { grid-column: auto; }
  .message-row { max-width: 100%; }
}
</style>
