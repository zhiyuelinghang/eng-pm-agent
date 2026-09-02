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
        </div>

        <div v-if="homeMode === 'work'" class="home-workbench">
          <aside class="home-queue-pane" aria-label="Dobby 推送的待处理工作">
            <div class="home-controlbar">
              <div class="home-status-tabs" role="tablist" aria-label="工作处理状态">
                <button
                  v-for="tab in homeStatusTabs"
                  :key="tab.key"
                  type="button"
                  role="tab"
                  :aria-selected="homeStatus === tab.key"
                  :class="{ active: homeStatus === tab.key }"
                  @click="homeStatus = tab.key"
                >
                  {{ tab.label }}
                  <span>{{ tab.count }}</span>
                </button>
              </div>
            </div>

            <div class="home-queue-list" role="listbox" :aria-label="`${homeStatusTabs.find(tab => tab.key === homeStatus)?.label || '任务'}列表`">
              <button
                v-for="(item, index) in pagedHomeWorkItems"
                :key="item.id"
                type="button"
                :class="['home-queue-card', { active: selectedHomeWorkItemId === item.id }]"
                :aria-selected="selectedHomeWorkItemId === item.id"
                role="option"
                @click="selectedHomeWorkItemId = item.id"
              >
                <span class="home-rank" :class="item.tone">{{ homePageIndex * homePageSize + index + 1 }}</span>
                <span class="home-work-icon" :class="item.tone">
                  <n-icon :size="22"><component :is="item.icon" /></n-icon>
                </span>
                <span class="home-work-main">
                  <span class="home-chip-row">
                    <span class="home-chip" :class="item.tone">{{ item.label }}</span>
                  </span>
                  <strong class="home-work-title">{{ item.title }}</strong>
                  <span class="home-work-reason">{{ item.reason }}</span>
                  <span class="home-work-meta">
                    <span><n-icon :size="14"><User /></n-icon>{{ item.owner }}</span>
                    <time>{{ item.deadline }}</time>
                  </span>
                </span>
              </button>
              <div v-if="!pagedHomeWorkItems.length" class="task-mine-queue-empty task-empty-state">
                <div class="task-empty-robot" aria-hidden="true">
                  <n-icon :size="26"><Robot /></n-icon>
                  <span></span>
                </div>
                <span class="task-empty-kicker">Dobby 已待命</span>
                <strong class="task-empty-title">{{ homeEmptyText }}</strong>
                <p class="task-empty-copy">Dobby 会持续同步任务引擎，新节点到达后会显示在这里。</p>
              </div>
            </div>
            <nav class="home-pagination" aria-label="工作列表分页">
              <span>{{ homePageRangeText }}</span>
              <div>
                <button type="button" :disabled="homePageIndex === 0" aria-label="上一页" @click="goHomePage(-1)">
                  <n-icon :size="17"><ChevronLeft /></n-icon>
                </button>
                <button
                  v-for="page in homePageCount"
                  :key="page"
                  type="button"
                  :class="{ active: homePageIndex === page - 1 }"
                  :aria-current="homePageIndex === page - 1 ? 'page' : undefined"
                  @click="homePageIndex = page - 1"
                >
                  {{ page }}
                </button>
                <button type="button" :disabled="homePageIndex >= homePageCount - 1" aria-label="下一页" @click="goHomePage(1)">
                  <n-icon :size="17"><ChevronRight /></n-icon>
                </button>
              </div>
            </nav>
          </aside>

          <section v-if="selectedHomeWorkItem" class="home-work-ai" aria-label="当前工作的 Dobby 交互">
            <header class="home-work-ai-head">
              <div class="home-work-ai-title">
                <span class="home-ai-presence"><n-icon :size="16"><Robot /></n-icon>Dobby 正在跟进</span>
                <h2>{{ selectedHomeWorkItem.title }}</h2>
                <p>{{ selectedHomeWorkItem.owner }} · {{ selectedHomeWorkItem.role }} · {{ selectedHomeWorkItem.deadline }}</p>
              </div>
            </header>

            <div ref="homeWorkThreadViewport" class="home-work-ai-thread">
              <article
                v-for="messageItem in homeWorkConversationMessages"
                :key="messageItem.id"
                :class="['message-row', messageItem.role]"
              >
                <div class="message-avatar" aria-hidden="true">{{ messageItem.role === 'assistant' ? '管' : '我' }}</div>
                <div class="message-stack">
                  <div v-if="messageItem.role === 'assistant'" class="message-role">Dobby</div>
                  <div class="message-bubble">
                    <p>{{ messageItem.content }}</p>
                    <div v-if="messageItem.attachments?.length" class="message-attachments" aria-label="消息附件">
                      <span v-for="attachment in messageItem.attachments" :key="attachment.id">
                        <n-icon :size="16"><FileText /></n-icon>
                        <b :title="attachment.name">{{ attachment.name }}</b>
                        <small>{{ formatFileSize(attachment.size) }}</small>
                      </span>
                    </div>
                  </div>
                </div>
              </article>

              <section class="home-work-context" aria-label="当前工作关联信息">
                <div>
                  <span>关联信息</span>
                  <strong>{{ selectedHomeWorkItem.label }}</strong>
                </div>
                <div class="home-work-context-tags">
                  <span v-for="tag in selectedHomeWorkItem.tags" :key="tag">{{ tag }}</span>
                </div>
              </section>

              <div class="home-work-suggestions" aria-label="快捷提问">
                <button
                  v-for="suggestion in homeWorkSuggestions"
                  :key="suggestion"
                  type="button"
                  @click="dispatchHomeWorkSuggestion(suggestion)"
                >
                  {{ suggestion }}
                </button>
              </div>
            </div>

            <form class="chat-composer home-work-composer" @submit.prevent="dispatchHomeWorkCommand">
              <div class="composer-entry">
                <div v-if="homeWorkFiles.length" class="composer-attachment-list" aria-label="待发送附件">
                  <span v-for="(file, index) in homeWorkFiles" :key="`${file.name}-${file.lastModified}`">
                    <n-icon :size="16"><FileText /></n-icon>
                    <b :title="file.name">{{ file.name }}</b>
                    <small>{{ formatFileSize(file.size) }}</small>
                    <button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('work', index)">×</button>
                  </span>
                </div>
                <div class="composer-input-row">
                  <label class="composer-attach-button" title="上传图片、PDF、表格或其他工程资料">
                    <input type="file" multiple @change="selectComposerFiles('work', $event)">
                    <n-icon :size="18"><Paperclip /></n-icon>
                    <span>添加附件</span>
                  </label>
                  <textarea
                    v-model="homeWorkCommand"
                    :placeholder="`围绕“${selectedHomeWorkItem.title}”继续交互，也可以直接上传资料`"
                    @keydown.enter.exact.prevent="dispatchHomeWorkCommand"
                  ></textarea>
                </div>
              </div>
              <button type="submit" :disabled="homeWorkUploading || (!homeWorkCommand.trim() && !homeWorkFiles.length)">
                <n-icon :size="17"><Send /></n-icon>
                {{ homeWorkUploading ? '上传中…' : '发送' }}
              </button>
            </form>
          </section>

          <section v-else class="home-work-ai task-mine-ai-empty task-empty-state" aria-label="暂无待处理工作">
            <div class="task-empty-robot" aria-hidden="true">
              <n-icon :size="26"><Robot /></n-icon>
              <span></span>
            </div>
            <span class="task-empty-kicker">Dobby 已待命</span>
            <strong class="task-empty-title">{{ homeEmptyText }}</strong>
            <p class="task-empty-copy">Dobby 会持续同步任务引擎，新节点到达后会显示在这里。</p>
          </section>
        </div>

        <section v-else class="home-chat-panel">
          <div class="chat-head home-chat-head" :class="{ 'is-empty': !homeQuickSession }">
            <div v-if="homeQuickSession" class="chat-title-block">
              <h1 :title="homeQuickSessionTitle">{{ homeQuickSessionTitle }}</h1>
              <div class="chat-subline">
                <span>{{ homeQuickSessionTime }}</span>
              </div>
            </div>
          </div>
          <div ref="homeQuickViewport" :class="['messages', 'home-chat-messages', { 'is-empty': !homeQuickChatMessages.length && !homeQuickStreamingTrace }]">
            <div v-if="!homeQuickChatMessages.length && !homeQuickStreamingTrace" class="home-chat-guide">
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
                <div v-if="message.role === 'assistant'" class="message-role">{{ homeQuickAgentName }}</div>
                <div class="message-bubble">
                  <AgentMessageContent
                    :content="message.content"
                    :runtime-trace="message.runtimeTrace"
                    @confirm="confirmHomeToolCall"
                  />
                  <div v-if="message.attachments?.length" class="message-attachments" aria-label="消息附件">
                    <span v-for="attachment in message.attachments" :key="attachment.id">
                      <n-icon :size="16"><FileText /></n-icon>
                      <b :title="attachment.name">{{ attachment.name }}</b>
                      <small>{{ formatFileSize(attachment.size) }}</small>
                    </span>
                  </div>
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
            <article v-if="homeQuickStreamingTrace" class="message-row assistant">
              <div class="message-avatar" aria-hidden="true">管</div>
              <div class="message-stack">
                <div class="message-role">{{ homeQuickAgentName }}</div>
                <div class="message-bubble">
                  <AgentMessageContent
                    :runtime-trace="homeQuickStreamingTrace"
                    streaming
                    @confirm="confirmHomeToolCall"
                  />
                </div>
              </div>
            </article>
          </div>
          <form class="chat-composer home-chat-composer" @submit.prevent="dispatchQuickCommand">
            <div class="composer-entry">
              <div v-if="quickFiles.length" class="composer-attachment-list" aria-label="待发送附件">
                <span v-for="(file, index) in quickFiles" :key="`${file.name}-${file.lastModified}`">
                  <n-icon :size="16"><FileText /></n-icon>
                  <b :title="file.name">{{ file.name }}</b>
                  <small>{{ formatFileSize(file.size) }}</small>
                  <button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('quick', index)">×</button>
                </span>
              </div>
              <div class="composer-input-row">
                <label class="composer-attach-button" title="上传图片、PDF、表格或其他工程资料">
                  <input type="file" multiple @change="selectComposerFiles('quick', $event)">
                  <n-icon :size="18"><Paperclip /></n-icon>
                  <span>添加附件</span>
                </label>
                <textarea
                  v-model="quickCommand"
                  :placeholder="`输入问题，也可以上传资料让${homeQuickAgentName}识别和分析`"
                  @keydown.enter.exact.prevent="dispatchQuickCommand"
                ></textarea>
              </div>
            </div>
            <button v-if="quickUploading" type="button" class="stop-agent" @click="stopHomeAgent">
              <n-icon :size="17"><PlayerStop /></n-icon>
              停止
            </button>
            <button v-else type="submit" :disabled="!quickCommand.trim() && !quickFiles.length">
              <n-icon :size="17"><Send /></n-icon>
              发送
            </button>
          </form>
        </section>
      </main>
    </section>

    <ProjectGroupChat v-else-if="section === 'ai'" />

    <section v-else-if="section === 'tasks'" class="task-page task-management-page">
      <header class="task-management-nav">
        <nav aria-label="任务管理模块">
          <button v-for="tab in taskManagementTabs" :key="tab.key" type="button" :title="tab.hint" :class="{ active: taskManagementTab === tab.key }" @click="taskManagementTab = tab.key">
            <span><n-icon :size="17"><component :is="tab.icon" /></n-icon>{{ tab.label }}</span>
            <b>{{ tab.count }}</b>
          </button>
        </nav>
      </header>

      <main v-if="taskManagementTab === 'mine'" class="task-mine-view">
        <div class="home-workbench task-mine-workbench">
          <aside class="home-queue-pane" aria-label="我的待办列表">
            <div class="home-controlbar">
              <div class="home-status-tabs" role="tablist" aria-label="我的待办状态">
                <button
                  v-for="tab in taskMineStatusTabs"
                  :key="tab.key"
                  type="button"
                  role="tab"
                  :aria-selected="taskMineStatus === tab.key"
                  :class="{ active: taskMineStatus === tab.key }"
                  @click="taskMineStatus = tab.key"
                >
                  {{ tab.label }}
                  <span>{{ tab.count }}</span>
                </button>
              </div>
            </div>

            <div class="home-queue-list" role="listbox" :aria-label="`${taskMineStatusTabs.find(tab => tab.key === taskMineStatus)?.label || '任务'}列表`">
              <button
                v-for="(item, index) in pagedTaskMineWorkItems"
                :key="item.id"
                type="button"
                :class="['home-queue-card', { active: selectedTaskMineWorkItemId === item.id }]"
                :aria-selected="selectedTaskMineWorkItemId === item.id"
                role="option"
                @click="selectedTaskMineWorkItemId = item.id"
              >
                <span class="home-rank" :class="item.tone">{{ taskMinePageIndex * taskMinePageSize + index + 1 }}</span>
                <span class="home-work-icon" :class="item.tone">
                  <n-icon :size="22"><component :is="item.icon" /></n-icon>
                </span>
                <span class="home-work-main">
                  <span class="home-chip-row"><span class="home-chip" :class="item.tone">{{ item.label }}</span></span>
                  <strong class="home-work-title">{{ item.title }}</strong>
                  <span class="home-work-reason">{{ item.reason }}</span>
                  <span class="home-work-meta">
                    <span><n-icon :size="14"><User /></n-icon>{{ item.owner }}</span>
                    <time>{{ item.deadline }}</time>
                  </span>
                </span>
              </button>
              <div v-if="!pagedTaskMineWorkItems.length" class="task-mine-queue-empty task-empty-state">
                <div class="task-empty-robot" aria-hidden="true">
                  <n-icon :size="26"><Robot /></n-icon>
                  <span></span>
                </div>
                <span class="task-empty-kicker">Dobby 已待命</span>
                <strong class="task-empty-title">{{ taskMineEmptyText }}</strong>
                <p class="task-empty-copy">Dobby 会持续同步任务引擎，新节点到达后会显示在这里。</p>
              </div>
            </div>

            <nav class="home-pagination" aria-label="我的待办分页">
              <span>{{ taskMinePageRangeText }}</span>
              <div>
                <button type="button" :disabled="taskMinePageIndex === 0" aria-label="上一页" @click="goTaskMinePage(-1)"><n-icon :size="17"><ChevronLeft /></n-icon></button>
                <button v-for="page in taskMinePageCount" :key="page" type="button" :class="{ active: taskMinePageIndex === page - 1 }" :aria-current="taskMinePageIndex === page - 1 ? 'page' : undefined" @click="taskMinePageIndex = page - 1">{{ page }}</button>
                <button type="button" :disabled="taskMinePageIndex >= taskMinePageCount - 1" aria-label="下一页" @click="goTaskMinePage(1)"><n-icon :size="17"><ChevronRight /></n-icon></button>
              </div>
            </nav>
          </aside>

          <section v-if="selectedTaskMineWorkItem" class="home-work-ai" aria-label="当前任务的 Dobby 交互">
            <header class="home-work-ai-head">
              <div class="home-work-ai-title">
                <span class="home-ai-presence"><n-icon :size="16"><Robot /></n-icon>Dobby 正在跟进</span>
                <h2>{{ selectedTaskMineWorkItem.title }}</h2>
                <p>{{ selectedTaskMineWorkItem.owner }} · {{ selectedTaskMineWorkItem.role }} · {{ selectedTaskMineWorkItem.deadline }}</p>
              </div>
            </header>

            <div ref="taskMineThreadViewport" class="home-work-ai-thread">
              <article v-for="messageItem in taskMineConversationMessages" :key="messageItem.id" :class="['message-row', messageItem.role]">
                <div class="message-avatar" aria-hidden="true">{{ messageItem.role === 'assistant' ? '管' : '我' }}</div>
                <div class="message-stack">
                  <div v-if="messageItem.role === 'assistant'" class="message-role">Dobby</div>
                  <div class="message-bubble">
                    <p>{{ messageItem.content }}</p>
                    <div v-if="messageItem.attachments?.length" class="message-attachments" aria-label="消息附件">
                      <span v-for="attachment in messageItem.attachments" :key="attachment.id"><n-icon :size="16"><FileText /></n-icon><b :title="attachment.name">{{ attachment.name }}</b><small>{{ formatFileSize(attachment.size) }}</small></span>
                    </div>
                  </div>
                </div>
              </article>

              <section class="home-work-context" aria-label="当前任务关联信息">
                <div><span>关联信息</span><strong>{{ selectedTaskMineWorkItem.label }}</strong></div>
                <div class="home-work-context-tags">
                  <span v-for="tag in selectedTaskMineWorkItem.tags" :key="tag">{{ tag }}</span>
                </div>
              </section>

              <div class="home-work-suggestions" aria-label="快捷提问">
                <button v-for="suggestion in taskMineSuggestions" :key="suggestion" type="button" @click="dispatchTaskMineSuggestion(suggestion)">{{ suggestion }}</button>
              </div>
            </div>

            <form class="chat-composer home-work-composer" @submit.prevent="dispatchTaskMineCommand">
              <div class="composer-entry">
                <div v-if="taskMineFiles.length" class="composer-attachment-list" aria-label="待发送附件">
                  <span v-for="(file, index) in taskMineFiles" :key="`${file.name}-${file.lastModified}`"><n-icon :size="16"><FileText /></n-icon><b :title="file.name">{{ file.name }}</b><small>{{ formatFileSize(file.size) }}</small><button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('task', index)">×</button></span>
                </div>
                <div class="composer-input-row">
                  <label class="composer-attach-button" title="上传任务证明材料或工程资料"><input type="file" multiple @change="selectComposerFiles('task', $event)"><n-icon :size="18"><Paperclip /></n-icon><span>添加附件</span></label>
                  <textarea v-model="taskMineCommand" :placeholder="`围绕“${selectedTaskMineWorkItem.title}”继续交互，也可以直接上传资料`" @keydown.enter.exact.prevent="dispatchTaskMineCommand"></textarea>
                </div>
              </div>
              <button type="submit" :disabled="taskMineUploading || (!taskMineCommand.trim() && !taskMineFiles.length)"><n-icon :size="17"><Send /></n-icon>{{ taskMineUploading ? '上传中…' : '发送' }}</button>
            </form>
          </section>

          <section v-else class="home-work-ai task-mine-ai-empty task-empty-state" aria-label="暂无任务">
            <div class="task-empty-robot" aria-hidden="true">
              <n-icon :size="26"><Robot /></n-icon>
              <span></span>
            </div>
            <span class="task-empty-kicker">Dobby 已待命</span>
            <strong class="task-empty-title">{{ taskMineEmptyText }}</strong>
            <p class="task-empty-copy">Dobby 会持续同步任务引擎，新节点到达后会显示在这里。</p>
          </section>
        </div>
      </main>

      <main v-else-if="taskManagementTab === 'history'" class="task-history-view">
        <form class="task-history-search" @submit.prevent>
          <label><span>任务名称</span><input v-model.trim="taskHistoryKeyword" placeholder="输入名称、类型或触发原因"></label>
          <label><span>任务状态</span><select v-model="taskHistoryStatus"><option value="all">全部状态</option><option value="pending">待处理</option><option value="processing">处理中</option><option value="need_more_info">待补充资料</option><option value="waiting_confirm">待确认</option><option value="overdue">已逾期</option><option value="done">已完成</option><option value="cancelled">已取消</option></select></label>
          <label><span>开始日期</span><input v-model="taskHistoryStart" type="date"></label>
          <label><span>结束日期</span><input v-model="taskHistoryEnd" type="date"></label>
          <button type="button" @click="clearTaskHistoryFilters">清除筛选</button>
        </form>
        <section class="task-history-results">
          <div class="task-history-table-head"><span>任务</span><span>状态</span><span>当前责任</span><span>最近更新</span><span>闭环结果</span><span></span></div>
          <article v-for="task in filteredHistoryTasks" :key="task.id">
            <div><strong>{{ task.title }}</strong><small>{{ taskLedgerTypeLabel(task) }} · {{ task.triggerReason || '无补充说明' }}</small></div><span class="task-ledger-status" :class="task.status">{{ statusLabel(task.status) }}</span><span>{{ taskLedgerOwner(task) }}</span><time>{{ formatDateTime(taskLedgerTimestamp(task)) }}</time><em :class="taskClosureTone(task)">{{ taskClosureLabel(task) }}</em><button type="button" @click="openTaskHistory(task.id)">查看记录</button>
          </article>
          <div v-if="!filteredHistoryTasks.length" class="task-history-no-result"><Notes :size="30" /><strong>没有匹配的任务记录</strong><p>调整名称、状态或日期范围后再试。</p></div>
        </section>
      </main>

      <main v-else-if="taskManagementTab === 'schedules'" class="task-schedule-view">
        <form class="task-history-search task-schedule-search" @submit.prevent>
          <label><span>计划名称</span><input v-model.trim="taskScheduleKeyword" placeholder="输入计划名称或触发规则"></label>
          <label><span>计划状态</span><select v-model="taskScheduleStatus"><option value="all">全部状态</option><option value="active">生效中</option><option value="paused">已暂停</option><option value="ended">已结束</option><option value="cancelled">已取消</option></select></label>
          <button type="button" @click="loadTaskSchedules"><n-icon :size="17"><Repeat /></n-icon>刷新</button>
          <button type="button" class="task-schedule-create" @click="taskManagementTab = 'assign'"><n-icon :size="17"><Plus /></n-icon>布置任务</button>
        </form>
        <section class="task-history-results task-schedule-results">
          <div class="task-history-table-head"><span>触发计划</span><span>状态</span><span>下次触发</span><span>已触发</span><span>操作</span></div>
          <article v-for="schedule in filteredTaskSchedules" :key="schedule.id" :class="{ paused: schedule.paused, inactive: !schedule.active }">
            <div class="task-schedule-main">
              <strong>{{ schedule.title }}</strong>
              <small>{{ taskScheduleKindLabel(schedule) }} · {{ schedule.trigger_description }}{{ taskScheduleActionDescription(schedule) }}</small>
              <small v-if="schedule.last_error" class="task-schedule-error">最近失败：{{ schedule.last_error }}</small>
            </div>
            <span class="task-schedule-status" :class="{ active: schedule.active && !schedule.paused, paused: schedule.paused, ended: !schedule.active }">{{ schedule.status }}</span>
            <time>{{ schedule.next_fire_at ? formatScheduleDateTime(schedule.next_fire_at) : '—' }}</time>
            <span>{{ schedule.fire_count }} 次</span>
            <div class="task-schedule-actions">
              <button v-if="schedule.active" type="button" @click="setTaskSchedulePaused(schedule, !schedule.paused)">{{ schedule.paused ? '恢复' : '暂停' }}</button>
              <button v-if="schedule.active" type="button" class="danger" @click="confirmCancelTaskSchedule(schedule)">取消</button>
              <span v-else>—</span>
            </div>
          </article>
          <div v-if="!filteredTaskSchedules.length" class="task-history-no-result">
            <div class="task-empty-robot" aria-hidden="true"><n-icon :size="26"><Robot /></n-icon><span></span></div>
            <strong>{{ taskSchedulesLoading ? '正在读取计划列表' : taskSchedules.length ? '没有匹配的计划' : '还没有计划' }}</strong>
            <p>{{ taskSchedules.length ? '调整名称或状态后再试。' : '选择定时单次、固定间隔或日历规则后，计划会显示在这里。' }}</p>
          </div>
        </section>
      </main>

      <main v-else class="task-assign-view">
        <form class="task-flow-builder" @submit.prevent="createManualTask">
          <section class="task-flow-global-settings" aria-label="任务全局配置：执行与触发设置">
            <div class="task-flow-global-head">
              <div class="task-flow-global-copy"><div><span>任务全局配置</span><strong>执行与触发设置</strong></div><p>以下设置作用于整个任务流，不属于任何单个节点。</p></div>
              <output class="task-flow-trigger-preview" aria-live="polite"><span>触发说明</span><strong>{{ taskTriggerSummary }}</strong></output>
            </div>
            <div class="task-flow-global-grid">
              <label class="form-field task-flow-title-field"><span class="task-flow-field-label"><n-icon :size="16"><Notes /></n-icon>任务名称</span><input v-model.trim="taskCreateForm.title" required placeholder="输入任务流名称"></label>
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><MapPin /></n-icon>关联工点</span><select v-model="taskCreateForm.wbs_item_id" :required="taskFlowSteps.some(step => step.node_type === 'manual')"><option value="">无</option><option v-for="item in store.wbsItems" :key="item.id" :value="item.id">{{ item.code }} {{ item.name }}</option></select></label>
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><User /></n-icon>确认人</span><select v-model="taskCreateForm.confirmer_user_id" :required="taskFlowSteps.some(step => step.node_type === 'manual')"><option value="">无</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label>
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><Repeat /></n-icon>触发方式</span><select v-model="taskCreateForm.run_mode"><option value="immediate">立即执行</option><option value="once">定时单次</option><option value="recurring">固定间隔</option><option value="calendar">日历规则</option></select></label>
              <label v-if="taskCreateForm.run_mode !== 'immediate'" class="form-field task-flow-time-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>{{ taskCreateForm.run_mode === 'once' ? '执行时间' : '生效时间' }}</span><input v-model="taskExecutionAt" type="datetime-local" required></label>
              <label v-if="taskCreateForm.run_mode === 'recurring'" class="form-field task-flow-interval-field"><span class="task-flow-field-label"><n-icon :size="16"><Clock /></n-icon>触发间隔</span><span><input v-model.number="taskCreateForm.trigger_interval_value" type="number" min="1" max="10000" required><select v-model="taskCreateForm.trigger_interval_unit"><option value="minute">分钟</option><option value="hour">小时</option><option value="day">天</option><option value="week">周</option><option value="month">个月</option></select></span></label>
              <label v-if="taskCreateForm.run_mode === 'calendar'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>日历规则</span><select v-model="taskCreateForm.trigger_calendar_mode"><option value="daily">每天</option><option value="weekdays">每个工作日</option><option value="weekly">每周指定星期</option><option value="monthly">每月指定日期</option></select></label>
              <div v-if="taskCreateForm.run_mode === 'calendar' && taskCreateForm.trigger_calendar_mode === 'weekly'" class="form-field task-calendar-weekdays"><span class="task-flow-field-label"><n-icon :size="16"><ListCheck /></n-icon>选择星期</span><div><label v-for="(day, index) in ['一','二','三','四','五','六','日']" :key="day"><input v-model="taskCreateForm.trigger_weekdays" type="checkbox" :value="index + 1">周{{ day }}</label></div></div>
              <label v-if="taskCreateForm.run_mode === 'calendar' && taskCreateForm.trigger_calendar_mode === 'monthly'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>每月日期</span><input v-model.number="taskCreateForm.trigger_day_of_month" type="number" min="1" max="31" required></label>
              <label v-if="taskCreateForm.run_mode === 'recurring' || taskCreateForm.run_mode === 'calendar'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><PlayerStop /></n-icon>结束条件</span><select v-model="taskCreateForm.trigger_end_mode"><option value="never">持续执行</option><option value="until">到指定日期</option><option value="count">执行指定次数</option></select></label>
              <label v-if="(taskCreateForm.run_mode === 'recurring' || taskCreateForm.run_mode === 'calendar') && taskCreateForm.trigger_end_mode === 'until'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>结束日期</span><input v-model="taskCreateForm.trigger_until_date" type="date" required></label>
              <label v-if="(taskCreateForm.run_mode === 'recurring' || taskCreateForm.run_mode === 'calendar') && taskCreateForm.trigger_end_mode === 'count'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><ListCheck /></n-icon>执行次数</span><input v-model.number="taskCreateForm.trigger_max_fires" type="number" min="1" max="10000" required></label>
              <label class="form-field task-flow-cc-field"><span class="task-flow-field-label"><n-icon :size="16"><At /></n-icon>抄送人</span><input v-model.trim="taskCreateForm.cc" placeholder="输入姓名，多个用逗号分隔"></label>
            </div>
          </section>

          <div class="task-flow-workspace">
            <main class="task-flow-authoring">
              <div class="task-flow-assistant-bar">
                <span class="task-flow-assistant-icon"><n-icon :size="20"><Robot /></n-icon></span>
                <strong>Dobby 任务流助手</strong>
                <button type="button" class="task-flow-assistant-toggle" :aria-expanded="taskFlowAssistantOpen" aria-controls="task-flow-assistant-panel" @click="taskFlowAssistantOpen = !taskFlowAssistantOpen">{{ taskFlowAssistantOpen ? '收起助手' : '展开助手' }}<n-icon :size="17"><ChevronDown /></n-icon></button>
              </div>

              <section id="task-flow-assistant-panel" :class="['task-flow-assistant-panel', { collapsed: !taskFlowAssistantOpen }]">
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
              </section>

              <div class="task-flow-editor-head">
                <div><span>流程节点</span><strong>{{ taskCreateForm.title || '未命名任务流' }}</strong><small>{{ taskFlowSteps.length }} 个节点，将按顺序依次流转</small></div>
                <div class="task-flow-editor-actions"><em>展开节点后编辑详细配置</em><button type="button" class="task-flow-add-button" @click="addTaskFlowStep"><n-icon :size="16"><Plus /></n-icon>添加节点</button></div>
              </div>

              <div class="task-flow-node-workspace">
                <section class="task-flow-node-list" aria-label="流程节点配置">
                  <div v-if="!taskFlowSteps.length" class="task-flow-node-empty">
                    <span><n-icon :size="26"><Robot /></n-icon></span>
                    <strong>还没有流程节点</strong>
                    <p>让 Dobby 生成、选择标准模板，或手工添加第一个节点。</p>
                    <button type="button" @click="addTaskFlowStep"><n-icon :size="16"><Plus /></n-icon>添加第一个节点</button>
                  </div>
                  <article v-for="(step, index) in taskFlowSteps" :id="`task-flow-node-${index}`" :key="step.id" class="task-flow-node-card" :class="{ active: selectedTaskFlowStepIndex === index }" tabindex="-1" @click="selectedTaskFlowStepIndex = index">
                    <header>
                      <span>{{ index + 1 }}</span>
                      <div class="task-flow-node-heading"><strong>{{ step.name || `节点 ${index + 1}` }}</strong><small>{{ taskFlowStepSummary(step) }}</small></div>
                      <em v-if="selectedTaskFlowStepIndex === index">当前节点</em>
                      <div class="task-flow-node-actions"><button type="button" :disabled="index === 0" title="上移" aria-label="上移节点" @click.stop="moveTaskFlowStep(index, -1)"><n-icon :size="16"><ChevronUp /></n-icon></button><button type="button" :disabled="index === taskFlowSteps.length - 1" title="下移" aria-label="下移节点" @click.stop="moveTaskFlowStep(index, 1)"><n-icon :size="16"><ChevronDown /></n-icon></button><button type="button" class="danger" title="删除" aria-label="删除节点" @click.stop="removeTaskFlowStep(index)"><n-icon :size="16"><Trash /></n-icon></button><button type="button" title="展开或收起" :aria-expanded="selectedTaskFlowStepIndex === index" @click.stop="selectedTaskFlowStepIndex = selectedTaskFlowStepIndex === index ? -1 : index"><n-icon :size="16"><component :is="selectedTaskFlowStepIndex === index ? ChevronUp : ChevronDown" /></n-icon></button></div>
                    </header>
                    <div v-if="selectedTaskFlowStepIndex === index" class="task-flow-node-fields">
                      <label class="form-field">节点类型<select v-model="step.node_type" @change="handleTaskFlowStepTypeChange(step)"><option value="manual">人工处理</option><option value="project_chat_message">发送群聊消息</option></select></label>
                      <label class="form-field">节点名称<input v-model.trim="step.name" required></label>
                      <template v-if="step.node_type === 'manual'">
                        <label class="form-field">节点负责人<select v-model="step.owner_user_id" required><option value="">待指定</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label>
                        <label class="form-field">截止日期<input v-model="step.due_at" type="date"></label>
                        <label class="form-field task-flow-node-material">交付材料 / 留证<input v-model.trim="step.material" placeholder="填写后引擎将要求上传证明材料"></label>
                      </template>
                      <template v-else>
                        <label class="form-field">发送智能体<select v-model="step.sender_agent_id" required><option v-for="agent in taskMessageSenderOptions" :key="agent.id" :value="agent.id">{{ agent.name }}</option></select></label>
                        <label class="form-field">目标群聊<select v-model.number="step.target_channel_id" required @change="handleTaskMessageChannelChange(step)"><option :value="null">请选择群聊</option><option v-for="channel in taskChatChannels" :key="channel.id" :value="channel.id">{{ channel.title }}</option></select></label>
                        <label class="form-field">提醒对象<select v-model="step.mention_mode"><option value="all">@全体成员</option><option value="users">指定成员</option><option value="none">不提及成员</option></select></label>
                        <label class="form-field task-flow-node-message">消息正文<textarea v-model.trim="step.message_content" maxlength="8000" rows="3" required placeholder="填写该节点到达时要发送的消息"></textarea><small>{{ step.message_content.length }} / 8000</small></label>
                        <fieldset v-if="step.mention_mode === 'users'" class="task-flow-node-recipients"><legend>选择提醒成员</legend><label v-for="member in taskChatMembersForStep(step)" :key="member.user_id"><input v-model="step.mentioned_user_ids" type="checkbox" :value="member.user_id"><span>{{ member.name }}</span></label><p v-if="!taskChatMembersForStep(step).length">当前群聊没有可选成员</p></fieldset>
                      </template>
                    </div>
                  </article>
                </section>
              </div>
            </main>

            <aside class="task-flow-validation" aria-label="任务引擎校验">
              <div class="task-flow-validation-head"><span>引擎校验</span><strong>布置前检查</strong></div>
              <div class="task-flow-validation-status" :class="{ passed: taskFlowCanSubmit }"><n-icon :size="23"><component :is="taskFlowCanSubmit ? CircleCheck : AlertCircle" /></n-icon><div><strong>{{ taskFlowCanSubmit ? '校验通过' : `还差 ${taskFlowMissingCount} 项` }}</strong><span>{{ taskFlowCanSubmit ? '可以提交给任务引擎' : '补齐后即可布置任务' }}</span></div></div>
              <ul class="task-flow-validation-list">
                <li v-for="item in taskFlowValidationItems" :key="item.key" :class="{ ok: item.ok }"><n-icon :size="17"><component :is="item.ok ? CircleCheck : AlertCircle" /></n-icon><div><strong>{{ item.label }}</strong><span>{{ item.detail }}</span></div></li>
              </ul>
              <details v-if="taskFlowSteps.length" class="task-flow-overview" open>
                <summary><span>流程概览</span><em>{{ taskFlowSteps.length }} 个节点</em><n-icon :size="16"><ChevronDown /></n-icon></summary>
                <ol>
                  <li v-for="(step, index) in taskFlowSteps" :key="`overview-${step.id}`">
                    <button type="button" :class="{ active: selectedTaskFlowStepIndex === index }" :aria-label="`定位到第 ${index + 1} 个节点：${step.name || `节点 ${index + 1}`}`" @click="focusTaskFlowStep(index)">
                      <span>{{ index + 1 }}</span>
                      <div><strong>{{ step.name || `节点 ${index + 1}` }}</strong><small>{{ step.node_type === 'project_chat_message' ? '自动消息' : '人工处理' }} · {{ taskFlowStepSummary(step) }}</small></div>
                      <n-icon :size="15"><ChevronRight /></n-icon>
                    </button>
                  </li>
                </ol>
              </details>
              <div class="task-flow-validation-note"><strong>引擎约束</strong><p>流程中存在“人工处理”节点时，任务引擎要求选择具体负责人、关联工点和确认人；全部为自动动作节点时，关联工点和确认人可以选择“无”。</p></div>
              <button type="submit" class="task-flow-submit" :disabled="!taskFlowCanSubmit">{{ taskCreateForm.run_mode === 'immediate' ? '校验并布置任务' : '校验并登记计划' }}</button>
              <button type="button" class="task-flow-back" @click="taskManagementTab = 'mine'">返回我的待办</button>
            </aside>
          </div>
        </form>
      </main>

      <div v-if="taskDispositionOpen && selectedTask" class="task-disposition-backdrop" @click.self="closeTaskDisposition">
        <aside class="task-disposition-drawer" role="dialog" aria-modal="true" aria-labelledby="task-disposition-title">
          <header><div><span>{{ taskTypeLabel(selectedTask.type) }} · {{ statusLabel(selectedTask.status) }}</span><h2 id="task-disposition-title">{{ selectedTask.title }}</h2><p>{{ taskCurrentOwnerName(selectedTask) }} · 截止 {{ taskCurrentStep(selectedTask)?.due_at || selectedTask.deadline }}</p></div><button type="button" aria-label="关闭任务处置" @click="closeTaskDisposition">关闭</button></header>
          <div class="task-disposition-body">
            <section class="task-disposition-ai"><span class="task-disposition-bot"><Robot :size="18" /></span><div><strong>Dobby 处置提示</strong><p>{{ selectedTaskConclusion }}</p><small>依据：{{ selectedTask.triggerReason }}</small></div></section>
            <section class="task-disposition-flow"><div class="task-disposition-section-title"><span>任务流程</span><strong>{{ selectedTaskCompletedSteps }}/{{ selectedTask.workflowSteps.length || 1 }} 个节点已完成</strong></div><ol><li v-for="(step, index) in selectedTask.workflowSteps" :key="`${selectedTask.id}-dispose-${index}`" :class="step.status"><span>{{ index + 1 }}</span><div><strong>{{ step.name }}</strong><small>{{ step.owner || store.getMemberName(step.owner_user_id || '') || '待指定负责人' }} · {{ step.due_at || '未设置截止时间' }}</small><small v-if="step.reopened" class="task-disposition-reopen-hint">⚠ 该节点被退回，需重新提交材料</small><p v-if="step.note" class="task-disposition-step-note">{{ step.note }}</p><div v-if="step.attachments?.length" class="task-disposition-step-files"><button v-for="attachment in step.attachments" :key="attachment" type="button" class="task-disposition-step-file" @click="downloadTaskAttachment(attachment)"><n-icon :size="14"><Paperclip /></n-icon>{{ taskAttachmentFileName(attachment) }}</button></div></div><em>{{ taskStepLabel(step.status) }}</em><button v-if="selectedTask.status === 'processing' && step.status !== 'completed'" type="button" @click="store.updateTaskStep(selectedTask.id, index, 'completed')">完成节点</button></li></ol></section>
            <section class="task-disposition-form"><div class="task-disposition-section-title"><span>回复与材料</span><strong>结果将进入任务处理记录</strong></div><textarea v-model.trim="taskDispositionReply" rows="5" placeholder="回复 Dobby，例如：已完成复核，照片符合闭环要求"></textarea><label class="task-disposition-files"><input type="file" multiple @change="handleTaskDispositionFiles"><span><Paperclip :size="16" />选择文件或图片</span><small>{{ taskDispositionFiles.length ? `已选择 ${taskDispositionFiles.length} 个文件` : '支持提交本节点的证明材料' }}</small></label><label class="task-disposition-forward"><span>转交当前节点</span><select v-model="taskDispositionForwardId"><option value="">不转交</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label></section>
          </div>
          <footer><button type="button" class="task-disposition-history" @click="openTaskHistory(selectedTask.id)">查看处理记录</button><router-link to="/ai">发起讨论</router-link><button v-if="canConfirmSelectedTask" type="button" class="task-disposition-history" :disabled="taskDispositionSubmitting" @click="rejectSelectedTask">退回重做</button><button v-if="canConfirmSelectedTask" type="button" class="task-disposition-submit" :disabled="taskDispositionSubmitting" @click="acceptSelectedTask">{{ taskDispositionSubmitting ? '正在提交…' : '确认通过' }}</button><button v-else type="button" class="task-disposition-submit" :disabled="taskDispositionSubmitting || needsFreshEvidence" @click="submitTaskDisposition">{{ taskDispositionSubmitting ? '正在提交…' : needsFreshEvidence ? '需重新上传材料' : '回复并推进' }}</button></footer>
        </aside>
      </div>
      <div v-if="taskHistoryOpenId && selectedTaskHistoryTask" class="workflow-modal-backdrop" @click.self="closeTaskHistory">
        <section class="workflow-modal task-history-modal" role="dialog" aria-modal="true" aria-labelledby="task-history-title">
          <div class="workflow-modal-head">
            <div><h2 id="task-history-title">任务记录 - {{ selectedTaskHistoryTask.title }}</h2></div>
            <button type="button" class="modal-close" aria-label="关闭处理记录" @click="closeTaskHistory">关闭</button>
          </div>
          <div class="task-history-summary">
            <div><span>当前状态</span><strong>{{ statusLabel(selectedTaskHistoryTask.status) }}</strong></div>
            <div><span>当前责任</span><strong>{{ taskLedgerOwner(selectedTaskHistoryTask) }}</strong></div>
            <div><span>截止时间</span><strong>{{ taskLedgerTypeLabel(selectedTaskHistoryTask) === '自动化动作' ? '—' : formatDateTime(selectedTaskHistoryTask.deadline, 'end') }}</strong></div>
          </div>
          <div class="task-history-body">
            <div v-if="taskHistoryLoading" class="task-history-loading">正在加载处理记录…</div>
            <ol v-else-if="(taskHistories[taskHistoryOpenId] || []).length" class="task-history-timeline">
              <li v-for="item in taskHistories[taskHistoryOpenId] || []" :key="item.id">
                <i aria-hidden="true"></i>
                <div><header><strong>{{ taskHistoryTitle(item) }}</strong><time>{{ formatDateTime(item.created_at) }}</time></header><p>{{ item.note || '状态更新' }}</p></div>
              </li>
            </ol>
            <div v-else class="task-history-empty"><strong>暂无处理记录</strong><p>开始处理或更新任务状态后，系统会在这里自动留痕。</p></div>
          </div>
          <div class="workflow-modal-actions task-history-actions"><button type="button" class="modal-primary" @click="closeTaskHistory">完成查看</button></div>
        </section>
      </div>
    </section>

    <section v-else-if="section === 'project'" class="page-stack project-page project-status-view project-status-v2">
      <section class="project-status-v2-summary" aria-label="项目关键数据">
        <article v-for="metric in projectStatusMetrics" :key="metric.label" :class="metric.tone">
          <div class="project-status-v2-metric-icon"><n-icon :size="27"><component :is="metric.icon" /></n-icon></div>
          <div><span>{{ metric.label }}</span><strong>{{ metric.value }}</strong><small>{{ metric.hint }}</small></div>
        </article>
      </section>

      <nav class="project-status-tabs" aria-label="项目状态汇总视图">
        <button
          v-for="tab in projectStatusTabs"
          :key="tab.key"
          type="button"
          :class="{ active: projectStatusTab === tab.key }"
          :aria-selected="projectStatusTab === tab.key"
          role="tab"
          @click="projectStatusTab = tab.key"
        ><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <main class="project-status-v2-content">
        <section v-if="projectStatusTab === 'progress'" class="project-status-v2-stack">
          <article class="project-status-v2-panel project-status-task-panel">
            <header class="project-status-task-title">
              <h2>责任任务</h2>
              <router-link to="/tasks">查看全部任务</router-link>
            </header>
            <div class="project-status-task-layout">
              <dl class="project-status-task-counts">
                <div v-for="item in projectTaskCounts" :key="item.label" :class="item.tone"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div>
              </dl>
              <div class="project-status-task-table">
                <div class="project-status-task-table-head"><span>任务名称</span><span>责任人</span><span>计划完成日期</span><span>状态</span></div>
                <article v-for="task in projectStatusTaskPreview" :key="task.id">
                  <strong :title="task.title">{{ task.title }}</strong>
                  <span>{{ store.getMemberName(task.responsibleId) || '未指定' }}</span>
                  <time>{{ projectDateLabel(task.deadline) || '未设置' }}</time>
                  <span :class="['project-status-task-state', task.status]"><i aria-hidden="true" />{{ projectTaskStatusLabel(task.status) }}</span>
                </article>
                <div v-if="!projectStatusTaskPreview.length" class="project-status-task-table-empty">当前没有未完成的责任任务</div>
              </div>
            </div>
          </article>

          <article class="project-status-v2-panel project-status-wbs-panel">
            <header class="project-status-wbs-title">
              <h2>工序进度 <small>{{ projectStatusWbsTotal }} 项</small></h2>
            </header>
            <div class="project-status-v2-table project-status-wbs-table">
              <div class="project-status-v2-table-head"><span>工序编码</span><span>工序名称</span><span>状态</span><span>进度</span><span>计划完成日期</span></div>
              <article v-for="item in projectStatusWbsRows" :key="item.id">
                <span>{{ item.code || '—' }}</span>
                <strong>{{ item.name }}</strong>
                <span :class="['project-status-state', item.status]">{{ item.statusText || wbsStatusLabel(item.status) }}</span>
                <div class="project-status-progress"><b>{{ Math.round(item.progress) }}%</b><i><em :style="{ width: `${item.progress}%` }" /></i></div>
                <time>{{ projectDateLabel(item.planEnd) || '未设置' }}</time>
              </article>
              <div v-if="!projectStatusWbsRows.length" class="project-status-wbs-empty"><strong>尚未配置 WBS</strong><router-link to="/settings">前往工程配置</router-link></div>
            </div>
          </article>
        </section>

        <section v-else-if="projectStatusTab === 'riskQuality'" class="project-status-v2-stack">
          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>风险源</span><h2>风险源配置汇总</h2><p>展示工程配置页面已维护的风险等级、工序和管控窗口，不推断风险是否触发。</p></div>
              <router-link class="project-status-v2-link" to="/settings">维护风险源 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusRiskRows.length" class="project-status-v2-table project-status-risk-table">
              <div class="project-status-v2-table-head"><span>风险等级</span><span>风险源</span><span>关联工序</span><span>管控窗口</span><span>责任人</span></div>
              <article v-for="risk in projectStatusRiskRows" :key="risk.id">
                <span :class="['project-status-risk-level', risk.level]">{{ risk.levelText || riskLabel(risk.level) }}</span>
                <strong>{{ risk.name }}</strong>
                <span>{{ risk.relatedProcessName || '未填写' }}</span>
                <time>{{ projectDateRange(risk.controlStart, risk.controlEnd) }}</time>
                <span>{{ store.getMemberName(risk.responsibleId) || '未指定' }}</span>
              </article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>风险源尚未维护</strong><p>这里不显示“无风险”，只说明工程配置中还没有风险源记录。</p><router-link to="/settings">前往工程配置</router-link></div>
          </article>

          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>质量要求</span><h2>质量检查要求汇总</h2><p>展示已配置的检查项、控制指标和检查频次，不作为质量问题统计。</p></div>
              <router-link class="project-status-v2-link" to="/settings">维护质量要求 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusQualityRows.length" class="project-status-v2-table project-status-quality-table">
              <div class="project-status-v2-table-head"><span>关联 WBS</span><span>检查项</span><span>控制指标</span><span>检查频次</span><span>责任人</span></div>
              <article v-for="item in projectStatusQualityRows" :key="item.id">
                <span>{{ projectQualityWbsLabel(item) }}</span>
                <strong>{{ item.name || '未命名检查项' }}</strong>
                <span>{{ item.controlIndicator || item.requirement || '未填写' }}</span>
                <span>{{ item.inspectionFrequency || '未填写' }}</span>
                <span>{{ store.getMemberName(item.ownerId || '') || '未指定' }}</span>
              </article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>质量要求尚未配置</strong><p>工程配置中新增质量要求后会自动出现在这里。</p><router-link to="/settings">前往工程配置</router-link></div>
          </article>
        </section>

        <section v-else-if="projectStatusTab === 'documents'" class="project-status-v2-stack">
          <article class="project-status-v2-panel project-status-documents-panel">
            <header class="project-status-v2-panel-head">
              <div><span>工程资料</span><h2>资料目录概览</h2><p>{{ projectDocumentSummary.caption }}</p></div>
              <router-link class="project-status-v2-link" to="/docs">查看工程资料 <ChevronRight :size="15" /></router-link>
            </header>
            <dl class="project-status-document-kpis">
              <div><dt>资料文件</dt><dd><strong>{{ projectDocumentSummary.totalFiles }}</strong><span>份</span></dd></div>
              <div><dt>资料目录</dt><dd><strong>{{ projectDocumentSummary.folderCount }}</strong><span>个</span></dd></div>
              <div><dt>资料库</dt><dd><strong>{{ projectDocumentSummary.knowledgeBaseCount }}</strong><span>个</span></dd></div>
            </dl>
            <div v-if="projectDocumentKnowledgeBases.length" class="project-status-document-grid">
              <section class="project-status-document-block">
                <header><h3>资料库构成</h3><span>{{ projectDocumentSummary.knowledgeBaseCount }} 个资料库</span></header>
                <div class="project-status-document-table">
                  <div class="project-status-document-table-head"><span>资料库</span><span>目录</span><span>文件</span></div>
                  <article v-for="item in projectDocumentKnowledgeBases" :key="item.id">
                    <strong :title="item.name">{{ item.name }}</strong><span>{{ item.folderCount }} 个</span><span>{{ item.totalDocumentCount }} 份</span>
                  </article>
                </div>
              </section>
              <section class="project-status-document-block">
                <header><h3>最近新增资料</h3><span>最近 {{ projectDocumentRecentFiles.length }} 份</span></header>
                <div v-if="projectDocumentRecentFiles.length" class="project-status-document-recent">
                  <article v-for="item in projectDocumentRecentFiles" :key="`${item.knowledgeBaseId}:${item.id}`">
                    <div>
                      <strong :title="item.name">{{ item.name }}</strong>
                      <small :title="`${item.knowledgeBaseName} / ${item.folderPath || '资料库根目录'}`">{{ projectDocumentTypeLabel(item.fileType, item.name) }} · {{ projectDocumentFileSizeLabel(item.fileSize) }} · {{ projectDocumentFolderLabel(item.folderPath) }}</small>
                    </div>
                    <time>{{ projectDateLabel(item.createdAt) || '日期未记录' }}</time>
                  </article>
                </div>
                <div v-else class="project-status-document-recent-empty">暂无可展示的最近新增资料</div>
              </section>
            </div>
            <div v-else class="project-status-v2-empty"><strong>尚无可汇总的资料目录</strong><p>{{ projectDocumentSummary.emptyHint }}</p><router-link to="/docs">前往工程资料</router-link></div>
          </article>
        </section>

        <section v-else class="project-status-v2-stack">
          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>项目基础信息</span><h2>已维护字段</h2><p>项目名称已在右上角项目选择器展示，此处不再重复。</p></div>
              <router-link class="project-status-v2-link" to="/settings">编辑项目信息 <ChevronRight :size="15" /></router-link>
            </header>
            <dl class="project-status-base-grid"><div v-for="item in projectBaseInfoRows" :key="item.label"><dt>{{ item.label }}</dt><dd :class="{ missing: !item.present }">{{ item.value }}</dd></div></dl>
          </article>

          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>项目成员</span><h2>成员与岗位</h2><p>汇总工程配置中已加入当前项目的成员。</p></div>
              <router-link class="project-status-v2-link" to="/settings">维护成员 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusMemberRows.length" class="project-status-v2-table project-status-member-table">
              <div class="project-status-v2-table-head"><span>成员</span><span>岗位</span><span>职责</span></div>
              <article v-for="member in projectStatusMemberRows" :key="member.id"><strong>{{ member.name }}</strong><span>{{ member.title || '未配置岗位' }}</span><span>{{ member.role.join('、') || '未填写职责' }}</span></article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>尚未配置项目成员</strong><p>项目成员及岗位配置后会自动汇总到这里。</p><router-link to="/settings">前往工程配置</router-link></div>
          </article>
        </section>
      </main>
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
import { computed, nextTick, onMounted, ref, shallowRef, watch, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { NIcon, useMessage } from 'naive-ui'
import {
  AlertCircle, At, CalendarEvent, ChartBar, ChevronDown,
  ChevronLeft, ChevronRight, ChevronUp, CircleCheck, Clock, FileText, Folder,
  ListCheck, MapPin, Notes, Paperclip, Pin, PlayerStop, Plus, Repeat, Robot, Search,
  Send, Settings, Table, Trash, User, UserPlus,
} from '@vicons/tabler'
import { useAppStore, type AttachmentRecord } from '@/stores/app'
import api, { type ApiEnvelope } from '@/api/client'
import {
  streamAgentConversationConfirmation,
  streamAgentConversationMessage,
} from '@/api/agentStream'
import {
  listProjectChatAgents,
  listProjectChatChannels,
  listProjectChatMembers,
  type ProjectChatAgent,
  type ProjectChatChannel,
  type ProjectChatMember,
} from '@/api/projectChat'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import ProjectGroupChat from '@/components/chat/ProjectGroupChat.vue'
import {
  applyAgentRuntimeEvents,
  createEmptyRuntimeTrace,
  runtimeTraceFromExtraData,
  type AgentRuntimeTrace,
  type AgentToolCallBlock,
  type ApiAgentMessage,
} from '@/types/agentRuntime'
import type { DraftStatus, FillStatus, Member, QualityMetric, RiskLevel, Task, TaskStatus } from '@/types'

type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  generatedTaskIds?: string[]
  attachments?: ChatAttachment[]
  runtimeTrace?: AgentRuntimeTrace | null
}

