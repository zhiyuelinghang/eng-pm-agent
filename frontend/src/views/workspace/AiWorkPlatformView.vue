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
          <button v-for="tab in taskManagementTabs" :key="tab.key" type="button" :class="{ active: taskManagementTab === tab.key }" @click="taskManagementTab = tab.key">
            <span><n-icon :size="17"><component :is="tab.icon" /></n-icon>{{ tab.label }}</span>
            <b>{{ tab.count }}</b>
          </button>
        </nav>
      </header>

      <main v-if="taskManagementTab === 'mine'" class="task-mine-view">
        <div class="home-workbench task-mine-workbench">
          <aside class="home-queue-pane" aria-label="我的任务列表">
            <div class="home-controlbar">
              <div class="home-status-tabs" role="tablist" aria-label="我的任务状态">
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

            <nav class="home-pagination" aria-label="我的任务分页">
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
          <label><span>任务名称</span><input v-model.trim="taskHistoryKeyword" placeholder="输入任务名称或触发原因"></label>
          <label><span>开始日期</span><input v-model="taskHistoryStart" type="date"></label>
          <label><span>结束日期</span><input v-model="taskHistoryEnd" type="date"></label>
          <button type="button" @click="clearTaskHistoryFilters">清除筛选</button>
        </form>
        <section class="task-history-results">
          <div class="task-history-table-head"><span>任务</span><span>类型</span><span>负责人</span><span>完成时间</span><span>闭环状态</span><span></span></div>
          <article v-for="task in filteredHistoryTasks" :key="task.id">
            <div><strong>{{ task.title }}</strong><small>{{ task.triggerReason || '无补充说明' }}</small></div><span>{{ taskTypeLabel(task.type) }}</span><span>{{ store.getMemberName(task.responsibleId) }}</span><time>{{ formatDateTime(task.deadline, 'end') }}</time><em :class="taskClosureTone(task)">{{ taskClosureLabel(task) }}</em><button type="button" @click="openTaskHistory(task.id)">查看记录</button>
          </article>
          <div v-if="!filteredHistoryTasks.length" class="task-history-no-result"><Notes :size="30" /><strong>没有匹配的历史任务</strong><p>调整名称或日期范围后再试。</p></div>
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
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><MapPin /></n-icon>关联工点</span><select v-model="taskCreateForm.wbs_item_id" required><option value="">请选择工点</option><option v-for="item in store.wbsItems" :key="item.id" :value="item.id">{{ item.code }} {{ item.name }}</option></select></label>
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><User /></n-icon>确认人</span><select v-model="taskCreateForm.confirmer_user_id" required><option value="">请选择确认人</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label>
              <label class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><Repeat /></n-icon>执行方式</span><select v-model="taskCreateForm.run_mode"><option value="immediate">立即执行</option><option value="once">定时单次</option><option value="recurring">周期执行</option></select></label>
              <label v-if="taskCreateForm.run_mode !== 'immediate'" class="form-field task-flow-time-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>{{ taskCreateForm.run_mode === 'once' ? '计划执行时间' : '首次触发时间' }}</span><input v-model="taskExecutionAt" type="datetime-local" required></label>
              <label v-if="taskCreateForm.run_mode === 'recurring'" class="form-field task-flow-interval-field"><span class="task-flow-field-label"><n-icon :size="16"><Clock /></n-icon>触发间隔</span><span><input v-model.number="taskCreateForm.trigger_interval_value" type="number" min="1" max="365" required><select v-model="taskCreateForm.trigger_interval_unit"><option value="hour">小时</option><option value="day">天</option><option value="week">周</option><option value="month">个月</option></select></span></label>
              <label v-if="taskCreateForm.run_mode === 'recurring'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><PlayerStop /></n-icon>结束条件</span><select v-model="taskCreateForm.trigger_end_mode"><option value="never">持续执行</option><option value="until">到指定日期</option><option value="count">执行指定次数</option></select></label>
              <label v-if="taskCreateForm.run_mode === 'recurring' && taskCreateForm.trigger_end_mode === 'until'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><CalendarEvent /></n-icon>结束日期</span><input v-model="taskCreateForm.trigger_until_date" type="date" required></label>
              <label v-if="taskCreateForm.run_mode === 'recurring' && taskCreateForm.trigger_end_mode === 'count'" class="form-field"><span class="task-flow-field-label"><n-icon :size="16"><ListCheck /></n-icon>执行次数</span><input v-model.number="taskCreateForm.trigger_max_fires" type="number" min="1" max="10000" required></label>
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
                  <article v-for="(step, index) in taskFlowSteps" :key="step.id" class="task-flow-node-card" :class="{ active: selectedTaskFlowStepIndex === index }" @click="selectedTaskFlowStepIndex = index">
                    <header>
                      <span>{{ index + 1 }}</span>
                      <div class="task-flow-node-heading"><strong>{{ step.name || `节点 ${index + 1}` }}</strong><small>{{ memberNameById(step.owner_user_id) }} · {{ step.due_at || '未设置截止日期' }} · {{ step.material || '未设置交付物' }}</small></div>
                      <em v-if="selectedTaskFlowStepIndex === index">当前节点</em>
                      <div class="task-flow-node-actions"><button type="button" :disabled="index === 0" title="上移" aria-label="上移节点" @click.stop="moveTaskFlowStep(index, -1)"><n-icon :size="16"><ChevronUp /></n-icon></button><button type="button" :disabled="index === taskFlowSteps.length - 1" title="下移" aria-label="下移节点" @click.stop="moveTaskFlowStep(index, 1)"><n-icon :size="16"><ChevronDown /></n-icon></button><button type="button" class="danger" :disabled="taskFlowSteps.length <= 2" title="删除" aria-label="删除节点" @click.stop="removeTaskFlowStep(index)"><n-icon :size="16"><Trash /></n-icon></button><button type="button" title="展开或收起" :aria-expanded="selectedTaskFlowStepIndex === index" @click.stop="selectedTaskFlowStepIndex = selectedTaskFlowStepIndex === index ? -1 : index"><n-icon :size="16"><component :is="selectedTaskFlowStepIndex === index ? ChevronUp : ChevronDown" /></n-icon></button></div>
                    </header>
                    <div v-if="selectedTaskFlowStepIndex === index" class="task-flow-node-fields"><label class="form-field">节点名称<input v-model.trim="step.name" required></label><label class="form-field">节点负责人<select v-model="step.owner_user_id" required><option value="">待指定</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label><label class="form-field">截止日期<input v-model="step.due_at" type="date"></label><label class="form-field">交付材料 / 留证<input v-model.trim="step.material" placeholder="填写后引擎将要求上传证明材料"></label></div>
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
              <div class="task-flow-validation-note"><strong>引擎约束</strong><p>工点、确认人和每个节点的具体负责人是布置任务的硬约束；交付物填写后，该节点必须留证。</p></div>
              <button type="submit" class="task-flow-submit" :disabled="!taskFlowCanSubmit">{{ taskCreateForm.run_mode === 'immediate' ? '校验并布置任务' : '校验并登记计划' }}</button>
              <button type="button" class="task-flow-back" @click="taskManagementTab = 'mine'">返回我的任务</button>
            </aside>
          </div>
        </form>
      </main>

      <div v-if="taskDispositionOpen && selectedTask" class="task-disposition-backdrop" @click.self="closeTaskDisposition">
        <aside class="task-disposition-drawer" role="dialog" aria-modal="true" aria-labelledby="task-disposition-title">
          <header><div><span>{{ taskTypeLabel(selectedTask.type) }} · {{ statusLabel(selectedTask.status) }}</span><h2 id="task-disposition-title">{{ selectedTask.title }}</h2><p>{{ taskCurrentOwnerName(selectedTask) }} · 截止 {{ taskCurrentStep(selectedTask)?.due_at || selectedTask.deadline }}</p></div><button type="button" aria-label="关闭任务处置" @click="closeTaskDisposition">关闭</button></header>
          <div class="task-disposition-body">
            <section class="task-disposition-ai"><span class="task-disposition-bot"><Robot :size="18" /></span><div><strong>Dobby 处置提示</strong><p>{{ selectedTaskConclusion }}</p><small>依据：{{ selectedTask.triggerReason }}</small></div></section>
            <section class="task-disposition-flow"><div class="task-disposition-section-title"><span>任务流程</span><strong>{{ selectedTaskCompletedSteps }}/{{ selectedTask.workflowSteps.length || 1 }} 个节点已完成</strong></div><ol><li v-for="(step, index) in selectedTask.workflowSteps" :key="`${selectedTask.id}-dispose-${index}`" :class="step.status"><span>{{ index + 1 }}</span><div><strong>{{ step.name }}</strong><small>{{ step.owner || store.getMemberName(step.owner_user_id || '') || '待指定负责人' }} · {{ step.due_at || '未设置截止时间' }}</small><small v-if="step.reopened" class="task-disposition-reopen-hint">⚠ 该节点被退回，需重新提交材料</small></div><em>{{ taskStepLabel(step.status) }}</em><button v-if="selectedTask.status === 'processing' && step.status !== 'completed'" type="button" @click="store.updateTaskStep(selectedTask.id, index, 'completed')">完成节点</button></li></ol></section>
            <section class="task-disposition-form"><div class="task-disposition-section-title"><span>回复与材料</span><strong>结果将进入任务处理记录</strong></div><textarea v-model.trim="taskDispositionReply" rows="5" placeholder="回复 Dobby，例如：已完成复核，照片符合闭环要求"></textarea><label class="task-disposition-files"><input type="file" multiple @change="handleTaskDispositionFiles"><span><Paperclip :size="16" />选择文件或图片</span><small>{{ taskDispositionFiles.length ? `已选择 ${taskDispositionFiles.length} 个文件` : '支持提交本节点的证明材料' }}</small></label><label class="task-disposition-forward"><span>转交当前节点</span><select v-model="taskDispositionForwardId"><option value="">不转交</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label></section>
          </div>
          <footer><button type="button" class="task-disposition-history" @click="openTaskHistory(selectedTask.id)">查看处理记录</button><router-link to="/ai">发起讨论</router-link><button type="button" class="task-disposition-submit" :disabled="taskDispositionSubmitting || needsFreshEvidence" @click="submitTaskDisposition">{{ taskDispositionSubmitting ? '正在提交…' : needsFreshEvidence ? '需重新上传材料' : '回复并推进' }}</button></footer>
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
          <div class="project-health-conclusion">
            <div class="project-conclusion-head">
              <dt>关键结论</dt>
              <em>{{ projectHealthGrade }}</em>
            </div>
            <dd>{{ projectHealth.label }}</dd>
            <div class="project-conclusion-points">
              <p><b>风险</b><span>{{ projectHealth.mainRisk }}</span></p>
              <p><b>安全</b><span>{{ projectHealth.mainSafety }}</span></p>
              <p><b>质量</b><span>{{ projectHealth.mainQuality }}</span></p>
            </div>
            <div class="project-conclusion-meta">
              <span>实际 {{ projectHealth.actual }}% · 计划 {{ projectHealth.planned }}% · 差异 {{ projectHealth.delta >= 0 ? '+' : '' }}{{ projectHealth.delta }}%</span>
              <strong>任务闭环 {{ projectHealth.doneTasks }}/{{ projectHealth.totalTasks }}</strong>
            </div>
          </div>
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
import type { DraftStatus, FillStatus, Member, RiskLevel, Task, TaskStatus } from '@/types'

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
type TaskFlowStepDraft = { id: string; name: string; owner_user_id: string; due_at: string; material: string }
type TriggerIntervalUnit = 'hour' | 'day' | 'week' | 'month'
type TaskRunMode = 'immediate' | 'once' | 'recurring'
type TriggerEndMode = 'never' | 'until' | 'count'
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
  steps: Array<{ name: string; owner_user_id?: number | null; due_at?: string; material?: string }>
  generated_by: 'ai' | 'rules'
  generation_note: string
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
const currentUserId = computed(() => sessionStorage.getItem('current_user_id') || store.members[0]?.id || '')
const projectProgress = computed(() => {
  if (!store.wbsItems.length) return 0
  return Math.round(store.wbsItems.reduce((sum, item) => sum + item.progress, 0) / store.wbsItems.length)
})
const focusTasks = computed(() => store.tasks.filter(task => ['overdue', 'pending', 'processing', 'waiting_confirm'].includes(task.status)))
const importantWbs = computed(() => store.wbsItems.filter(item => item.level <= 2).slice(0, 5))
const activeWbs = computed(() => store.wbsItems.find(item => item.status === 'in_progress' && item.level > 1) ?? store.wbsItems.find(item => item.status === 'in_progress') ?? importantWbs.value[0])
const criticalRisks = computed(() => store.riskSources.filter(risk => risk.level === 'critical' || risk.level === 'high'))
const projectStatusTab = ref<ProjectStatusTab>('latest')
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
  const conclusion = criticalRisks.value.length
    ? `重点关注 ${criticalRisks.value.slice(0, 2).map(item => item.name).join('、')}。`
    : focusTasks.value.length
      ? `当前有 ${focusTasks.value.length} 项待办需要持续推进。`
      : '暂无未闭环的重点事项。'
  return {
    label,
    planned: plannedProgress.value,
    actual: actualProgress.value,
    delta,
    taskCompletion,
    doneTasks,
    totalTasks,
    conclusion,
    mainRisk,
    mainSafety,
    mainQuality,
  }
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

