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
                <div v-if="message.role === 'assistant'" class="message-role">工程智管家</div>
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
            <button title="邀请参与人">
              <n-icon :size="18"><UserPlus /></n-icon>
            </button>
            <button title="更多">
              <n-icon :size="18"><Dots /></n-icon>
            </button>
          </div>
        </div>

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
                <span>工程智管家</span>
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
      <div class="task-hero">
        <div class="task-summary-strip">
          <article>
            <span>逾期</span>
            <strong>{{ store.overdueTasks.length }}</strong>
          </article>
          <article>
            <span>待处理</span>
            <strong>{{ store.pendingTasks.length }}</strong>
          </article>
          <article>
            <span>处理中</span>
            <strong>{{ store.processingTasks.length }}</strong>
          </article>
          <article>
            <span>待确认</span>
            <strong>{{ store.waitingConfirmTasks.length }}</strong>
          </article>
        </div>
      </div>
      <div class="task-filterbar">
        <span>当前显示 {{ filteredTasks.length }} / {{ store.tasks.length }} 条</span>
        <button class="task-create-button" @click="taskCreateOpen = !taskCreateOpen">{{ taskCreateOpen ? '收起新建任务' : '新建任务' }}</button>
        <div class="filter-tabs">
          <button v-for="tab in taskTabs" :key="tab.key" :class="{ active: taskFilter === tab.key }" @click="taskFilter = tab.key">
            {{ tab.label }}
          </button>
        </div>
      </div>
      <form v-if="taskCreateOpen" class="task-create-form" @submit.prevent="createManualTask">
        <input v-model.trim="taskCreateForm.title" required placeholder="任务名称，例如：基坑开挖条件核查">
        <select v-model="taskCreateForm.task_type"><option value="risk_alert">风险预警</option><option value="material_missing">资料缺项</option><option value="daily_confirm">日报确认</option><option value="draft_review">草稿审核</option><option value="fill_platform">平台填报</option></select>
        <select v-model="taskCreateForm.assignee_user_id"><option value="">选择负责人</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }}</option></select>
        <select v-model="taskCreateForm.risk_source_id"><option value="">关联风险源（可选）</option><option v-for="risk in store.riskSources" :key="risk.id" :value="risk.id">{{ risk.name }}</option></select>
        <input v-model="taskCreateForm.due_at" type="date" aria-label="截止日期">
        <button type="submit">创建并分派</button>
      </form>
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
          <div class="task-actions">
            <router-link to="/ai">协同处理</router-link>
            <button @click="store.updateTaskStatus(task.id, 'processing')">开始处理</button>
            <button @click="store.updateTaskStatus(task.id, 'waiting_confirm')">提交确认</button>
            <button class="done" @click="store.updateTaskStatus(task.id, 'done')">完成</button>
          </div>
        </article>
      </div>
    </section>

    <section v-else-if="section === 'project'" class="page-stack project-page">
      <div class="project-focus-strip">
        <article class="focus-card focus-card-main">
          <span>当前施工重点</span>
          <strong>{{ activeWbs?.name ?? '暂无进行中工序' }}</strong>
          <p>{{ activeWbs ? `负责人：${store.getMemberName(activeWbs.responsibleId)} · 计划 ${activeWbs.planStart} 至 ${activeWbs.planEnd}` : '当前项目没有进行中的 WBS 工序。' }}</p>
          <div class="progress-track compact"><span :style="{ width: `${activeWbs?.progress ?? 0}%` }"></span></div>
        </article>
        <article class="focus-card">
          <span>风险关注</span>
          <strong>{{ criticalRisks.length }} 个重大风险</strong>
          <p>{{ criticalRisks[0]?.name ?? '当前无重大风险源。' }}</p>
        </article>
        <article class="focus-card">
          <span>需协调事项</span>
          <strong>{{ focusTasks.length }} 件待处理</strong>
          <p>{{ focusTasks[0]?.title ?? '暂无待处理任务。' }}</p>
        </article>
      </div>
      <div class="status-grid">
        <section class="panel span-2">
          <div class="panel-head">
            <div>
              <h2>WBS 进度</h2>
              <p>工序、责任人和完成率</p>
            </div>
          </div>
          <div class="wbs-table">
            <div v-for="item in store.wbsItems" :key="item.id" class="wbs-row">
              <span class="wbs-code">{{ item.code }}</span>
              <strong>{{ item.name }}</strong>
              <span>{{ store.getMemberName(item.responsibleId) }}</span>
              <div class="mini-track"><i :style="{ width: `${item.progress}%` }"></i></div>
              <b>{{ item.progress }}%</b>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>风险热区</h2>
              <p>当前项目风险源</p>
            </div>
          </div>
          <div class="risk-list">
            <article v-for="risk in store.riskSources.slice(0, 5)" :key="risk.id">
              <span :class="['risk-indicator', risk.level]"></span>
              <div>
                <strong>{{ risk.name }}</strong>
                <p>{{ risk.type }} · {{ store.getMemberName(risk.responsibleId) }}</p>
              </div>
            </article>
          </div>
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
          <button type="button" class="document-action confirm" @click="draftCreateOpen = !draftCreateOpen">{{ draftCreateOpen ? '收起草稿' : '新建草稿' }}</button>
        </div>
        <form v-if="draftCreateOpen" class="draft-create-form" @submit.prevent="createRiskDraft">
          <select v-model="draftCreateForm.risk_source_id" required><option value="">关联风险源</option><option v-for="risk in store.riskSources" :key="risk.id" :value="risk.id">{{ risk.name }}</option></select>
          <input v-model.trim="draftCreateForm.title" required placeholder="草稿标题">
          <textarea v-model.trim="draftCreateForm.content" required placeholder="填写风险说明、处置建议和资料依据"></textarea>
          <button type="submit" class="document-action confirm">保存草稿</button>
        </form>
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
import { NIcon } from 'naive-ui'
import {
  AdjustmentsHorizontal, At, CalendarEvent, ChartBar, ChevronDown, ChevronLeft, ChevronRight,
  Dots, FileText, Folder, ListCheck, Notes, Paperclip, Pin, Plus, Refresh, Robot,
  Search, Send, Settings, Table, User, UserPlus,
} from '@vicons/tabler'
import { useAppStore } from '@/stores/app'
import type { DraftStatus, FillStatus, Member, RiskLevel, Task, TaskStatus } from '@/types'