type ChatAttachment = {
  id: string
  name: string
  size: number
  type: string
}

type ApiAgentConversation = {
  id: number
  project_id: number
  agent_id: string
  agent_name: string
  conversation_type: 'general' | 'business'
  title: string
  status: string
  created_at: string
  updated_at: string
}
type TaskNodeType = 'manual' | 'project_chat_message'
type TaskMessageMentionMode = 'none' | 'all' | 'users'
type TaskFlowStepDraft = {
  id: string
  name: string
  node_type: TaskNodeType
  owner_user_id: string
  due_at: string
  material: string
  sender_agent_id: string
  target_channel_id: number | null
  mention_mode: TaskMessageMentionMode
  mentioned_user_ids: number[]
  message_content: string
}
type TriggerIntervalUnit = 'minute' | 'hour' | 'day' | 'week' | 'month'
type TaskRunMode = 'immediate' | 'once' | 'recurring' | 'calendar'
type TriggerEndMode = 'never' | 'until' | 'count'
type TriggerCalendarMode = 'daily' | 'weekdays' | 'weekly' | 'monthly'
type TaskSchedule = {
  id: string
  flow_id: string
  title: string
  status: string
  active: boolean
  paused: boolean
  trigger_description: string
  next_fire_at: string | null
  last_fire_at: string | null
  fire_count: number
  last_error: string
  execution_kind: 'responsibility' | 'automation'
  action?: { type?: string; mention_mode?: string; content?: string } | null
}
type GeneratedTaskFlow = {
  title: string
  task_type: Task['type']
  risk_level: RiskLevel
  assignee_user_id?: number | null
  confirmer_user_id?: number | null
  wbs_item_id?: number | null
  risk_source_id?: number | null
  run_mode: 'single' | 'scheduled' | TaskRunMode
  trigger_date: string
  trigger_time: string
  trigger_rule: string
  trigger_interval_value: number
  trigger_interval_unit: TriggerIntervalUnit
  cc: string
  steps: Array<{
    name: string
    node_type?: TaskNodeType
    owner_user_id?: number | null
    due_at?: string | null
    material?: string
    action?: {
      type: 'project_chat_message'
      channel_id: number
      sender_agent_id: string
      sender_agent_name?: string
      mention_mode: TaskMessageMentionMode
      mentioned_user_ids: number[]
      content: string
    }
  }>
  generated_by: 'ai' | 'rules'
  generation_note: string
}