type TaskManagementTab = 'mine' | 'history' | 'assign'

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
const taskHistoryStart = ref('')
const taskHistoryEnd = ref('')
const informationDispositionOpen = ref(false)
const selectedInformationRecordId = ref('')
const informationRevision = ref('')
const selectedInformationRecord = computed(() => (store.informationRecords || []).find(item => item.id === selectedInformationRecordId.value))
const taskHistoryOpenId = ref('')
const taskHistories = ref<Record<string, Array<{ id: number; from_status?: string; to_status: string; note?: string; created_at: string }>>>({})
const taskHistoryLoading = ref(false)
const selectedTaskHistoryTask = computed(() => store.tasks.find(task => task.id === taskHistoryOpenId.value))
const taskCreateMode = ref<'dobby' | 'template'>('dobby')
const taskFlowAssistantOpen = ref(true)
const taskFlowRequirement = ref('')
const taskFlowGenerating = ref(false)
const taskFlowGenerationNote = ref('')
const taskTemplateOptions = ['条件核查', '隐患整改', '资料补全', '风险处置', '报告审核', '自定义'] as const
const taskTemplateType = ref<(typeof taskTemplateOptions)[number]>('隐患整改')
const taskTemplateTopic = ref('整改现场隐患并完成复核闭环')
const selectedTaskFlowStepIndex = ref(0)
const taskFlowExamples = ['每周核查基坑监测数据并完成复核归档', '发现临边防护缺失后发起整改并闭环', '补齐日报缺失资料并由资料员复核']
const taskCreateForm = ref({
  title: taskTemplateTopic.value,
  task_type: 'risk_alert' as Task['type'],
  run_mode: 'immediate' as TaskRunMode,
  trigger_date: todayDateString(),
  trigger_time: '09:00',
  trigger_interval_value: 1,
  trigger_interval_unit: 'week' as TriggerIntervalUnit,
  trigger_end_mode: 'never' as TriggerEndMode,
  trigger_until_date: todayDateString(30),
  trigger_max_fires: 4,
  cc: '项目经理',
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
const triggerIntervalUnitLabel = computed(() => ({ hour: '小时', day: '天', week: '周', month: '个月' })[taskCreateForm.value.trigger_interval_unit])
const taskFlowSteps = ref<TaskFlowStepDraft[]>(createTemplateFlowSteps('隐患整改'))
const taskTriggerSummary = computed(() => {
  const form = taskCreateForm.value
  if (form.run_mode === 'immediate') return '提交后立即创建任务并激活首个节点'
  if (form.run_mode === 'once') return `${form.trigger_date} ${form.trigger_time} 自动执行一次`
  const ending = form.trigger_end_mode === 'until'
    ? `，执行至 ${form.trigger_until_date}`
    : form.trigger_end_mode === 'count'
      ? `，共执行 ${form.trigger_max_fires} 次`
      : '，持续执行'
  return `${form.trigger_date} ${form.trigger_time} 首次执行，之后每 ${form.trigger_interval_value} ${triggerIntervalUnitLabel.value}执行一次${ending}`
})
const taskScheduleIsValid = computed(() => {
  const form = taskCreateForm.value
  if (form.run_mode === 'immediate') return true
  if (!form.trigger_date || !form.trigger_time) return false
  if (form.run_mode === 'once') return true
  if (!Number.isFinite(form.trigger_interval_value) || form.trigger_interval_value < 1) return false
  if (form.trigger_end_mode === 'until') return !!form.trigger_until_date && form.trigger_until_date >= form.trigger_date
  if (form.trigger_end_mode === 'count') return Number.isFinite(form.trigger_max_fires) && form.trigger_max_fires >= 1
  return true
})
const taskFlowValidationItems = computed(() => {
  const form = taskCreateForm.value
  const namedSteps = taskFlowSteps.value.filter(step => step.name.trim()).length
  const assignedSteps = taskFlowSteps.value.filter(step => step.owner_user_id).length
  return [
    { key: 'title', label: '任务名称', ok: !!form.title.trim(), detail: form.title.trim() || '请填写任务名称' },
    { key: 'site', label: '关联工点', ok: !!form.wbs_item_id, detail: form.wbs_item_id ? store.getWbsName(form.wbs_item_id) : '请选择具体 WBS 工点' },
    { key: 'confirmer', label: '确认人', ok: !!form.confirmer_user_id, detail: form.confirmer_user_id ? memberNameById(form.confirmer_user_id) : '请选择最终验收人' },
    { key: 'schedule', label: '执行计划', ok: taskScheduleIsValid.value, detail: taskScheduleIsValid.value ? taskTriggerSummary.value : '请补全有效的触发设置' },
    { key: 'steps', label: '流程节点', ok: taskFlowSteps.value.length >= 2 && namedSteps === taskFlowSteps.value.length, detail: `${namedSteps}/${taskFlowSteps.value.length} 个节点名称完整` },
    { key: 'assignees', label: '节点负责人', ok: taskFlowSteps.value.length >= 2 && assignedSteps === taskFlowSteps.value.length, detail: `${assignedSteps}/${taskFlowSteps.value.length} 个节点已落到具体人员` },
  ]
})
const taskFlowCanSubmit = computed(() => taskFlowValidationItems.value.every(item => item.ok))
const taskFlowMissingCount = computed(() => taskFlowValidationItems.value.filter(item => !item.ok).length)
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
const closedTasks = computed(() => store.tasks.filter(task => ['done', 'cancelled'].includes(task.status)))
const filteredHistoryTasks = computed(() => closedTasks.value.filter(task => {
  const keyword = taskHistoryKeyword.value.toLowerCase()
  const searchMatched = !keyword || `${task.title} ${task.triggerReason} ${taskTypeLabel(task.type)}`.toLowerCase().includes(keyword)
  const date = (task.deadline || task.createdAt).slice(0, 10)
  return searchMatched && (!taskHistoryStart.value || date >= taskHistoryStart.value) && (!taskHistoryEnd.value || date <= taskHistoryEnd.value)
}))
const taskManagementTabs = computed(() => [
  { key: 'mine' as const, label: '我的任务', count: homeWorkItems.value.length, icon: ListCheck },
  { key: 'history' as const, label: '历史任务', count: closedTasks.value.length, icon: Notes },
  { key: 'assign' as const, label: '布置任务', count: 'AI', icon: Plus },
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

function clearTaskHistoryFilters() {
  taskHistoryKeyword.value = ''
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
  taskCreateMode.value = 'dobby'
  taskFlowAssistantOpen.value = true
  taskFlowRequirement.value = ''
  taskFlowGenerationNote.value = ''
  taskTemplateType.value = '隐患整改'
  taskTemplateTopic.value = '整改现场隐患并完成复核闭环'
  taskCreateForm.value = {
    title: taskTemplateTopic.value,
    task_type: 'risk_alert',
    run_mode: 'immediate',
    trigger_date: todayDateString(),
    trigger_time: '09:00',
    trigger_interval_value: 1,
    trigger_interval_unit: 'week',
    trigger_end_mode: 'never',
    trigger_until_date: todayDateString(30),
    trigger_max_fires: 4,
    cc: '项目经理',
    wbs_item_id: '',
    confirmer_user_id: '',
  }
  taskFlowSteps.value = createTemplateFlowSteps('隐患整改')
  selectedTaskFlowStepIndex.value = 0
}

async function createManualTask() {
  if (!taskFlowCanSubmit.value) return
  const form = taskCreateForm.value
  const requiredMaterials = Array.from(new Set(taskFlowSteps.value.map(step => step.material.trim()).filter(Boolean)))
  const workflow_steps = taskFlowSteps.value.map((step, index) => ({ name: step.name.trim(), owner: memberNameById(step.owner_user_id), owner_user_id: step.owner_user_id || undefined, due_at: step.due_at || undefined, material: step.material.trim(), order: index + 1, next_step: index < taskFlowSteps.value.length - 1 ? index + 2 : undefined, status: 'pending' as const })) as Task['workflowSteps']
  const triggerParts = [taskTriggerSummary.value, form.cc ? `抄送：${form.cc}` : ''].filter(Boolean)
  try {
    await store.createTask({
      title: form.title,
      task_type: form.task_type,
      risk_level: 'medium',
      assignee_user_id: taskFlowSteps.value[0]?.owner_user_id,
      due_at: taskFlowSteps.value[taskFlowSteps.value.length - 1]?.due_at,
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
      cc: form.cc,
      wbs_item_id: form.wbs_item_id,
      confirmer_user_id: form.confirmer_user_id,
    })
    if (form.run_mode !== 'immediate') {
      message.success(`执行计划已登记：${taskTriggerSummary.value}`)
      resetTaskFlowCreator()
    } else {
      message.success('任务流已创建并进入我的任务。')
      taskManagementTab.value = 'mine'
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
  font-size: 12px;
  font-weight: 760;
  line-height: 1;
}

.home-console {
  display: block;
  height: calc(100dvh - var(--header-height, 56px) - 36px);
  min-height: 600px;
}

.home-workspace {
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

.home-workbench {
  display: grid;
  grid-template-columns: minmax(430px, 42%) minmax(520px, 58%);
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.home-queue-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-right: 1px solid rgba(20, 45, 54, 0.1);
  background: rgba(251, 253, 252, 0.74);
}

.home-controlbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
}

.home-status-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  width: 100%;
}

.home-status-tabs button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(20, 45, 54, 0.12);
  border-radius: 6px;
  background: #fff;
  color: #455b63;
  font: inherit;
  font-size: 12px;
  font-weight: 780;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(255, 255, 255, .7) inset;
}

.home-status-tabs button span {
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

.home-status-tabs button.active {
  border-color: #08383e;
  background: #08383e;
  color: #fff;
  box-shadow: 0 10px 22px rgba(8, 56, 62, 0.18);
}

.home-status-tabs button.active span {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.home-queue-list {
  display: grid;
  grid-template-rows: repeat(5, minmax(0, 1fr));
  flex: 1 1 auto;
  align-content: start;
  min-height: 0;
  overflow: hidden;
  padding: 0;
}

.home-queue-card {
  position: relative;
  display: grid;
  grid-template-columns: 34px 48px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  width: 100%;
  min-height: 110px;
  padding: 13px 14px 13px 10px;
  border: 0;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background .18s ease, box-shadow .18s ease, transform .18s ease;
}

.home-queue-card::before {
  content: "";
  position: absolute;
  inset: 10px auto 10px 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: transparent;
}

.home-queue-card:hover {
  background: rgba(237, 246, 243, 0.7);
}

.home-queue-card.active {
  background: #eef7f4;
  box-shadow: inset -1px 0 rgba(15, 118, 110, 0.14);
}

.home-queue-card.active::before {
  background: #0f766e;
}

.home-queue-card:focus-visible {
  z-index: 1;
  outline: 2px solid rgba(15, 118, 110, 0.55);
  outline-offset: -3px;
}

.home-rank {
  display: grid;
  place-items: center;
  width: 32px;
  height: 46px;
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

.home-rank.success {
  background: #e8f7f0;
  color: #16845f;
}

.home-work-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
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

.home-work-icon.success {
  border-color: rgba(22, 132, 95, 0.16);
  background: #edf8f3;
  color: #16845f;
}

.home-work-main {
  display: grid;
  gap: 4px;
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

.home-chip.success {
  background: #dcf3e9;
  color: #16845f;
}

.home-work-title {
  display: block;
  overflow: hidden;
  color: #122933;
  font-size: 15px;
  line-height: 1.28;
  font-weight: 820;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-work-reason {
  display: block;
  overflow: hidden;
  color: #6a7d88;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-work-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  margin-top: 2px;
  color: #6f7f89;
  font-size: 12px;
  line-height: 1.4;
}

.home-work-meta > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: #415b63;
  font-weight: 760;
}

.home-work-meta time {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
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
  font-size: 12px;
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

.home-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 54px;
  padding: 9px 14px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
  background: rgba(255, 255, 255, 0.88);
}

.home-pagination > span {
  color: #6c7e88;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.home-pagination > div {
  display: flex;
  align-items: center;
  gap: 5px;
}

.home-pagination button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  height: 30px;
  padding: 0 7px;
  border: 1px solid rgba(20, 45, 54, 0.13);
  border-radius: 6px;
  background: #fff;
  color: #3f565e;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, background .18s ease, color .18s ease, opacity .18s ease;
}

.home-pagination button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.38);
  color: #0f766e;
}

.home-pagination button.active {
  border-color: #0f766e;
  background: #0f766e;
  color: #fff;
}

.home-pagination button:disabled {
  cursor: not-allowed;
  opacity: .34;
}

.home-pagination button:focus-visible {
  outline: 2px solid rgba(15, 118, 110, 0.48);
  outline-offset: 2px;
}

.home-work-ai {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 12% 0, rgba(15, 118, 110, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(250, 252, 251, 0.94), #fff 52%);
}

.home-work-ai-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px 16px;
  border-bottom: 1px solid rgba(20, 45, 54, 0.08);
  background: rgba(255, 255, 255, 0.82);
}

.home-work-ai-title {
  min-width: 0;
}

.home-ai-presence {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  color: #0f766e;
  font-size: 12px;
  font-weight: 820;
}

.home-ai-presence::after {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #14a56f;
  box-shadow: 0 0 0 4px rgba(20, 165, 111, 0.1);
}

.home-work-ai-title h2 {
  overflow: hidden;
  margin: 0;
  color: #10242a;
  font-size: 19px;
  line-height: 1.3;
  font-weight: 840;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-work-ai-title p {
  overflow: hidden;
  margin: 7px 0 0;
  color: #6b7d87;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.home-work-ai-thread {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
}

.home-work-ai-thread .message-row {
  max-width: min(650px, 94%);
}

.home-work-ai-thread .message-bubble {
  border: 1px solid rgba(20, 45, 54, 0.08);
  background: #fff;
  box-shadow: 0 10px 24px rgba(28, 48, 44, 0.055);
}

.home-work-ai-thread .message-row.user .message-bubble {
  border-color: rgba(8, 56, 62, 0.24);
  background: #153336;
}

.home-work-context {
  display: grid;
  gap: 10px;
  width: min(620px, calc(100% - 37px));
  margin-left: 37px;
  padding: 13px 14px;
  border: 1px solid rgba(15, 118, 110, 0.14);
  border-radius: 8px;
  background: rgba(238, 248, 245, 0.82);
}

.home-work-context > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.home-work-context > div:first-child span {
  color: #668078;
  font-size: 12px;
}

.home-work-context > div:first-child strong {
  color: #0f766e;
  font-size: 12px;
  font-weight: 820;
}

.home-work-context-tags,
.home-work-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.home-work-context-tags span {
  padding: 5px 7px;
  border-radius: 5px;
  background: #fff;
  color: #536b72;
  font-size: 12px;
  font-weight: 720;
}

.home-work-suggestions {
  margin-left: 37px;
}

.home-work-suggestions button {
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid rgba(15, 118, 110, 0.2);
  border-radius: 6px;
  background: #fff;
  color: #215e59;
  font: inherit;
  font-size: 12px;
  font-weight: 740;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, background .18s ease;
}

.home-work-suggestions button:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.42);
  background: #f1f8f6;
}

.home-work-suggestions button:focus-visible {
  outline: 2px solid rgba(15, 118, 110, 0.48);
  outline-offset: 2px;
}

.chat-composer.home-work-composer {
  grid-template-columns: minmax(0, 1fr) 92px;
  align-items: end;
  padding: 14px 20px 18px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
  background: rgba(255, 255, 255, 0.92);
}

.home-work-composer textarea {
  min-height: 58px;
  max-height: 104px;
}

.home-work-composer > button[type="submit"] {
  min-width: 92px;
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
  align-items: end;
  padding: 14px 22px 18px;
  border-top: 1px solid rgba(20, 45, 54, 0.08);
  background: rgba(255, 255, 255, 0.84);
}

.home-chat-composer textarea {
  min-height: 58px;
  max-height: 104px;
}

.home-chat-composer > button[type="submit"] {
  min-width: 92px;
}
.home-chat-composer > .stop-agent {
  display:inline-flex;
  min-width:92px;
  min-height:58px;
  align-items:center;
  align-self:end;
  justify-content:center;
  gap:6px;
  border:0;
  border-radius:8px;
  color:#fff;
  background:#3e5f5a;
  font:inherit;
  font-size:13px;
  font-weight:800;
  cursor:pointer;
}
.home-chat-composer > .stop-agent:hover { background:#304f4a; }

.composer-entry {
  display: grid;
  min-width: 0;
  gap: 8px;
}

.composer-input-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: stretch;
  gap: 8px;
}

.composer-attach-button {
  min-width: 108px;
  min-height: 58px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 12px;
  border: 1px solid rgba(15, 118, 110, 0.22);
  border-radius: 6px;
  background: #f3f8f6;
  color: #155f5a;
  font-size: 13px;
  font-weight: 760;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, background .18s ease;
}

.composer-attach-button:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 118, 110, 0.5);
  background: #eaf5f1;
}

.composer-attach-button:focus-within {
  outline: 2px solid rgba(15, 118, 110, 0.42);
  outline-offset: 2px;
}

.composer-attach-button input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.composer-attachment-list,
.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.composer-attachment-list > span,
.message-attachments > span {
  min-width: 0;
  max-width: min(100%, 320px);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 6px;
  padding: 6px 7px 6px 9px;
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 6px;
  background: #eef7f4;
  color: #284f4c;
}

.composer-attachment-list b,
.message-attachments b {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-attachment-list small,
.message-attachments small {
  color: #667a76;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
}

.composer-attachment-list button {
  width: 24px;
  height: 24px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #6c7f7b;
  font: inherit;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.composer-attachment-list button:hover {
  transform: none;
  background: rgba(205, 91, 32, 0.1);
  color: var(--color-primary);
  box-shadow: none;
}

.message-attachments {
  margin-top: 9px;
}

.message-attachments > span {
  grid-template-columns: auto minmax(0, 1fr) auto;
  background: rgba(255, 255, 255, 0.84);
}

.message-row.user .message-attachments > span {
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.message-row.user .message-attachments small {
  color: rgba(255, 255, 255, 0.72);
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
.chat-composer > button[type="submit"],
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
.chat-composer > button[type="submit"]:hover,
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
.chat-composer > button[type="submit"]:active,
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
.chat-composer > button[type="submit"],
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
  font-size: 12px;
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
.session-item time { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
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
  font-size: 12px;
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
.chat-composer > button[type="submit"] {
  min-height: 58px;
  align-self: end;
}
.chat-composer > button[type="submit"]:disabled {
  opacity: .48;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
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
  font-size: 12px;
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

.page-stack {
  display: grid;
  gap: 14px;
}

.task-page {
  gap: 12px;
}

/* Task command center — AI-first triage instead of a status card wall */
.task-command-page {
  display: grid;
  height: calc(100dvh - var(--header-height, 56px) - 36px);
  min-height: 640px;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  overflow: hidden;
}

.task-commandbar {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 22px;
  min-height: 84px;
  padding: 15px 18px 16px 20px;
  overflow: hidden;
  border: 1px solid rgba(26, 61, 60, .1);
  border-radius: 10px;
  background:
    radial-gradient(circle at 82% -35%, rgba(15, 118, 110, .15), transparent 18rem),
    linear-gradient(110deg, rgba(255,255,255,.97), rgba(244,249,247,.95));
  box-shadow: 0 12px 32px rgba(30, 59, 55, .065);
}

.task-commandbar::after {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: '';
  opacity: .24;
  background-image: radial-gradient(rgba(26, 77, 72, .22) .65px, transparent .65px);
  background-size: 8px 8px;
  mask-image: linear-gradient(90deg, transparent 25%, #000 100%);
}

.task-command-copy,
.task-command-stats,
.task-command-create {
  position: relative;
  z-index: 1;
}

.task-command-copy {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 15px;
}

.task-command-eyebrow {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-left: 3px solid #0f766e;
  border-radius: 3px 7px 7px 3px;
  color: #0c625c;
  background: rgba(224, 241, 236, .82);
  font-size: 12px;
  font-weight: 820;
  letter-spacing: .02em;
}

.task-command-copy > div { min-width: 0; }
.task-command-copy h1 {
  overflow: hidden;
  margin: 0;
  color: #102d2d;
  font-size: clamp(18px, 1.45vw, 23px);
  font-weight: 850;
  letter-spacing: -.025em;
  line-height: 1.18;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-command-copy p {
  overflow: hidden;
  margin: 6px 0 0;
  color: #66807a;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-command-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(74px, 1fr));
  gap: 1px;
  margin: 0;
  overflow: hidden;
  border: 1px solid rgba(33, 69, 66, .09);
  border-radius: 8px;
  background: rgba(32, 69, 66, .09);
}
.task-command-stats > div {
  display: grid;
  grid-template-columns: auto auto;
  align-items: baseline;
  gap: 8px;
  padding: 10px 11px;
  background: rgba(255,255,255,.91);
}
.task-command-stats dt { color: #6e827d; font-size: 12px; white-space: nowrap; }
.task-command-stats dd { margin: 0; color: #173b39; font-size: 19px; font-weight: 850; font-variant-numeric: tabular-nums; }
.task-command-stats .danger dd { color: #c65126; }

.task-command-create {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 38px;
  padding: 0 14px;
  border: 0;
  color: #fff;
  background: #c95622;
  box-shadow: 0 8px 18px rgba(201, 86, 34, .2);
  transition: transform .2s ease, background .2s ease, box-shadow .2s ease;
}
.task-command-create:hover { transform: translateY(-1px); background: #b94a1b; box-shadow: 0 11px 22px rgba(201, 86, 34, .25); }
.task-command-create:active { transform: translateY(1px) scale(.98); }

.task-ai-workbench {
  display: grid;
  min-height: 0;
  grid-template-columns: minmax(330px, .73fr) minmax(0, 1.62fr);
  overflow: hidden;
  border: 1px solid rgba(26, 61, 60, .11);
  border-radius: 10px;
  background: rgba(255,255,255,.93);
  box-shadow: 0 16px 38px rgba(24, 53, 50, .07);
}

.task-command-queue {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  border-right: 1px solid #dfe9e5;
  background: #f8faf9;
}
.task-command-queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 17px 12px;
}
.task-command-queue-head h2 { margin: 0; color: #173735; font-size: 15px; font-weight: 820; }
.task-command-queue-head p { margin: 4px 0 0; color: #7a8e89; font-size: 12px; }
.task-live-state { display: inline-flex; align-items: center; gap: 6px; color: #57716b; font-size: 12px; white-space: nowrap; }
.task-live-state i,
.task-ai-presence i { display: block; width: 6px; height: 6px; border-radius: 50%; background: #16a277; box-shadow: 0 0 0 4px rgba(22,162,119,.1); }

.task-queue-filters {
  display: flex;
  gap: 5px;
  padding: 0 12px 11px;
  overflow-x: auto;
  border-bottom: 1px solid #e3ebe8;
  scrollbar-width: none;
}
.task-queue-filters::-webkit-scrollbar { display: none; }
.task-queue-filters button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #60766f;
  background: transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 730;
  cursor: pointer;
  transition: color .18s ease, background .18s ease, border-color .18s ease;
}
.task-queue-filters button span { min-width: 17px; padding: 2px 5px; border-radius: 4px; color: #5d746d; background: #e8efec; font-size: 12px; font-variant-numeric: tabular-nums; }
.task-queue-filters button:hover { color: #0f766e; background: #eef6f3; }
.task-queue-filters button.active { border-color: #214c49; color: #fff; background: #173f3d; }
.task-queue-filters button.active span { color: #d9efea; background: rgba(255,255,255,.13); }

.task-command-list { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.task-command-item {
  position: relative;
  display: grid;
  width: 100%;
  min-height: 116px;
  grid-template-columns: 32px minmax(0, 1fr) 18px;
  align-items: start;
  gap: 10px;
  padding: 14px 13px 13px;
  border: 0;
  border-bottom: 1px solid #e4ebe9;
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background .2s ease, box-shadow .2s ease;
}
.task-command-item::before { position: absolute; inset: 9px auto 9px 0; width: 3px; border-radius: 0 3px 3px 0; content: ''; background: transparent; transition: background .2s ease; }
.task-command-item:hover { background: #f1f7f4; }
.task-command-item.active { background: #eaf4f0; box-shadow: inset -1px 0 #d5e5df; }
.task-command-item.active::before { background: #0f766e; }
.task-command-rank {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 7px;
  color: #607c75;
  background: #e7efec;
  font-size: 12px;
  font-weight: 850;
  font-variant-numeric: tabular-nums;
}
.task-command-item.active .task-command-rank { color: #fff; background: #0f766e; }
.task-command-item-main { display: block; min-width: 0; }
.task-command-item-tags { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.task-command-item-tags em,
.task-dobby-context header > em {
  padding: 3px 6px;
  border-radius: 4px;
  color: #0f766e;
  background: #dff1eb;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  line-height: 1;
}
.task-command-item-tags em.danger,
.task-dobby-context header > em.danger { color: #bd4822; background: #fae5dc; }
.task-command-item-tags em.attention,
.task-dobby-context header > em.attention { color: #9a6509; background: #fff0cd; }
.task-command-item-tags em.complete,
.task-dobby-context header > em.complete { color: #527069; background: #e8eeec; }
.task-command-item-tags small { color: #738983; font-size: 12px; }
.task-command-item-main > strong { display: block; overflow: hidden; color: #173735; font-size: 14px; line-height: 1.42; text-overflow: ellipsis; white-space: nowrap; }
.task-command-item-reason { display: block; overflow: hidden; margin-top: 5px; color: #6b7f7a; font-size: 12px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.task-command-item-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; color: #718680; font-size: 12px; font-variant-numeric: tabular-nums; }
.task-command-item-meta span { display: inline-flex; align-items: center; gap: 4px; }
.task-command-item-meta time { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-command-chevron { align-self: center; color: #a0b1ac; transition: transform .18s ease, color .18s ease; }
.task-command-item:hover .task-command-chevron,
.task-command-item.active .task-command-chevron { transform: translateX(2px); color: #0f766e; }

.task-command-queue-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-top: 1px solid #e1e9e6;
  color: #7a8f89;
  background: rgba(255,255,255,.75);
  font-size: 12px;
}
.task-command-queue-foot button { border: 0; padding: 3px 0; color: #0f766e; background: transparent; font: inherit; font-size: 12px; font-weight: 760; cursor: pointer; }
.task-command-empty { display: grid; min-height: 240px; place-content: center; justify-items: center; padding: 24px; color: #78908a; text-align: center; }
.task-command-empty strong { margin-top: 10px; color: #284a46; font-size: 14px; }
.task-command-empty p { max-width: 28ch; margin: 6px 0 0; font-size: 12px; line-height: 1.55; }

.task-dobby-panel {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background:
    radial-gradient(circle at 92% 10%, rgba(15,118,110,.055), transparent 20rem),
    #fff;
}
.task-dobby-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 18px 15px;
  border-bottom: 1px solid #e3eae8;
}
.task-dobby-head-copy { min-width: 0; }
.task-ai-presence { display: inline-flex; align-items: center; gap: 6px; color: #0f766e; font-size: 12px; font-weight: 800; }
.task-dobby-head h2 { overflow: hidden; margin: 7px 0 4px; color: #143431; font-size: 18px; font-weight: 850; letter-spacing: -.015em; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.task-dobby-head p { margin: 0; color: #70857f; font-size: 12px; font-variant-numeric: tabular-nums; }
.task-dobby-head-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.task-dobby-head-actions button,
.task-dobby-head-actions a {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  justify-content: center;
  padding: 0 11px;
  border: 1px solid #cfddd9;
  border-radius: 6px;
  color: #43625c;
  background: #fff;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  text-decoration: none;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, background .18s ease;
}
.task-dobby-head-actions button:hover,
.task-dobby-head-actions a:hover { transform: translateY(-1px); border-color: #0f766e; }
.task-dobby-head-actions .task-primary-action { border-color: #0f766e; color: #fff; background: #0f766e; }

.task-dobby-thread {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
  padding: 18px clamp(16px, 2.1vw, 28px) 26px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.task-dobby-message { display: grid; max-width: min(820px, 96%); grid-template-columns: 30px minmax(0, 1fr); align-items: start; gap: 9px; }
.task-dobby-message.user { align-self: flex-end; grid-template-columns: minmax(0, 1fr) 30px; }
.task-dobby-message.user .task-dobby-avatar { grid-column: 2; grid-row: 1; color: #fff; background: #c95622; }
.task-dobby-message.user .task-dobby-bubble { grid-column: 1; grid-row: 1; border-color: #f0d6c9; background: #fff8f4; }
.task-dobby-avatar { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; color: #dcefeb; background: #173f3d; }
.task-dobby-bubble {
  padding: 13px 15px 14px;
  border: 1px solid #dce7e3;
  border-radius: 5px 10px 10px 10px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(26, 55, 52, .055);
}
.task-dobby-bubble > span { color: #c45528; font-size: 12px; font-weight: 800; }
.task-dobby-bubble h3 { margin: 6px 0 5px; color: #193c39; font-size: 14px; }
.task-dobby-bubble p { max-width: 70ch; margin: 5px 0 0; color: #405c57; font-size: 12px; line-height: 1.65; }
.task-dobby-judgement {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid #e1e9e6;
  border-radius: 7px;
  background: #e1e9e6;
}
.task-dobby-judgement div { min-width: 0; padding: 9px 10px; background: #f7faf9; }
.task-dobby-judgement span { display: block; color: #7a8d88; font-size: 12px; }
.task-dobby-judgement strong { display: block; overflow: hidden; margin-top: 4px; color: #294b47; font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }

.task-dobby-context,
.task-dobby-flow {
  width: min(820px, calc(96% - 39px));
  box-sizing: border-box;
  margin-left: 39px;
  padding: 13px 14px;
  border-left: 3px solid #0f766e;
  border-radius: 4px 8px 8px 4px;
  background: #eff7f4;
}
.task-dobby-context header,
.task-dobby-flow header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.task-dobby-context header span,
.task-dobby-flow header span { display: block; color: #0f766e; font-size: 12px; font-weight: 800; letter-spacing: .04em; }
.task-dobby-context header strong,
.task-dobby-flow header strong { display: block; margin-top: 3px; color: #234a46; font-size: 12px; }
.task-dobby-context > p { margin: 10px 0; color: #536d68; font-size: 12px; line-height: 1.6; }
.task-context-facts { display: grid; grid-template-columns: 1.25fr .55fr .55fr; gap: 7px; }
.task-context-facts > span { min-width: 0; padding: 8px 9px; border-radius: 5px; background: rgba(255,255,255,.78); }
.task-context-facts small { display: block; color: #7b8e89; font-size: 12px; }
.task-context-facts strong { display: block; overflow: hidden; margin-top: 4px; color: #31534f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }

.task-dobby-flow { border-left-color: #c95622; background: #fff8f3; }
.task-dobby-flow header > small { color: #8b817a; font-size: 12px; }
.task-dobby-flow ol { display: grid; gap: 5px; margin: 11px 0 0; padding: 0; list-style: none; }
.task-dobby-flow li { display: grid; min-height: 39px; grid-template-columns: 24px minmax(0, 1fr) auto auto; align-items: center; gap: 8px; padding: 5px 7px; border-radius: 5px; background: rgba(255,255,255,.83); }
.task-dobby-flow li > span { display: grid; width: 22px; height: 22px; place-items: center; border-radius: 5px; color: #5f7a74; background: #e3ece8; font-size: 12px; font-weight: 820; }
.task-dobby-flow li.completed > span { color: #fff; background: #0f766e; }
.task-dobby-flow li.blocked > span { color: #fff; background: #c95622; }
.task-dobby-flow li div { min-width: 0; }
.task-dobby-flow li div strong { display: block; overflow: hidden; color: #294945; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-dobby-flow li div small { display: block; overflow: hidden; margin-top: 2px; color: #82918d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-dobby-flow li > em { color: #758a84; font-size: 12px; font-style: normal; white-space: nowrap; }
.task-dobby-flow li > button { border: 1px solid #c9dbd5; border-radius: 5px; padding: 5px 7px; color: #0f766e; background: #fff; font: inherit; font-size: 12px; font-weight: 760; cursor: pointer; }

.task-dobby-suggestions { display: flex; flex-wrap: wrap; gap: 6px; width: min(820px, calc(96% - 39px)); margin-left: 39px; }
.task-dobby-suggestions button { padding: 7px 9px; border: 1px solid #c9ddd7; border-radius: 6px; color: #0e6c65; background: #fff; font: inherit; font-size: 12px; font-weight: 760; cursor: pointer; transition: transform .18s ease, border-color .18s ease, background .18s ease; }
.task-dobby-suggestions button:hover { transform: translateY(-1px); border-color: #0f766e; background: #f2f9f6; }

.task-dobby-composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 82px;
  gap: 8px;
  padding: 12px 16px 15px;
  border-top: 1px solid #e1e9e6;
  background: rgba(252,253,253,.95);
}
.task-dobby-composer textarea { min-height: 46px; max-height: 92px; box-sizing: border-box; padding: 10px 11px; border: 1px solid #cddbd7; border-radius: 7px; color: #23423f; background: #fff; font: inherit; font-size: 12px; line-height: 1.5; resize: none; transition: border-color .18s ease, box-shadow .18s ease; }
.task-dobby-composer textarea:focus { outline: 0; border-color: #0f766e; box-shadow: 0 0 0 3px rgba(15,118,110,.1); }
.task-dobby-composer button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 7px; color: #fff; background: #c95622; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; transition: transform .18s ease, background .18s ease; }
.task-dobby-composer button:hover { transform: translateY(-1px); background: #b94a1b; }
.task-dobby-composer button:disabled { opacity: .42; cursor: not-allowed; transform: none; }
.task-dobby-empty { place-content: center; justify-items: center; color: #78908a; text-align: center; }
.task-dobby-empty h2 { margin: 12px 0 0; color: #284a46; font-size: 17px; }
.task-dobby-empty p { margin: 6px 0 0; font-size: 12px; }

.task-command-page button:focus-visible,
.task-command-page a:focus-visible,
.task-command-page textarea:focus-visible { outline: 2px solid #0f766e; outline-offset: 2px; }

/* Task management — lifecycle workspace aligned with the prototype */
.task-management-page {
  display: grid;
  height: calc(100dvh - var(--header-height, 56px) - 36px);
  min-height: 680px;
  min-width: 0;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  overflow: hidden;
  container-name: task-management;
  container-type: inline-size;
}
.task-management-nav {
  display: flex;
  min-height: 42px;
  align-items: center;
  padding: 3px;
  border: 1px solid rgba(25, 61, 58, .11);
  border-radius: 8px;
  background: rgba(255,255,255,.94);
  box-shadow: 0 5px 16px rgba(27, 55, 52, .04);
}
.task-management-nav nav { display: flex; min-width: 0; align-items: center; gap: 2px; }
.task-management-nav nav button {
  display: inline-flex;
  min-width: 0;
  min-height: 34px;
  align-items: center;
  gap: 8px;
  padding: 5px 13px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #58716b;
  background: transparent;
  font: inherit;
  cursor: pointer;
  transition: color .18s ease, border-color .18s ease, background .18s ease;
}
.task-management-nav nav button:hover { color: #0f766e; background: #f0f7f4; }
.task-management-nav nav button.active { border-color: #cfe2dc; color: #0d625b; background: #e9f4f0; box-shadow: inset 0 -2px 0 #0f766e; }
.task-management-nav nav button > span { display: inline-flex; min-width: 0; align-items: center; gap: 7px; font-size: 13px; font-weight: 820; }
.task-management-nav nav button b { min-width: 22px; padding: 3px 5px; border-radius: 5px; color: #49645e; background: #e7efec; font-size: 12px; line-height: 1; text-align: center; font-variant-numeric: tabular-nums; }
.task-management-nav nav button.active b { color: #0d625b; background: #fff; }

.task-mine-view,
.task-history-view,
.task-assign-view { min-height: 0; }
.task-mine-view { display: grid; grid-template-rows: minmax(0, 1fr); }
.task-mine-workbench {
  height: 100%;
  border: 1px solid rgba(20, 45, 54, .1);
  border-radius: 9px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 12px 30px rgba(25, 53, 50, .055);
}
.task-mine-queue-empty {
  grid-row: 1 / -1;
}
.task-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: clamp(24px, 6vh, 48px) 24px;
  color: #81948e;
  text-align: center;
}
.task-empty-robot {
  position: relative;
  display: grid;
  width: 54px;
  height: 54px;
  place-items: center;
  border: 1px solid rgba(15, 118, 110, .16);
  border-radius: 18px;
  color: #0f766e;
  background:
    radial-gradient(circle at 30% 22%, rgba(255, 255, 255, .95), transparent 42%),
    #eaf5f2;
  box-shadow: 0 12px 28px rgba(31, 85, 77, .12), inset 0 0 0 1px rgba(255, 255, 255, .62);
  transform: rotate(-2deg);
}
.task-empty-robot .n-icon { transform: rotate(2deg); }
.task-empty-robot > span {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 9px;
  height: 9px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: #27a478;
  box-shadow: 0 0 0 3px rgba(39, 164, 120, .1);
}
.task-empty-kicker {
  margin-top: 14px;
  color: #5d7771;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .04em;
}
.task-empty-title {
  max-width: 28ch;
  margin-top: 5px;
  color: #31524c;
  font-size: 14px;
  font-weight: 780;
  line-height: 1.45;
  text-wrap: balance;
}
.task-empty-copy {
  max-width: 32ch;
  margin: 7px 0 0;
  color: #7a8f89;
  font-size: 12px;
  line-height: 1.65;
  text-wrap: pretty;
}
.task-mine-ai-empty { grid-template-rows: none; }
.task-mine-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 15px 18px 16px;
  overflow: hidden;
  border-radius: 9px;
  background:
    radial-gradient(circle at 86% 5%, rgba(15,118,110,.12), transparent 18rem),
    linear-gradient(110deg, #fff, #f4f9f7);
  box-shadow: inset 0 0 0 1px rgba(25, 61, 58, .09);
}
.task-mine-intro > div { min-width: 0; }
.task-mine-intro > div > span,
.task-assign-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .05em; }
.task-mine-intro h1,
.task-assign-head h1 { margin: 4px 0; color: #143531; font-size: 20px; font-weight: 860; letter-spacing: -.02em; line-height: 1.25; }
.task-mine-intro p,
.task-assign-head p { max-width: 68ch; margin: 0; color: #6b817b; font-size: 12px; line-height: 1.55; }
.task-mine-intro dl { display: grid; flex: 0 0 auto; grid-template-columns: repeat(3, minmax(80px, 1fr)); gap: 1px; margin: 0; overflow: hidden; border: 1px solid #dfe8e5; border-radius: 7px; background: #dfe8e5; }
.task-mine-intro dl div { display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 9px; padding: 9px 11px; background: rgba(255,255,255,.88); }
.task-mine-intro dt { color: #738680; font-size: 12px; white-space: nowrap; }
.task-mine-intro dd { margin: 0; color: #214641; font-size: 18px; font-weight: 860; font-variant-numeric: tabular-nums; }
.task-mine-intro .danger dd { color: #c65327; }

.task-lifecycle-board { display: grid; min-height: 0; grid-template-columns: minmax(0, 1.13fr) minmax(360px, .87fr); grid-template-rows: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.task-life-group { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid #dfe8e5; border-radius: 9px; background: rgba(255,255,255,.93); }
.task-life-group.primary { grid-row: 1 / 3; }
.task-life-group > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 13px 15px 12px; border-bottom: 1px solid #e4ebe9; background: #f9fbfa; }
.task-life-group > header span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .05em; }
.task-life-group.overdue > header span { color: #bd4a22; }
.task-life-group > header h2 { margin: 3px 0 2px; color: #21433f; font-size: 14px; }
.task-life-group > header p { margin: 0; color: #7b8d88; font-size: 12px; }
.task-life-group > header > strong { display: grid; min-width: 27px; height: 27px; place-items: center; border-radius: 6px; color: #0f766e; background: #e2f1ec; font-size: 12px; font-variant-numeric: tabular-nums; }
.task-life-group.overdue > header > strong { color: #bd4a22; background: #fae9e1; }
.task-life-list { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.task-life-card { position: relative; padding: 13px 14px 12px; border-bottom: 1px solid #e5ecea; background: #fff; transition: background .18s ease; }
.task-life-card:last-child { border-bottom: 0; }
.task-life-card:hover { background: #f8fbfa; }
.task-life-group.primary .task-life-card::before { position: absolute; inset: 12px auto 12px 0; width: 3px; border-radius: 0 3px 3px 0; content: ''; background: #0f766e; }
.task-life-group.overdue .task-life-card::before { background: #c95622; }
.task-life-card-top { display: flex; align-items: center; gap: 6px; }
.task-life-card-top > span { color: #0f766e; font-size: 12px; font-weight: 800; }
.task-life-card-top em { padding: 3px 6px; border-radius: 4px; color: #0f766e; background: #e4f3ee; font-size: 12px; font-style: normal; font-weight: 800; }
.task-life-card-top em.danger { color: #bd4822; background: #fae5dc; }
.task-life-card-top em.attention { color: #976407; background: #fff0cf; }
.task-life-card-top em.complete { color: #57726b; background: #e8eeec; }
.task-life-card-top small { margin-left: auto; overflow: hidden; color: #81928e; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-life-card h3 { overflow: hidden; margin: 8px 0 4px; color: #183a37; font-size: 13px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.task-life-card > p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin: 0; color: #70837e; font-size: 12px; line-height: 1.5; -webkit-line-clamp: 2; }
.task-current-node { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 9px; margin-top: 9px; padding: 8px 9px; border-left: 2px solid #8cb8ae; background: #f2f7f5; }
.task-current-node span { grid-row: 1 / 3; align-self: center; color: #0f766e; font-size: 12px; font-weight: 800; }
.task-current-node strong { overflow: hidden; color: #31514d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-current-node small { overflow: hidden; color: #81918d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-line { display: flex; gap: 0; margin: 9px 0 0; padding: 0; overflow-x: auto; list-style: none; scrollbar-width: none; }
.task-flow-line::-webkit-scrollbar { display: none; }
.task-flow-line li { position: relative; display: grid; flex: 1 0 74px; justify-items: center; gap: 4px; color: #84958f; font-size: 12px; text-align: center; }
.task-flow-line li:not(:last-child)::after { position: absolute; top: 9px; right: -50%; width: 100%; height: 1px; content: ''; background: #d5e1dd; }
.task-flow-line i { position: relative; z-index: 1; display: grid; width: 19px; height: 19px; place-items: center; border-radius: 5px; color: #6d817b; background: #e6eeeb; font-size: 12px; font-style: normal; font-weight: 800; }
.task-flow-line li.completed i { color: #fff; background: #0f766e; }
.task-flow-line li.processing i { color: #fff; background: #c95622; }
.task-flow-line li span { overflow: hidden; width: 100%; text-overflow: ellipsis; white-space: nowrap; }
.task-life-card footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; }
.task-life-card footer > span { overflow: hidden; color: #7a8e88; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-life-card footer button { flex: 0 0 auto; border: 1px solid #bed5cf; border-radius: 5px; padding: 6px 9px; color: #0f766e; background: #fff; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; transition: transform .18s ease, border-color .18s ease, background .18s ease; }
.task-life-card footer button:hover { transform: translateY(-1px); border-color: #0f766e; background: #eff8f5; }
.task-life-empty { display: grid; min-height: 120px; place-content: center; justify-items: center; gap: 8px; color: #859690; font-size: 12px; text-align: center; }
.task-life-empty strong { color: #627872; font-weight: 650; }

.task-history-view { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; }
.task-assign-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 14px 17px; border: 1px solid #dfe8e5; border-radius: 9px; background: #fff; }
.task-history-search { display: grid; grid-template-columns: minmax(260px, 1fr) 180px 180px auto; align-items: end; gap: 9px; padding: 12px 14px; border: 1px solid #dfe8e5; border-radius: 8px; background: #f8faf9; }
.task-history-search label { display: grid; gap: 5px; color: #647b75; font-size: 12px; }
.task-history-search input { width: 100%; min-height: 34px; box-sizing: border-box; border: 1px solid #ccdbd7; border-radius: 5px; padding: 0 9px; color: #294844; background: #fff; font: inherit; font-size: 12px; }
.task-history-search button { min-height: 34px; border: 1px solid #c9dad5; border-radius: 5px; padding: 0 11px; color: #48665f; background: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
.task-history-results { min-height: 0; overflow-y: auto; border: 1px solid #dfe8e5; border-radius: 9px; background: #fff; }
.task-history-table-head,
.task-history-results > article { display: grid; grid-template-columns: minmax(260px, 1.5fr) .55fr .55fr .72fr .5fr auto; align-items: center; gap: 12px; }
.task-history-table-head { position: sticky; top: 0; z-index: 1; padding: 10px 13px; border-bottom: 1px solid #dfe8e5; color: #748983; background: #f4f8f6; font-size: 12px; font-weight: 780; }
.task-history-results > article { min-height: 66px; padding: 9px 13px; border-bottom: 1px solid #e7edeb; color: #5e756f; font-size: 12px; }
.task-history-results > article:last-of-type { border-bottom: 0; }
.task-history-results > article:hover { background: #f8fbfa; }
.task-history-results article > div { min-width: 0; }
.task-history-results article strong { display: block; overflow: hidden; color: #284a46; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-history-results article small { display: block; overflow: hidden; margin-top: 4px; color: #85958f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-history-results article time { font-variant-numeric: tabular-nums; }
.task-history-results article em { width: fit-content; padding: 4px 6px; border-radius: 4px; color: #55716a; background: #e8efed; font-size: 12px; font-style: normal; }
.task-history-results article em.closed { color: #0f766e; background: #e4f2ed; }
.task-history-results article button { border: 0; padding: 5px 0; color: #0f766e; background: transparent; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; }
.task-history-no-result { display: grid; min-height: 260px; place-content: center; justify-items: center; color: #83958f; text-align: center; }
.task-history-no-result strong { margin-top: 9px; color: #45615b; font-size: 13px; }
.task-history-no-result p { margin: 5px 0 0; font-size: 12px; }

.task-assign-view { display: grid; min-width: 0; grid-template-rows: minmax(0, 1fr); overflow: hidden; }
.task-assign-head { align-items: center; background: radial-gradient(circle at 90% 0%, rgba(15,118,110,.1), transparent 20rem), #fff; }
.task-assign-head span { display: inline-flex; align-items: center; gap: 6px; }
.task-assign-head > small { color: #748a84; font-size: 12px; }
.task-flow-scroll {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  border-radius: 9px;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}
.task-flow-scroll:focus-visible { outline: 2px solid rgba(15,118,110,.34); outline-offset: -2px; }
.task-flow-modal.task-flow-inline { width: 100%; height: 100%; max-height: none; box-sizing: border-box; border: 1px solid #dbe6e2; border-radius: 9px; background: #fff; box-shadow: 0 12px 30px rgba(25,53,50,.055); }

@media (min-width: 721px) {
  .task-flow-inline { min-width: 1120px; min-height: 720px; }
  .task-flow-inline .task-flow-body { grid-template-columns: minmax(320px, 32%) minmax(780px, 1fr); }
  .task-flow-inline .task-flow-canvas-body { grid-template-columns: minmax(540px, 1fr) minmax(210px, .38fr); }
}

@container task-management (max-width: 1050px) {
  .task-assign-head > small { display: none; }
  .task-assign-head h1 { font-size: 18px; }
}

@container task-management (max-width: 820px) {
  .task-mine-intro { align-items: flex-start; flex-direction: column; }
  .task-mine-intro dl { width: 100%; }
}

.task-disposition-backdrop { position: fixed; inset: 0; z-index: 30; background: rgba(17,35,36,.38); backdrop-filter: blur(2px); }
.task-disposition-drawer { position: absolute; inset: 0 0 0 auto; display: grid; width: min(640px, 94vw); grid-template-rows: auto minmax(0,1fr) auto; background: #fff; box-shadow: -22px 0 55px rgba(14,37,38,.22); animation: task-drawer-in .24s ease both; }
@keyframes task-drawer-in { from { transform: translateX(32px); opacity: .6; } to { transform: translateX(0); opacity: 1; } }
.task-disposition-drawer > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 18px 20px 16px; border-bottom: 1px solid #dfe8e5; background: #f8faf9; }
.task-disposition-drawer > header > div { min-width: 0; }
.task-disposition-drawer > header span { color: #0f766e; font-size: 12px; font-weight: 800; }
.task-disposition-drawer > header h2 { margin: 6px 0 4px; color: #173a36; font-size: 18px; line-height: 1.35; }
.task-disposition-drawer > header p { margin: 0; color: #748983; font-size: 12px; }
.task-disposition-drawer > header button { border: 1px solid #cddbd7; border-radius: 5px; padding: 6px 9px; color: #536f68; background: #fff; font: inherit; font-size: 12px; cursor: pointer; }
.task-disposition-body { min-height: 0; padding: 16px 20px 24px; overflow-y: auto; }
.task-disposition-ai { display: grid; grid-template-columns: 32px minmax(0,1fr); gap: 10px; padding: 13px; border-left: 3px solid #0f766e; border-radius: 4px 8px 8px 4px; background: #eff8f5; }
.task-disposition-bot { display: grid; width: 31px; height: 31px; place-items: center; border-radius: 7px; color: #e0f1ed; background: #173f3d; }
.task-disposition-ai strong { color: #214944; font-size: 12px; }
.task-disposition-ai p { margin: 5px 0; color: #4e6a64; font-size: 12px; line-height: 1.6; }
.task-disposition-ai small { color: #78908a; font-size: 12px; line-height: 1.5; }
.task-disposition-flow,
.task-disposition-form { margin-top: 17px; }
.task-disposition-section-title { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.task-disposition-section-title span { color: #0f766e; font-size: 12px; font-weight: 820; }
.task-disposition-section-title strong { color: #6d837d; font-size: 12px; font-weight: 650; }
.task-disposition-flow ol { display: grid; gap: 5px; margin: 0; padding: 0; list-style: none; }
.task-disposition-flow li { display: grid; grid-template-columns: 26px minmax(0,1fr) auto auto; align-items: center; gap: 8px; min-height: 43px; padding: 5px 8px; border-radius: 6px; background: #f6f8f7; }
.task-disposition-flow li > span { display: grid; width: 23px; height: 23px; place-items: center; border-radius: 5px; color: #637c75; background: #e1eae7; font-size: 12px; font-weight: 800; }
.task-disposition-flow li.completed > span { color: #fff; background: #0f766e; }
.task-disposition-flow li div { min-width: 0; }
.task-disposition-flow li div strong { display: block; overflow: hidden; color: #35534f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-disposition-flow li div small { display: block; overflow: hidden; margin-top: 3px; color: #85958f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-disposition-flow li div .task-disposition-reopen-hint { color: #b45309; font-size: 12px; font-weight: 700; text-overflow: clip; white-space: normal; }
.task-disposition-flow li em { color: #738983; font-size: 12px; font-style: normal; }
.task-disposition-flow li button { border: 1px solid #c8d9d4; border-radius: 5px; padding: 5px 7px; color: #0f766e; background: #fff; font: inherit; font-size: 12px; cursor: pointer; }
.task-disposition-form textarea { width: 100%; min-height: 92px; box-sizing: border-box; padding: 10px; border: 1px solid #cddbd7; border-radius: 6px; color: #294844; background: #fff; font: inherit; font-size: 12px; line-height: 1.6; resize: vertical; }
.task-disposition-files,
.task-disposition-forward { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding: 9px 10px; border: 1px solid #dde7e4; border-radius: 6px; background: #fafcfb; }
.task-disposition-files input { display: none; }
.task-disposition-files > span { display: inline-flex; align-items: center; gap: 5px; color: #0f766e; font-size: 12px; font-weight: 780; cursor: pointer; }
.task-disposition-files small { margin-left: auto; color: #82948f; font-size: 12px; }
.task-disposition-forward > span { color: #617871; font-size: 12px; }
.task-disposition-forward select { flex: 1; min-width: 0; border: 0; color: #31514c; background: transparent; font: inherit; font-size: 12px; }
.task-disposition-drawer > footer { display: flex; align-items: center; justify-content: flex-end; gap: 7px; padding: 12px 20px 15px; border-top: 1px solid #dfe8e5; background: #f9fbfa; }
.task-disposition-drawer > footer button,
.task-disposition-drawer > footer a { display: inline-flex; min-height: 34px; align-items: center; justify-content: center; padding: 0 11px; border: 1px solid #cadad5; border-radius: 5px; color: #4a6861; background: #fff; font: inherit; font-size: 12px; font-weight: 760; text-decoration: none; cursor: pointer; }
.task-disposition-drawer > footer .task-disposition-submit { border-color: #c95622; color: #fff; background: #c95622; }
.task-disposition-drawer > footer .task-disposition-submit:disabled { opacity: .5; cursor: wait; }

.task-management-page button:focus-visible,
.task-management-page a:focus-visible,
.task-management-page input:focus-visible,
.task-management-page select:focus-visible,
.task-management-page textarea:focus-visible { outline: 2px solid #0f766e; outline-offset: 2px; }

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
  font-size: 12px;
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
.task-flow-trigger-grid { display:flex; flex-wrap:wrap; align-items:end; gap:9px; }
.task-flow-trigger-grid>.form-field { flex:0 1 190px; }
.task-flow-trigger-grid>.form-field:nth-child(2) { flex-basis:230px; }
.task-flow-trigger-grid>.task-flow-cc-field { flex:1 1 240px; }
.task-flow-interval-field { flex-basis:230px !important; }
.task-flow-interval-field>span { display:grid; grid-template-columns:minmax(72px,.65fr) minmax(100px,1fr); gap:6px; }
.task-flow-trigger-preview { display:flex; flex:0 1 auto; min-width:0; align-items:center; gap:8px; padding:6px 10px; border-left:2px solid #58a698; background:#eef6f3; }
.task-flow-trigger-preview span { flex:0 0 auto; color:#64817b; font-size:12px; }
.task-flow-trigger-preview strong { overflow:hidden; color:#164a43; font-size:12px; font-variant-numeric:tabular-nums; text-overflow:ellipsis; white-space:nowrap; }
.task-flow-body { display: grid; flex: 1 1 auto; min-height: 0; grid-template-columns: minmax(330px, 31%) minmax(0, 1fr); }
.task-flow-brief { display: flex; min-height: 0; flex-direction: column; overflow: hidden; padding: 16px; border-right: 1px solid #e1e9e7; background: #f7faf9; }
.task-flow-mode-switch { display: grid; grid-template-columns: 1fr 1fr; padding: 3px; border: 1px solid #dbe6e2; border-radius: 8px; background: #eaf1ef; }
.task-flow-mode-switch button { border: 0; border-radius: 6px; padding: 9px 12px; color: #5b716e; background: transparent; font: inherit; font-size: 13px; font-weight: 750; cursor: pointer; }
.task-flow-mode-switch button.active { color: #fff; background: #173f3e; box-shadow: 0 3px 8px rgba(23,63,62,.17); }
.task-flow-generator { margin-top: 12px; padding: 14px; border: 1px solid #dde8e5; border-radius: 9px; background: #fff; }
.dobby-generator { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; border-color: rgba(15,118,110,.26); background: linear-gradient(145deg, #f2fbf8, #fff 58%); }
.task-flow-section-title,.task-flow-editor-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.task-flow-section-title > div,.task-flow-editor-head > div { display: grid; gap: 3px; }
.task-flow-section-title span,.task-flow-editor-head span,.task-flow-canvas-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }
.task-flow-section-title strong,.task-flow-editor-head strong { color: #173235; font-size: 14px; }
.task-flow-section-title em,.task-flow-editor-head em { color: #76908b; font-size: 12px; font-style: normal; white-space: nowrap; }
.task-flow-generator textarea { width: 100%; min-height: 100px; box-sizing: border-box; padding: 10px 11px; border: 1px solid #cadbd6; border-radius: 7px; color: #173235; background: #fff; font: inherit; font-size: 13px; line-height: 1.6; resize: none; }
.dobby-generator textarea { flex: 1 1 auto; min-height: 0; }
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
.task-step-list li > span { display: grid; width: 19px; height: 19px; place-items: center; border-radius: 50%; background: #dce6e2; color: #48625e; font-size: 12px; font-weight: 800; }.task-step-list li.completed > span { background: #0f766e; color: #fff; }.task-step-list li.blocked { background: #fff5ed; }.task-step-list em { font-style: normal; color: var(--text-muted); }.task-step-list button { border: 0; border-radius: 4px; padding: 4px 6px; background: #e9f3f0; color: #0f766e; font-size: 12px; font-weight: 700; cursor: pointer; }
.task-history-modal { width:min(720px,100%); max-height:min(82dvh,760px); overflow:hidden; }
.task-history-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; overflow:hidden; margin-bottom:16px; border:1px solid #dfe8e5; border-radius:8px; background:#dfe8e5; }
.task-history-summary>div { display:grid; gap:5px; padding:12px 14px; background:#f7faf9; }
.task-history-summary span { color:var(--text-muted); font-size: 12px; }
.task-history-summary strong { overflow:hidden; color:#173235; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.task-history-body { min-height:250px; max-height:46dvh; overflow-y:auto; padding:2px 4px 2px 0; }
.task-history-timeline { display:grid; gap:0; margin:0; padding:0; list-style:none; }
.task-history-timeline li { position:relative; display:grid; grid-template-columns:24px minmax(0,1fr); gap:10px; min-height:72px; }
.task-history-timeline li:not(:last-child)::after { position:absolute; top:20px; bottom:-2px; left:8px; width:1px; content:''; background:#cbdcd7; }
.task-history-timeline i { position:relative; z-index:1; display:block; width:17px; height:17px; margin-top:2px; border:4px solid #dff0eb; border-radius:50%; background:#0f766e; box-sizing:border-box; }
.task-history-timeline li>div { padding:0 2px 15px 0; }
.task-history-timeline header { display:flex; align-items:center; justify-content:space-between; gap:14px; }
.task-history-timeline header strong { color:#173235; font-size:13px; }
.task-history-timeline time { flex:0 0 auto; color:var(--text-muted); font-size: 12px; font-variant-numeric:tabular-nums; }
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
.document-intake-panel span { color: var(--color-primary); font-size: 12px; font-weight: 800; letter-spacing: .06em; }
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
  font-size: 12px;
  font-weight: 760;
}
.status-pill {
  padding: 2px 8px;
  border-radius: 4px;
  background: #eef4f1;
  color: #173235;
  font-size: 12px;
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
.status-side-panel header span { display: block; color: #0f766e; font-size: 12px; font-weight: 800; letter-spacing: .05em; }
.project-status-heading h1 { margin: 4px 0; color: #173235; font-size: 21px; line-height: 1.25; }
.project-status-heading p { max-width: 68ch; margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.project-status-heading > small { flex: 0 0 auto; margin-bottom: 3px; color: var(--text-muted); font-size: 12px; }

.project-kpi-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.project-kpi-strip article { position: relative; min-width: 0; padding: 14px 15px 13px; border-right: 1px solid #edf1ef; }
.project-kpi-strip article:last-child { border-right: 0; }
.project-kpi-strip article::before { content: ''; position: absolute; top: 13px; bottom: 13px; left: 0; width: 3px; border-radius: 0 999px 999px 0; background: #0f766e; opacity: .9; }
.project-kpi-strip article.orange::before { background: #d97706; }
.project-kpi-strip article.red::before { background: #c2410c; }
.project-kpi-strip article.blue::before { background: #2563eb; }
.project-kpi-strip span { display: block; overflow: hidden; color: var(--text-secondary); font-size: 12px; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
.project-kpi-strip strong { display: block; margin: 7px 0 3px; color: #173235; font-size: 23px; line-height: 1; font-variant-numeric: tabular-nums; }
.project-kpi-strip small { display: block; overflow: hidden; color: var(--text-muted); font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }

.project-health-band { display: grid; grid-template-columns: minmax(250px, .78fr) minmax(0, 2.22fr); overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; }
.project-health-summary { padding: 15px 17px; border-right: 1px solid #edf1ef; background: #f8fbfa; }
.project-health-summary span { display: block; color: #0f766e; font-size: 12px; font-weight: 800; letter-spacing: .04em; }
.project-health-summary strong { display: block; margin: 6px 0 5px; color: #173235; font-size: 17px; }
.project-health-summary p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.project-health-data { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; }
.project-health-data > div { min-width: 0; padding: 15px 17px; border-right: 1px solid #edf1ef; }
.project-health-data > div:last-child { border-right: 0; }
.project-health-data dt { overflow: hidden; color: var(--text-secondary); font-size: 12px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.project-health-data dd { margin: 7px 0 4px; color: #173235; font-size: 20px; font-weight: 830; font-variant-numeric: tabular-nums; }
.project-health-data dd.positive { color: #0f766e; }.project-health-data dd.negative { color: #c2410c; }
.project-health-data small { display: block; color: var(--text-muted); font-size: 12px; line-height: 1.45; }
.project-health-data .project-health-conclusion { overflow: hidden; min-height: 24px; margin-top: 5px; color: #0f4c49; font-size: 13px; line-height: 1.45; }

.project-status-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.project-status-tabs button { min-width: 0; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: 7px; background: #fff; color: var(--text-secondary); font: inherit; text-align: left; cursor: pointer; transition: border-color .16s ease, background .16s ease, color .16s ease, transform .16s ease; }
.project-status-tabs button:hover { border-color: rgba(15, 118, 110, .42); transform: translateY(-1px); }
.project-status-tabs button.active { border-color: #0f766e; background: #f0faf7; color: #0c615b; box-shadow: inset 0 0 0 1px rgba(15, 118, 110, .08); }
.project-status-tabs strong { display: block; overflow: hidden; font-size: 12px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.project-status-tabs span { display: block; overflow: hidden; margin-top: 3px; color: var(--text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }

.project-status-content { display: grid; grid-template-columns: minmax(0, 1.72fr) minmax(286px, .72fr); min-height: 0; gap: 12px; align-items: stretch; }
.project-status-main, .project-status-aside { min-width: 0; min-height: 0; }
.project-status-aside { display: grid; gap: 12px; }
.status-workspace, .status-side-panel { overflow: hidden; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.status-workspace { min-height: 0; }
.status-workspace-head, .status-side-panel header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 15px 17px 13px; border-bottom: 1px solid #edf1ef; }
.status-workspace-head h2, .status-side-panel h2 { margin: 5px 0 3px; color: #173235; font-size: 16px; line-height: 1.25; }
.status-workspace-head p { max-width: 60ch; margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
.status-link-action, .status-side-panel header a, .status-side-panel header button, .status-row-action { flex: 0 0 auto; border: 1px solid rgba(15, 118, 110, .25); border-radius: 5px; padding: 6px 9px; background: #fff; color: #0e675f; font: inherit; font-size: 12px; font-weight: 780; line-height: 1.2; text-decoration: none; cursor: pointer; }
.status-link-action:hover, .status-side-panel header a:hover, .status-side-panel header button:hover, .status-row-action:hover { border-color: #0f766e; background: #f1faf8; }
.status-empty { display: grid; min-height: 290px; place-items: center; box-sizing: border-box; margin: 0; padding: 34px; color: var(--text-muted); font-size: 13px; line-height: 1.65; text-align: center; }

.status-execution-table, .process-supervision-table { overflow-x: auto; }
.status-execution-head, .status-execution-table article { display: grid; grid-template-columns: 82px minmax(180px, 1.45fr) minmax(150px, 1.05fr) 92px 96px 92px; min-width: 770px; align-items: center; gap: 13px; padding: 11px 17px; }
.status-execution-head { color: var(--text-muted); font-size: 12px; font-weight: 760; background: #f8faf9; border-bottom: 1px solid #edf1ef; }
.status-execution-table article { min-height: 59px; border-bottom: 1px solid #edf1ef; color: var(--text-secondary); font-size: 12px; }
.status-execution-table article:last-child { border-bottom: 0; }
.status-execution-table article > div { min-width: 0; }.status-execution-table article strong { display: block; overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-execution-table article small { display: block; margin-top: 3px; color: var(--text-muted); font-size: 12px; }
.execution-status { width: fit-content; border-radius: 999px; padding: 4px 7px; background: #f0f3f2; color: #536964; font-size: 12px; font-weight: 780; white-space: nowrap; }.execution-status.overdue { background: #fff0e7; color: #b84e18; }.execution-status.processing { background: #e8f6f2; color: #0f766e; }.execution-status.waiting_confirm { background: #eef5ff; color: #2563a8; }.execution-status.done { background: #edf7ef; color: #39834c; }.execution-status.need_more_info { background: #fff8df; color: #9a6700; }.status-execution-table .overdue { color: #bd4d17; font-weight: 750; }

.status-latest-list { padding: 3px 17px; }
.status-latest-list article { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto; align-items: center; gap: 10px; min-height: 61px; border-bottom: 1px solid #edf1ef; }
.status-latest-list article:last-of-type { border-bottom: 0; }.status-event-dot { width: 7px; height: 7px; border-radius: 50%; background: #0f766e; }.status-event-dot.orange { background: #d97706; }.status-event-dot.red { background: #c2410c; }.status-event-dot.blue { background: #2563eb; }
.status-latest-list article > div { min-width: 0; }.status-latest-list strong { display: block; overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-latest-list p { overflow: hidden; max-width: 56ch; margin: 3px 0 0; color: var(--text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-latest-list time { color: var(--text-muted); font-size: 12px; white-space: nowrap; }

.process-supervision-head, .process-supervision-table article { display: grid; grid-template-columns: minmax(185px, 1.18fr) 150px minmax(118px, .82fr) minmax(125px, .9fr) minmax(120px, .88fr) minmax(130px, 1fr); min-width: 920px; gap: 12px; align-items: center; padding: 11px 17px; }
.process-supervision-head { border-bottom: 1px solid #edf1ef; background: #f8faf9; color: var(--text-muted); font-size: 12px; font-weight: 760; }.process-supervision-table article { min-height: 60px; border-bottom: 1px solid #edf1ef; color: var(--text-secondary); font-size: 12px; }.process-supervision-table article:last-child { border-bottom: 0; }.process-supervision-table article > div { min-width: 0; }.process-supervision-table article strong { display: block; overflow: hidden; margin-top: 2px; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.process-supervision-table article > div:first-child small { color: var(--text-muted); font-family: var(--font-mono, monospace); font-size: 12px; }
.process-progress { display: grid; grid-template-columns: auto minmax(35px, 1fr); gap: 4px 7px; align-items: center; }.process-progress b { font-size: 12px; color: #173235; }.process-progress i { display: block; height: 5px; overflow: hidden; border-radius: 999px; background: #e6ece9; }.process-progress i em { display: block; height: 100%; border-radius: inherit; background: #0f766e; }.process-progress small { grid-column: 1 / -1; color: var(--text-muted); font-size: 12px; }.process-risk { color: #4e6964; }.process-risk.critical,.process-risk.high { color: #b94b18; font-weight: 760; }.process-risk.medium { color: #b77800; }

.status-change-list { padding: 2px 17px; }.status-change-list article { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 12px; min-height: 71px; border-bottom: 1px solid #edf1ef; }.status-change-list article:last-child { border-bottom: 0; }.status-change-list article > div { min-width: 0; }.status-change-list span { display: block; color: #0f766e; font-size: 12px; font-weight: 780; }.status-change-list strong { display: block; overflow: hidden; margin-top: 3px; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.status-change-list p { overflow: hidden; max-width: 58ch; margin: 3px 0 0; color: var(--text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.status-change-list time { color: var(--text-muted); font-size: 12px; white-space: nowrap; }.status-change-list em { border-radius: 999px; padding: 4px 7px; background: #f0f5f3; color: #41615b; font-size: 12px; font-style: normal; font-weight: 760; white-space: nowrap; }

.status-side-panel header { padding: 14px 15px 11px; }.status-side-panel h2 { font-size: 14px; }.status-side-panel header a, .status-side-panel header button { padding: 5px 7px; font-size: 12px; }.risk-window-list { padding: 0 15px 8px; }.risk-window-list article { padding: 12px 0; border-bottom: 1px solid #edf1ef; }.risk-window-list article:last-child { border-bottom: 0; }.risk-window-list article > div { display: flex; align-items: center; gap: 7px; }.risk-indicator { width: 7px; height: 7px; border-radius: 50%; background: #84958f; }.risk-indicator.critical { background: #bd4c1a; }.risk-indicator.high { background: #e08416; }.risk-indicator.medium { background: #d1a000; }.risk-window-list strong { overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.risk-window-list dl { display: grid; gap: 4px; margin: 8px 0; }.risk-window-list dl div { display: grid; grid-template-columns: 55px minmax(0, 1fr); gap: 7px; }.risk-window-list dt { color: var(--text-muted); font-size: 12px; }.risk-window-list dd { overflow: hidden; margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }.risk-window-list .status-row-action { display: inline-block; padding: 4px 7px; font-size: 12px; }
.status-side-empty { margin: 0; padding: 24px 15px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }.change-preview-list { padding: 0 15px 8px; }.change-preview-list article { display: grid; gap: 3px; padding: 10px 0; border-bottom: 1px solid #edf1ef; }.change-preview-list article:last-child { border-bottom: 0; }.change-preview-list span { color: #0f766e; font-size: 12px; font-weight: 780; }.change-preview-list strong { overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.change-preview-list small { color: var(--text-muted); font-size: 12px; }

/* 原型项目状态的内容结构：摘要 + 四个完整业务视图 */
.project-summary-panel { padding: 14px 17px; border: 1px solid var(--border-default); border-radius: 9px; background: #fff; box-shadow: 0 7px 20px rgba(20, 49, 48, .035); }
.project-summary-panel header { display: flex; align-items: center; gap: 9px; }.project-summary-panel header span { color: #0f766e; font-size: 12px; font-weight: 800; letter-spacing: .05em; }.project-summary-panel header strong { color: #173235; font-size: 13px; }.project-summary-panel p { margin: 8px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
.project-status-content { display: flex; min-height: 0; }.project-status-main { display: flex; width: 100%; min-height: 0; }.project-status-main > .status-workspace { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.status-latest-card-grid, .process-grid, .status-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px; padding: 14px 16px 16px; }
.status-info-card, .process-card, .task-execution-card { min-width: 0; padding: 13px; border: 1px solid #e4ece9; border-radius: 7px; background: #fbfcfb; }
.status-info-card { display: flex; flex-direction: column; align-items: flex-start; }.status-info-meta { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 8px; }.status-info-meta > span { overflow: hidden; color: #0f766e; font-size: 12px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }.status-info-meta em { flex: 0 0 auto; border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #127265; font-size: 12px; font-style: normal; font-weight: 780; }.status-info-meta em.orange { background: #fff5df; color: #a66a00; }.status-info-meta em.red { background: #fff0e9; color: #bf4a1b; }.status-info-meta em.blue { background: #edf5ff; color: #2563a8; }.status-info-meta em.pending { background: #f0f3f2; color: #536964; }.status-info-meta em.processing { background: #e8f6f2; color: #0f766e; }.status-info-meta em.overdue { background: #fff0e7; color: #b84e18; }.status-info-meta em.waiting_confirm { background: #eef5ff; color: #2563a8; }.status-info-meta em.done { background: #edf7ef; color: #39834c; }.status-info-card > small { display: block; margin-top: 8px; color: var(--text-muted); font-size: 12px; }.status-info-card > strong, .task-execution-card > strong { display: block; overflow: hidden; width: 100%; margin-top: 7px; color: #173235; font-size: 13px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.status-info-card > p, .task-execution-card > p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; -webkit-line-clamp: 2; }.status-info-card .status-row-action, .task-execution-card .status-row-action { margin-top: 11px; }
.process-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.process-card { border-left: 3px solid #b8d8d1; }.process-card.key-process { border-color: #d97706; background: #fffdf8; }.process-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; margin-bottom: 9px; }.process-card-head > div { min-width: 0; }.process-card-head small { display: block; color: var(--text-muted); font-size: 12px; font-family: var(--font-mono, monospace); }.process-card-head strong { display: block; overflow: hidden; margin-top: 2px; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.process-card-head > span { flex: 0 0 auto; border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #0f766e; font-size: 12px; font-weight: 780; }.process-card-head > span.high, .process-card-head > span.critical { background: #fff0e9; color: #b84e18; }.process-card-head > span.medium { background: #fff5df; color: #9a6700; }.process-card p { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.52; }.process-card p b { color: #45635d; font-weight: 780; }.process-card-note { display: block; margin-top: 9px; color: #0f766e; font-size: 12px; font-weight: 750; }
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
.project-kpi-strip span { font-size: 12px; font-weight: 720; }
.project-kpi-strip strong { margin: 4px 0 3px; font-size: 24px; letter-spacing: -.03em; }
.project-kpi-strip small { font-size: 12px; }

.project-health-band { grid-template-columns: minmax(320px, 1.1fr) minmax(0, 2.55fr); border-radius: 8px; box-shadow: 0 8px 24px rgba(24, 54, 51, .045); }
.project-health-summary { display: grid; grid-template-columns: 112px minmax(0, 1fr); align-items: center; gap: 15px; padding: 18px; background: #fff; }
.project-health-gauge { position: relative; display: grid; width: 104px; height: 104px; place-items: center; border-radius: 50%; background: conic-gradient(#0f9d92 var(--health-progress), #e5eeeb 0); }
.project-health-gauge::after { position: absolute; inset: 11px; border-radius: inherit; background: #fff; content: ''; }
.project-health-gauge > div { position: relative; z-index: 1; display: grid; gap: 3px; place-items: center; text-align: center; }
.project-health-gauge strong { margin: 0; color: #0b786f; font-size: 16px; line-height: 1.15; }
.project-health-gauge small { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
.project-health-copy span { color: #193b39; font-size: 14px; font-weight: 800; }
.project-health-copy p { margin: 9px 0 6px; color: var(--text-secondary); font-size: 12px; line-height: 1.65; }
.project-health-copy small { display: block; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
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
.project-status-tabs strong { font-size: 13px; }.project-status-tabs span { margin-top: 2px; font-size: 12px; }

.project-status-content { display: grid; grid-template-columns: minmax(0, 1.82fr) minmax(300px, .78fr); min-height: 0; gap: 12px; }
.project-status-main { display: flex; width: auto; min-width: 0; min-height: 0; }
.project-status-main > .status-workspace { display: flex; flex: 1; min-height: 0; flex-direction: column; }
.project-status-aside { display: grid; grid-template-rows: minmax(0, 1fr) minmax(160px, .52fr); min-height: 0; gap: 12px; }
.status-workspace, .status-side-panel { border-radius: 8px; box-shadow: 0 8px 22px rgba(24, 54, 51, .04); }
.status-workspace-head, .status-side-panel header { align-items: center; padding: 15px 17px 13px; }
.status-workspace-head > div, .status-side-panel header > div { min-width: 0; }
.status-workspace-head h2, .status-side-panel h2 { margin: 3px 0 2px; font-size: 16px; }
.status-workspace-head p { max-width: 72ch; font-size: 12px; }
.status-workspace-head > small, .status-side-panel header > small { flex: 0 0 auto; color: var(--text-muted); font-size: 12px; white-space: nowrap; }
.status-execution-table, .process-supervision-table, .status-latest-list, .status-change-list { flex: 1; min-height: 0; overflow: auto; }
.status-execution-head, .status-execution-table article { grid-template-columns: 76px minmax(195px, 1.46fr) minmax(155px, 1fr) 82px 118px 98px; min-width: 820px; padding: 11px 16px; }
.status-execution-table article { min-height: 66px; }
.status-execution-table article:hover, .process-supervision-table article:hover, .status-latest-list article:hover, .status-change-list article:hover { background: #fbfdfc; }
.status-execution-table article > div { overflow: hidden; }
.status-execution-table article > div:not(:nth-child(2)):not(:nth-child(5)) { display: -webkit-box; -webkit-box-orient: vertical; color: #5b706b; font-size: 12px; line-height: 1.5; -webkit-line-clamp: 2; }
.status-execution-table article > div:nth-child(4) { color: #173235; font-weight: 700; }
.status-execution-table article > div:last-child { color: #46645e; }
.status-execution-table article small { line-height: 1.4; }
.execution-status { padding: 4px 8px; }
.status-latest-list { padding: 2px 17px; }
.status-latest-list article { grid-template-columns: 10px minmax(0, 1fr) auto auto 42px; gap: 10px; min-height: 64px; }
.status-latest-list p { max-width: 54ch; }
.status-latest-list em { border-radius: 999px; padding: 3px 7px; background: #edf7f3; color: #127265; font-size: 12px; font-style: normal; font-weight: 780; white-space: nowrap; }
.status-latest-list em.orange { background: #fff5df; color: #a66a00; }.status-latest-list em.red { background: #fff0e9; color: #bf4a1b; }.status-latest-list em.blue { background: #edf5ff; color: #2563a8; }
.status-row-placeholder { width: 42px; }
.status-row-action { padding: 5px 7px; font-size: 12px; }
.process-supervision-head, .process-supervision-table article { grid-template-columns: minmax(175px, 1.12fr) minmax(165px, 1.06fr) minmax(145px, 1fr) minmax(150px, 1fr) minmax(135px, .92fr) minmax(145px, 1fr); min-width: 1000px; padding: 11px 16px; }
.process-supervision-table article > div:not(:first-child) { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; line-height: 1.5; -webkit-line-clamp: 3; }
.process-progress { display: grid !important; -webkit-line-clamp: unset !important; }
.process-progress small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-change-list { padding: 2px 17px; }
.status-change-list article { min-height: 73px; }
.status-side-panel { display: flex; min-height: 0; flex-direction: column; }
.status-side-panel header { flex: 0 0 auto; }.risk-window-list, .change-preview-list { flex: 1; min-height: 0; overflow-y: auto; }
.risk-window-list article { padding: 12px 0; }.risk-window-list p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; margin: 0; color: #5c726d; font-size: 12px; line-height: 1.5; -webkit-line-clamp: 2; }
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

.project-health-band {
  grid-template-columns: minmax(340px, 1.1fr) minmax(170px, .55fr) minmax(170px, .55fr) minmax(360px, 1.45fr);
  gap: 12px;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.project-health-data { display: contents; }

.project-health-summary,
.project-health-data > div {
  position: relative;
  min-width: 0;
  min-height: 176px;
  box-sizing: border-box;
  border: 1px solid #dfe9e6;
  border-top: 3px solid #76b8ae;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(24, 54, 51, .055);
}

.project-health-summary {
  display: grid;
  grid-template-columns: 114px minmax(0, 240px);
  place-content: center;
  align-items: center;
  gap: 20px;
  padding: 22px 24px;
  border-right: 1px solid #dfe9e6;
  background: linear-gradient(135deg, #f2faf7 0%, #fff 72%);
}

.project-health-gauge { width: 110px; height: 110px; }
.project-health-gauge strong { font-size: 18px; }
.project-health-gauge small { font-size: 12px; }
.project-health-copy { min-width: 0; }
.project-health-copy span { font-size: 16px; }
.project-health-copy p { margin: 9px 0 6px; font-size: 14px; line-height: 1.55; text-wrap: pretty; }
.project-health-copy small { font-size: 12px; line-height: 1.55; }

.project-health-data > div {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 22px 20px;
  text-align: center;
}

.project-health-data > div:nth-child(2) { border-top-color: #0f9d92; }
.project-health-data .project-health-conclusion {
  overflow: visible;
  margin-top: 0;
  border-top-color: #d97706;
  background: linear-gradient(135deg, #fff 18%, #fffaf3 100%);
}

.project-health-data dt {
  width: 100%;
  overflow: visible;
  color: #496761;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.35;
  text-align: center;
  text-overflow: clip;
  white-space: normal;
}

.project-health-data dd { margin: 10px 0 7px; font-size: 30px; line-height: 1; }
.project-health-data small { font-size: 12px; }

.project-progress-compare { display: flex !important; width: auto; justify-self: stretch; padding: 22px 18px !important; }
.progress-compare-values { display: grid; width: min(100%, 176px); grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 14px; padding: 0; border: 0; }
.progress-compare-values span { display: grid; min-width: 0; gap: 5px; justify-items: center; text-align: center; }
.progress-compare-values small { color: #71867f; font-size: 12px; font-weight: 720; line-height: 1.25; }
.progress-compare-values b { color: #27433f; font-size: 24px; font-variant-numeric: tabular-nums; line-height: 1.05; letter-spacing: -.035em; }
.progress-compare-values span:last-child b { color: #0d8278; }
.project-progress-compare dd {
  position: static;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: 15px 0 0;
  padding: 6px 10px;
  border-radius: 6px;
  background: #e9f7f3;
  font-size: inherit;
  line-height: 1;
}
.project-progress-compare dd::before { display: none; }
.project-progress-compare dd small { color: #5f7770; font-size: 12px; font-weight: 740; line-height: 1; }
.project-progress-compare dd strong { color: currentColor; font-size: 18px; font-variant-numeric: tabular-nums; line-height: 1; letter-spacing: -.03em; }

.project-health-progress { width: min(100%, 184px); }
.project-health-data .project-health-conclusion {
  align-items: stretch;
  justify-content: center;
  padding: 18px 20px;
  text-align: left;
}
.project-conclusion-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.project-conclusion-head dt {
  display: inline-flex;
  width: auto;
  align-items: center;
  gap: 7px;
  color: #6f5a39;
  text-align: left;
}
.project-conclusion-head dt::before {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #d97706;
  box-shadow: 0 0 0 4px rgba(217, 119, 6, .1);
  content: '';
}
.project-conclusion-head em {
  flex: 0 0 auto;
  padding: 4px 7px;
  border: 1px solid #efd5ad;
  border-radius: 5px;
  background: #fff6e7;
  color: #9a6208;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  line-height: 1.2;
}
.project-health-conclusion > dd {
  width: 100%;
  margin: 9px 0 10px;
  color: #173235;
  font-size: 18px;
  line-height: 1.4;
  text-align: left;
  text-wrap: balance;
}
.project-conclusion-points {
  display: grid;
  gap: 0;
  width: 100%;
  border-top: 1px solid #efe8dc;
}
.project-conclusion-points p {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 9px;
  margin: 0;
  padding: 7px 0;
  border-bottom: 1px solid #f2ece3;
}
.project-conclusion-points b {
  color: #9a6b24;
  font-size: 12px;
  line-height: 1.5;
  font-weight: 800;
}
.project-conclusion-points span {
  min-width: 0;
  color: #536b65;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.project-conclusion-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding-top: 9px;
  color: #6d7f79;
  font-size: 12px;
  line-height: 1.4;
}
.project-conclusion-meta span { min-width: 0; }
.project-conclusion-meta strong {
  flex: 0 0 auto;
  color: #0f766e;
  font-size: 12px;
  font-weight: 820;
  white-space: nowrap;
}

@media (max-width: 1400px) {
  .project-health-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

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
.execution-status { padding: 5px 9px; font-size: 12px; }
.closure-status { display: inline-flex; align-items: center; width: fit-content; border: 1px solid transparent; border-radius: 5px; padding: 5px 9px; background: #f2f5f4; color: #557069; font-size: 12px; font-weight: 780; line-height: 1.2; white-space: nowrap; }
.closure-status.open { border-color: #dce5e2; background: #f3f6f5; color: #62746f; }
.closure-status.review { border-color: #f1d6ad; background: #fff7e8; color: #a46600; }
.closure-status.supplement { border-color: #e7d7a6; background: #fff9e8; color: #927100; }
.closure-status.closed { border-color: #b9e2cd; background: #ecf8f0; color: #247449; }
.closure-status.cancelled { border-color: #e0e3e2; background: #f4f5f5; color: #78837f; }

.status-latest-list article { grid-template-columns: 10px minmax(0, 1fr) auto auto 48px; gap: 12px; min-height: 74px; }
.status-latest-list strong { font-size: 14px; }
.status-latest-list p, .status-latest-list time { font-size: 12px; }
.status-latest-list em { padding: 4px 8px; font-size: 12px; }
.status-row-placeholder { width: 48px; }
.status-row-action { padding: 6px 9px; font-size: 12px; }

.process-supervision-head, .process-supervision-table article {
  grid-template-columns: minmax(195px, 1.12fr) minmax(180px, 1.06fr) minmax(155px, 1fr) minmax(165px, 1fr) minmax(150px, .92fr) minmax(160px, 1fr);
  min-width: 1100px;
  padding: 14px 18px;
}
.process-supervision-head { font-size: 12px; }
.process-supervision-table article { min-height: 76px; font-size: 13px; }
.process-supervision-table article strong, .process-progress b { font-size: 14px; }
.process-supervision-table article > div:first-child small { color: #5f7771; font-size: 13px; font-weight: 720; line-height: 1.4; letter-spacing: .01em; }
.process-progress small { font-size: 12px; }

.status-change-list article { min-height: 82px; }
.status-change-list span { font-size: 12px; }
.status-change-list strong { font-size: 14px; }
.status-change-list p, .status-change-list time, .status-change-list em { font-size: 12px; }

.risk-window-list article { padding: 15px 0; }
.risk-window-list p { font-size: 12px; line-height: 1.55; }
.risk-window-list strong { font-size: 14px; }
.risk-window-list dl { margin: 8px 0; }
.risk-window-list dl div { grid-template-columns: 60px minmax(0, 1fr); }
.risk-window-list dt { font-size: 12px; }
.risk-window-list dd { font-size: 12px; white-space: normal; }
.change-preview-list article { padding: 13px 0; }
.change-preview-list strong { font-size: 13px; }
.change-preview-list span, .change-preview-list small { font-size: 12px; }

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
  .task-lifecycle-board { grid-template-columns: minmax(0, 1.08fr) minmax(320px, .92fr); }
  .task-commandbar { grid-template-columns: minmax(0, 1fr) auto; gap: 14px; }
  .task-command-stats { display: none; }
  .task-ai-workbench { grid-template-columns: minmax(320px, 39%) minmax(0, 61%); }
  .task-dobby-judgement { grid-template-columns: 1fr; }
  .task-dobby-judgement div + div { border-top: 1px solid #e1e9e6; }
  .task-context-facts { grid-template-columns: 1fr 1fr; }
  .task-context-facts > span:first-child { grid-column: 1 / -1; }
  .home-workbench {
    grid-template-columns: minmax(350px, 43%) minmax(0, 57%);
  }
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
  .project-health-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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

@media (max-width: 900px) {
  .task-management-page { height: auto; min-height: 0; overflow: visible; }
  .task-mine-view,
  .task-history-view,
  .task-assign-view { min-height: 720px; }
  .task-lifecycle-board { grid-template-columns: 1fr; grid-template-rows: none; }
  .task-life-group,
  .task-life-group.primary { grid-row: auto; min-height: 300px; }
  .task-history-results { min-height: 520px; }
  .task-history-search { grid-template-columns: minmax(220px, 1fr) 160px 160px auto; }
  .task-flow-inline { min-height: 760px; }
  .task-command-page { height: auto; min-height: 0; overflow: visible; }
  .task-ai-workbench { grid-template-columns: 1fr; overflow: visible; }
  .task-command-queue { min-height: 540px; max-height: 68dvh; border-right: 0; border-bottom: 1px solid #dfe9e5; }
  .task-dobby-panel { min-height: 700px; }
  .task-dobby-judgement { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .task-dobby-judgement div + div { border-top: 0; }
  .task-context-facts { grid-template-columns: 1.25fr .55fr .55fr; }
  .task-context-facts > span:first-child { grid-column: auto; }
  .home-console {
    height: auto;
    min-height: 0;
  }
  .home-workspace {
    height: auto;
    overflow: visible;
  }
  .home-workbench {
    grid-template-columns: 1fr;
    overflow: visible;
  }
  .home-queue-pane {
    min-height: 590px;
    border-right: 0;
    border-bottom: 1px solid rgba(20, 45, 54, 0.1);
  }
  .home-work-ai {
    min-height: 620px;
  }
  .home-chat-panel {
    min-height: 660px;
  }
}

@media (max-width: 720px) {
  .ai-platform { padding: 12px; }
  .task-management-nav { padding: 6px; }
  .task-management-nav nav button { display: flex; min-height: 42px; align-items: center; justify-content: center; padding: 7px 6px; text-align: center; }
  .task-management-nav nav button > span { font-size: 12px; }
  .task-management-nav nav button b { display: none; }
  .task-mine-view,
  .task-history-view,
  .task-assign-view { min-height: 0; }
  .task-mine-intro { align-items: stretch; flex-direction: column; padding: 14px; }
  .task-mine-intro h1,
  .task-assign-head h1 { font-size: 17px; }
  .task-mine-intro dl { width: 100%; }
  .task-mine-intro dl div { display: grid; grid-template-columns: 1fr; gap: 4px; }
  .task-lifecycle-board { overflow: visible; }
  .task-life-group,
  .task-life-group.primary { min-height: 320px; }
  .task-assign-head { align-items: flex-start; flex-direction: column; padding: 13px; }
  .task-history-search { grid-template-columns: 1fr; }
  .task-history-results { min-height: 420px; }
  .task-history-table-head { display: none; }
  .task-history-results > article { grid-template-columns: 1fr auto; gap: 7px 12px; padding: 12px; }
  .task-history-results > article > div { grid-column: 1 / -1; }
  .task-history-results > article > span:nth-of-type(2),
  .task-history-results > article time { display: none; }
  .task-history-results > article button { grid-column: 2; grid-row: 2 / 4; }
  .task-assign-view { min-height: 1100px; }
  .task-flow-modal.task-flow-inline { width: 100%; height: auto; min-height: 980px; max-height: none; }
  .task-disposition-drawer { width: 100vw; }
  .task-disposition-drawer > header,
  .task-disposition-body,
  .task-disposition-drawer > footer { padding-right: 14px; padding-left: 14px; }
  .task-disposition-flow li { grid-template-columns: 24px minmax(0,1fr) auto; }
  .task-disposition-flow li button { grid-column: 2 / -1; justify-self: start; }
  .task-disposition-files { align-items: flex-start; flex-direction: column; }
  .task-disposition-files small { margin-left: 0; }
  .task-disposition-drawer > footer { display: grid; grid-template-columns: 1fr 1fr; }
  .task-disposition-drawer > footer .task-disposition-submit { grid-column: 1 / -1; }
  .task-commandbar { grid-template-columns: 1fr; align-items: stretch; padding: 15px; }
  .task-command-copy { align-items: flex-start; flex-direction: column; gap: 10px; }
  .task-command-copy h1 { white-space: normal; }
  .task-command-copy p { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; white-space: normal; -webkit-line-clamp: 2; }
  .task-command-create { width: 100%; justify-content: center; }
  .task-command-queue { min-height: 560px; max-height: 74dvh; }
  .task-command-item { min-height: 122px; grid-template-columns: 30px minmax(0, 1fr); }
  .task-command-chevron { display: none; }
  .task-command-item-meta { align-items: flex-start; flex-direction: column; gap: 3px; }
  .task-dobby-panel { min-height: 760px; }
  .task-dobby-head { align-items: stretch; flex-direction: column; padding: 14px; }
  .task-dobby-head h2 { white-space: normal; }
  .task-dobby-head-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .task-dobby-thread { padding: 15px 12px 22px; }
  .task-dobby-message { max-width: 100%; }
  .task-dobby-judgement { grid-template-columns: 1fr; }
  .task-dobby-judgement div + div { border-top: 1px solid #e1e9e6; }
  .task-dobby-context,
  .task-dobby-flow,
  .task-dobby-suggestions { width: calc(100% - 39px); }
  .task-context-facts { grid-template-columns: 1fr 1fr; }
  .task-context-facts > span:first-child { grid-column: 1 / -1; }
  .task-dobby-flow li { grid-template-columns: 24px minmax(0, 1fr) auto; }
  .task-dobby-flow li > button { grid-column: 2 / -1; justify-self: start; }
  .task-dobby-composer { grid-template-columns: 1fr; }
  .task-dobby-composer button { min-height: 39px; }
  .home-titlebar {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
  }
  .home-mode-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    min-width: 0;
  }
  .home-mode-tabs button {
    padding: 0 10px;
  }
  .home-controlbar {
    padding: 10px;
  }
  .home-status-tabs button {
    padding: 0 10px;
  }
  .home-pagination {
    align-items: flex-start;
    flex-direction: column;
  }
  .home-pagination > div {
    width: 100%;
  }
  .home-queue-card {
    grid-template-columns: 30px 42px minmax(0, 1fr);
    gap: 9px;
    padding-right: 10px;
  }
  .home-work-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }
  .home-work-ai-head {
    align-items: stretch;
    flex-direction: column;
    padding: 16px;
  }
  .home-work-ai-thread {
    padding: 16px;
  }
  .home-work-context,
  .home-work-suggestions {
    width: auto;
    margin-left: 0;
  }
  .chat-composer.home-work-composer,
  .chat-composer.home-chat-composer {
    grid-template-columns: 1fr;
    padding: 12px 16px 16px;
  }
  .composer-input-row {
    grid-template-columns: 1fr;
  }
  .composer-attach-button {
    min-height: 40px;
    justify-content: flex-start;
  }
  .home-work-composer > button[type="submit"],
  .home-chat-composer > button[type="submit"] {
    min-height: 40px;
  }
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
  .project-health-band { grid-template-columns: 1fr; }
  .project-health-summary { grid-template-columns: 1fr; justify-items: center; text-align: center; }
  .project-health-copy { max-width: 36ch; }
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
  .task-flow-brief { display: block; overflow: visible; border-right: 0; border-bottom: 1px solid #e1e9e7; }
  .dobby-generator { display: block; }
  .dobby-generator textarea { min-height: 180px; }
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

/* 布置任务：紧凑全局约束 + 可展开节点 + 引擎校验 */
.task-flow-builder {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #dce6e3;
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 10px 28px rgba(25, 53, 50, .055);
}
.task-flow-builder .task-flow-global-settings { display: grid; flex: 0 0 auto; gap: 9px; padding: 10px 16px 12px; border-bottom: 1px solid #dfe8e6; background: #f8faf9; }
.task-flow-builder .task-flow-global-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.task-flow-builder .task-flow-global-copy { display: flex; min-width: 0; align-items: center; gap: 15px; }
.task-flow-builder .task-flow-global-copy > div { display: flex; flex: 0 0 auto; align-items: baseline; gap: 9px; }
.task-flow-builder .task-flow-global-copy span { color: #0f766e; font-size: 12px; font-weight: 850; }
.task-flow-builder .task-flow-global-copy strong { color: #173235; font-size: 14px; }
.task-flow-builder .task-flow-global-copy p { overflow: hidden; margin: 0; color: #6c817d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-builder .task-flow-trigger-preview { display: flex; min-width: 0; align-items: center; gap: 8px; padding: 5px 9px; border-left: 2px solid #58a698; background: #edf6f3; }
.task-flow-builder .task-flow-trigger-preview span { flex: 0 0 auto; color: #66817b; font-size: 12px; }
.task-flow-builder .task-flow-trigger-preview strong { overflow: hidden; max-width: 420px; color: #164a43; font-size: 12px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-global-grid { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; }
.task-flow-global-grid > .form-field { min-width: 150px; flex: 1 1 170px; gap: 5px; color: #4a625e; font-size: 12px; }
.task-flow-global-grid > .task-flow-title-field { min-width: 220px; flex-basis: 250px; }
.task-flow-global-grid > .task-flow-time-field { min-width: 210px; flex-basis: 220px; }
.task-flow-global-grid > .task-flow-cc-field { min-width: 210px; flex-basis: 230px; }
.task-flow-global-grid .form-field input,.task-flow-global-grid .form-field select { min-height: 34px; padding: 6px 9px; font-size: 12px; }
.task-flow-field-label { display: inline-flex; align-items: center; gap: 5px; color: #48615d; font-size: 12px; font-weight: 700; }
.task-flow-field-label .n-icon { color: #0f766e; }
.task-flow-global-grid .task-flow-interval-field > span:last-child { display: grid; grid-template-columns: minmax(70px, .72fr) minmax(88px, 1fr); gap: 6px; }

.task-flow-workspace { display: grid; flex: 1 1 auto; min-width: 0; min-height: 0; grid-template-columns: minmax(0, 1fr) 245px; }
.task-flow-authoring { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 10px; padding: 12px 14px 14px; overflow: hidden; background: #fff; }
.task-flow-assistant-bar { display: grid; min-height: 48px; flex: 0 0 auto; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 10px; border: 1px solid #bcd8d2; border-radius: 8px; padding: 7px 10px; color: #43605b; background: #f7fbfa; }
.task-flow-assistant-icon { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; color: #fff; background: #0f766e; }
.task-flow-assistant-bar > strong { color: #0b655d; font-size: 13px; }
.task-flow-assistant-toggle { display: inline-flex; min-height: 32px; align-items: center; gap: 4px; border: 0; border-radius: 6px; padding: 5px 7px; color: #47716a; background: transparent; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.task-flow-assistant-toggle:hover { color: #0f766e; background: #e8f3f0; }
.task-flow-assistant-toggle:focus-visible { outline: 2px solid rgba(15, 118, 110, .3); outline-offset: 1px; }
.task-flow-assistant-toggle[aria-expanded="true"] .n-icon { transform: rotate(180deg); }
.task-flow-assistant-panel { display: grid; flex: 0 0 auto; grid-template-columns: minmax(0, 1fr); gap: 8px; padding: 9px; overflow: visible; border: 1px solid #dce7e4; border-radius: 8px; background: #f8faf9; }
.task-flow-assistant-panel.collapsed { display: none; }
.task-flow-assistant-panel .task-flow-mode-switch { display: grid; width: min(300px, 100%); align-self: start; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; padding: 3px; }
.task-flow-assistant-panel .task-flow-mode-switch button { min-height: 36px; }
.task-flow-assistant-panel .task-flow-generator { min-height: 0; margin: 0; padding: 9px 10px 10px; overflow: visible; }
.task-flow-assistant-panel .task-flow-section-title { margin-bottom: 8px; }
.task-flow-assistant-panel .dobby-generator textarea { min-height: 72px; flex: 0 0 auto; }
.task-flow-assistant-panel .task-flow-generate-button { min-height: 40px; }
.task-flow-assistant-panel .template-generator { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; gap: 8px; }
.task-flow-assistant-panel .template-generator .task-flow-section-title,.task-flow-assistant-panel .template-generator .task-flow-generate-button { grid-column: 1 / -1; }

.task-flow-builder .task-flow-editor-head { display: flex; min-height: 42px; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 14px; margin: 0; padding: 0 2px; }
.task-flow-builder .task-flow-editor-head > div:first-child { display: flex; min-width: 0; align-items: baseline; gap: 9px; }
.task-flow-builder .task-flow-editor-head span { color: #0f766e; font-size: 12px; font-weight: 850; }
.task-flow-builder .task-flow-editor-head strong { overflow: hidden; color: #173235; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-builder .task-flow-editor-head small { color: #7b8c87; font-size: 12px; white-space: nowrap; }
.task-flow-builder .task-flow-editor-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.task-flow-builder .task-flow-editor-actions em { color: #7a8d88; font-size: 12px; font-style: normal; }
.task-flow-builder .task-flow-add-button { display: inline-flex; align-items: center; gap: 5px; padding: 7px 10px; }
.task-flow-node-workspace { display: grid; flex: 1 1 auto; min-width: 0; min-height: 0; grid-template-columns: minmax(0, 1fr); overflow: hidden; }
.task-flow-node-list { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 8px; padding: 3px 5px 12px 0; overflow-y: auto; scrollbar-color: transparent transparent; scrollbar-width: thin; }
.task-flow-node-list:hover { scrollbar-color: #b8c8c4 transparent; }
.task-flow-node-list::-webkit-scrollbar { width: 6px; }
.task-flow-node-list::-webkit-scrollbar-track { background: transparent; }
.task-flow-node-list::-webkit-scrollbar-thumb { border-radius: 999px; background: transparent; }
.task-flow-node-list:hover::-webkit-scrollbar-thumb { background: #b8c8c4; }
.task-flow-builder .task-flow-node-card { flex: 0 0 auto; border: 1px solid #dce6e3; border-radius: 8px; padding: 0; background: #fff; box-shadow: none; }
.task-flow-builder .task-flow-node-card.active { border-color: #67a99d; box-shadow: 0 0 0 2px rgba(15, 118, 110, .08); }
.task-flow-builder .task-flow-node-card header { display: grid; min-height: 54px; grid-template-columns: 29px minmax(0, 1fr) auto auto; align-items: center; gap: 9px; margin: 0; padding: 7px 9px; cursor: pointer; }
.task-flow-builder .task-flow-node-card header > span { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 50%; color: #fff; background: #809993; font-size: 12px; font-weight: 850; }
.task-flow-builder .task-flow-node-card.active header > span { background: #0f766e; }
.task-flow-node-heading { min-width: 0; }
.task-flow-node-heading strong,.task-flow-node-heading small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-flow-node-heading strong { color: #203d38; font-size: 13px; }
.task-flow-node-heading small { margin-top: 3px; color: #7b8d88; font-size: 12px; }
.task-flow-builder .task-flow-node-card header > em { border: 1px solid #c7ddd7; border-radius: 5px; padding: 3px 6px; color: #0f766e; background: #eef7f4; font-size: 12px; font-style: normal; font-weight: 700; }
.task-flow-node-actions { display: flex; gap: 4px; }
.task-flow-builder .task-flow-node-card .task-flow-node-actions button { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid #d8e3e0; border-radius: 5px; padding: 0; color: #48645f; background: #f8faf9; cursor: pointer; }
.task-flow-builder .task-flow-node-card .task-flow-node-actions button.danger { color: #b24b2b; }
.task-flow-builder .task-flow-node-card .task-flow-node-actions button:disabled { opacity: .35; cursor: not-allowed; }
.task-flow-builder .task-flow-node-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; padding: 4px 9px 10px 47px; border-top: 1px solid #e6ecea; }
.task-flow-builder .task-flow-node-fields .form-field { gap: 5px; color: #536a66; font-size: 12px; }
.task-flow-builder .task-flow-node-fields input,.task-flow-builder .task-flow-node-fields select { min-height: 35px; padding: 7px 8px; font-size: 12px; }

.task-flow-validation { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 11px; padding: 14px; overflow: hidden; border-left: 1px solid #e0e8e6; background: #f8faf9; }
.task-flow-validation-head { display: grid; gap: 3px; }
.task-flow-validation-head span { color: #0f766e; font-size: 12px; font-weight: 850; }
.task-flow-validation-head strong { color: #173235; font-size: 15px; }
.task-flow-validation-status { display: grid; grid-template-columns: 28px minmax(0, 1fr); align-items: center; gap: 9px; padding: 10px; border: 1px solid #ead7cc; border-radius: 8px; color: #b25b2e; background: #fff8f4; }
.task-flow-validation-status.passed { border-color: #bfd9d3; color: #0f766e; background: #eff8f5; }
.task-flow-validation-status div { min-width: 0; }
.task-flow-validation-status strong,.task-flow-validation-status span { display: block; }
.task-flow-validation-status strong { color: #314f49; font-size: 13px; }
.task-flow-validation-status span { margin-top: 2px; color: #768984; font-size: 12px; }
.task-flow-validation-list { display: grid; min-height: 0; flex: 1 1 auto; align-content: start; gap: 9px; margin: 0; padding: 0 3px 0 0; overflow-y: auto; list-style: none; }
.task-flow-validation-list li { display: grid; grid-template-columns: 19px minmax(0, 1fr); gap: 7px; color: #bd6b39; }
.task-flow-validation-list li.ok { color: #16806f; }
.task-flow-validation-list li div { min-width: 0; }
.task-flow-validation-list strong,.task-flow-validation-list span { display: block; }
.task-flow-validation-list strong { color: #36534e; font-size: 12px; }
.task-flow-validation-list span { overflow: hidden; margin-top: 2px; color: #82918d; font-size: 12px; line-height: 1.4; text-overflow: ellipsis; }
.task-flow-validation-note { flex: 0 0 auto; padding-top: 9px; border-top: 1px solid #dfe7e5; }
.task-flow-validation-note strong { color: #395650; font-size: 12px; }
.task-flow-validation-note p { margin: 5px 0 0; color: #788b86; font-size: 12px; line-height: 1.55; }
.task-flow-submit,.task-flow-back { min-height: 40px; border-radius: 7px; padding: 9px 11px; font: inherit; font-size: 13px; font-weight: 800; cursor: pointer; }
.task-flow-submit { border: 0; color: #fff; background: #0f766e; box-shadow: 0 5px 12px rgba(15, 118, 110, .16); }
.task-flow-submit:disabled { opacity: .45; cursor: not-allowed; box-shadow: none; }
.task-flow-back { border: 1px solid #d4dfdc; color: #526b66; background: #fff; }

@media (max-width: 1180px) {
  .task-flow-workspace { grid-template-columns: minmax(0, 1fr) 225px; }
  .task-flow-builder .task-flow-node-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 860px) {
  .task-assign-view { min-height: 920px; overflow: visible; }
  .task-flow-builder { height: auto; min-height: 920px; overflow: visible; }
  .task-flow-builder .task-flow-global-head { align-items: flex-start; flex-direction: column; gap: 5px; }
  .task-flow-builder .task-flow-global-copy { align-items: flex-start; flex-direction: column; gap: 3px; }
  .task-flow-builder .task-flow-global-copy p { white-space: normal; }
  .task-flow-builder .task-flow-trigger-preview { width: 100%; box-sizing: border-box; }
  .task-flow-workspace { display: block; }
  .task-flow-authoring { min-height: 620px; overflow: visible; }
  .task-flow-assistant-panel { grid-template-columns: 1fr; }
  .task-flow-node-workspace { grid-template-columns: 1fr; overflow: visible; }
  .task-flow-node-list { overflow: visible; }
  .task-flow-validation { border-top: 1px solid #e0e8e6; border-left: 0; }
}

@container task-management (min-width: 1100px) {
  .task-flow-builder .task-flow-global-settings {
    gap: 0;
    padding: 8px 14px 9px;
  }
  .task-flow-builder .task-flow-global-head { display: none; }
  .task-flow-global-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 8px;
  }
  .task-flow-builder .task-flow-global-grid > .form-field,
  .task-flow-builder .task-flow-global-grid > .task-flow-title-field,
  .task-flow-builder .task-flow-global-grid > .task-flow-time-field,
  .task-flow-builder .task-flow-global-grid > .task-flow-cc-field {
    min-width: 0;
    flex: none;
  }
  .task-flow-authoring {
    display: grid;
    grid-template-columns: minmax(320px, 38%) minmax(0, 1fr);
    grid-template-rows: 48px minmax(0, 1fr);
    gap: 10px 14px;
  }
  .task-flow-authoring .task-flow-assistant-bar {
    grid-column: 1;
    grid-row: 1;
  }
  .task-flow-authoring .task-flow-assistant-toggle { display: none; }
  .task-flow-authoring .task-flow-assistant-panel,
  .task-flow-authoring .task-flow-assistant-panel.collapsed {
    display: grid;
    min-height: 0;
    grid-column: 1;
    grid-row: 2;
    grid-template-rows: auto minmax(0, 1fr);
    overflow: hidden;
  }
  .task-flow-authoring .task-flow-assistant-panel .task-flow-mode-switch { width: 100%; }
  .task-flow-authoring .task-flow-assistant-panel .task-flow-generator {
    min-height: 0;
    overflow-y: auto;
  }
  .task-flow-authoring .task-flow-assistant-panel .dobby-generator textarea {
    min-height: 132px;
    flex: 1 1 132px;
  }
  .task-flow-authoring .task-flow-editor-head {
    grid-column: 2;
    grid-row: 1;
  }
  .task-flow-authoring .task-flow-editor-head small,
  .task-flow-authoring .task-flow-editor-actions em { display: none; }
  .task-flow-authoring .task-flow-node-workspace {
    grid-column: 2;
    grid-row: 2;
  }
  .task-flow-builder .task-flow-node-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@container task-management (min-width: 1480px) {
  .task-flow-workspace {
    grid-template-columns: minmax(0, 1fr) clamp(330px, 22%, 380px);
  }
  .task-flow-validation { padding-right: 18px; padding-left: 18px; }
  .task-flow-authoring {
    grid-template-columns: minmax(340px, 36%) minmax(0, 1fr);
  }
  .task-flow-authoring .task-flow-editor-head small { display: inline; }
  .task-flow-builder .task-flow-node-fields { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
</style>