type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  generatedTaskIds?: string[]
}

type ChatSuggestion = {
  label: string
  desc: string
  prompt: string
}

const route = useRoute()
const store = useAppStore()

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
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateHomePageSize)
})
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

const sessions = ref([
  {
    id: 's1',
    title: '今日项目跟进：风险、资料与填报闭环',
    desc: '深基坑风险、日报解析、资料缺口',
    time: '2026-06-10 09:42:18',
    participantIds: ['m1', 'm2', 'm3'],
    taskIds: ['t2', 't4', 't6', 't3'],
  },
  {
    id: 's2',
    title: '深基坑风险上报草稿审核',
    desc: '草稿材料、缺项附件、确认人',
    time: '2026-06-09 18:12:43',
    participantIds: ['m1', 'm2', 'm3'],
    taskIds: ['t4', 't2'],
  },
  {
    id: 's3',
    title: '施工日报解析与 WBS 进度复核',
    desc: '日报内容匹配 WBS，提取风险材料',
    time: '2026-06-09 08:16:05',
    participantIds: ['m1', 'm3'],
    taskIds: ['t3'],
  },
])
const activeSessionId = ref('s1')
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
const sessionMessages = ref<Record<string, ChatMessage[]>>({
  s1: [
    { id: 'm1', role: 'assistant', content: '我已读取当前项目、WBS、风险源、日报和待办任务。今天建议先处理地面沉降监测报告缺项，再审核深基坑风险草稿。' },
    { id: 'm2', role: 'user', content: '把今天需要我参与的事项排个优先级。' },
    {
      id: 'm3',
      role: 'assistant',
      content: '已按截止时间、风险等级和资料阻塞关系拆成下面 4 项工作。每项工作会继续跟踪责任人、截止时间和处理状态。',
      generatedTaskIds: ['t2', 't4', 't3', 't6'],
    },
  ],
  s2: [
    { id: 'm4', role: 'assistant', content: '深基坑风险草稿已生成，但还有材料缺项会影响确认。建议先锁定缺项附件，再提交审核。' },
    { id: 'm5', role: 'user', content: '把草稿审核和缺项补充拆成可以跟踪的工作。' },
    {
      id: 'm6',
      role: 'assistant',
      content: '已生成 2 项工作：王芳负责草稿审核，李明补齐地表沉降监测报告。完成后再进入填报包生成。',
      generatedTaskIds: ['t4', 't2'],
    },
  ],
  s3: [
    { id: 'm7', role: 'assistant', content: '已从 2026-06-09 施工日报中识别到基坑开挖进度、监测数据和风险材料引用。' },
    { id: 'm8', role: 'user', content: '生成一项日报复核任务，确认后同步 WBS 进度。' },
    {
      id: 'm9',
      role: 'assistant',
      content: '已生成日报解析确认任务。王芳确认后，系统会把基坑开挖进度和风险材料引用同步到项目状态与资料流。',
      generatedTaskIds: ['t3'],
    },
  ],
})
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