type ProjectStatusTab = 'progress' | 'riskQuality' | 'documents' | 'overview'

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
const currentUserId = computed(() => sessionStorage.getItem('current_user_id') || store.members[0]?.id || '')
const focusTasks = computed(() => store.tasks.filter(task => ['overdue', 'pending', 'processing', 'waiting_confirm'].includes(task.status)))
const projectStatusTab = ref<ProjectStatusTab>('progress')
const projectStatusTabs: Array<{ key: ProjectStatusTab; label: string; hint: string }> = [
  { key: 'progress', label: '进度与任务', hint: 'WBS 与责任任务' },
  { key: 'riskQuality', label: '风险与质量', hint: '风险源与质量要求' },
  { key: 'documents', label: '工程资料', hint: '目录与最近资料' },
  { key: 'overview', label: '项目概况', hint: '基础信息与成员' },
]
const projectResponsibilityTasks = computed(() => {
  const rank: Record<TaskStatus, number> = { overdue: 0, need_more_info: 1, pending: 2, processing: 3, waiting_confirm: 4, done: 5, cancelled: 6 }
  return store.tasks
    .filter(task => task.type !== 'automation' && !['done', 'cancelled'].includes(task.status))
    .slice()
    .sort((left, right) => (rank[left.status] ?? 9) - (rank[right.status] ?? 9) || (left.deadline || '9999').localeCompare(right.deadline || '9999'))
})
const projectStatusTaskPreview = computed(() => projectResponsibilityTasks.value.slice(0, 2))
const projectTaskCounts = computed(() => {
  const overview = store.projectStatusOverview?.tasks
  const counts = overview || {
    total: projectResponsibilityTasks.value.length,
    pending: projectResponsibilityTasks.value.filter(task => ['pending', 'need_more_info'].includes(task.status)).length,
    processing: projectResponsibilityTasks.value.filter(task => task.status === 'processing').length,
    waitingConfirm: projectResponsibilityTasks.value.filter(task => task.status === 'waiting_confirm').length,
    overdue: projectResponsibilityTasks.value.filter(task => task.status === 'overdue').length,
  }
  return [
    { label: '待处理', value: counts.pending, tone: 'pending' },
    { label: '进行中', value: counts.processing, tone: 'processing' },
    { label: '待确认', value: counts.waitingConfirm, tone: 'waiting' },
    { label: '已逾期', value: counts.overdue, tone: counts.overdue ? 'overdue' : 'quiet' },
  ]
})
const projectStatusWbsRows = computed(() => store.wbsItems.slice().sort((left, right) => left.code.localeCompare(right.code, 'zh-CN')).slice(0, 8))
const projectStatusWbsTotal = computed(() => store.projectStatusOverview?.wbs.totalItems ?? store.wbsItems.length)
const projectStatusRiskRows = computed(() => store.riskSources.slice().sort((left, right) => (left.serialNo || 0) - (right.serialNo || 0)).slice(0, 8))
const projectStatusQualityRows = computed(() => store.qualityMetrics.slice(0, 8))
const projectStatusMemberRows = computed(() => store.members.slice(0, 10))

const projectDocumentSummary = computed(() => {
  const documents = store.projectStatusOverview?.documents
  if (!documents) return { caption: '正在读取工程资料汇总。', emptyHint: '资料目录数据正在加载。', totalFiles: '—', folderCount: '—', knowledgeBaseCount: '—' }
  return {
    caption: '汇总工程资料页中的资料库、目录和最近新增文件。',
    emptyHint: '工程资料页当前还没有可汇总的资料库。',
    totalFiles: documents.totalFiles,
    folderCount: documents.folderCount,
    knowledgeBaseCount: documents.knowledgeBaseCount,
  }
})
const projectDocumentKnowledgeBases = computed(() => store.projectStatusOverview?.documents.knowledgeBases || [])
const projectDocumentRecentFiles = computed(() => store.projectStatusOverview?.documents.recentFiles || [])
const projectBaseInfoRows = computed(() => {
  const project = currentProject.value
  const amount = project?.contractAmountWanYuan
  const duration = project?.contractDurationDays
  return [
    projectBaseInfoRow('工程类型', project?.engineeringTypeDescription),
    projectBaseInfoRow('合同开工日期', projectDateLabel(project?.contractStartDate)),
    projectBaseInfoRow('合同竣工日期', projectDateLabel(project?.contractEndDate)),
    projectBaseInfoRow('合同工期', duration == null ? '' : `${duration} 天`),
    projectBaseInfoRow('合同金额', amount == null ? '' : `${amount.toLocaleString('zh-CN')} 万元`),
    projectBaseInfoRow('建设单位', project?.constructionUnitName),
    projectBaseInfoRow('施工总承包单位', project?.generalContractorUnitName),
    projectBaseInfoRow('监理单位', project?.supervisionUnitName),
    projectBaseInfoRow('设计单位', project?.designUnitName),
    projectBaseInfoRow('勘察单位', project?.surveyUnitName),
  ]
})
const projectStatusMetrics = computed(() => {
  const overview = store.projectStatusOverview
  const documents = projectDocumentSummary.value
  const wbsValue = !overview ? '—' : overview.wbs.configured && overview.wbs.progressRate != null ? `${overview.wbs.progressRate}%` : '未配置'
  const riskValue = !overview ? '—' : overview.risks.configured ? overview.risks.highLevelCount : '未维护'
  return [
    { label: '基础信息', value: overview ? `${overview.baseInfo.completedFields} / ${overview.baseInfo.totalFields}` : '—', hint: '已录入字段', icon: FileText, tone: 'teal' },
    { label: '工序进度', value: wbsValue, hint: '叶子工序平均', icon: ChartBar, tone: 'teal' },
    { label: '项目任务', value: overview?.tasks.total ?? projectResponsibilityTasks.value.length, hint: '责任任务', icon: ListCheck, tone: 'teal' },
    { label: '高等级风险源', value: riskValue, hint: '重大级、高风险', icon: AlertCircle, tone: 'orange' },
    { label: '工程资料', value: documents.totalFiles, hint: '目录内文件', icon: Folder, tone: 'teal' },
  ]
})