watch(activeSessionId, () => {
  chatSuggestionsOpen.value = false
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

function sendPrompt() {
  const content = prompt.value.trim()
  if (!content) return
  const messages = sessionMessages.value[activeSessionId.value] ?? []
  const isFirstUserMessage = !messages.some(message => message.role === 'user')
  const generatedTaskIds = generatedTaskIdsFromPrompt(content)
  messages.push({ id: `u${Date.now()}`, role: 'user', content })
  messages.push({
    id: `a${Date.now() + 1}`,
    role: 'assistant',
    content: generatedTaskIds.length
      ? `已按当前项目的任务、风险和资料状态生成可跟踪工作。右侧会同步更新责任人、截止时间和处理状态。`
      : `已收到。我会按 ${currentProject.value?.name ?? '当前项目'} 的任务、风险和资料状态继续处理。`,
    generatedTaskIds: generatedTaskIds.length ? generatedTaskIds : undefined,
  })
  sessionMessages.value[activeSessionId.value] = messages
  const targetSession = sessions.value.find(session => session.id === activeSessionId.value)
  if (targetSession) {
    if (isFirstUserMessage || targetSession.title === '新的工程协同') targetSession.title = sessionTitleFromFirstMessage(content)
    targetSession.desc = content.slice(0, 22)
    targetSession.time = nowStr()
    if (generatedTaskIds.length) {
      const generatedTasks = generatedTaskIds
        .map(id => store.tasks.find(task => task.id === id))
        .filter((task): task is Task => Boolean(task))
      targetSession.taskIds = Array.from(new Set([...targetSession.taskIds, ...generatedTaskIds]))
      targetSession.participantIds = Array.from(new Set([
        ...targetSession.participantIds,
        ...generatedTasks.flatMap(task => [task.responsibleId, task.confirmatorId]),
      ]))
    }
  }
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

function startNewSession() {
  const id = `s${Date.now()}`
  sessions.value.unshift({
    id,
    title: '新的工程协同',
    desc: '新会话',
    time: nowStr(),
    participantIds: ['m1'],
    taskIds: [],
  })
  sessionMessages.value[id] = []
  activeSessionId.value = id
}

const taskFilter = ref<'all' | TaskStatus>('all')
const taskCreateOpen = ref(false)
const taskCreateForm = ref<{ title: string; task_type: Task['type']; assignee_user_id: string; risk_source_id: string; due_at: string }>({ title: '', task_type: 'risk_alert', assignee_user_id: '', risk_source_id: '', due_at: '' })
const taskTabs: Array<{ key: 'all' | TaskStatus, label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'overdue', label: '逾期' },
  { key: 'pending', label: '待处理' },
  { key: 'processing', label: '处理中' },
  { key: 'waiting_confirm', label: '待确认' },
  { key: 'done', label: '已完成' },
]
const filteredTasks = computed(() => taskFilter.value === 'all' ? store.tasks : store.tasks.filter(task => task.status === taskFilter.value))

async function createManualTask() {
  if (!taskCreateForm.value.title) return
  await store.createTask({ ...taskCreateForm.value, trigger_reason: '由项目成员在任务中心创建' })
  taskCreateForm.value = { title: '', task_type: 'risk_alert', assignee_user_id: '', risk_source_id: '', due_at: '' }
  taskCreateOpen.value = false
}

const documentCards = computed(() => [
  { title: '日报解析', desc: '施工内容、风险和进度记录', count: store.dailyReports.length, icon: FileText },
  { title: '风险草稿', desc: '待审核的风险上报内容', count: store.riskDrafts.length, icon: Notes },
  { title: '填报包', desc: '字段与附件映射到平台', count: store.fillPackages.length, icon: Table },
  { title: '目录监控', desc: store.dirConfig.enabled ? '文件目录监听中' : '目录监听未启用', count: `${store.dirConfig.scanInterval}m`, icon: Folder },
])
const documentUploading = ref(false)
const draftCreateOpen = ref(false)
const draftCreateForm = ref({ risk_source_id: '', title: '', content: '' })
async function uploadDocument(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  documentUploading.value = true
  try { await store.uploadAttachment(file) } finally { documentUploading.value = false; input.value = '' }
}
async function createRiskDraft() {
  if (!draftCreateForm.value.risk_source_id || !draftCreateForm.value.title || !draftCreateForm.value.content) return
  await store.createRiskDraft(draftCreateForm.value)
  draftCreateForm.value = { risk_source_id: '', title: '', content: '' }
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

function taskTypeLabel(type: Task['type']) {
  return ({
    risk_alert: '风险预警',
    material_missing: '资料缺项',
    daily_confirm: '日报确认',
    draft_review: '草稿审核',
    fill_platform: '平台填报',
  } as Record<Task['type'], string>)[type]
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, .86);
  border: 1px solid rgba(42, 52, 62, 0.09);
}

.task-filterbar > span {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 760;
}
.task-create-button {
  margin-left: auto;
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
.task-create-form {
  display: grid;
  grid-template-columns: 1.5fr .9fr 1fr 1.2fr .9fr auto;
  gap: 8px;
  padding: 12px;
  margin: -2px 0 14px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: #fff;
}
.task-create-form input, .task-create-form select {
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--border-emphasis);
  border-radius: 5px;
  font: inherit;
  font-size: 12px;
  background: #fff;
}
.task-create-form button { border: 0; border-radius: 5px; padding: 7px 11px; color: #fff; background: var(--color-primary); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }

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
.document-storage-panel, .document-review-panel { margin-top: 18px; }.empty-document-note { padding: 14px 0; color: var(--text-muted); font-size: 13px; }
.draft-create-form { display: grid; grid-template-columns: minmax(160px, .7fr) minmax(180px, 1fr) minmax(240px, 1.7fr) auto; gap: 9px; margin: 12px 0; }
.draft-create-form input, .draft-create-form select, .draft-create-form textarea { min-width: 0; padding: 8px 9px; border: 1px solid var(--border-color); border-radius: 5px; background: #fff; color: var(--text-main); font: inherit; font-size: 12px; }
.draft-create-form textarea { min-height: 36px; resize: vertical; }

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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.task-card { padding: 16px; }
.task-top,
.task-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.task-card h2 { margin: 12px 0 6px; font-size: 17px; }
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
.task-actions { margin-top: 14px; }
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
  .chat-layout { height: auto; }
  .conversation-list,
  .realtime-panel { max-height: none; }
  .doc-grid,
  .metric-row,
  .task-board { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
  .task-filterbar {
    display: grid;
  }
  .work-hero { min-height: 260px; align-items: end; }
  .wbs-row,
  .document-list article {
    grid-template-columns: 1fr;
  }
  .message-row { max-width: 100%; }
}
</style>