const myAttentionTasks = computed(() =>
  focusTasks.value.filter(task =>
    task.responsibleId === currentUserId.value ||
    task.confirmatorId === currentUserId.value ||
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
  { key: 'work' as const, label: 'Dobby推推' },
  { key: 'quick' as const, label: '问问Dobby' },
]
type WorkQueueStatus = 'pending' | 'overdue' | 'processing'
type WorkQueueCategory = 'decision' | 'upload' | 'generated'
type WorkQueueTone = 'danger' | 'upload' | 'warning' | 'info'
type HomeWorkItem = {
  id: string
  rank: number
  workflowStatus: WorkQueueStatus
  category: WorkQueueCategory
  label: string
  title: string
  reason: string
  tags: string[]
  owner: string
  role: string
  deadline: string
  action: string
  to: string
  tone: WorkQueueTone
  icon: Component
}

const homeStatus = ref<WorkQueueStatus>('pending')
const homePageIndex = ref(0)
const homePageSize = 5
const homeWorkThreadViewport = ref<HTMLElement | null>(null)
const selectedHomeWorkItemId = ref('')
const homeWorkCommand = ref('')
const homeWorkFiles = ref<File[]>([])
const homeWorkUploading = ref(false)
const quickFiles = ref<File[]>([])
const quickUploading = ref(false)
const homeWorkThreads = ref<Record<string, ChatMessage[]>>({})

function workQueueStatus(task: Task): WorkQueueStatus {
  if (task.status === 'overdue') return 'overdue'
  if (task.status === 'processing') return 'processing'
  return 'pending'
}

function workQueueCategory(task: Task): WorkQueueCategory {
  if (task.status === 'need_more_info' || task.type === 'material_missing') return 'upload'
  if (task.status === 'processing' || task.type === 'fill_platform') return 'generated'
  return 'decision'
}

function workQueueLabel(task: Task) {
  if (task.status === 'need_more_info') return '需补充资料'
  if (task.status === 'waiting_confirm') return '待我验收'
  if (task.status === 'overdue') return '已逾期'
  if (task.status === 'processing') return '执行中'
  return '待处理'
}

function workQueueDeadline(value: string) {
  if (!value) return '未设置截止时间'
  if (!value.includes(':')) return `截止 ${formatDateTime(value, 'end')}`
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return `截止 ${value.replace('T', ' ')}`
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `截止 ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function workQueueTags(task: Task) {
  const tags = [taskTypeLabel(task.type), `风险等级 ${riskLabel(task.riskLevel)}`]
  tags.push(...task.linkedWbsIds.map(id => `工点 ${store.getWbsName(id)}`))
  if (task.linkedRiskId) tags.push(`风险 ${store.getRiskName(task.linkedRiskId)}`)
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  if (currentStep?.material) tags.push(`交付 ${currentStep.material}`)
  return Array.from(new Set(tags.filter(Boolean))).slice(0, 4)
}

function isCurrentUserTask(task: Task) {
  if (['done', 'cancelled'].includes(task.status) || !currentUserId.value) return false
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  return task.responsibleId === currentUserId.value
    || currentStep?.owner_user_id === currentUserId.value
    || (task.status === 'waiting_confirm' && task.confirmatorId === currentUserId.value)
}

const homeWorkItems = computed<HomeWorkItem[]>(() => {
  const statusRank: Record<TaskStatus, number> = {
    overdue: 0,
    waiting_confirm: 1,
    need_more_info: 2,
    pending: 3,
    processing: 4,
    done: 5,
    cancelled: 6,
  }
  return store.tasks
    .filter(isCurrentUserTask)
    .slice()
    .sort((left, right) => statusRank[left.status] - statusRank[right.status] || (left.deadline || '9999').localeCompare(right.deadline || '9999'))
    .map((task, index) => {
      const currentStep = task.workflowSteps.find(step => step.status !== 'completed') ?? task.workflowSteps[task.workflowSteps.length - 1]
      const confirmationTask = task.status === 'waiting_confirm'
      const ownerId = confirmationTask ? task.confirmatorId : currentStep?.owner_user_id || task.responsibleId
      const category = workQueueCategory(task)
      const reason = task.triggerReason.trim()
      return {
        id: task.id,
        rank: index + 1,
        workflowStatus: workQueueStatus(task),
        category,
        label: workQueueLabel(task),
        title: task.title,
        reason: reason ? (/^(原因|结果)：/.test(reason) ? reason : `原因：${reason}`) : '原因：由任务引擎生成，等待当前责任节点处理。',
        tags: workQueueTags(task),
        owner: confirmationTask ? store.getMemberName(ownerId) : currentStep?.owner || store.getMemberName(ownerId),
        role: confirmationTask ? '任务验收人' : currentStep?.name || '当前责任节点',
        deadline: workQueueDeadline(task.deadline),
        action: task.status === 'need_more_info' ? '补充资料' : confirmationTask ? '验收确认' : task.status === 'processing' ? '继续处理' : '开始处理',
        to: '/tasks',
        tone: task.status === 'overdue' ? 'danger' : category === 'upload' ? 'upload' : task.status === 'processing' ? 'warning' : 'info',
        icon: category === 'upload' ? Folder : confirmationTask ? Notes : task.status === 'processing' ? FileText : ListCheck,
      }
    })
})
const filteredHomeWorkItems = computed(() => homeWorkItems.value.filter(item => item.workflowStatus === homeStatus.value))
const homePageCount = computed(() =>
  Math.max(1, Math.ceil(filteredHomeWorkItems.value.length / homePageSize))
)
const pagedHomeWorkItems = computed(() => {
  const start = homePageIndex.value * homePageSize
  return filteredHomeWorkItems.value.slice(start, start + homePageSize)
})
const selectedHomeWorkItem = computed(() =>
  pagedHomeWorkItems.value.find(item => item.id === selectedHomeWorkItemId.value)
  ?? pagedHomeWorkItems.value[0]
  ?? null
)
const selectedHomeWorkRank = computed(() => Math.max(1, filteredHomeWorkItems.value.findIndex(item => item.id === selectedHomeWorkItemId.value) + 1))
const homeWorkAssistantIntro = computed(() => {
  const item = selectedHomeWorkItem.value
  if (!item) return ''
  const reason = item.reason.replace(/^(原因|结果)：/, '')
  const statusText = homeStatus.value === 'overdue' ? '已逾期工作' : homeStatus.value === 'processing' ? '执行中工作' : '待处理工作'
  return `我已把“${item.title}”列为第 ${selectedHomeWorkRank.value} 项${statusText}。${reason} 当前涉及${item.owner}（${item.role}），你可以直接让我核对依据、整理协同内容或继续推进。`
})
const homeWorkConversationMessages = computed<ChatMessage[]>(() => {
  const item = selectedHomeWorkItem.value
  if (!item) return []
  return [
    { id: `${item.id}-intro`, role: 'assistant', content: homeWorkAssistantIntro.value },
    ...(homeWorkThreads.value[item.id] ?? []),
  ]
})
const homeWorkSuggestions = computed(() => {
  const item = selectedHomeWorkItem.value
  if (!item) return []
  if (item.category === 'upload') {
    return ['列出还缺哪些资料', '生成资料催办消息', '判断对后续流程的影响']
  }
  if (item.category === 'generated') {
    return ['说明 AI 生成依据', '拆解下一步协同动作', '生成给责任人的消息']
  }
  return ['整理需要确认的关键结论', '检查关联资料是否齐全', '生成协同处理说明']
})
const homePageRangeText = computed(() => {
  const total = filteredHomeWorkItems.value.length
  if (!total) return '0 / 0'
  const start = homePageIndex.value * homePageSize + 1
  const end = Math.min(start + homePageSize - 1, total)
  return `第 ${start}-${end} 项，共 ${total} 项`
})
const homeStatusTabs = computed(() => [
  { key: 'pending' as const, label: '待处理', count: homeWorkItems.value.filter(item => item.workflowStatus === 'pending').length },
  { key: 'overdue' as const, label: '已逾期', count: homeWorkItems.value.filter(item => item.workflowStatus === 'overdue').length },
  { key: 'processing' as const, label: '执行中', count: homeWorkItems.value.filter(item => item.workflowStatus === 'processing').length },
])
const homeEmptyText = computed(() => ({
  pending: '当前没有需要立即处理的任务',
  overdue: '当前没有已逾期任务',
  processing: '当前没有执行中的任务',
})[homeStatus.value])
function clampHomePageIndex() {
  homePageIndex.value = Math.min(homePageIndex.value, homePageCount.value - 1)
}

function goHomePage(direction: number) {
  homePageIndex.value = Math.min(Math.max(homePageIndex.value + direction, 0), homePageCount.value - 1)
}

const composerFileLimit = 8
const composerFileSizeLimit = 50 * 1024 * 1024

function selectComposerFiles(mode: 'work' | 'quick' | 'task', event: Event) {
  const input = event.target as HTMLInputElement
  const target = mode === 'work' ? homeWorkFiles : mode === 'quick' ? quickFiles : taskMineFiles
  const selected = Array.from(input.files || [])
  const rejected = selected.filter(file => file.size > composerFileSizeLimit)
  const accepted = selected.filter(file => file.size <= composerFileSizeLimit)
  const merged = [...target.value, ...accepted].filter((file, index, files) =>
    files.findIndex(candidate => candidate.name === file.name && candidate.size === file.size && candidate.lastModified === file.lastModified) === index
  )
  target.value = merged.slice(0, composerFileLimit)
  input.value = ''
  if (rejected.length) message.warning(`有 ${rejected.length} 个文件超过 50 MB，未加入发送列表。`)
  if (merged.length > composerFileLimit) message.warning(`单次最多发送 ${composerFileLimit} 个附件。`)
}

function removeComposerFile(mode: 'work' | 'quick' | 'task', index: number) {
  const target = mode === 'work' ? homeWorkFiles : mode === 'quick' ? quickFiles : taskMineFiles
  target.value = target.value.filter((_, fileIndex) => fileIndex !== index)
}

function createChatAttachments(files: File[]): ChatAttachment[] {
  return files.map(file => ({
    id: `${file.name}-${file.size}-${file.lastModified}`,
    name: file.name,
    size: file.size,
    type: file.type || 'application/octet-stream',
  }))
}

async function uploadComposerFiles(files: File[], category: string) {
  for (const file of files) await store.uploadAttachment(file, category)
}

function buildHomeWorkReply(content: string, attachments: ChatAttachment[] = []) {
  const item = selectedHomeWorkItem.value
  if (!item) return ''
  const attachmentLead = attachments.length
    ? `已收到 ${attachments.length} 个附件（${attachments.map(file => file.name).join('、')}），并归入当前项目资料库。`
    : ''
  if (/资料|依据|附件/.test(content)) {
    return `${attachmentLead}已围绕“${item.title}”整理关联信息：${item.tags.join('、')}。建议先核对关键资料是否完整，再决定是否进入${item.action}。`
  }
  if (/协同|责任人|消息/.test(content)) {
    return `${attachmentLead}建议由${item.owner}继续负责当前事项，我可以根据“${item.title}”生成协同说明，并把截止要求同步给相关人员。`
  }
  if (/影响|流程|顺序/.test(content)) {
    return `${attachmentLead}这项工作当前排在第 ${selectedHomeWorkRank.value} 位。主要影响是：${item.reason.replace(/^原因：/, '')}处理完成后再推进后续任务，可以减少重复确认。`
  }
  return `${attachmentLead}我已结合“${item.title}”的当前状态记录你的要求：${content}。下一步可以继续补充依据，或直接进入${item.action}。`
}

async function dispatchHomeWorkCommand() {
  const item = selectedHomeWorkItem.value
  const files = [...homeWorkFiles.value]
  const content = homeWorkCommand.value.trim() || (files.length ? '请识别并分析我上传的资料' : '')
  if (!item || !content || homeWorkUploading.value) return
  homeWorkUploading.value = true
  try {
    if (files.length) await uploadComposerFiles(files, 'Dobby工作附件')
    const attachments = createChatAttachments(files)
    const messages = [...(homeWorkThreads.value[item.id] ?? [])]
    const timestamp = Date.now()
    messages.push({ id: `${item.id}-user-${timestamp}`, role: 'user', content, attachments: attachments.length ? attachments : undefined })
    messages.push({ id: `${item.id}-assistant-${timestamp + 1}`, role: 'assistant', content: buildHomeWorkReply(content, attachments) })
    homeWorkThreads.value = { ...homeWorkThreads.value, [item.id]: messages }
    homeWorkCommand.value = ''
    homeWorkFiles.value = []
    await nextTick()
    const viewport = homeWorkThreadViewport.value
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  } catch {
    message.error('附件上传失败，请检查文件或网络后重试。')
  } finally {
    homeWorkUploading.value = false
  }
}

function dispatchHomeWorkSuggestion(content: string) {
  homeWorkCommand.value = content
  dispatchHomeWorkCommand()
}

watch(homeStatus, () => {
  homePageIndex.value = 0
})

watch(pagedHomeWorkItems, items => {
  if (!items.some(item => item.id === selectedHomeWorkItemId.value)) {
    selectedHomeWorkItemId.value = items[0]?.id ?? ''
  }
}, { immediate: true })

watch(homePageCount, clampHomePageIndex)

watch(selectedHomeWorkItemId, () => {
  homeWorkFiles.value = []
})

onMounted(() => {
  void loadHomeAgentConversation()
})
watch(() => store.currentProjectId, () => {
  void loadHomeAgentConversation()
})
watch(section, currentSection => {
  if (currentSection === 'home') {
    void loadHomeAgentConversation()
  }
})

const quickCommand = ref('')
async function dispatchQuickCommand() {
  const files = [...quickFiles.value]
  const content = quickCommand.value.trim() || (files.length ? '请识别并分析我上传的资料' : '')
  if (!content || quickUploading.value) return
  quickUploading.value = true
  try {
    if (files.length) await uploadComposerFiles(files, 'Dobby问答附件')
    const attachments = createChatAttachments(files)
    const optimisticUser: ChatMessage = {
      id: `hq-u-${Date.now()}`,
      role: 'user',
      content,
      attachments: attachments.length ? attachments : undefined,
    }
    homeQuickChatMessages.value = [...homeQuickChatMessages.value, optimisticUser]
    const conversation = await ensureHomeAgentConversation()
    homeQuickStreamingTrace.value = createEmptyRuntimeTrace()
    quickCommand.value = ''
    quickFiles.value = []
    const completion: {
      message: ApiAgentMessage | null
      runtimeStatus: string
    } = { message: null, runtimeStatus: 'running' }
    await streamAgentConversationMessage(conversation.id, content, {
      onEvents: async runtimeEvents => {
        homeQuickStreamingTrace.value = applyAgentRuntimeEvents(
          homeQuickStreamingTrace.value,
          runtimeEvents,
        )
        await nextTick()
        scrollHomeQuick()
      },
      onDone: payload => {
        completion.message = payload.message
        completion.runtimeStatus = payload.runtime_status
      },
    })
    if (!completion.message) {
      throw new Error('AgentScope 已结束事件流，但没有返回最终消息。')
    }
    homeQuickChatMessages.value = [
      ...homeQuickChatMessages.value,
      mapAgentMessage(completion.message),
    ]
    homeQuickStreamingTrace.value = null
    homeAgentConversation.value = {
      ...conversation,
      status: completion.runtimeStatus,
      updated_at: nowStr(),
    }
    store.addLog({
      id: `log${Date.now()}`,
      time: nowStr(),
      operator: '张伟',
      action: files.length ? '资料问答' : '任务下发',
      detail: files.length ? `${content}；附件：${files.map(file => file.name).join('、')}` : content,
      level: 'info',
    })
    await nextTick()
    scrollHomeQuick(true)
  } catch (error: any) {
    homeQuickStreamingTrace.value = null
    if (homeAgentConversation.value) {
      homeAgentConversation.value = {
        ...homeAgentConversation.value,
        status: 'error',
        updated_at: nowStr(),
      }
    }
    message.error(error?.response?.data?.detail || error?.message || '主智能体处理失败，请检查 AgentScope 配置后重试。')
  } finally {
    quickUploading.value = false
  }
}

function scrollHomeQuick(smooth = false) {
  const viewport = homeQuickViewport.value
  if (!viewport) return
  viewport.scrollTo({
    top: viewport.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto',
  })
}

async function stopHomeAgent() {
  if (!homeAgentConversation.value) return
  try {
    await api.post(`/agent-conversations/${homeAgentConversation.value.id}/interrupt`)
    message.info('已请求停止，正在等待智能体安全结束当前步骤。')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '停止主智能体失败。')
  }
}

async function confirmHomeToolCall(
  replyId: string,
  toolCall: AgentToolCallBlock,
  confirmed: boolean,
) {
  const conversation = homeAgentConversation.value
  if (!conversation || quickUploading.value) return
  quickUploading.value = true
  homeQuickStreamingTrace.value = createEmptyRuntimeTrace()
  try {
    await streamAgentConversationConfirmation(
      conversation.id,
      {
        reply_id: replyId,
        tool_call: toolCall,
        confirmed,
      },
      {
        onAccepted: payload => {
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
          homeQuickStreamingTrace.value = applyAgentRuntimeEvents(
            homeQuickStreamingTrace.value,
            runtimeEvents,
          )
          await nextTick()
          scrollHomeQuick()
        },
      },
    )
    await loadHomeAgentConversation()
  } catch (error: any) {
    message.error(
      error?.response?.data?.detail
      || error?.message
      || '提交人工确认失败。',
    )
  } finally {
    homeQuickStreamingTrace.value = null
    quickUploading.value = false
  }
}

const homeAgentConversation = ref<ApiAgentConversation | null>(null)
const homeQuickChatMessages = ref<ChatMessage[]>([])
const homeQuickStreamingTrace = shallowRef<AgentRuntimeTrace | null>(null)
const homeQuickViewport = ref<HTMLElement | null>(null)
const homeQuickSession = computed(() => homeAgentConversation.value)
const homeQuickSessionTitle = computed(() => homeQuickSession.value?.title ?? '')
const homeQuickSessionTime = computed(
  () => homeQuickSession.value?.updated_at ?? homeQuickSession.value?.created_at ?? '',
)
const homeQuickAgentName = computed(
  () => homeQuickSession.value?.agent_name || '平台主智能体',
)

function mapAgentMessage(row: ApiAgentMessage): ChatMessage {
  return {
    id: String(row.id),
    role: row.role,
    content: row.content,
    runtimeTrace: runtimeTraceFromExtraData(row.extra_data),
  }
}

async function loadHomeAgentConversation() {
  homeAgentConversation.value = null
  homeQuickChatMessages.value = []
  homeQuickStreamingTrace.value = null
  if (!store.currentProjectId) return
  try {
    const response = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
      `/projects/${store.currentProjectId}/agent-conversations`,
      { params: { conversation_type: 'general' } },
    )
    const conversation = response.data.data[0]
    if (!conversation) return
    homeAgentConversation.value = conversation
    const messagesResponse = await api.get<ApiEnvelope<ApiAgentMessage[]>>(
      `/agent-conversations/${conversation.id}/messages`,
    )
    homeQuickChatMessages.value = messagesResponse.data.data.map(mapAgentMessage)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '加载主智能体会话失败。')
  }
}

async function ensureHomeAgentConversation() {
  if (homeAgentConversation.value) return homeAgentConversation.value
  if (!store.currentProjectId) throw new Error('请先选择项目')
  const response = await api.post<ApiEnvelope<ApiAgentConversation>>(
    `/projects/${store.currentProjectId}/agent-conversations`,
    { conversation_type: 'general' },
  )
  homeAgentConversation.value = response.data.data
  return response.data.data
}

type TaskManagementTab = 'mine' | 'history' | 'schedules' | 'assign'

const taskManagementTab = ref<TaskManagementTab>('mine')
const taskMineStatus = ref<WorkQueueStatus>('pending')
const taskMinePageIndex = ref(0)
const taskMinePageSize = 5
const selectedTaskMineWorkItemId = ref('')
const taskMineThreadViewport = ref<HTMLElement | null>(null)
const taskMineCommand = ref('')
const taskMineFiles = ref<File[]>([])
const taskMineUploading = ref(false)
const taskMineThreads = ref<Record<string, ChatMessage[]>>({})
const selectedTaskId = ref('')
const taskDispositionOpen = ref(false)
const taskDispositionReply = ref('')
const taskDispositionForwardId = ref('')
const taskDispositionFiles = ref<File[]>([])
const taskDispositionSubmitting = ref(false)
const taskHistoryKeyword = ref('')
const taskHistoryStatus = ref<'all' | TaskStatus>('all')
const taskHistoryStart = ref('')
const taskHistoryEnd = ref('')
const taskHistoryOpenId = ref('')
type TaskHistoryEntry = { id: string | number; kind?: string; step_seq?: number | null; from_status?: string; to_status?: string; note?: string; created_at: string }
const taskHistories = ref<Record<string, TaskHistoryEntry[]>>({})
const taskHistoryLoading = ref(false)
const taskSchedules = ref<TaskSchedule[]>([])
const taskSchedulesLoading = ref(false)
const taskScheduleKeyword = ref('')
const taskScheduleStatus = ref<'all' | 'active' | 'paused' | 'ended' | 'cancelled'>('all')
const taskChatChannels = ref<ProjectChatChannel[]>([])
const taskChatAgents = ref<ProjectChatAgent[]>([])
const taskChatMembersByChannel = ref<Record<number, ProjectChatMember[]>>({})
const selectedTaskHistoryTask = computed(() => store.tasks.find(task => task.id === taskHistoryOpenId.value))
const taskCreateMode = ref<'dobby' | 'template'>('dobby')
const taskFlowAssistantOpen = ref(true)
const taskFlowRequirement = ref('')
const taskFlowGenerating = ref(false)
const taskFlowGenerationNote = ref('')
const taskTemplateOptions = ['条件核查', '隐患整改', '资料补全', '风险处置', '报告审核', '自定义'] as const
const taskTemplateType = ref<(typeof taskTemplateOptions)[number]>('隐患整改')
const taskTemplateTopic = ref('')
const selectedTaskFlowStepIndex = ref(-1)
const taskFlowExamples = ['每周核查基坑监测数据并完成复核归档', '发现临边防护缺失后发起整改并闭环', '补齐日报缺失资料并由资料员复核']
const taskCreateForm = ref({
  title: '',
  task_type: 'risk_alert' as Task['type'],
  run_mode: 'immediate' as TaskRunMode,
  trigger_date: todayDateString(),
  trigger_time: '09:00',
  trigger_interval_value: 1,
  trigger_interval_unit: 'week' as TriggerIntervalUnit,
  trigger_end_mode: 'never' as TriggerEndMode,
  trigger_until_date: todayDateString(30),
  trigger_max_fires: 4,
  trigger_calendar_mode: 'weekdays' as TriggerCalendarMode,
  trigger_weekdays: [1, 2, 3, 4, 5] as number[],
  trigger_day_of_month: 1,
  cc: '',
  wbs_item_id: '',
  confirmer_user_id: '',
})
const taskExecutionAt = computed({
  get: () => `${taskCreateForm.value.trigger_date}T${taskCreateForm.value.trigger_time}`,
  set: (value: string) => {
    const [triggerDate, triggerTime] = value.split('T')
    taskCreateForm.value.trigger_date = triggerDate || todayDateString()
    taskCreateForm.value.trigger_time = triggerTime || '09:00'
  },
})
const triggerIntervalUnitLabel = computed(() => ({ minute: '分钟', hour: '小时', day: '天', week: '周', month: '个月' })[taskCreateForm.value.trigger_interval_unit])
const calendarModeLabel = computed(() => {
  const form = taskCreateForm.value
  if (form.trigger_calendar_mode === 'daily') return '每天'
  if (form.trigger_calendar_mode === 'weekdays') return '每个工作日'
  if (form.trigger_calendar_mode === 'monthly') return `每月 ${form.trigger_day_of_month} 日`
  const names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  return `每周 ${form.trigger_weekdays.map(day => names[day - 1]).join('、') || '未选择'}`
})
const taskFlowSteps = ref<TaskFlowStepDraft[]>([])
const taskMessageSenderOptions = computed(() => {
  const options = [{ id: 'dobby-task-engine', name: 'Dobby（任务引擎）' }]
  for (const agent of taskChatAgents.value) {
    if (!agent.enabled || !agent.published || options.some(item => item.id === agent.id)) continue
    options.push({ id: agent.id, name: agent.name })
  }
  return options
})

function taskChatMembersForStep(step: TaskFlowStepDraft) {
  return step.target_channel_id
    ? taskChatMembersByChannel.value[step.target_channel_id] || []
    : []
}

function taskFlowStepSummary(step: TaskFlowStepDraft) {
  if (step.node_type === 'project_chat_message') {
    const sender = taskMessageSenderOptions.value.find(item => item.id === step.sender_agent_id)?.name || '未选择发送智能体'
    const channel = taskChatChannels.value.find(item => item.id === step.target_channel_id)?.title || '未选择群聊'
    const mention = step.mention_mode === 'all' ? '@全体成员' : step.mention_mode === 'users' ? `提醒 ${step.mentioned_user_ids.length} 人` : '普通消息'
    return `${sender} · ${channel} · ${mention}`
  }
  return `${memberNameById(step.owner_user_id)} · ${step.due_at || '未设置截止日期'} · ${step.material || '未设置交付物'}`
}
const taskTriggerSummary = computed(() => {
  const form = taskCreateForm.value
  if (form.run_mode === 'immediate') return '提交后立即创建任务并激活首个节点'
  if (form.run_mode === 'once') return `${form.trigger_date} ${form.trigger_time} 自动执行一次`
  const ending = form.trigger_end_mode === 'until'
    ? `，执行至 ${form.trigger_until_date}`
    : form.trigger_end_mode === 'count'
      ? `，共执行 ${form.trigger_max_fires} 次`
      : '，持续执行'
  if (form.run_mode === 'calendar') return `自 ${form.trigger_date} 起，${calendarModeLabel.value} ${form.trigger_time} 执行${ending}`
  return `${form.trigger_date} ${form.trigger_time} 首次执行，之后每 ${form.trigger_interval_value} ${triggerIntervalUnitLabel.value}执行一次${ending}`
})
const taskScheduleIsValid = computed(() => {
  const form = taskCreateForm.value
  if (form.run_mode === 'immediate') return true
  if (!form.trigger_date || !form.trigger_time) return false
  if (form.run_mode === 'once') return true
  if (form.run_mode === 'recurring' && (!Number.isFinite(form.trigger_interval_value) || form.trigger_interval_value < 1)) return false
  if (form.run_mode === 'calendar') {
    if (form.trigger_calendar_mode === 'weekly' && !form.trigger_weekdays.length) return false
    if (form.trigger_calendar_mode === 'monthly' && (!form.trigger_day_of_month || form.trigger_day_of_month < 1 || form.trigger_day_of_month > 31)) return false
  }
  if (form.trigger_end_mode === 'until') return !!form.trigger_until_date && form.trigger_until_date >= form.trigger_date
  if (form.trigger_end_mode === 'count') return Number.isFinite(form.trigger_max_fires) && form.trigger_max_fires >= 1
  return true
})
const taskFlowValidationItems = computed(() => {
  const form = taskCreateForm.value
  const manualSteps = taskFlowSteps.value.filter(step => step.node_type === 'manual')
  const messageSteps = taskFlowSteps.value.filter(step => step.node_type === 'project_chat_message')
  const namedSteps = taskFlowSteps.value.filter(step => step.name.trim()).length
  const assignedSteps = manualSteps.filter(step => step.owner_user_id).length
  const configuredMessageSteps = messageSteps.filter(step => (
    !!step.sender_agent_id
    && !!step.target_channel_id
    && !!step.message_content.trim()
    && (step.mention_mode !== 'users' || step.mentioned_user_ids.length > 0)
  )).length
  const items = [
    { key: 'title', label: '任务名称', ok: !!form.title.trim(), detail: form.title.trim() || '请填写任务名称' },
    { key: 'schedule', label: '执行计划', ok: taskScheduleIsValid.value, detail: taskScheduleIsValid.value ? taskTriggerSummary.value : '请补全有效的触发设置' },
    { key: 'steps', label: '流程节点', ok: taskFlowSteps.value.length >= 1 && namedSteps === taskFlowSteps.value.length, detail: `${namedSteps}/${taskFlowSteps.value.length} 个节点名称完整` },
  ]
  if (manualSteps.length) {
    items.splice(1, 0,
      { key: 'site', label: '关联工点', ok: !!form.wbs_item_id, detail: form.wbs_item_id ? store.getWbsName(form.wbs_item_id) : '含“人工处理”节点时必须选择具体工点' },
      { key: 'confirmer', label: '确认人', ok: !!form.confirmer_user_id, detail: form.confirmer_user_id ? memberNameById(form.confirmer_user_id) : '含“人工处理”节点时必须选择确认人' },
    )
    items.push({ key: 'assignees', label: '人工节点负责人', ok: assignedSteps === manualSteps.length, detail: `${assignedSteps}/${manualSteps.length} 个人工节点已落到具体人员` })
  }
  if (messageSteps.length) {
    items.push({ key: 'actions', label: '自动消息节点', ok: configuredMessageSteps === messageSteps.length, detail: `${configuredMessageSteps}/${messageSteps.length} 个消息节点配置完整` })
  }
  return items
})
const taskFlowCanSubmit = computed(() => taskFlowValidationItems.value.every(item => item.ok))
const taskFlowMissingCount = computed(() => taskFlowValidationItems.value.filter(item => !item.ok).length)

async function loadTaskSchedules() {
  if (!store.currentProjectId) {
    taskSchedules.value = []
    return
  }
  taskSchedulesLoading.value = true
  try {
    const response = await api.get<ApiEnvelope<TaskSchedule[]>>(
      `/projects/${store.currentProjectId}/task-schedules`,
    )
    taskSchedules.value = response.data.data
  } catch (error: any) {
    message.error(error.response?.data?.detail || '计划列表加载失败。')
  } finally {
    taskSchedulesLoading.value = false
  }
}

async function loadTaskChatChannels() {
  if (!store.currentProjectId) {
    taskChatChannels.value = []
    taskChatMembersByChannel.value = {}
    return
  }
  try {
    taskChatChannels.value = await listProjectChatChannels(store.currentProjectId)
    for (const step of taskFlowSteps.value) {
      if (step.node_type !== 'project_chat_message') continue
      if (!taskChatChannels.value.some(channel => channel.id === step.target_channel_id)) {
        step.target_channel_id = taskChatChannels.value[0]?.id || null
      }
      if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
    }
  } catch (error: any) {
    message.error(error.response?.data?.detail || '项目群聊加载失败。')
  }
}

async function loadTaskChatMembers(channelId: number | null) {
  if (!channelId || taskChatMembersByChannel.value[channelId]) return
  try {
    taskChatMembersByChannel.value[channelId] = await listProjectChatMembers(channelId)
  } catch (error: any) {
    taskChatMembersByChannel.value[channelId] = []
    message.error(error.response?.data?.detail || '群聊成员加载失败。')
  }
}

async function loadTaskChatAgents() {
  try {
    taskChatAgents.value = await listProjectChatAgents()
  } catch (error: any) {
    taskChatAgents.value = []
    message.error(error.response?.data?.detail || '可用智能体加载失败。')
  }
}

async function loadTaskPlanningContext() {
  await Promise.all([loadTaskSchedules(), loadTaskChatChannels(), loadTaskChatAgents()])
}

async function setTaskSchedulePaused(schedule: TaskSchedule, paused: boolean) {
  try {
    await api.post(`/task-schedules/${schedule.id}/pause`, null, {
      params: { paused },
    })
    message.success(paused ? '执行计划已暂停。' : '执行计划已恢复。')
    await loadTaskSchedules()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '执行计划状态更新失败。')
  }
}

async function cancelTaskSchedule(schedule: TaskSchedule) {
  try {
    await api.delete(`/task-schedules/${schedule.id}`)
    message.success('执行计划已取消。')
    await loadTaskSchedules()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '执行计划取消失败。')
  }
}

function confirmCancelTaskSchedule(schedule: TaskSchedule) {
  if (!window.confirm(`确认取消执行计划“${schedule.title}”吗？取消后不会再次触发。`)) return
  void cancelTaskSchedule(schedule)
}

watch(taskManagementTab, tab => {
  if (tab === 'assign') void Promise.all([loadTaskChatChannels(), loadTaskChatAgents()])
  if (tab === 'schedules') void loadTaskSchedules()
  if (tab === 'mine' || tab === 'history') void store.loadProjectData()
})

watch(
  () => store.currentProjectId,
  () => {
    taskSchedules.value = []
    taskChatChannels.value = []
    taskChatAgents.value = []
    taskChatMembersByChannel.value = {}
    if (section.value === 'tasks') void loadTaskPlanningContext()
  },
)

watch(section, currentSection => {
  if (currentSection === 'tasks') void loadTaskPlanningContext()
})

onMounted(() => {
  if (section.value === 'tasks') void loadTaskPlanningContext()
})
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
const selectedTask = computed(() => store.tasks.find(task => task.id === selectedTaskId.value))
const canConfirmSelectedTask = computed(() => (
  selectedTask.value?.status === 'waiting_confirm'
  && selectedTask.value.confirmatorId === currentUserId.value
))
const selectedTaskCompletedSteps = computed(() => selectedTask.value?.workflowSteps.filter(step => step.status === 'completed').length ?? 0)
const needsFreshEvidence = computed(() => {
  const step = selectedTask.value?.workflowSteps.find(item => item.status === 'processing' && item.reopened)
  return !!step && !taskDispositionFiles.value.length
})

function taskCurrentStep(task: Task) {
  return task.workflowSteps.find(step => step.status !== 'completed') || task.workflowSteps[task.workflowSteps.length - 1]
}

function taskCurrentOwnerId(task: Task) {
  return taskCurrentStep(task)?.owner_user_id || task.responsibleId
}

function taskCurrentOwnerName(task: Task) {
  const step = taskCurrentStep(task)
  return step?.owner || store.getMemberName(step?.owner_user_id || task.responsibleId)
}

function taskLedgerOwner(task: Task) {
  const automatedStep = task.workflowSteps.find(step => step.node_type === 'project_chat_message')
  if (automatedStep?.action) {
    const name = automatedStep.action.sender_agent_name?.trim() || ''
    if (automatedStep.action.sender_agent_id === 'dobby-task-engine' || /^Dobby(?:\s*自动执行|\s*任务引擎|（任务引擎）)?$/.test(name) || (!name && task.type === 'automation')) {
      return 'Dobby（任务引擎）'
    }
    return name || '自动执行'
  }
  return taskCurrentOwnerName(task)
}

function taskHistoryTitle(item: TaskHistoryEntry) {
  if (item.from_status || item.to_status) {
    const from = item.from_status ? statusLabel(item.from_status) : ''
    const to = item.to_status ? statusLabel(item.to_status) : ''
    return [from, to].filter(Boolean).join(' → ') || '状态更新'
  }
  const kindTitle = ({
    created: '任务创建',
    fired: '计划触发',
    step_activated: '节点开始',
    step_done: '节点完成',
    step_skipped: '节点跳过',
    step_blocked: '节点受阻',
    forwarded: '任务转办',
    note_added: '添加备注',
    attachment_added: '上传附件',
    overdue_marked: '标记逾期',
    state_changed: '状态更新',
  } as Record<string, string>)[item.kind || '']
  if (kindTitle) return kindTitle
  const note = item.note || ''
  if (/^任务「.+」已创建/.test(note)) return '任务创建'
  if (/^节点「.+」开始/.test(note)) return '节点开始'
  if (/^节点「.+」已完成/.test(note)) return '节点完成'
  if (/^节点「.+」已跳过/.test(note)) return '节点跳过'
  if (/^节点「.+」受阻/.test(note)) return '节点受阻'
  return '处理记录'
}

function taskLedgerTypeLabel(task: Task) {
  const steps = task.workflowSteps || []
  return steps.length > 0 && steps.every(step => step.node_type === 'project_chat_message')
    ? '自动化动作'
    : taskTypeLabel(task.type)
}

function taskScheduleAction(schedule: TaskSchedule) {
  if (schedule.action) return schedule.action
  const execution = taskLedgerTasks.value.find(task => task.title === schedule.title)
  return execution?.workflowSteps.find(step => step.node_type === 'project_chat_message')?.action
}

function taskScheduleKindLabel(schedule: TaskSchedule) {
  return schedule.execution_kind === 'automation' || taskScheduleAction(schedule)
    ? '自动化动作'
    : '责任任务'
}

function taskScheduleActionDescription(schedule: TaskSchedule) {
  const action = taskScheduleAction(schedule)
  if (action?.type !== 'project_chat_message') return ''
  const mention = action.mention_mode === 'all'
    ? '@全体成员'
    : action.mention_mode === 'users' ? '指定成员' : '普通消息'
  return ` · 群聊消息 ${mention}`
}

function taskLedgerTimestamp(task: Task) {
  return task.closedAt || task.updatedAt || task.createdAt || task.deadline || ''
}

function taskLedgerDateKey(task: Task) {
  const value = taskLedgerTimestamp(task)
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value.slice(0, 10)
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const taskMineStatusTabs = computed(() => [
  { key: 'pending' as const, label: '待处理', count: homeWorkItems.value.filter(item => item.workflowStatus === 'pending').length },
  { key: 'overdue' as const, label: '已逾期', count: homeWorkItems.value.filter(item => item.workflowStatus === 'overdue').length },
  { key: 'processing' as const, label: '执行中', count: homeWorkItems.value.filter(item => item.workflowStatus === 'processing').length },
])
const filteredTaskMineWorkItems = computed(() => homeWorkItems.value.filter(item => item.workflowStatus === taskMineStatus.value))
const taskMinePageCount = computed(() => Math.max(1, Math.ceil(filteredTaskMineWorkItems.value.length / taskMinePageSize)))
const pagedTaskMineWorkItems = computed(() => {
  const start = taskMinePageIndex.value * taskMinePageSize
  return filteredTaskMineWorkItems.value.slice(start, start + taskMinePageSize)
})
const selectedTaskMineWorkItem = computed(() => pagedTaskMineWorkItems.value.find(item => item.id === selectedTaskMineWorkItemId.value) ?? pagedTaskMineWorkItems.value[0] ?? null)
const taskMinePageRangeText = computed(() => {
  const total = filteredTaskMineWorkItems.value.length
  if (!total) return '0 / 0'
  const start = taskMinePageIndex.value * taskMinePageSize + 1
  const end = Math.min(start + taskMinePageSize - 1, total)
  return `第 ${start}-${end} 项，共 ${total} 项`
})
const taskMineEmptyText = computed(() => ({
  pending: '当前没有需要立即处理的任务',
  overdue: '当前没有已逾期任务',
  processing: '当前没有执行中的任务',
})[taskMineStatus.value])
const taskLedgerTasks = computed(() => [...store.tasks].sort((left, right) => (
  Date.parse(taskLedgerTimestamp(right)) || 0
) - (
  Date.parse(taskLedgerTimestamp(left)) || 0
)))
const filteredHistoryTasks = computed(() => taskLedgerTasks.value.filter(task => {
  const keyword = taskHistoryKeyword.value.toLowerCase()
  const searchMatched = !keyword || `${task.title} ${task.triggerReason} ${taskLedgerTypeLabel(task)}`.toLowerCase().includes(keyword)
  const statusMatched = taskHistoryStatus.value === 'all' || task.status === taskHistoryStatus.value
  const date = taskLedgerDateKey(task)
  return searchMatched && statusMatched && (!taskHistoryStart.value || date >= taskHistoryStart.value) && (!taskHistoryEnd.value || date <= taskHistoryEnd.value)
}))
const filteredTaskSchedules = computed(() => taskSchedules.value.filter(schedule => {
  const keyword = taskScheduleKeyword.value.toLowerCase()
  const searchMatched = !keyword || `${schedule.title} ${schedule.trigger_description} ${taskScheduleAction(schedule)?.content || ''}`.toLowerCase().includes(keyword)
  const scheduleState = schedule.active
    ? schedule.paused ? 'paused' : 'active'
    : schedule.fire_count > 0 ? 'ended' : 'cancelled'
  return searchMatched && (taskScheduleStatus.value === 'all' || taskScheduleStatus.value === scheduleState)
}))
const taskManagementTabs = computed(() => [
  { key: 'mine' as const, label: '我的待办', hint: '当前轮到我处理的责任节点', count: homeWorkItems.value.length, icon: ListCheck },
  { key: 'history' as const, label: '执行记录', hint: '全部任务实例及其执行结果', count: taskLedgerTasks.value.length, icon: Notes },
  { key: 'schedules' as const, label: '计划列表', hint: '单次、间隔与日历触发规则', count: taskSchedules.value.length, icon: Clock },
  { key: 'assign' as const, label: '布置任务', hint: '通过 Dobby、模板或手工创建流程', count: 'AI', icon: Plus },
])
const selectedTaskConclusion = computed(() => {
  const task = selectedTask.value
  if (!task) return ''
  if (task.status === 'overdue') return `任务已超过截止时间，建议立即联系 ${store.getMemberName(task.responsibleId)}，确认新的完成时间，并先处理阻塞节点。`
  if (task.status === 'waiting_confirm') return '执行动作已经完成，当前只等待你的确认。建议先核对交付物和流程记录，再决定通过或退回。'
  if (task.status === 'need_more_info') return `当前流程被资料缺口阻断，还需要补齐 ${taskMaterialLabel(task)}。补充后可直接恢复原流程。`
  if (task.status === 'pending') return '任务尚未启动，但风险和截止时间都已进入关注窗口。现在启动可以避免后续节点集中等待。'
  if (task.status === 'processing') return '任务正在推进。建议先完成当前节点，再由 Dobby 生成下一责任人的推进消息。'
  if (task.status === 'done') return '任务节点和状态已经闭环。建议核对处理记录，确认相关资料已同步归档。'
  return '任务当前不需要继续推进，可在处理记录中核对原因。'
})

const taskMineConversationMessages = computed<ChatMessage[]>(() => {
  const item = selectedTaskMineWorkItem.value
  if (!item) return []
  const reason = item.reason.replace(/^(原因|结果)：/, '')
  const intro = `我正在跟进“${item.title}”。${reason} 当前涉及${item.owner}（${item.role}），你可以直接让我核对依据、整理协同内容或继续推进。`
  return [
    { id: `${item.id}-intro`, role: 'assistant', content: intro },
    ...(taskMineThreads.value[item.id] ?? []),
  ]
})

const taskMineSuggestions = computed(() => {
  const item = selectedTaskMineWorkItem.value
  if (!item) return []
  if (item.category === 'upload') return ['列出还缺哪些资料', '生成资料催办消息', '判断对后续流程的影响']
  if (item.category === 'generated') return ['说明 AI 生成依据', '拆解下一步协同动作', '生成给责任人的消息']
  return ['整理需要确认的关键结论', '检查关联资料是否齐全', '生成协同处理说明']
})

function buildTaskMineReply(content: string, attachments: ChatAttachment[] = []) {
  const item = selectedTaskMineWorkItem.value
  if (!item) return ''
  const attachmentLead = attachments.length
    ? `已收到 ${attachments.length} 个附件（${attachments.map(file => file.name).join('、')}），并归入当前项目资料库。`
    : ''
  if (/资料|依据|附件/.test(content)) return `${attachmentLead}已围绕“${item.title}”整理关联信息：${item.tags.join('、')}。建议先核对关键资料是否完整，再决定是否进入${item.action}。`
  if (/协同|责任人|消息/.test(content)) return `${attachmentLead}建议由${item.owner}继续负责当前事项，我可以根据“${item.title}”生成协同说明，并把截止要求同步给相关人员。`
  if (/影响|流程|顺序/.test(content)) return `${attachmentLead}主要影响是：${item.reason.replace(/^原因：/, '')}处理完成后再推进后续任务，可以减少重复确认。`
  return `${attachmentLead}我已结合“${item.title}”的当前状态记录你的要求：${content}。下一步可以继续补充依据，或直接进入${item.action}。`
}

async function dispatchTaskMineCommand() {
  const item = selectedTaskMineWorkItem.value
  const files = [...taskMineFiles.value]
  const content = taskMineCommand.value.trim() || (files.length ? '请识别并分析我上传的资料' : '')
  if (!item || !content || taskMineUploading.value) return
  taskMineUploading.value = true
  try {
    if (files.length) await uploadComposerFiles(files, 'Dobby工作附件')
    const attachments = createChatAttachments(files)
    const messages = [...(taskMineThreads.value[item.id] ?? [])]
    const timestamp = Date.now()
    messages.push({ id: `${item.id}-user-${timestamp}`, role: 'user', content, attachments: attachments.length ? attachments : undefined })
    messages.push({ id: `${item.id}-assistant-${timestamp + 1}`, role: 'assistant', content: buildTaskMineReply(content, attachments) })
    taskMineThreads.value = { ...taskMineThreads.value, [item.id]: messages }
    taskMineCommand.value = ''
    taskMineFiles.value = []
    await nextTick()
    const viewport = taskMineThreadViewport.value
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  } catch {
    message.error('附件上传失败，请检查文件或网络后重试。')
  } finally {
    taskMineUploading.value = false
  }
}

function dispatchTaskMineSuggestion(content: string) {
  taskMineCommand.value = content
  void dispatchTaskMineCommand()
}

function goTaskMinePage(direction: number) {
  taskMinePageIndex.value = Math.min(Math.max(taskMinePageIndex.value + direction, 0), taskMinePageCount.value - 1)
}

watch(taskMineStatus, () => {
  taskMinePageIndex.value = 0
})

watch(taskMinePageCount, count => {
  taskMinePageIndex.value = Math.min(taskMinePageIndex.value, count - 1)
})

watch(pagedTaskMineWorkItems, items => {
  if (!items.some(item => item.id === selectedTaskMineWorkItemId.value)) selectedTaskMineWorkItemId.value = items[0]?.id ?? ''
}, { immediate: true })

watch(selectedTaskMineWorkItemId, () => {
  taskMineFiles.value = []
})

function openTaskDisposition(taskId: string) {
  selectedTaskId.value = taskId
  taskDispositionReply.value = ''
  taskDispositionForwardId.value = ''
  taskDispositionFiles.value = []
  taskDispositionOpen.value = true
}

function closeTaskDisposition() {
  taskDispositionOpen.value = false
}

function handleTaskDispositionFiles(event: Event) {
  taskDispositionFiles.value = Array.from((event.target as HTMLInputElement).files || [])
}

async function submitTaskDisposition() {
  const task = selectedTask.value
  if (!task) return
  if (!taskDispositionReply.value && !taskDispositionForwardId.value && !taskDispositionFiles.value.length) {
    message.warning('请填写回复、选择材料或指定转交人。')
    return
  }
  taskDispositionSubmitting.value = true
  try {
    const attachmentRefs = taskDispositionFiles.value.map(file => file.name)
    for (const file of taskDispositionFiles.value) await store.uploadAttachment(file, '任务处置')
    let dispositionRecorded = false
    if (taskDispositionForwardId.value && taskDispositionForwardId.value !== taskCurrentOwnerId(task)) {
      await store.reassignTask(task.id, taskDispositionForwardId.value, taskDispositionReply.value || '转交当前任务节点')
      dispositionRecorded = true
    }
    if (!dispositionRecorded) {
      const currentStepIndex = task.workflowSteps.findIndex(step => step.status === 'processing' || step.status === 'blocked')
      const currentStepWasBlocked = currentStepIndex >= 0 && task.workflowSteps[currentStepIndex].status === 'blocked'
      if (currentStepWasBlocked) {
        await store.updateTaskStep(
          task.id,
          currentStepIndex,
          'processing',
          taskDispositionReply.value || '已补充材料，继续处理',
        )
        dispositionRecorded = true
      }
      if (currentStepIndex >= 0 && (!currentStepWasBlocked || attachmentRefs.length)) {
        await store.updateTaskStep(
          task.id,
          currentStepIndex,
          'completed',
          taskDispositionReply.value,
          attachmentRefs,
        )
        dispositionRecorded = true
      }
    }
    if (!dispositionRecorded) await store.addTaskNote(task.id, taskDispositionReply.value || `已提交 ${taskDispositionFiles.value.length} 个任务材料`)
    message.success('任务处置结果已记录。')
    closeTaskDisposition()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '任务处置提交失败，请稍后重试。')
  } finally {
    taskDispositionSubmitting.value = false
  }
}

async function acceptSelectedTask() {
  const task = selectedTask.value
  if (!task) return
  taskDispositionSubmitting.value = true
  try {
    await store.updateTaskStatus(
      task.id,
      'done',
      taskDispositionReply.value || '确认通过',
    )
    message.success('任务已通过验收。')
    closeTaskDisposition()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '验收提交失败，请稍后重试。')
  } finally {
    taskDispositionSubmitting.value = false
  }
}

async function rejectSelectedTask() {
  const task = selectedTask.value
  if (!task) return
  taskDispositionSubmitting.value = true
  try {
    await store.updateTaskStatus(
      task.id,
      'processing',
      taskDispositionReply.value || '退回重做',
    )
    message.success('任务已退回重做。')
    closeTaskDisposition()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '退回提交失败，请稍后重试。')
  } finally {
    taskDispositionSubmitting.value = false
  }
}

function taskAttachmentRecord(reference: string) {
  return store.attachments.find(item => (
    item.id === reference || item.fileName === reference
  ))
}

function taskAttachmentFileName(reference: string) {
  return taskAttachmentRecord(reference)?.fileName || reference
}

async function downloadTaskAttachment(reference: string) {
  const attachment = taskAttachmentRecord(reference)
  if (!attachment) {
    message.warning('未找到对应附件记录。')
    return
  }
  try {
    await store.downloadAttachment(attachment.id, attachment.fileName)
  } catch (error: any) {
    message.error(error.response?.data?.detail || '附件下载失败，请稍后重试。')
  }
}

function clearTaskHistoryFilters() {
  taskHistoryKeyword.value = ''
  taskHistoryStatus.value = 'all'
  taskHistoryStart.value = ''
  taskHistoryEnd.value = ''
}

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
function todayDateString(offsetDays = 0) {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function createTaskFlowStepDraft(
  input: Partial<TaskFlowStepDraft> & Pick<TaskFlowStepDraft, 'id' | 'name'>,
): TaskFlowStepDraft {
  return {
    node_type: 'manual',
    owner_user_id: '',
    due_at: '',
    material: '',
    sender_agent_id: 'dobby-task-engine',
    target_channel_id: taskChatChannels.value[0]?.id || null,
    mention_mode: 'all',
    mentioned_user_ids: [],
    message_content: '',
    ...input,
  }
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
  return templates[type].map(([name, material], index) => createTaskFlowStepDraft({ id: `flow-${Date.now()}-${index}`, name, owner_user_id: store.members[index % Math.max(store.members.length, 1)]?.id || '', due_at: todayDateString(index + 1), material }))
}

function taskTypeFromTemplate(type: (typeof taskTemplateOptions)[number]): Task['type'] {
  if (type === '资料补全') return 'material_missing'
  if (type === '报告审核') return 'draft_review'
  return 'risk_alert'
}

function memberNameById(memberId: string) {
  return store.members.find(member => member.id === memberId)?.name || '待指定'
}

function normalizeGeneratedRunMode(mode: GeneratedTaskFlow['run_mode']): TaskRunMode {
  if (mode === 'scheduled' || mode === 'recurring') return 'recurring'
  if (mode === 'once') return 'once'
  return 'immediate'
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
  taskCreateForm.value.run_mode = normalizeGeneratedRunMode(flow.run_mode)
  taskCreateForm.value.trigger_date = flow.trigger_date
  taskCreateForm.value.trigger_time = flow.trigger_time
  taskCreateForm.value.trigger_interval_value = flow.trigger_interval_value
  taskCreateForm.value.trigger_interval_unit = flow.trigger_interval_unit
  taskCreateForm.value.cc = flow.cc
  taskCreateForm.value.wbs_item_id = flow.wbs_item_id ? String(flow.wbs_item_id) : ''
  taskCreateForm.value.confirmer_user_id = flow.confirmer_user_id ? String(flow.confirmer_user_id) : ''
  taskFlowSteps.value = flow.steps.map((step, index) => {
    const nodeType = step.node_type || 'manual'
    const action = step.action
    return createTaskFlowStepDraft({
      id: `generated-${Date.now()}-${index}`,
      name: step.name,
      node_type: nodeType,
      owner_user_id: step.owner_user_id ? String(step.owner_user_id) : '',
      due_at: step.due_at?.slice(0, 10) || (nodeType === 'manual' ? todayDateString(index + 1) : ''),
      material: step.material || '',
      sender_agent_id: action?.sender_agent_id || 'dobby-task-engine',
      target_channel_id: action?.channel_id || taskChatChannels.value[0]?.id || null,
      mention_mode: action?.mention_mode || 'none',
      mentioned_user_ids: action?.mentioned_user_ids || [],
      message_content: action?.content || '',
    })
  })
  for (const step of taskFlowSteps.value) {
    if (step.node_type === 'project_chat_message' && step.target_channel_id) {
      void loadTaskChatMembers(step.target_channel_id)
    }
  }
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
  taskFlowSteps.value.push(createTaskFlowStepDraft({ id: `manual-${Date.now()}`, name: `新节点 ${taskFlowSteps.value.length + 1}`, due_at: todayDateString(taskFlowSteps.value.length + 1) }))
  selectedTaskFlowStepIndex.value = taskFlowSteps.value.length - 1
}

async function focusTaskFlowStep(index: number) {
  if (index < 0 || index >= taskFlowSteps.value.length) return
  selectedTaskFlowStepIndex.value = index
  await nextTick()
  const node = document.getElementById(`task-flow-node-${index}`)
  node?.focus({ preventScroll: true })
  node?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function handleTaskFlowStepTypeChange(step: TaskFlowStepDraft) {
  if (step.node_type === 'project_chat_message') {
    step.name = step.name.startsWith('新节点') ? '发送群聊消息' : step.name
    step.sender_agent_id ||= 'dobby-task-engine'
    step.target_channel_id ||= taskChatChannels.value[0]?.id || null
    step.message_content ||= '请大家及时查看并处理当前项目事项。'
    step.owner_user_id = ''
    step.material = ''
    if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
    return
  }
  step.mentioned_user_ids = []
}

function handleTaskMessageChannelChange(step: TaskFlowStepDraft) {
  step.mentioned_user_ids = []
  if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
}

function moveTaskFlowStep(index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= taskFlowSteps.value.length) return
  const [step] = taskFlowSteps.value.splice(index, 1)
  taskFlowSteps.value.splice(nextIndex, 0, step)
  selectedTaskFlowStepIndex.value = nextIndex
}

function removeTaskFlowStep(index: number) {
  if (index < 0 || index >= taskFlowSteps.value.length) return
  taskFlowSteps.value.splice(index, 1)
  selectedTaskFlowStepIndex.value = taskFlowSteps.value.length
    ? Math.min(selectedTaskFlowStepIndex.value, taskFlowSteps.value.length - 1)
    : -1
}

function resetTaskFlowCreator() {
  taskCreateMode.value = 'dobby'
  taskFlowAssistantOpen.value = true
  taskFlowRequirement.value = ''
  taskFlowGenerationNote.value = ''
  taskTemplateType.value = '隐患整改'
  taskTemplateTopic.value = ''
  taskCreateForm.value = {
    title: '',
    task_type: 'risk_alert',
    run_mode: 'immediate',
    trigger_date: todayDateString(),
    trigger_time: '09:00',
    trigger_interval_value: 1,
    trigger_interval_unit: 'week',
    trigger_end_mode: 'never',
    trigger_until_date: todayDateString(30),
    trigger_max_fires: 4,
    trigger_calendar_mode: 'weekdays',
    trigger_weekdays: [1, 2, 3, 4, 5],
    trigger_day_of_month: 1,
    cc: '',
    wbs_item_id: '',
    confirmer_user_id: '',
  }
  taskFlowSteps.value = []
  selectedTaskFlowStepIndex.value = -1
}

async function createManualTask() {
  if (!taskFlowCanSubmit.value) return
  const form = taskCreateForm.value
  const manualSteps = taskFlowSteps.value.filter(step => step.node_type === 'manual')
  const requiredMaterials = Array.from(new Set(manualSteps.map(step => step.material.trim()).filter(Boolean)))
  const workflow_steps = taskFlowSteps.value.map((step, index) => ({
    name: step.name.trim(),
    node_type: step.node_type,
    owner: step.node_type === 'manual' ? memberNameById(step.owner_user_id) : undefined,
    owner_user_id: step.node_type === 'manual' ? step.owner_user_id || undefined : undefined,
    due_at: step.node_type === 'manual' ? step.due_at || undefined : undefined,
    material: step.node_type === 'manual' ? step.material.trim() : undefined,
    action: step.node_type === 'project_chat_message'
      ? {
          type: 'project_chat_message' as const,
          channel_id: step.target_channel_id as number,
          sender_agent_id: step.sender_agent_id,
          sender_agent_name: taskMessageSenderOptions.value.find(item => item.id === step.sender_agent_id)?.name || 'Dobby',
          mention_mode: step.mention_mode,
          mentioned_user_ids: step.mentioned_user_ids,
          content: step.message_content.trim(),
        }
      : undefined,
    order: index + 1,
    next_step: index < taskFlowSteps.value.length - 1 ? index + 2 : undefined,
    status: 'pending' as const,
  })) as Task['workflowSteps']
  const triggerParts = [taskTriggerSummary.value, form.cc ? `抄送：${form.cc}` : ''].filter(Boolean)
  try {
    await store.createTask({
      title: form.title,
      task_type: form.task_type,
      risk_level: 'medium',
      assignee_user_id: manualSteps[0]?.owner_user_id,
      due_at: manualSteps[manualSteps.length - 1]?.due_at,
      trigger_reason: triggerParts.join(' · '),
      required_materials: requiredMaterials,
      workflow_steps,
      run_mode: form.run_mode,
      trigger_date: form.trigger_date,
      trigger_time: form.trigger_time,
      trigger_interval_value: form.trigger_interval_value,
      trigger_interval_unit: form.trigger_interval_unit,
      trigger_end_mode: form.trigger_end_mode,
      trigger_until_date: form.trigger_until_date,
      trigger_max_fires: form.trigger_max_fires,
      trigger_calendar_mode: form.trigger_calendar_mode,
      trigger_weekdays: form.trigger_weekdays,
      trigger_day_of_month: form.trigger_day_of_month,
      cc: form.cc,
      wbs_item_id: form.wbs_item_id,
      confirmer_user_id: form.confirmer_user_id,
    })
    if (form.run_mode !== 'immediate') {
      message.success(`计划已登记：${taskTriggerSummary.value}`)
      resetTaskFlowCreator()
      taskManagementTab.value = 'schedules'
    } else {
      message.success('任务流已创建，可在执行记录中查看。')
      taskManagementTab.value = 'history'
      resetTaskFlowCreator()
    }
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

function projectBaseInfoRow(label: string, rawValue?: string | null) {
  const value = String(rawValue || '').trim()
  return { label, value: value || '未填写', present: Boolean(value) }
}

function projectDateLabel(value?: string | null) {
  if (!value) return ''
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function projectDocumentTypeLabel(fileType: string, fileName: string) {
  const extension = fileName.includes('.') ? fileName.split('.').pop() || '' : ''
  const normalized = (fileType || extension).trim().replace(/^\./, '').split('/').pop() || ''
  return normalized ? normalized.toUpperCase() : '文件'
}

function projectDocumentFileSizeLabel(fileSize: number) {
  return fileSize > 0 ? formatFileSize(fileSize) : '大小未记录'
}

function projectDocumentFolderLabel(folderPath: string) {
  const segments = folderPath.replace(/\\/g, '/').split('/').map(item => item.trim()).filter(Boolean)
  return segments.length ? segments[segments.length - 1] : '资料库根目录'
}

function projectDateRange(start?: string | null, end?: string | null) {
  const startLabel = projectDateLabel(start)
  const endLabel = projectDateLabel(end)
  if (startLabel && endLabel) return `${startLabel} 至 ${endLabel}`
  if (startLabel) return `${startLabel} 起`
  if (endLabel) return `截至 ${endLabel}`
  return '未填写'
}

function projectQualityWbsLabel(item: QualityMetric) {
  const code = item.wbsCode || (item.wbsId ? store.getWbsName(item.wbsId) : '')
  return [code, item.wbsName].filter(Boolean).join(' · ') || '未关联'
}

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
    automation: '自动化动作',
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
    automation: '任务引擎自动执行',
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
  if (!date) return '—'
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(date)
    ? `${date}T${mode === 'end' ? '18:00' : '00:00'}:00`
    : date
  const timestamp = Date.parse(normalized)
  if (!Number.isFinite(timestamp)) return date.replace('T', ' ')

  const value = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`
}

function formatScheduleDateTime(value: string) {
  return formatDateTime(value)
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
    running: '处理中',
    review: '待确认',
    blocked: '受阻',
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

<style scoped src="./styles/AiWorkPlatformView.base.css"></style>
<style scoped src="./styles/AiWorkPlatformView.tasks.css"></style>
