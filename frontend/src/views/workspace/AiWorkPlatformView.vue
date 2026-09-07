<template>
  <div class="ai-platform">
    <section v-if="section === 'home'" class="home-console">
      <main class="home-workspace">
        <div class="home-titlebar">
          <div class="home-mode-tabs" role="tablist" aria-label="工作首页模式">
            <button
              v-for="mode in homeModeTabs"
              :key="mode.key"
              type="button"
              role="tab"
              :aria-selected="homeMode === mode.key"
              :class="{ active: homeMode === mode.key }"
              @click="selectHomeMode(mode.key)"
            >
              {{ mode.label }}
            </button>
          </div>
        </div>

        <div v-if="homeMode === 'work'" class="home-workbench" :class="{ 'is-announcements': homeStatus === 'announcements' }">
          <aside class="home-queue-pane" aria-label="我的任务列表">
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
                  <span v-if="tab.count !== undefined">{{ tab.count }}</span>
                </button>
              </div>
            </div>

            <div v-if="homeStatus !== 'announcements'" class="home-queue-list" role="listbox" :aria-label="`${homeStatusTabs.find(tab => tab.key === homeStatus)?.label || '任务'}列表`">
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
                  <span class="home-work-title-row">
                    <strong class="home-work-title" :title="item.title">{{ item.title }}</strong>
                    <span v-if="item.workflowStatus === 'unfinished'" class="home-chip" :class="item.tone">{{ item.label }}</span>
                  </span>
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
                <p class="task-empty-copy">{{ homeStatus === 'done' ? '任务完成后会保存在这里，方便回看处理记录。' : 'Dobby 会持续同步任务引擎，新节点到达后会显示在这里。' }}</p>
              </div>
            </div>
            <nav v-if="homeStatus !== 'announcements'" class="home-pagination" aria-label="工作列表分页">
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

          <HomeAnnouncements v-if="homeStatus === 'announcements'" :project-id="store.currentProjectId" />
          <section v-else-if="selectedHomeWorkItem" class="home-work-ai" aria-label="当前工作的 Dobby 交互">
            <header class="home-work-ai-head">
              <div class="home-work-ai-title">
                <span class="home-ai-presence"><n-icon :size="16"><Robot /></n-icon>{{ selectedHomeWorkItem.workflowStatus === 'done' ? '任务已完成' : 'Dobby 正在跟进' }}</span>
                <h2>{{ selectedHomeWorkItem.title }}</h2>
                <p>{{ selectedHomeWorkItem.owner }} · {{ selectedHomeWorkItem.role }} · {{ selectedHomeWorkItem.deadline }}</p>
              </div>
              <router-link class="home-work-open-task" :to="taskDetailRoute(selectedHomeWorkItem.id, selectedHomeWorkItem.workflowStatus === 'done' ? 'history' : 'disposition')">{{ selectedHomeWorkItem.workflowStatus === 'done' ? '查看记录' : '处理任务' }}</router-link>
            </header>

            <div ref="homeWorkThreadViewport" class="home-work-ai-thread">
              <article
                v-for="messageItem in homeWorkConversationMessages"
                :key="messageItem.id"
                :class="['message-row', messageItem.role]"
              >
                <div class="message-avatar" aria-hidden="true">
                  <n-icon v-if="messageItem.role === 'assistant'" :size="17"><Robot /></n-icon>
                  <span v-else>我</span>
                </div>
                <div class="message-stack">
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

            </div>

            <form class="chat-composer home-work-composer" @submit.prevent="dispatchHomeWorkCommand">
              <ChatComposerSurface :busy="homeWorkUploading" contained>
                <template v-if="homeWorkFiles.length" #attachments>
                  <div class="chat-composer-files" aria-label="待发送附件">
                    <span v-for="(file, index) in homeWorkFiles" :key="`${file.name}-${file.lastModified}`" class="chat-composer-file">
                      <n-icon :size="16"><FileText /></n-icon>
                      <b :title="file.name">{{ file.name }}</b>
                      <small>{{ formatFileSize(file.size) }}</small>
                      <button type="button" class="chat-composer-file-remove" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('work', index)">×</button>
                    </span>
                  </div>
                </template>
                <textarea
                  v-model="homeWorkCommand"
                  class="chat-composer-input"
                  rows="1"
                  :placeholder="`围绕“${selectedHomeWorkItem.title}”继续交互，也可以直接上传资料`"
                  @keydown.enter.exact.prevent="dispatchHomeWorkCommand"
                ></textarea>
                <template #tools>
                  <label class="chat-composer-tool" title="上传图片、PDF、表格或其他工程资料">
                    <input type="file" multiple @change="selectComposerFiles('work', $event)">
                    <n-icon :size="17"><Paperclip /></n-icon>
                    <span>附件</span>
                  </label>
                </template>
                <template #action>
                  <button type="submit" class="chat-composer-action" :disabled="homeWorkUploading || (!homeWorkCommand.trim() && !homeWorkFiles.length)">
                    <n-icon :size="17"><Send /></n-icon>
                    {{ homeWorkUploading ? '处理中' : '发送' }}
                  </button>
                </template>
              </ChatComposerSurface>
            </form>
          </section>

          <section v-else class="home-work-ai task-mine-ai-empty task-empty-state" aria-label="暂无待处理工作">
            <div class="task-empty-robot" aria-hidden="true">
              <n-icon :size="26"><Robot /></n-icon>
              <span></span>
            </div>
            <span class="task-empty-kicker">Dobby 已待命</span>
            <strong class="task-empty-title">{{ homeEmptyText }}</strong>
            <p class="task-empty-copy">{{ homeStatus === 'done' ? '任务完成后会保存在这里，方便回看处理记录。' : 'Dobby 会持续同步任务引擎，新节点到达后会显示在这里。' }}</p>
          </section>
        </div>

        <div v-else class="home-chat-workspace">
          <aside class="home-conversation-rail" aria-label="首页聊天记录">
            <header class="home-conversation-rail-head">
              <button
                type="button"
                aria-label="新建聊天"
                title="新建聊天"
                :disabled="quickUploading"
                @click="startNewHomeConversation()"
              >
                <n-icon :size="18"><Plus /></n-icon>
                <span>新会话</span>
              </button>
            </header>

            <label class="home-conversation-search">
              <n-icon :size="16"><Search /></n-icon>
              <input v-model="homeConversationKeyword" type="search" aria-label="搜索聊天记录" placeholder="搜索聊天记录">
            </label>

            <div class="home-conversation-list" aria-live="polite">
              <div v-if="homeConversationListLoading" class="home-conversation-loading">
                <i v-for="index in 4" :key="index"></i>
              </div>
              <template v-else>
                <article
                  v-for="conversation in filteredHomeAgentConversations"
                  :key="conversation.id"
                  :class="{ active: homeAgentConversation?.id === conversation.id }"
                >
                  <button
                    type="button"
                    class="home-conversation-select"
                    :aria-current="homeAgentConversation?.id === conversation.id ? 'true' : undefined"
                    :disabled="quickUploading"
                    @click="selectHomeConversation(conversation.id)"
                  >
                    <strong :title="conversation.title">{{ conversation.title }}</strong>
                    <span>
                      <time>{{ formatHomeConversationTime(conversation.updated_at || conversation.created_at) }}</time>
                    </span>
                  </button>
                  <button
                    type="button"
                    class="home-conversation-delete"
                    :aria-busy="homeConversationDeletingId === conversation.id"
                    :aria-label="homeConversationDeletingId === conversation.id ? `正在删除聊天 ${conversation.title}` : `删除聊天 ${conversation.title}`"
                    :title="homeConversationDeletingId === conversation.id ? '正在删除' : `删除“${conversation.title}”`"
                    :disabled="quickUploading || homeConversationDeletingId !== null"
                    @click.stop="deleteHomeConversation(conversation.id)"
                  >
                    <n-icon v-if="homeConversationDeletingId === conversation.id" class="home-conversation-delete-spinner" :size="15"><Loader /></n-icon>
                    <n-icon v-else :size="15"><Trash /></n-icon>
                  </button>
                </article>
              </template>
              <div
                v-if="!homeConversationListLoading && !filteredHomeAgentConversations.length"
                class="home-conversation-empty"
              >
                <n-icon :size="22"><Robot /></n-icon>
                <strong>{{ homeAgentConversations.length ? '没有匹配的聊天' : '还没有聊天记录' }}</strong>
                <span>{{ homeAgentConversations.length ? '换个关键词试试' : '发送第一条消息后会显示在这里' }}</span>
              </div>
            </div>
          </aside>

          <section class="home-chat-panel">
            <div class="chat-head home-chat-head">
              <div class="chat-title-block">
                <h1 :title="homeQuickSessionTitle">{{ homeQuickSessionTitle }}</h1>
                <div class="chat-subline">
                  <span>{{ homeQuickSessionTime }}</span>
                  <span>{{ homeQuickAgentName }}</span>
                </div>
              </div>
            </div>
            <div ref="homeQuickViewport" :class="['messages', 'home-chat-messages', { 'is-empty': !homeQuickChatMessages.length && !homeQuickStreamingTrace && !homeConversationMessagesLoading }]">
              <div v-if="homeConversationMessagesLoading" class="home-chat-loading">
                <span></span>
                <strong>正在加载聊天记录</strong>
              </div>
              <div v-else-if="!homeQuickChatMessages.length && !homeQuickStreamingTrace" class="home-chat-guide">
                <div class="home-chat-guide-copy">
                  <strong>从这里开始协同处理</strong>
                  <p>直接输入问题开始对话；需要调用其他智能体时，输入 @ 选择。</p>
                </div>
              </div>
            <article
              v-for="message in homeQuickChatMessages"
              :key="message.id"
              :class="['message-row', message.role, { 'has-generated': message.generatedTaskIds?.length }]"
            >
              <div class="message-avatar" aria-hidden="true">
                <n-icon v-if="message.role === 'assistant'" :size="17"><Robot /></n-icon>
                <span v-else>我</span>
              </div>
              <div class="message-stack">
                <div class="message-bubble">
                  <AgentMessageContent
                    :content="message.content"
                    :runtime-trace="message.runtimeTrace"
                    :confirmation-busy="quickUploading"
                    @confirm="confirmHomeToolCall"
                  />
                  <div v-if="message.attachments?.length" class="message-attachments" aria-label="消息附件">
                    <span v-for="attachment in message.attachments" :key="attachment.id">
                      <n-icon :size="16"><FileText /></n-icon>
                      <b :title="attachment.name">{{ attachment.name }}</b>
                      <small>{{ formatFileSize(attachment.size) }}</small>
                    </span>
                  </div>
                  <p v-if="message.sendError" class="home-message-send-error" role="status">{{ message.sendError }}</p>
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
                      <router-link :to="taskDetailRoute(task.id, 'history')">跟踪</router-link>
                    </article>
                  </div>
                </div>
              </div>
            </article>
            <article
              v-if="homeQuickStreamingTrace"
              :class="['message-row', 'assistant', { 'is-awaiting-first-event': !homeQuickStreamingTrace.messages.length }]"
            >
              <div class="message-avatar" aria-hidden="true"><n-icon :size="17"><Robot /></n-icon></div>
              <div class="message-stack">
                <div class="message-bubble">
                  <AgentMessageContent
                    :runtime-trace="homeQuickStreamingTrace"
                    :starting-label="quickPreparationLabel || '正在处理请求…'"
                    :confirmation-busy="quickUploading"
                    streaming
                    @confirm="confirmHomeToolCall"
                  />
                </div>
              </div>
            </article>
            </div>
            <form class="chat-composer home-chat-composer" @submit.prevent="dispatchQuickCommand()">
              <ChatComposerSurface :busy="quickUploading || homeCapabilityDispatching" contained>
                <template v-if="quickFiles.length" #attachments>
                  <div class="chat-composer-files" aria-label="待发送附件">
                    <span v-for="(file, index) in quickFiles" :key="`${file.name}-${file.lastModified}`" class="chat-composer-file">
                      <n-icon :size="16"><FileText /></n-icon>
                      <b :title="file.name">{{ file.name }}</b>
                      <small>{{ formatFileSize(file.size) }}</small>
                      <button type="button" class="chat-composer-file-remove" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('quick', index)">×</button>
                    </span>
                  </div>
                </template>
                <textarea
                  v-model="quickCommand"
                  ref="homeQuickComposerInput"
                  class="chat-composer-input"
                  rows="1"
                  placeholder="输入消息，或通过 @ 调用已发布智能体、任务助手"
                  :disabled="homeConversationMessagesLoading || homeCapabilityDispatching"
                  @blur="closeHomeCapabilityMenuLater"
                  @keydown.esc="homeCapabilityMenuOpen = false"
                  @keydown.enter.exact.prevent="dispatchQuickCommand()"
                ></textarea>
                <template #tools>
                  <label class="chat-composer-tool" title="上传图片、PDF、表格或其他工程资料">
                    <input type="file" multiple @change="selectComposerFiles('quick', $event)">
                    <n-icon :size="17"><Paperclip /></n-icon>
                    <span>附件</span>
                  </label>
                  <div class="home-capability-picker" @focusout="closeHomeCapabilityMenuLater">
                    <button
                      type="button"
                      class="chat-composer-tool home-capability-trigger"
                      aria-label="选择助手"
                      title="选择助手"
                      :aria-expanded="homeCapabilityMenuOpen"
                      @click="homeCapabilityMenuOpen = !homeCapabilityMenuOpen"
                    >
                      <n-icon :size="17"><At /></n-icon>
                      <span>助手</span>
                    </button>
                    <div v-if="homeCapabilityMenuOpen" class="home-capability-menu" role="listbox" aria-label="可用助手">
                      <button
                        v-for="capability in homeCapabilities"
                        :key="capability.name"
                        type="button"
                        role="option"
                        @mousedown.prevent
                        @click="insertHomeCapabilityMention(capability.name)"
                      >
                        <span><n-icon :size="18"><component :is="capability.icon" /></n-icon></span>
                        <span><strong>{{ capability.name }}</strong><small>{{ capability.description }}</small></span>
                      </button>
                    </div>
                  </div>
                </template>
                <template #action>
                  <button v-if="quickUploading" type="button" class="chat-composer-action is-stop" :disabled="quickStopping" :aria-busy="quickStopping" @click="stopHomeAgent">
                    <n-icon v-if="quickStopping" :size="17" class="task-inline-spinner"><Loader /></n-icon>
                    <n-icon v-else :size="17"><PlayerStop /></n-icon>
                    <span>{{ quickStopping ? '正在停止…' : '停止' }}</span>
                  </button>
                  <button
                    v-else
                    type="submit"
                    class="chat-composer-action"
                    :disabled="homeConversationMessagesLoading || homeCapabilityDispatching || (!quickCommand.trim() && !quickFiles.length)"
                  >
                    <n-icon :size="17"><Send /></n-icon>
                    <span>{{ homeCapabilityDispatching ? '准备中' : '发送' }}</span>
                  </button>
                </template>
              </ChatComposerSurface>
            </form>
            <HomeTaskDraftDialog
              ref="homeTaskDraftDialog"
              :project-id="store.currentProjectId"
            />
          </section>
        </div>
      </main>
    </section>

    <ProjectGroupChat v-else-if="section === 'ai'" />

    <section v-else-if="section === 'tasks'" class="task-page task-management-page">
      <header class="task-management-nav">
        <nav aria-label="任务管理模块" role="tablist">
          <button v-for="tab in taskManagementTabs" :key="tab.key" type="button" role="tab" :aria-selected="taskManagementTab === tab.key" :title="tab.hint" :class="{ active: taskManagementTab === tab.key }" @click="selectTaskManagementTab(tab.key)">
            <span><n-icon :size="17"><component :is="tab.icon" /></n-icon>{{ tab.label }}</span>
            <b>{{ tab.count }}</b>
          </button>
        </nav>
      </header>

      <main v-if="taskManagementTab === 'mine'" class="task-mine-view">
        <div class="home-workbench task-mine-workbench">
          <aside class="home-queue-pane" aria-label="我的任务列表">
            <div class="home-controlbar">
              <div class="home-status-tabs" role="tablist" aria-label="我的任务完成情况">
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
                  <span class="home-work-title-row">
                    <strong class="home-work-title" :title="item.title">{{ item.title }}</strong>
                    <span v-if="item.workflowStatus === 'unfinished'" class="home-chip" :class="item.tone">{{ item.label }}</span>
                  </span>
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
                <p class="task-empty-copy">{{ taskMineStatus === 'done' ? '任务完成后会保存在这里，方便回看处理记录。' : 'Dobby 会持续同步任务引擎，新节点到达后会显示在这里。' }}</p>
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
                <span class="home-ai-presence"><n-icon :size="16"><Robot /></n-icon>{{ selectedTaskMineWorkItem.workflowStatus === 'done' ? '任务已完成' : 'Dobby 正在跟进' }}</span>
                <h2>{{ selectedTaskMineWorkItem.title }}</h2>
                <p>{{ selectedTaskMineWorkItem.owner }} · {{ selectedTaskMineWorkItem.role }} · {{ selectedTaskMineWorkItem.deadline }}</p>
              </div>
              <button type="button" class="home-work-open-task" @click="selectedTaskMineWorkItem.workflowStatus === 'done' ? openTaskHistory(selectedTaskMineWorkItem.id) : openTaskDisposition(selectedTaskMineWorkItem.id)">{{ selectedTaskMineWorkItem.workflowStatus === 'done' ? '查看记录' : '处理任务' }}</button>
            </header>

            <div ref="taskMineThreadViewport" class="home-work-ai-thread">
              <article v-for="messageItem in taskMineConversationMessages" :key="messageItem.id" :class="['message-row', messageItem.role]">
                <div class="message-avatar" aria-hidden="true">
                  <n-icon v-if="messageItem.role === 'assistant'" :size="17"><Robot /></n-icon>
                  <span v-else>我</span>
                </div>
                <div class="message-stack">
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

            </div>

            <form class="chat-composer home-work-composer" @submit.prevent="dispatchTaskMineCommand">
              <ChatComposerSurface :busy="taskMineUploading" contained>
                <template v-if="taskMineFiles.length" #attachments>
                  <div class="chat-composer-files" aria-label="待发送附件">
                    <span v-for="(file, index) in taskMineFiles" :key="`${file.name}-${file.lastModified}`" class="chat-composer-file"><n-icon :size="16"><FileText /></n-icon><b :title="file.name">{{ file.name }}</b><small>{{ formatFileSize(file.size) }}</small><button type="button" class="chat-composer-file-remove" :aria-label="`移除附件 ${file.name}`" @click="removeComposerFile('task', index)">×</button></span>
                  </div>
                </template>
                <textarea v-model="taskMineCommand" class="chat-composer-input" rows="1" :placeholder="`围绕“${selectedTaskMineWorkItem.title}”继续交互，也可以直接上传资料`" @keydown.enter.exact.prevent="dispatchTaskMineCommand"></textarea>
                <template #tools>
                  <label class="chat-composer-tool" title="上传任务证明材料或工程资料"><input type="file" multiple @change="selectComposerFiles('task', $event)"><n-icon :size="17"><Paperclip /></n-icon><span>附件</span></label>
                </template>
                <template #action>
                  <button type="submit" class="chat-composer-action" :disabled="taskMineUploading || (!taskMineCommand.trim() && !taskMineFiles.length)"><n-icon :size="17"><Send /></n-icon>{{ taskMineUploading ? '处理中' : '发送' }}</button>
                </template>
              </ChatComposerSurface>
            </form>
          </section>

          <section v-else class="home-work-ai task-mine-ai-empty task-empty-state" aria-label="暂无任务">
            <div class="task-empty-robot" aria-hidden="true">
              <n-icon :size="26"><Robot /></n-icon>
              <span></span>
            </div>
            <span class="task-empty-kicker">Dobby 已待命</span>
            <strong class="task-empty-title">{{ taskMineEmptyText }}</strong>
            <p class="task-empty-copy">{{ taskMineStatus === 'done' ? '任务完成后会保存在这里，方便回看处理记录。' : 'Dobby 会持续同步任务引擎，新节点到达后会显示在这里。' }}</p>
          </section>
        </div>
      </main>

      <main v-else-if="taskManagementTab === 'history'" class="task-history-view">
        <form class="task-history-search" @submit.prevent>
          <label><span>任务名称</span><input v-model.trim="taskHistoryKeyword" placeholder="输入名称、类型或触发原因"></label>
          <label><span>任务状态</span><select v-model="taskHistoryStatus"><option value="all">全部状态</option><option value="unfinished">未完成</option><option value="done">已完成</option><option value="cancelled">已取消</option></select></label>
          <label><span>开始日期</span><input v-model="taskHistoryStart" type="date"></label>
          <label><span>结束日期</span><input v-model="taskHistoryEnd" type="date"></label>
          <button type="button" @click="clearTaskHistoryFilters">清除筛选</button>
        </form>
        <section class="task-history-results">
          <div class="task-history-table-head"><span>任务</span><span>状态</span><span>当前责任</span><span>最近更新</span><span>闭环结果</span><span></span></div>
          <article v-for="task in filteredHistoryTasks" :key="task.id">
            <div><strong>{{ task.title }}</strong><small>{{ taskLedgerTypeLabel(task) }} · {{ task.triggerReason || '无补充说明' }}</small></div><span class="task-ledger-status" :class="task.status === 'done' || task.status === 'cancelled' || task.status === 'overdue' ? task.status : 'pending'">{{ workQueueLabel(task) }}</span><span>{{ taskLedgerOwner(task) }}</span><time>{{ formatDateTime(taskLedgerTimestamp(task)) }}</time><em :class="taskClosureTone(task)">{{ taskClosureLabel(task) }}</em><button type="button" @click="openTaskHistory(task.id)">查看记录</button>
          </article>
          <div v-if="!filteredHistoryTasks.length" class="task-history-no-result"><Notes :size="30" /><strong>没有匹配的任务记录</strong><p>调整名称、状态或日期范围后再试。</p></div>
        </section>
      </main>

      <main v-else-if="taskManagementTab === 'schedules'" class="task-schedule-view">
        <form class="task-history-search task-schedule-search" @submit.prevent>
          <label><span>计划名称</span><input v-model.trim="taskScheduleKeyword" placeholder="输入计划名称或触发规则"></label>
          <label><span>计划状态</span><select v-model="taskScheduleStatus"><option value="all">全部状态</option><option value="active">生效中</option><option value="paused">已暂停</option><option value="ended">已结束</option><option value="cancelled">已取消</option></select></label>
          <button type="button" @click="loadTaskSchedules"><n-icon :size="17"><Repeat /></n-icon>刷新</button>
          <button type="button" class="task-schedule-create" @click="selectTaskManagementTab('assign')"><n-icon :size="17"><Plus /></n-icon>布置任务</button>
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
              <button v-if="schedule.active" type="button" :disabled="taskSchedulePendingAction !== null" :aria-busy="taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'state'" @click="setTaskSchedulePaused(schedule, !schedule.paused)"><n-icon v-if="taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'state'" class="task-schedule-action-spinner" :size="14"><Loader /></n-icon>{{ taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'state' ? '处理中…' : schedule.paused ? '恢复' : '暂停' }}</button>
              <button v-if="schedule.active" type="button" class="danger" :disabled="taskSchedulePendingAction !== null" :aria-busy="taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'cancel'" @click="confirmCancelTaskSchedule(schedule)"><n-icon v-if="taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'cancel'" class="task-schedule-action-spinner" :size="14"><Loader /></n-icon>{{ taskSchedulePendingAction?.id === schedule.id && taskSchedulePendingAction.kind === 'cancel' ? '正在取消…' : '取消' }}</button>
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
                  <button type="button" :class="{ active: taskCreateMode === 'dobby' }" :disabled="taskFlowGenerating" @click="taskCreateMode = 'dobby'">Dobby 生成</button>
                  <button type="button" :class="{ active: taskCreateMode === 'template' }" :disabled="taskFlowGenerating" @click="taskCreateMode = 'template'">模板生成</button>
                </div>
                <section v-if="taskCreateMode === 'dobby'" class="task-flow-generator dobby-generator">
                  <div class="task-flow-section-title"><div><span>Dobby 任务流助手</span><strong>描述你想完成的工作</strong></div></div>
                  <textarea v-model.trim="taskFlowRequirement" :disabled="taskFlowGenerating" placeholder="例如：每周一检查基坑监测数据；接近预警值时由监测员复核，项目负责人确认，最后归档监测报告。"></textarea>
                  <button v-if="taskFlowGenerating" type="button" class="task-flow-generate-button is-generating" :disabled="taskFlowGenerationStopping" @click="stopTaskFlowGeneration"><span v-if="taskFlowGenerationStopping" class="task-flow-button-spinner" aria-hidden="true"></span><n-icon v-else :size="17"><PlayerStop /></n-icon>{{ taskFlowGenerationStopping ? '正在停止…' : '停止生成' }}</button>
                  <button v-else type="button" class="task-flow-generate-button" :disabled="taskFlowRequirement.length < 4" @click="generateTaskFlowWithDobby">让 Dobby 生成任务流</button>
                  <p v-if="taskFlowGenerationNote" class="task-flow-generation-note">{{ taskFlowGenerationNote }}</p>
                </section>
                <section v-else class="task-flow-generator template-generator">
                  <div class="task-flow-section-title"><div><span>标准流程模板</span><strong>选择场景并生成基础节点</strong></div><em>可编辑</em></div>
                  <label class="form-field">任务场景<select v-model="taskTemplateType"><option v-for="item in taskTemplateOptions" :key="item" :value="item">{{ item }}</option></select></label>
                  <label class="form-field">任务主题<input v-model.trim="taskTemplateTopic" placeholder="例如：整改现场隐患并完成复核闭环"></label>
                  <button type="button" class="task-flow-generate-button" @click="generateTemplateTaskFlow">按模板生成流程</button>
                </section>
              </section>

              <div class="task-flow-editor-head" :class="{ 'is-generating': taskFlowGenerating }">
                <div><span>流程节点</span><strong>{{ taskFlowGenerating ? taskFlowGenerationStopping ? '正在停止本次生成' : 'Dobby 正在设计新任务流' : taskCreateForm.title || '未命名任务流' }}</strong><small>{{ taskFlowGenerating ? taskFlowGenerationStopping ? '正在停止生成' : '生成后将显示可编辑节点' : `${taskFlowSteps.length} 个节点，将按顺序依次流转` }}</small></div>
                <div class="task-flow-editor-actions"><em>{{ taskFlowGenerating ? taskFlowGenerationStopping ? '正在停止' : '正在编排' : '展开节点后编辑详细配置' }}</em><button type="button" class="task-flow-add-button" :disabled="taskFlowGenerating" @click="addTaskFlowStep"><n-icon :size="16"><Plus /></n-icon>添加节点</button></div>
              </div>

              <div class="task-flow-node-workspace">
                <section class="task-flow-node-list" aria-label="流程节点配置" :aria-busy="taskFlowGenerating">
                  <div v-if="taskFlowGenerating" class="task-flow-ai-loading" :class="{ 'is-stopping': taskFlowGenerationStopping }" role="status" aria-live="polite">
                    <div class="task-flow-ai-loading-head">
                      <span><n-icon :size="26"><Robot /></n-icon></span>
                      <div><strong>{{ taskFlowGenerationStopping ? '正在停止生成' : 'Dobby 正在设计任务流' }}</strong><p>{{ taskFlowGenerationStopping ? '请稍候' : '正在结合你的描述和当前项目内容编排节点' }}</p></div>
                    </div>
                    <div class="task-flow-ai-loading-track" aria-hidden="true">
                      <span><b>1</b><em>理解需求</em></span>
                      <span><b>2</b><em>读取项目</em></span>
                      <span><b>3</b><em>编排节点</em></span>
                      <span><b>4</b><em>校验结果</em></span>
                    </div>
                    <div class="task-flow-ai-loading-bar" aria-hidden="true"><i></i></div>
                  </div>
                  <template v-else>
                    <div v-if="!taskFlowSteps.length" class="task-flow-node-empty">
                      <span><n-icon :size="26"><Robot /></n-icon></span>
                      <strong>还没有流程节点</strong>
                      <p>让 Dobby 生成、选择标准模板，或手工添加第一个节点。</p>
                      <button type="button" @click="addTaskFlowStep"><n-icon :size="16"><Plus /></n-icon>添加第一个节点</button>
                    </div>
                    <article v-for="(step, index) in taskFlowSteps" :id="`task-flow-node-${index}`" :key="step.id" class="task-flow-node-card" :class="{ active: selectedTaskFlowStepIndex === index }" tabindex="-1" @click="selectedTaskFlowStepIndex = index">
                    <header>
                      <span>{{ index + 1 }}</span>
                      <div class="task-flow-node-heading"><strong>{{ step.name || `节点 ${index + 1}` }}</strong></div>
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
                        <label class="form-field task-flow-node-target">目标群聊<select v-model.number="step.target_channel_id" required @change="handleTaskMessageChannelChange(step)"><option :value="null">请选择群聊</option><option v-for="channel in taskChatChannels" :key="channel.id" :value="channel.id">{{ channel.title }}{{ (channel.all_members ?? channel.channel_type !== 'private') ? ' · ALL' : '' }}</option></select></label>
                        <label class="form-field task-flow-node-message">消息正文<textarea v-model.trim="step.message_content" maxlength="8000" rows="3" required placeholder="填写该节点到达时要发送的消息"></textarea><small>{{ step.message_content.length }} / 8000</small></label>
                        <section class="task-flow-node-audience" :class="{ 'has-recipient-picker': step.mention_mode === 'users' }" aria-label="提醒对象设置">
                          <label class="form-field">提醒方式<select v-model="step.mention_mode" @change="handleTaskMentionModeChange(step)"><option value="all">@全体成员</option><option value="users">指定成员</option><option value="none">不提及成员</option></select></label>
                          <div v-if="step.mention_mode === 'users'" class="form-field task-flow-recipient-picker">
                            <span>添加成员</span>
                            <n-select
                              :value="null"
                              :options="taskAvailableChatMemberOptions(step)"
                              :loading="Boolean(step.target_channel_id && taskChatMemberLoadingChannelIds.has(step.target_channel_id))"
                              :disabled="taskRecipientPickerDisabled(step)"
                              :placeholder="taskRecipientPickerPlaceholder(step)"
                              filterable
                              clear-filter-after-select
                              size="small"
                              @update:value="addTaskMentionedUser(step, $event)"
                            />
                          </div>
                          <section v-if="step.mention_mode === 'users'" class="task-flow-selected-recipients" aria-label="已添加的提醒成员">
                            <div class="task-flow-selected-recipients-head"><strong>提醒成员</strong><span>已添加 {{ taskSelectedChatMembers(step).length }} 人</span></div>
                            <div v-if="taskSelectedChatMembers(step).length" class="task-flow-recipient-card-list">
                              <article v-for="member in taskSelectedChatMembers(step)" :key="member.user_id" class="task-flow-recipient-card">
                                <span class="task-flow-recipient-avatar" aria-hidden="true">{{ member.name.trim().slice(0, 1) }}</span>
                                <div><strong>{{ member.name }}</strong><small>{{ member.title || '群聊成员' }}</small></div>
                                <button type="button" :aria-label="`移除提醒成员 ${member.name}`" :title="`移除 ${member.name}`" @click.stop="removeTaskMentionedUser(step, member.user_id)"><n-icon :size="14"><X /></n-icon></button>
                              </article>
                            </div>
                            <p v-else>{{ step.target_channel_id && taskChatMemberLoadingChannelIds.has(step.target_channel_id) ? '正在读取群聊成员…' : '尚未添加成员，请从上方下拉框选择。' }}</p>
                          </section>
                        </section>
                      </template>
                    </div>
                    </article>
                  </template>
                </section>
              </div>
            </main>

            <aside class="task-flow-validation" aria-label="任务引擎校验">
              <div class="task-flow-validation-head"><span>引擎校验</span><strong>布置前检查</strong></div>
              <div class="task-flow-validation-status" :class="{ passed: !taskFlowGenerating && taskFlowCanSubmit, loading: taskFlowGenerating }"><n-icon :size="23"><component :is="taskFlowGenerating ? taskFlowGenerationStopping ? PlayerStop : Robot : taskFlowCanSubmit ? CircleCheck : AlertCircle" /></n-icon><div><strong>{{ taskFlowGenerating ? taskFlowGenerationStopping ? '正在停止' : 'AI 正在编排' : taskFlowCanSubmit ? '校验通过' : `还差 ${taskFlowMissingCount} 项` }}</strong><span>{{ taskFlowGenerating ? taskFlowGenerationStopping ? '请稍候' : '生成完成后自动刷新校验' : taskFlowCanSubmit ? '可以提交给任务引擎' : '补齐后即可布置任务' }}</span></div></div>
              <ul class="task-flow-validation-list" :class="{ 'is-muted': taskFlowGenerating }">
                <li v-for="item in taskFlowValidationItems" :key="item.key" :class="{ ok: item.ok }"><n-icon :size="17"><component :is="item.ok ? CircleCheck : AlertCircle" /></n-icon><div><strong>{{ item.label }}</strong><span>{{ item.detail }}</span></div></li>
              </ul>
              <details v-if="taskFlowSteps.length && !taskFlowGenerating" class="task-flow-overview" open>
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
              <button type="submit" class="task-flow-submit" :class="{ 'is-submitting': taskFlowSubmitting }" :disabled="taskFlowGenerating || taskFlowSubmitting || !taskFlowCanSubmit" :aria-busy="taskFlowSubmitting"><span v-if="taskFlowSubmitting" class="task-flow-button-spinner" aria-hidden="true"></span>{{ taskFlowSubmitLabel }}</button>
              <button type="button" class="task-flow-back" :disabled="taskFlowSubmitting" @click="selectTaskManagementTab('mine')">返回我的任务</button>
            </aside>
          </div>
        </form>
      </main>

      <div v-if="taskDispositionOpen && selectedTask" class="task-disposition-backdrop" @click.self="closeTaskDisposition()">
        <aside class="task-disposition-drawer" role="dialog" aria-modal="true" aria-labelledby="task-disposition-title">
          <header><div><span>{{ taskTypeLabel(selectedTask.type) }} · {{ statusLabel(selectedTask.status) }}</span><h2 id="task-disposition-title">{{ selectedTask.title }}</h2><p>{{ taskCurrentOwnerName(selectedTask) }} · 截止 {{ taskCurrentStep(selectedTask)?.due_at || selectedTask.deadline }}</p></div><button type="button" aria-label="关闭任务处置" @click="closeTaskDisposition()">关闭</button></header>
          <div class="task-disposition-body">
            <section class="task-disposition-ai"><span class="task-disposition-bot"><Robot :size="18" /></span><div><strong>Dobby 处置提示</strong><p>{{ selectedTaskConclusion }}</p><small>依据：{{ selectedTask.triggerReason }}</small></div></section>
            <section v-if="taskContextLoadingIds.has(selectedTask.id) || taskContextHasLinks(selectedTaskContext)" class="task-context-links" aria-label="任务来源与关联">
              <header><span>来源与关联</span><strong>{{ taskContextLoadingIds.has(selectedTask.id) ? '正在读取…' : '可直接跳转' }}</strong></header>
              <div v-if="selectedTaskContext">
                <router-link v-for="source in selectedTaskContext.chat_messages" :key="`chat-${source.id}`" :to="taskChatMessageRoute(selectedTask.id, source.channel_id, source.id)">群聊：{{ source.channel_title }}</router-link>
                <router-link v-for="channel in selectedTaskContext.related_channels" :key="`channel-${channel.id}`" :to="taskChatMessageRoute(selectedTask.id, channel.id)">协同群：{{ channel.title }}</router-link>
                <router-link v-if="selectedTaskContext.risk" :to="projectSetupRoute('risks', selectedTaskContext.risk.id)">风险源：{{ selectedTaskContext.risk.name }}</router-link>
                <router-link v-if="selectedTaskContext.wbs" :to="projectSetupRoute('wbs', selectedTaskContext.wbs.id)">WBS：{{ selectedTaskContext.wbs.code }} {{ selectedTaskContext.wbs.name }}</router-link>
                <router-link v-for="document in selectedTaskContext.documents" :key="`document-${document.id}`" :to="documentsSearchRoute(document.file_name)">资料：{{ document.file_name }}</router-link>
                <span v-for="sessionItem in selectedTaskContext.collaboration_sessions" :key="`session-${sessionItem.id}`">历史协同：{{ sessionItem.title }}</span>
              </div>
            </section>
            <section class="task-disposition-flow">
              <div class="task-disposition-section-title"><span>任务流程</span><strong>{{ selectedTaskCompletedSteps }}/{{ selectedTask.workflowSteps.length || 1 }} 个节点已完成</strong></div>
              <ol>
                <li v-for="(step, index) in selectedTask.workflowSteps" :key="`${selectedTask.id}-dispose-${index}`" :class="step.status">
                  <span>{{ index + 1 }}</span>
                  <div>
                    <strong>{{ step.name }}</strong>
                    <small>{{ step.owner || store.getMemberName(step.owner_user_id || '') || '待指定负责人' }} · {{ step.due_at || '未设置截止时间' }}</small>
                    <small v-if="step.reopened" class="task-disposition-reopen-hint">⚠ 该节点被退回，需重新提交材料</small>
                    <p v-if="step.note" class="task-disposition-step-note">{{ step.note }}</p>
                    <div v-if="step.attachments?.length" class="task-disposition-step-files">
                      <button
                        v-for="attachment in step.attachments"
                        :key="attachment"
                        type="button"
                        class="task-disposition-step-file"
                        :disabled="Boolean(taskAttachmentDownloadingReference)"
                        :aria-busy="taskAttachmentDownloadingReference === attachment"
                        @click="downloadTaskAttachment(attachment)"
                      >
                        <n-icon v-if="taskAttachmentDownloadingReference === attachment" :size="14" class="task-inline-spinner"><Loader /></n-icon>
                        <n-icon v-else :size="14"><Paperclip /></n-icon>
                        {{ taskAttachmentDownloadingReference === attachment ? '下载中…' : taskAttachmentFileName(attachment) }}
                      </button>
                    </div>
                  </div>
                  <em>{{ taskStepLabel(step.status) }}</em>
                  <button
                    v-if="selectedTask.status === 'processing' && step.status !== 'completed'"
                    type="button"
                    :disabled="Boolean(taskStepUpdatingKey) || taskDispositionSubmitting"
                    :aria-busy="taskStepUpdatingKey === `${selectedTask.id}:${index}`"
                    @click="completeTaskStep(selectedTask, index)"
                  >
                    <n-icon v-if="taskStepUpdatingKey === `${selectedTask.id}:${index}`" :size="14" class="task-inline-spinner"><Loader /></n-icon>
                    {{ taskStepUpdatingKey === `${selectedTask.id}:${index}` ? '完成中…' : '完成节点' }}
                  </button>
                </li>
              </ol>
            </section>
            <section class="task-disposition-form"><div class="task-disposition-section-title"><span>回复与材料</span><strong>结果将进入任务处理记录</strong></div><textarea v-model.trim="taskDispositionReply" rows="5" :disabled="taskDispositionSubmitting" placeholder="回复 Dobby，例如：已完成复核，照片符合闭环要求"></textarea><label class="task-disposition-files"><input type="file" multiple :disabled="taskDispositionSubmitting" @change="handleTaskDispositionFiles"><span><Paperclip :size="16" />选择文件或图片</span><small>{{ taskDispositionFiles.length ? `已选择 ${taskDispositionFiles.length} 个文件` : '支持提交本节点的证明材料' }}</small></label><label class="task-disposition-forward"><span>转交当前节点</span><select v-model="taskDispositionForwardId" :disabled="taskDispositionSubmitting"><option value="">不转交</option><option v-for="member in store.members" :key="member.id" :value="member.id">{{ member.name }} · {{ member.title }}</option></select></label></section>
          </div>
          <footer><button type="button" class="task-disposition-history" :disabled="taskDispositionSubmitting" @click="openTaskHistory(selectedTask.id)">查看处理记录</button><router-link :to="taskDiscussionRoute(selectedTask.id)">发起讨论</router-link><button v-if="canConfirmSelectedTask" type="button" class="task-disposition-history" :disabled="taskDispositionSubmitting" @click="rejectSelectedTask"><n-icon v-if="taskDispositionAction === 'reject'" :size="15" class="task-inline-spinner"><Loader /></n-icon>{{ taskDispositionAction === 'reject' ? '正在退回…' : '退回重做' }}</button><button v-if="canConfirmSelectedTask" type="button" class="task-disposition-submit" :disabled="taskDispositionSubmitting" @click="acceptSelectedTask"><n-icon v-if="taskDispositionAction === 'accept'" :size="15" class="task-inline-spinner"><Loader /></n-icon>{{ taskDispositionAction === 'accept' ? '正在通过…' : '确认通过' }}</button><button v-else type="button" class="task-disposition-submit" :disabled="taskDispositionSubmitting || needsFreshEvidence" @click="submitTaskDisposition"><n-icon v-if="taskDispositionAction === 'submit'" :size="15" class="task-inline-spinner"><Loader /></n-icon>{{ taskDispositionAction === 'submit' ? '正在提交…' : needsFreshEvidence ? '需重新上传材料' : '回复并推进' }}</button></footer>
        </aside>
      </div>
      <div v-if="taskHistoryOpenId && selectedTaskHistoryTask" class="workflow-modal-backdrop" @click.self="closeTaskHistory()">
        <section class="workflow-modal task-history-modal" role="dialog" aria-modal="true" aria-labelledby="task-history-title">
          <div class="workflow-modal-head">
            <div><h2 id="task-history-title">任务记录 - {{ selectedTaskHistoryTask.title }}</h2></div>
            <button type="button" class="modal-close" aria-label="关闭处理记录" @click="closeTaskHistory()">关闭</button>
          </div>
          <div class="task-history-summary">
            <div><span>当前状态</span><strong>{{ statusLabel(selectedTaskHistoryTask.status) }}</strong></div>
            <div><span>当前责任</span><strong>{{ taskLedgerOwner(selectedTaskHistoryTask) }}</strong></div>
            <div><span>截止时间</span><strong>{{ taskLedgerTypeLabel(selectedTaskHistoryTask) === '自动化动作' ? '—' : formatDateTime(selectedTaskHistoryTask.deadline, 'end') }}</strong></div>
          </div>
          <section v-if="taskContextLoadingIds.has(selectedTaskHistoryTask.id) || taskContextHasLinks(selectedTaskContext)" class="task-context-links" aria-label="任务来源与关联">
            <header><span>来源与关联</span><strong>{{ taskContextLoadingIds.has(selectedTaskHistoryTask.id) ? '正在读取…' : '可直接回到原始上下文' }}</strong></header>
            <div v-if="selectedTaskContext">
              <router-link v-for="source in selectedTaskContext.chat_messages" :key="`history-chat-${source.id}`" :to="taskChatMessageRoute(selectedTaskHistoryTask.id, source.channel_id, source.id)">群聊：{{ source.channel_title }}</router-link>
              <router-link v-for="channel in selectedTaskContext.related_channels" :key="`history-channel-${channel.id}`" :to="taskChatMessageRoute(selectedTaskHistoryTask.id, channel.id)">协同群：{{ channel.title }}</router-link>
              <router-link v-if="selectedTaskContext.risk" :to="projectSetupRoute('risks', selectedTaskContext.risk.id)">风险源：{{ selectedTaskContext.risk.name }}</router-link>
              <router-link v-if="selectedTaskContext.wbs" :to="projectSetupRoute('wbs', selectedTaskContext.wbs.id)">WBS：{{ selectedTaskContext.wbs.code }} {{ selectedTaskContext.wbs.name }}</router-link>
              <router-link v-for="document in selectedTaskContext.documents" :key="`history-document-${document.id}`" :to="documentsSearchRoute(document.file_name)">资料：{{ document.file_name }}</router-link>
              <span v-for="sessionItem in selectedTaskContext.collaboration_sessions" :key="`history-session-${sessionItem.id}`">历史协同：{{ sessionItem.title }}</span>
            </div>
          </section>
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
          <div class="workflow-modal-actions task-history-actions"><button type="button" class="modal-primary" @click="closeTaskHistory()">完成查看</button></div>
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
          @click="selectProjectStatusTab(tab.key)"
        ><strong>{{ tab.label }}</strong><span>{{ tab.hint }}</span></button>
      </nav>

      <main class="project-status-v2-content">
        <section v-if="projectStatusTab === 'progress'" class="project-status-v2-stack">
          <article class="project-status-v2-panel project-status-task-panel">
            <header class="project-status-task-title">
              <h2>责任任务</h2>
              <router-link :to="{ path: '/tasks', query: { tab: 'history' } }">查看全部任务</router-link>
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
                <router-link :to="projectSetupRoute('wbs', item.id)"><strong>{{ item.name }}</strong></router-link>
                <span :class="['project-status-state', item.status]">{{ item.statusText || wbsStatusLabel(item.status) }}</span>
                <div class="project-status-progress"><b>{{ Math.round(item.progress) }}%</b><i><em :style="{ width: `${item.progress}%` }" /></i></div>
                <time>{{ projectDateLabel(item.planEnd) || '未设置' }}</time>
              </article>
              <div v-if="!projectStatusWbsRows.length" class="project-status-wbs-empty"><strong>尚未配置 WBS</strong><router-link :to="projectSetupRoute('wbs')">前往工程配置</router-link></div>
            </div>
          </article>
        </section>

        <section v-else-if="projectStatusTab === 'riskQuality'" class="project-status-v2-stack">
          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>风险源</span><h2>风险源配置汇总</h2><p>展示工程配置页面已维护的风险等级、工序和管控窗口，不推断风险是否触发。</p></div>
              <router-link class="project-status-v2-link" :to="projectSetupRoute('risks')">维护风险源 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusRiskRows.length" class="project-status-v2-table project-status-risk-table">
              <div class="project-status-v2-table-head"><span>风险等级</span><span>风险源</span><span>关联工序</span><span>管控窗口</span><span>责任人</span></div>
              <article v-for="risk in projectStatusRiskRows" :key="risk.id">
                <span :class="['project-status-risk-level', risk.level]">{{ risk.levelText || riskLabel(risk.level) }}</span>
                <router-link :to="projectSetupRoute('risks', risk.id)"><strong>{{ risk.name }}</strong></router-link>
                <span>{{ risk.relatedProcessName || '未填写' }}</span>
                <time>{{ projectDateRange(risk.controlStart, risk.controlEnd) }}</time>
                <span>{{ store.getMemberName(risk.responsibleId) || '未指定' }}</span>
              </article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>风险源尚未维护</strong><p>这里不显示“无风险”，只说明工程配置中还没有风险源记录。</p><router-link :to="projectSetupRoute('risks')">前往工程配置</router-link></div>
          </article>

          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>质量要求</span><h2>质量检查要求汇总</h2><p>展示已配置的检查项、控制指标和检查频次，不作为质量问题统计。</p></div>
              <router-link class="project-status-v2-link" :to="projectSetupRoute('quality')">维护质量要求 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusQualityRows.length" class="project-status-v2-table project-status-quality-table">
              <div class="project-status-v2-table-head"><span>关联 WBS</span><span>检查项</span><span>控制指标</span><span>检查频次</span><span>责任人</span></div>
              <article v-for="item in projectStatusQualityRows" :key="item.id">
                <span>{{ projectQualityWbsLabel(item) }}</span>
                <router-link :to="projectSetupRoute('quality', item.id)"><strong>{{ item.name || '未命名检查项' }}</strong></router-link>
                <span>{{ item.controlIndicator || item.requirement || '未填写' }}</span>
                <span>{{ item.inspectionFrequency || '未填写' }}</span>
                <span>{{ store.getMemberName(item.ownerId || '') || '未指定' }}</span>
              </article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>质量要求尚未配置</strong><p>工程配置中新增质量要求后会自动出现在这里。</p><router-link :to="projectSetupRoute('quality')">前往工程配置</router-link></div>
          </article>
        </section>

        <ProjectStatusSupplement v-else-if="projectStatusTab === 'safety'" mode="safety" :overview="store.projectStatusOverview" />
        <section v-else-if="projectStatusTab === 'documents'" class="project-status-v2-stack">
          <ProjectStatusSupplement mode="documents" :overview="store.projectStatusOverview" :completeness-label="documentCompletenessLabel" />
          <article class="project-status-v2-panel project-status-documents-panel">
            <header class="project-status-v2-panel-head">
              <div><span>工程资料</span><h2>资料目录概览</h2><p>{{ projectDocumentSummary.caption }}</p></div>
              <router-link class="project-status-v2-link" :to="documentsRoute()">查看工程资料 <ChevronRight :size="15" /></router-link>
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
                      <router-link :to="documentsSearchRoute(item.name)"><strong :title="item.name">{{ item.name }}</strong></router-link>
                      <small :title="`${item.knowledgeBaseName} / ${item.folderPath || '资料库根目录'}`">{{ projectDocumentTypeLabel(item.fileType, item.name) }} · {{ projectDocumentFileSizeLabel(item.fileSize) }} · {{ projectDocumentFolderLabel(item.folderPath) }}</small>
                    </div>
                    <time>{{ projectDateLabel(item.createdAt) || '日期未记录' }}</time>
                  </article>
                </div>
                <div v-else class="project-status-document-recent-empty">暂无可展示的最近新增资料</div>
              </section>
            </div>
            <div v-else class="project-status-v2-empty"><strong>尚无可汇总的资料目录</strong><p>{{ projectDocumentSummary.emptyHint }}</p><router-link :to="documentsRoute()">前往工程资料</router-link></div>
          </article>
        </section>

        <section v-else class="project-status-v2-stack">
          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>项目基础信息</span><h2>已维护字段</h2><p>项目名称已在右上角项目选择器展示，此处不再重复。</p></div>
              <router-link class="project-status-v2-link" :to="projectSetupRoute('overview')">编辑项目信息 <ChevronRight :size="15" /></router-link>
            </header>
            <dl class="project-status-base-grid"><div v-for="item in projectBaseInfoRows" :key="item.label"><dt>{{ item.label }}</dt><dd :class="{ missing: !item.present }">{{ item.value }}</dd></div></dl>
          </article>

          <article class="project-status-v2-panel">
            <header class="project-status-v2-panel-head">
              <div><span>项目成员</span><h2>成员与岗位</h2><p>汇总工程配置中已加入当前项目的成员。</p></div>
              <router-link class="project-status-v2-link" :to="projectSetupRoute('members')">维护成员 <ChevronRight :size="15" /></router-link>
            </header>
            <div v-if="projectStatusMemberRows.length" class="project-status-v2-table project-status-member-table">
              <div class="project-status-v2-table-head"><span>成员</span><span>岗位</span><span>职责</span></div>
              <article v-for="member in projectStatusMemberRows" :key="member.id"><strong>{{ member.name }}</strong><span>{{ member.title || '未配置岗位' }}</span><span>{{ member.role.join('、') || '未填写职责' }}</span></article>
            </div>
            <div v-else class="project-status-v2-empty"><strong>尚未配置项目成员</strong><p>项目成员及岗位配置后会自动汇总到这里。</p><router-link :to="projectSetupRoute('members')">前往工程配置</router-link></div>
          </article>
        </section>
      </main>
    </section>

  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { NIcon, NSelect, useMessage } from 'naive-ui'
import {
  AlertCircle, At, CalendarEvent, ChartBar, ChevronDown,
  ChevronLeft, ChevronRight, ChevronUp, CircleCheck, Clock, FileText, Folder,
  ListCheck, Loader, MapPin, Notes, Paperclip, Pin, PlayerStop, Plus, Repeat, Robot, Search,
  Send, Settings, ShieldCheck, Trash, User, UserPlus, X,
} from '@vicons/tabler'
import { useAppStore } from '@/stores/app'
import api, { type ApiEnvelope } from '@/api/client'
import {
  listProjectChatChannels,
  listProjectChatMembers,
  type ProjectChatChannel,
  type ProjectChatMember,
} from '@/api/projectChat'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import ChatComposerSurface from '@/components/chat/ChatComposerSurface.vue'
import ProjectGroupChat from '@/components/chat/ProjectGroupChat.vue'
import HomeAnnouncements from '@/components/business/HomeAnnouncements.vue'
import ProjectStatusSupplement from '@/components/business/ProjectStatusSupplement.vue'
import HomeTaskDraftDialog from '@/components/task/HomeTaskDraftDialog.vue'
import { useAsyncConfirmDialog } from '@/composables/useAsyncConfirmDialog'
import { useHomeAgentConversations } from '@/composables/useHomeAgentConversations'
import type { Member, QualityMetric, RiskLevel, Task, TaskStatus } from '@/types'
import {
  formatDateTime, formatFileSize, formatScheduleDateTime, nowStr,
  projectBaseInfoRow, projectDateLabel, projectDateRange,
  projectDocumentFileSizeLabel, projectDocumentFolderLabel, projectDocumentTypeLabel,
  projectTaskStatusLabel, riskLabel, statusLabel, taskClosureLabel, taskClosureTone,
  taskMaterialLabel, taskProgress, taskSourceLabel, taskStepLabel, taskTypeLabel,
  wbsStatusLabel, workQueueCategory, workQueueDeadline, workQueueLabel, workQueueStatus, isUserWorkQueueTask,
  type ChatMessage, type GeneratedTaskFlow, type HomeWorkItem, type TaskFlowStepDraft,
  type TaskMessageMentionMode, type TaskNodeType, type TaskRunMode, type TaskSchedule,
  type TriggerCalendarMode, type TriggerEndMode, type TriggerIntervalUnit,
  type WorkQueueStatus,
} from './ai-work-platform/presentation'

type ProjectStatusTab = 'progress' | 'riskQuality' | 'safety' | 'documents' | 'overview'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const message = useMessage()
const { confirmAsyncAction } = useAsyncConfirmDialog()
const {
  homeAgentConversations,
  homeDirectAgents,
  filteredHomeAgentConversations,
  homeAgentConversation,
  homeConversationKeyword,
  homeConversationListLoading,
  homeConversationMessagesLoading,
  homeConversationDeletingId,
  homeQuickChatMessages,
  homeQuickStreamingTrace,
  homeQuickViewport,
  quickCommand,
  quickFiles,
  quickUploading,
  quickStopping,
  quickPreparationLabel,
  pendingTaskDraftId,
  homeQuickSessionTitle,
  homeQuickSessionTime,
  homeQuickAgentName,
  formatHomeConversationTime,
  selectHomeConversation,
  startNewHomeConversation,
  deleteHomeConversation,
  dispatchQuickCommand: dispatchGeneralQuickCommand,
  sendHomeAgentMessage,
  stopHomeAgent,
  confirmHomeToolCall,
} = useHomeAgentConversations()

const homeCapabilities = computed(() => [
  ...homeDirectAgents.value.map(agent => ({
    name: agent.name,
    description: agent.description || '调用管理中心已发布智能体',
    icon: agent.name === '资料助手' ? Folder : Robot,
  })),
  {
    name: '任务助手',
    description: '分析当前对话并整理待确认任务',
    icon: ListCheck,
  },
])
const homeCapabilityMenuOpen = ref(false)
const homeCapabilityDispatching = ref(false)
const homeQuickComposerInput = ref<HTMLTextAreaElement | null>(null)
const homeTaskDraftDialog = ref<InstanceType<typeof HomeTaskDraftDialog> | null>(null)

watch(pendingTaskDraftId, async draftId => {
  if (!draftId) return
  await nextTick()
  await homeTaskDraftDialog.value?.openExisting(draftId)
  pendingTaskDraftId.value = 0
})

function closeHomeCapabilityMenuLater() {
  window.setTimeout(() => {
    homeCapabilityMenuOpen.value = false
  }, 120)
}

async function insertHomeCapabilityMention(name: string) {
  const mention = `@${name}`
  const current = quickCommand.value
  const trailingMention = current.match(/@[^\s@]*$/)
  const settledContent = trailingMention
    ? current.slice(0, trailingMention.index)
    : current
  if (/(?:^|\s)@[^\s@]+/.test(settledContent)) {
    message.warning('每条消息最多只能明确提及一个智能体。')
    return
  }
  if (/@[^\s@]*$/.test(current)) {
    quickCommand.value = current.replace(/@[^\s@]*$/, `${mention} `)
  } else {
    quickCommand.value = `${current}${current && !/\s$/.test(current) ? ' ' : ''}${mention} `
  }
  homeCapabilityMenuOpen.value = false
  await nextTick()
  homeQuickComposerInput.value?.focus()
}

async function dispatchQuickCommand() {
  const content = quickCommand.value.trim()
  const explicitAgents = [...content.matchAll(/(?:^|\s)@([^\s@，。！？；：,.!?;:]+)/g)]
    .map(match => match[1])
  if (new Set(explicitAgents).size > 1) {
    message.warning('每条消息最多只能明确提及一个智能体。')
    return false
  }
  const directAgentName = explicitAgents[0]
  const invokesTask = directAgentName === '任务助手'
  if (directAgentName && !invokesTask) return dispatchGeneralQuickCommand(directAgentName)
  if (!invokesTask) return dispatchGeneralQuickCommand()
  if (homeCapabilityDispatching.value || quickUploading.value) return false
  if (quickFiles.value.length) {
    message.warning('请先发送并分析附件，再让任务助手结合对话布置任务。')
    return false
  }
  const requirement = content.replace('@任务助手', '').trim()
  if (requirement.length < 4) {
    message.warning('请在 @任务助手 后说明要布置的任务。')
    return false
  }
  const projectId = Number(store.currentProjectId || 0)
  if (!projectId) {
    message.warning('请先选择项目。')
    return false
  }
  homeCapabilityDispatching.value = true
  try {
    const started = await homeTaskDraftDialog.value?.start(
      homeAgentConversation.value?.id || null,
      content,
    )
    if (started) quickCommand.value = ''
    return Boolean(started)
  } catch (error: any) {
    message.error(
      error?.response?.data?.detail
      || error?.message
      || '无法启动 Dobby 任务分析。',
    )
    return false
  } finally {
    homeCapabilityDispatching.value = false
  }
}

watch(quickCommand, value => {
  if (/(^|\s)@$/.test(value)) homeCapabilityMenuOpen.value = true
})

const section = computed(() => {
  const name = String(route.name || '')
  if (name === 'AiWorkspace') return 'ai'
  if (name === 'TaskManagement') return 'tasks'
  if (name === 'ProjectStatus') return 'project'
  return 'home'
})

function routeQueryValue(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function replaceWorkspaceQuery(patch: Record<string, string | undefined>) {
  const query = { ...route.query }
  Object.entries(patch).forEach(([key, value]) => {
    if (value) query[key] = value
    else delete query[key]
  })
  return router.replace({ path: route.path, query })
}

function projectSetupRoute(
  targetSection: 'overview' | 'members' | 'wbs' | 'quality' | 'risks',
  recordId?: string,
): RouteLocationRaw {
  return {
    path: '/settings',
    query: { tab: 'manual', section: targetSection, recordId: recordId || undefined },
  }
}

function documentsRoute(documentId?: string): RouteLocationRaw {
  return { path: '/docs', query: { tab: 'files', documentId: documentId || undefined } }
}

function documentsSearchRoute(fileName: string): RouteLocationRaw {
  return { path: '/docs', query: { tab: 'files', search: fileName } }
}

function taskDetailRoute(taskId: string, view: 'disposition' | 'history' = 'disposition'): RouteLocationRaw {
  return { path: '/tasks', query: { tab: view === 'history' ? 'history' : 'mine', taskId, view } }
}

function taskDiscussionRoute(taskId: string): RouteLocationRaw {
  const source = taskContexts.value[taskId]?.chat_messages[0]
  return {
    path: '/ai',
    query: {
      taskId,
      channelId: source?.channel_id ? String(source.channel_id) : undefined,
      messageId: source?.id ? String(source.id) : undefined,
    },
  }
}

function taskChatMessageRoute(taskId: string, channelId: number, messageId?: number): RouteLocationRaw {
  return {
    path: '/ai',
    query: {
      taskId,
      channelId: String(channelId),
      messageId: messageId ? String(messageId) : undefined,
    },
  }
}

function selectHomeMode(mode: 'work' | 'quick') {
  homeMode.value = mode
  if (route.path === '/workbench') {
    return replaceWorkspaceQuery({
      mode,
      conversationId: mode === 'quick'
        ? String(homeAgentConversation.value?.id || '') || undefined
        : undefined,
    })
  }
  return Promise.resolve()
}

function selectTaskManagementTab(tab: TaskManagementTab) {
  taskManagementTab.value = tab
  if (route.path === '/tasks') {
    replaceWorkspaceQuery({ tab, taskId: undefined, view: undefined })
  }
}

function selectProjectStatusTab(tab: ProjectStatusTab) {
  projectStatusTab.value = tab
  if (route.path === '/project') replaceWorkspaceQuery({ tab })
}

const currentProject = computed(() => store.currentProject)
const currentUserId = computed(() => sessionStorage.getItem('current_user_id') || store.members[0]?.id || '')
const focusTasks = computed(() => store.tasks.filter(task => ['overdue', 'pending', 'processing', 'waiting_confirm'].includes(task.status)))
const projectStatusTab = ref<ProjectStatusTab>('progress')
const projectStatusTabs: Array<{ key: ProjectStatusTab; label: string; hint: string }> = [
  { key: 'progress', label: '进度与任务', hint: 'WBS 与责任任务' },
  { key: 'riskQuality', label: '风险与质量', hint: '风险源与质量要求' },
  { key: 'safety', label: '安全', hint: '安全风险与管控要求' },
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
const documentCompletenessLabel = computed(() => {
  const documents = store.projectStatusOverview?.documents
  return !documents || documents.complete === null ? '待核验' : documents.complete ? '文件已齐备' : `${documents.missingMaterials.length} 项待补齐`
})
const projectStatusMetrics = computed(() => {
  const overview = store.projectStatusOverview
  const wbsValue = !overview ? '—' : overview.wbs.configured && overview.wbs.progressRate != null ? `${overview.wbs.progressRate}%` : '未配置'
  const riskValue = !overview ? '—' : overview.risks.configured ? overview.risks.highLevelCount : '未维护'
  return [
    { label: '风险点', value: overview?.risks.total ?? '—', hint: `高等级风险 ${riskValue}`, icon: AlertCircle, tone: 'orange' },
    { label: '工序进度', value: wbsValue, hint: '叶子工序平均', icon: ChartBar, tone: 'teal' },
    { label: '安全', value: overview?.safety.total ?? '—', hint: '安全类风险记录', icon: ShieldCheck, tone: overview?.safety.total ? 'orange' : 'teal' },
    { label: '资料是否完善', value: documentCompletenessLabel.value, hint: '按资料要求核对文件，内容待审', icon: Folder, tone: 'teal' },
    { label: '今日新增资料', value: overview?.documents.todayCount ?? '—', hint: '北京时间 · 当前可见资料', icon: FileText, tone: 'teal' },
    { label: '待完成任务', value: overview?.tasks.total ?? projectResponsibilityTasks.value.length, hint: '项目责任任务', icon: ListCheck, tone: 'teal' },
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
const homeStatus = ref<WorkQueueStatus | 'announcements'>('unfinished')
const homePageIndex = ref(0)
const homePageSize = 5
const homeWorkThreadViewport = ref<HTMLElement | null>(null)
const selectedHomeWorkItemId = ref('')
const homeWorkCommand = ref('')
const homeWorkFiles = ref<File[]>([])
const homeWorkUploading = ref(false)

function workQueueTags(task: Task) {
  const tags = [taskTypeLabel(task.type), `风险等级 ${riskLabel(task.riskLevel)}`]
  tags.push(...task.linkedWbsIds.map(id => `工点 ${store.getWbsName(id)}`))
  if (task.linkedRiskId) tags.push(`风险 ${store.getRiskName(task.linkedRiskId)}`)
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  if (currentStep?.material) tags.push(`交付 ${currentStep.material}`)
  return Array.from(new Set(tags.filter(Boolean))).slice(0, 4)
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
    .filter(task => isUserWorkQueueTask(task, currentUserId.value))
    .slice()
    .sort((left, right) => {
      if (left.status === 'done' && right.status === 'done') {
        return (Date.parse(taskLedgerTimestamp(right)) || 0) - (Date.parse(taskLedgerTimestamp(left)) || 0)
      }
      return statusRank[left.status] - statusRank[right.status] || (left.deadline || '9999').localeCompare(right.deadline || '9999')
    })
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
        action: task.status === 'done' ? '查看记录' : task.status === 'need_more_info' ? '补充资料' : confirmationTask ? '验收确认' : task.status === 'processing' ? '继续处理' : '开始处理',
        to: '/tasks',
        tone: task.status === 'done' ? 'success' : task.status === 'overdue' ? 'danger' : 'info',
        icon: task.status === 'done' ? CircleCheck : category === 'upload' ? Folder : confirmationTask ? Notes : task.status === 'processing' ? FileText : ListCheck,
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
  if (item.workflowStatus === 'done') return `“${item.title}”已完成。你可以查看处理记录、核对交付资料或整理完成情况。`
  const statusText = item.label === '已逾期' ? '已逾期工作' : '待处理工作'
  return `我已把“${item.title}”列为第 ${selectedHomeWorkRank.value} 项${statusText}。${reason} 当前涉及${item.owner}（${item.role}），你可以直接让我核对依据、整理协同内容或继续推进。`
})
const homeWorkConversationMessages = computed<ChatMessage[]>(() => {
  const item = selectedHomeWorkItem.value
  if (!item) return []
  return [
    { id: `${item.id}-intro`, role: 'assistant', content: homeWorkAssistantIntro.value },
  ]
})
const homePageRangeText = computed(() => {
  const total = filteredHomeWorkItems.value.length
  if (!total) return '0 / 0'
  const start = homePageIndex.value * homePageSize + 1
  const end = Math.min(start + homePageSize - 1, total)
  return `第 ${start}-${end} 项，共 ${total} 项`
})
const workStatusTabs = computed(() => [
  { key: 'unfinished' as const, label: '未完成', count: homeWorkItems.value.filter(item => item.workflowStatus === 'unfinished').length },
  { key: 'done' as const, label: '已完成', count: homeWorkItems.value.filter(item => item.workflowStatus === 'done').length },
])
const homeStatusTabs = computed(() => [
  ...workStatusTabs.value,
  { key: 'announcements' as const, label: '公告', count: undefined },
])
const homeEmptyText = computed(() => ({
  announcements: '当前项目暂无公告',
  unfinished: '当前没有未完成的任务',
  done: '当前暂无已完成任务',
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

function taskAgentPrompt(item: HomeWorkItem, content: string) {
  return [
    `请在当前项目中围绕任务“${item.title}”（任务 ID：${item.id}）处理下面的请求。`,
    `当前状态：${item.label}；当前责任：${item.owner}（${item.role}）；${item.deadline}。`,
    `关联信息：${item.tags.join('、') || '暂无'}。`,
    `用户请求：${content}`,
  ].join('\n')
}

async function dispatchHomeWorkCommand() {
  const item = selectedHomeWorkItem.value
  const files = [...homeWorkFiles.value]
  const content = homeWorkCommand.value.trim() || (files.length ? '请识别并分析我上传的资料' : '')
  if (!item || !content || homeWorkUploading.value) return
  homeWorkUploading.value = true
  try {
    await selectHomeMode('quick')
    await nextTick()
    if (!startNewHomeConversation(false)) return
    const sent = await sendHomeAgentMessage(taskAgentPrompt(item, content), files)
    if (sent) {
      homeWorkCommand.value = ''
      homeWorkFiles.value = []
    }
  } finally {
    homeWorkUploading.value = false
  }
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

watch(() => store.currentProjectId, () => {
  homeCapabilityMenuOpen.value = false
  const hadDraft = Boolean(
    homeWorkCommand.value.trim()
    || homeWorkFiles.value.length
    || quickCommand.value.trim()
    || quickFiles.value.length
    || taskMineCommand.value.trim()
    || taskMineFiles.value.length,
  )
  homeWorkCommand.value = ''
  homeWorkFiles.value = []
  quickCommand.value = ''
  quickFiles.value = []
  taskMineCommand.value = ''
  taskMineFiles.value = []
  taskDispositionOpen.value = false
  taskHistoryOpenId.value = ''
  selectedTaskId.value = ''
  if (hadDraft) message.info('项目已切换，未发送的文字和附件已清空，避免带入其他项目。')
})

type TaskManagementTab = 'mine' | 'history' | 'schedules' | 'assign'

const taskManagementTab = ref<TaskManagementTab>('mine')
const taskMineStatus = ref<WorkQueueStatus>('unfinished')
const taskMinePageIndex = ref(0)
const taskMinePageSize = 5
const selectedTaskMineWorkItemId = ref('')
const taskMineThreadViewport = ref<HTMLElement | null>(null)
const taskMineCommand = ref('')
const taskMineFiles = ref<File[]>([])
const taskMineUploading = ref(false)
const selectedTaskId = ref('')
const taskDispositionOpen = ref(false)
const taskDispositionReply = ref('')
const taskDispositionForwardId = ref('')
const taskDispositionFiles = ref<File[]>([])
const taskDispositionSubmitting = ref(false)
const taskDispositionAction = ref<'submit' | 'accept' | 'reject' | ''>('')
const taskStepUpdatingKey = ref('')
const taskAttachmentDownloadingReference = ref('')
const taskHistoryKeyword = ref('')
const taskHistoryStatus = ref<'all' | WorkQueueStatus | 'cancelled'>('all')
const taskHistoryStart = ref('')
const taskHistoryEnd = ref('')
const taskHistoryOpenId = ref('')
type TaskHistoryEntry = { id: string | number; kind?: string; step_seq?: number | null; from_status?: string; to_status?: string; note?: string; created_at: string }
type TaskContext = {
  task_id: string
  risk: { id: string; name: string } | null
  wbs: { id: string; code: string; name: string } | null
  chat_messages: Array<{ id: number; channel_id: number; channel_title: string; content: string; created_at: string | null }>
  collaboration_sessions: Array<{ id: number; title: string; message_id: number | null; content: string }>
  documents: Array<{ id: string; file_name: string; category: string }>
  related_channels: Array<{ id: number; title: string }>
}
const taskHistories = ref<Record<string, TaskHistoryEntry[]>>({})
const taskContexts = ref<Record<string, TaskContext>>({})
const taskContextLoadingIds = ref<Set<string>>(new Set())
const taskHistoryLoading = ref(false)
const taskSchedules = ref<TaskSchedule[]>([])
const taskSchedulesLoading = ref(false)
const taskSchedulePendingAction = ref<{ id: string; kind: 'state' | 'cancel' } | null>(null)
const taskScheduleKeyword = ref('')
const taskScheduleStatus = ref<'all' | 'active' | 'paused' | 'ended' | 'cancelled'>('all')
const taskChatChannels = ref<ProjectChatChannel[]>([])
const taskChatMembersByChannel = ref<Record<number, ProjectChatMember[]>>({})
const taskChatMemberLoadingChannelIds = ref<Set<number>>(new Set())
const selectedTaskHistoryTask = computed(() => store.tasks.find(task => task.id === taskHistoryOpenId.value))
const selectedTaskContext = computed(() => {
  const taskId = taskHistoryOpenId.value || selectedTaskId.value
  return taskId ? taskContexts.value[taskId] : undefined
})
function taskContextHasLinks(context?: TaskContext) {
  return Boolean(
    context
    && (
      context.risk
      || context.wbs
      || context.chat_messages.length
      || context.collaboration_sessions.length
      || context.documents.length
      || context.related_channels.length
    ),
  )
}
const taskCreateMode = ref<'dobby' | 'template'>('dobby')
const taskFlowAssistantOpen = ref(true)
const taskFlowRequirement = ref('')
const taskFlowGenerating = ref(false)
const taskFlowSubmitting = ref(false)
const taskFlowGenerationStopping = ref(false)
const taskFlowGenerationNote = ref('')
const taskFlowGenerationId = ref('')
const taskFlowGenerationProjectId = ref<string | null>(null)
let taskFlowGenerationController: AbortController | null = null
let taskFlowStopRequestedId = ''
const taskTemplateOptions = ['条件核查', '隐患整改', '资料补全', '风险处置', '报告审核', '自定义'] as const
const taskTemplateType = ref<(typeof taskTemplateOptions)[number]>('隐患整改')
const taskTemplateTopic = ref('')
const selectedTaskFlowStepIndex = ref(-1)
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

function defaultTaskChatChannelId() {
  return taskChatChannels.value.find(channel => channel.channel_type === 'project')?.id || null
}

function taskChatMembersForStep(step: TaskFlowStepDraft) {
  return step.target_channel_id
    ? taskChatMembersByChannel.value[step.target_channel_id] || []
    : []
}

function taskSelectedChatMembers(step: TaskFlowStepDraft) {
  const membersById = new Map(
    taskChatMembersForStep(step).map(member => [member.user_id, member]),
  )
  return step.mentioned_user_ids
    .map(userId => membersById.get(userId))
    .filter((member): member is ProjectChatMember => Boolean(member))
}

function taskAvailableChatMemberOptions(step: TaskFlowStepDraft) {
  const selectedUserIds = new Set(step.mentioned_user_ids)
  return taskChatMembersForStep(step)
    .filter(member => !selectedUserIds.has(member.user_id))
    .map(member => ({
      label: member.title ? `${member.name} · ${member.title}` : member.name,
      value: member.user_id,
    }))
}

function taskRecipientPickerPlaceholder(step: TaskFlowStepDraft) {
  if (!step.target_channel_id) return '请先选择目标群聊'
  if (taskChatMemberLoadingChannelIds.value.has(step.target_channel_id)) return '正在读取群聊成员…'
  if (!taskChatMembersForStep(step).length) return '当前群聊没有可选成员'
  if (!taskAvailableChatMemberOptions(step).length) return '群聊成员已全部添加'
  return '下拉选择要提醒的成员'
}

function taskRecipientPickerDisabled(step: TaskFlowStepDraft) {
  if (!step.target_channel_id) return true
  if (taskChatMemberLoadingChannelIds.value.has(step.target_channel_id)) return false
  return !taskAvailableChatMemberOptions(step).length
}

function addTaskMentionedUser(
  step: TaskFlowStepDraft,
  value: string | number | null,
) {
  const userId = Number(value)
  if (!Number.isInteger(userId)) return
  if (!taskChatMembersForStep(step).some(member => member.user_id === userId)) return
  if (step.mentioned_user_ids.includes(userId)) return
  step.mentioned_user_ids = [...step.mentioned_user_ids, userId]
}

function removeTaskMentionedUser(step: TaskFlowStepDraft, userId: number) {
  step.mentioned_user_ids = step.mentioned_user_ids.filter(item => item !== userId)
}

function taskFlowStepSummary(step: TaskFlowStepDraft) {
  if (step.node_type === 'project_chat_message') {
    const channel = taskChatChannels.value.find(item => item.id === step.target_channel_id)?.title || '未选择群聊'
    const selectedNames = taskSelectedChatMembers(step).map(member => member.name)
    const selectedMention = selectedNames.length
      ? `@${selectedNames.join('、')}`
      : `提醒 ${step.mentioned_user_ids.length} 人`
    const mention = step.mention_mode === 'all'
      ? '@全体成员'
      : step.mention_mode === 'users'
        ? selectedMention
        : '普通消息'
    return `${channel} · ${mention}`
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
    !!step.target_channel_id
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
const taskFlowSubmitLabel = computed(() => {
  if (taskFlowSubmitting.value) {
    return taskCreateForm.value.run_mode === 'immediate' ? '正在布置任务…' : '正在登记计划…'
  }
  if (taskFlowGenerating.value) {
    return taskFlowGenerationStopping.value ? '正在停止 AI 生成' : '等待 AI 生成完成'
  }
  return taskCreateForm.value.run_mode === 'immediate' ? '校验并布置任务' : '校验并登记计划'
})

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
    taskChatMemberLoadingChannelIds.value = new Set()
    return
  }
  try {
    taskChatChannels.value = await listProjectChatChannels(store.currentProjectId)
    for (const step of taskFlowSteps.value) {
      if (step.node_type !== 'project_chat_message') continue
      if (step.target_channel_id === null) {
        step.target_channel_id = defaultTaskChatChannelId()
      } else if (!taskChatChannels.value.some(channel => channel.id === step.target_channel_id)) {
        step.target_channel_id = null
      }
      if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
    }
  } catch (error: any) {
    message.error(error.response?.data?.detail || '项目群聊加载失败。')
  }
}

async function loadTaskChatMembers(channelId: number | null) {
  if (
    !channelId
    || taskChatMembersByChannel.value[channelId]
    || taskChatMemberLoadingChannelIds.value.has(channelId)
  ) return
  taskChatMemberLoadingChannelIds.value = new Set([
    ...taskChatMemberLoadingChannelIds.value,
    channelId,
  ])
  try {
    taskChatMembersByChannel.value[channelId] = await listProjectChatMembers(channelId)
  } catch (error: any) {
    taskChatMembersByChannel.value[channelId] = []
    message.error(error.response?.data?.detail || '群聊成员加载失败。')
  } finally {
    const loadingIds = new Set(taskChatMemberLoadingChannelIds.value)
    loadingIds.delete(channelId)
    taskChatMemberLoadingChannelIds.value = loadingIds
  }
}

async function loadTaskPlanningContext() {
  await Promise.all([loadTaskSchedules(), loadTaskChatChannels()])
}

async function setTaskSchedulePaused(schedule: TaskSchedule, paused: boolean) {
  if (taskSchedulePendingAction.value !== null) return
  taskSchedulePendingAction.value = { id: schedule.id, kind: 'state' }
  try {
    await api.post(`/task-schedules/${schedule.id}/pause`, null, {
      params: { paused },
    })
    message.success(paused ? '执行计划已暂停。' : '执行计划已恢复。')
    await loadTaskSchedules()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '执行计划状态更新失败。')
  } finally {
    taskSchedulePendingAction.value = null
  }
}

async function cancelTaskSchedule(schedule: TaskSchedule): Promise<boolean> {
  if (taskSchedulePendingAction.value !== null) return false
  taskSchedulePendingAction.value = { id: schedule.id, kind: 'cancel' }
  try {
    await api.delete(`/task-schedules/${schedule.id}`)
    message.success('执行计划已取消。')
    await loadTaskSchedules()
    return true
  } catch (error: any) {
    message.error(error.response?.data?.detail || '执行计划取消失败。')
    return false
  } finally {
    taskSchedulePendingAction.value = null
  }
}

function confirmCancelTaskSchedule(schedule: TaskSchedule) {
  if (taskSchedulePendingAction.value !== null) return
  confirmAsyncAction({
    title: '取消执行计划',
    content: `确认取消执行计划“${schedule.title}”吗？取消后不会再次触发。`,
    positiveText: '取消计划',
    negativeText: '返回',
    loadingText: '正在取消…',
    onConfirm: () => cancelTaskSchedule(schedule),
  })
}

watch(taskManagementTab, tab => {
  if (tab === 'assign') void loadTaskChatChannels()
  if (tab === 'schedules') void loadTaskSchedules()
  if (tab === 'mine' || tab === 'history') void store.loadProjectData()
})

watch(
  () => store.currentProjectId,
  () => {
    if (taskFlowGenerating.value) void stopTaskFlowGeneration()
    taskSchedules.value = []
    taskChatChannels.value = []
    taskChatMembersByChannel.value = {}
    taskChatMemberLoadingChannelIds.value = new Set()
    taskContexts.value = {}
    taskContextLoadingIds.value = new Set()
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
      return 'Dobby'
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

const taskMineStatusTabs = workStatusTabs
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
  unfinished: '当前没有未完成的任务',
  done: '当前暂无已完成任务',
})[taskMineStatus.value])
const taskLedgerTasks = computed(() => [...store.tasks].sort((left, right) => (
  Date.parse(taskLedgerTimestamp(right)) || 0
) - (
  Date.parse(taskLedgerTimestamp(left)) || 0
)))
const filteredHistoryTasks = computed(() => taskLedgerTasks.value.filter(task => {
  const keyword = taskHistoryKeyword.value.toLowerCase()
  const searchMatched = !keyword || `${task.title} ${task.triggerReason} ${taskLedgerTypeLabel(task)}`.toLowerCase().includes(keyword)
  const statusMatched = taskHistoryStatus.value === 'all'
    || (taskHistoryStatus.value === 'cancelled'
      ? task.status === 'cancelled'
      : task.status !== 'cancelled' && workQueueStatus(task) === taskHistoryStatus.value)
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
  { key: 'mine' as const, label: '我的任务', hint: '查看我的未完成任务与已完成记录', count: homeWorkItems.value.filter(item => item.workflowStatus === 'unfinished').length, icon: ListCheck },
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
  const intro = item.workflowStatus === 'done'
    ? `“${item.title}”已完成。你可以查看处理记录、核对交付资料或整理完成情况。`
    : `我正在跟进“${item.title}”。${reason} 当前涉及${item.owner}（${item.role}），你可以直接让我核对依据、整理协同内容或继续推进。`
  return [
    { id: `${item.id}-intro`, role: 'assistant', content: intro },
  ]
})


async function dispatchTaskMineCommand() {
  const item = selectedTaskMineWorkItem.value
  const files = [...taskMineFiles.value]
  const content = taskMineCommand.value.trim() || (files.length ? '请识别并分析我上传的资料' : '')
  if (!item || !content || taskMineUploading.value) return
  taskMineUploading.value = true
  try {
    homeMode.value = 'quick'
    await router.push({ path: '/workbench', query: { mode: 'quick', taskId: item.id } })
    await nextTick()
    if (!startNewHomeConversation(false)) return
    const sent = await sendHomeAgentMessage(taskAgentPrompt(item, content), files)
    if (!sent) return
    taskMineCommand.value = ''
    taskMineFiles.value = []
  } finally {
    taskMineUploading.value = false
  }
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

async function loadTaskContext(taskId: string) {
  if (
    !store.currentProjectId
    || taskContexts.value[taskId]
    || taskContextLoadingIds.value.has(taskId)
  ) return
  taskContextLoadingIds.value = new Set(taskContextLoadingIds.value).add(taskId)
  try {
    const response = await api.get<ApiEnvelope<TaskContext>>(
      `/projects/${store.currentProjectId}/tasks/${taskId}/context`,
    )
    taskContexts.value = { ...taskContexts.value, [taskId]: response.data.data }
  } catch (error: any) {
    if (Number(error.response?.status || 0) !== 404) {
      message.warning(error.response?.data?.detail || '任务关联信息暂时无法加载。')
    }
  } finally {
    const pending = new Set(taskContextLoadingIds.value)
    pending.delete(taskId)
    taskContextLoadingIds.value = pending
  }
}

function openTaskDisposition(taskId: string, syncRoute = true) {
  selectedTaskId.value = taskId
  taskDispositionReply.value = ''
  taskDispositionForwardId.value = ''
  taskDispositionFiles.value = []
  taskDispositionOpen.value = true
  taskHistoryOpenId.value = ''
  void loadTaskContext(taskId)
  if (syncRoute && route.path === '/tasks') {
    taskManagementTab.value = 'mine'
    replaceWorkspaceQuery({ tab: 'mine', taskId, view: 'disposition' })
  }
}

function closeTaskDisposition(syncRoute = true) {
  taskDispositionOpen.value = false
  selectedTaskId.value = ''
  if (syncRoute && route.path === '/tasks') {
    replaceWorkspaceQuery({ taskId: undefined, view: undefined })
  }
}

function handleTaskDispositionFiles(event: Event) {
  taskDispositionFiles.value = Array.from((event.target as HTMLInputElement).files || [])
}

async function submitTaskDisposition() {
  const task = selectedTask.value
  if (!task || taskDispositionSubmitting.value) return
  if (!taskDispositionReply.value && !taskDispositionForwardId.value && !taskDispositionFiles.value.length) {
    message.warning('请填写回复、选择材料或指定转交人。')
    return
  }
  taskDispositionAction.value = 'submit'
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
    taskDispositionAction.value = ''
  }
}

async function acceptSelectedTask() {
  const task = selectedTask.value
  if (!task || taskDispositionSubmitting.value) return
  taskDispositionAction.value = 'accept'
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
    taskDispositionAction.value = ''
  }
}

async function rejectSelectedTask() {
  const task = selectedTask.value
  if (!task || taskDispositionSubmitting.value) return
  taskDispositionAction.value = 'reject'
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
    taskDispositionAction.value = ''
  }
}

async function completeTaskStep(task: Task, stepIndex: number) {
  const key = `${task.id}:${stepIndex}`
  if (taskStepUpdatingKey.value || taskDispositionSubmitting.value) return
  taskStepUpdatingKey.value = key
  try {
    await store.updateTaskStep(task.id, stepIndex, 'completed')
    message.success('节点已完成。')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '节点状态更新失败，请稍后重试。')
  } finally {
    taskStepUpdatingKey.value = ''
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
  if (taskAttachmentDownloadingReference.value) return
  const attachment = taskAttachmentRecord(reference)
  if (!attachment) {
    message.warning('未找到对应附件记录。')
    return
  }
  taskAttachmentDownloadingReference.value = reference
  try {
    await store.downloadAttachment(attachment.id, attachment.fileName)
  } catch (error: any) {
    message.error(error.response?.data?.detail || '附件下载失败，请稍后重试。')
  } finally {
    taskAttachmentDownloadingReference.value = ''
  }
}

function clearTaskHistoryFilters() {
  taskHistoryKeyword.value = ''
  taskHistoryStatus.value = 'all'
  taskHistoryStart.value = ''
  taskHistoryEnd.value = ''
}

async function openTaskHistory(taskId: string, syncRoute = true) {
  taskHistoryOpenId.value = taskId
  taskDispositionOpen.value = false
  selectedTaskId.value = ''
  if (syncRoute && route.path === '/tasks') {
    taskManagementTab.value = 'history'
    replaceWorkspaceQuery({ tab: 'history', taskId, view: 'history' })
  }
  void loadTaskContext(taskId)
  if (taskHistories.value[taskId]) return
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

function closeTaskHistory(syncRoute = true) {
  taskHistoryOpenId.value = ''
  if (syncRoute && route.path === '/tasks') {
    replaceWorkspaceQuery({ taskId: undefined, view: undefined })
  }
}

let routeContextSequence = 0
async function syncAiWorkspaceFromRoute() {
  const sequence = ++routeContextSequence
  if (section.value === 'home') {
    const mode = routeQueryValue(route.query.mode)
    if (mode === 'work' || mode === 'quick') homeMode.value = mode
    return
  }
  if (section.value === 'project') {
    const tab = routeQueryValue(route.query.tab) as ProjectStatusTab
    if (projectStatusTabs.some(item => item.key === tab)) projectStatusTab.value = tab
    return
  }
  if (section.value !== 'tasks') return
  const tab = routeQueryValue(route.query.tab) as TaskManagementTab
  if (taskManagementTabs.value.some(item => item.key === tab)) taskManagementTab.value = tab
  const taskId = routeQueryValue(route.query.taskId)
  if (!taskId) {
    taskDispositionOpen.value = false
    taskHistoryOpenId.value = ''
    return
  }
  if (!store.tasks.some(task => task.id === taskId)) await store.loadProjectData()
  if (sequence !== routeContextSequence) return
  if (!store.tasks.some(task => task.id === taskId)) {
    message.warning('链接中的任务不属于当前项目，已返回任务列表。')
    replaceWorkspaceQuery({ taskId: undefined, view: undefined })
    return
  }
  if (routeQueryValue(route.query.view) === 'history' || taskManagementTab.value === 'history') {
    await openTaskHistory(taskId, false)
  } else {
    openTaskDisposition(taskId, false)
  }
}

watch(
  () => [section.value, route.query.mode, route.query.tab, route.query.taskId, route.query.view] as const,
  () => void syncAiWorkspaceFromRoute(),
  { immediate: true },
)
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
    target_channel_id: defaultTaskChatChannelId(),
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
      target_channel_id: action?.channel_id ?? null,
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
  const projectId = store.currentProjectId
  const generationId = globalThis.crypto?.randomUUID?.() || `flow-${Date.now()}-${Math.random().toString(36).slice(2)}`
  const controller = new AbortController()
  taskFlowGenerationId.value = generationId
  taskFlowGenerationProjectId.value = projectId
  taskFlowGenerationController = controller
  taskFlowGenerationStopping.value = false
  taskFlowGenerating.value = true
  taskFlowGenerationNote.value = ''
  try {
    const response = await api.post<ApiEnvelope<GeneratedTaskFlow>>(
      `/projects/${projectId}/tasks/generate-flow`,
      { requirement: taskFlowRequirement.value, generation_id: generationId },
      { timeout: 0, signal: controller.signal },
    )
    if (store.currentProjectId === projectId) {
      applyGeneratedTaskFlow(response.data.data)
      message.success('Dobby AI 已生成任务流')
    }
  } catch (error: any) {
    const stopped = taskFlowStopRequestedId === generationId
      || error?.code === 'ERR_CANCELED'
      || (error?.response?.status === 409 && String(error.response?.data?.detail || '').includes('停止'))
    if (stopped) {
      taskFlowGenerationNote.value = '已停止本次 AI 生成。'
    } else {
      taskFlowGenerationNote.value = error.response?.data?.detail || '生成失败，请检查后端服务或模型配置后重试。'
      message.error(taskFlowGenerationNote.value)
    }
  } finally {
    if (taskFlowGenerationController === controller) taskFlowGenerationController = null
    if (taskFlowGenerationId.value === generationId) {
      taskFlowGenerationId.value = ''
      taskFlowGenerationProjectId.value = null
      taskFlowGenerating.value = false
      taskFlowGenerationStopping.value = false
    }
    if (taskFlowStopRequestedId === generationId) taskFlowStopRequestedId = ''
  }
}

async function stopTaskFlowGeneration() {
  const projectId = taskFlowGenerationProjectId.value
  const generationId = taskFlowGenerationId.value
  if (!projectId || !generationId || !taskFlowGenerating.value || taskFlowGenerationStopping.value) return

  taskFlowStopRequestedId = generationId
  taskFlowGenerationStopping.value = true
  let stopAcknowledged = false
  try {
    const response = await api.post<ApiEnvelope<{ stopped: boolean }>>(
      `/projects/${projectId}/tasks/generate-flow/${encodeURIComponent(generationId)}/stop`,
    )
    stopAcknowledged = true
    taskFlowGenerationNote.value = response.data.data.stopped
      ? '已停止本次 AI 生成。'
      : '本次 AI 生成已经结束。'
    message.info(response.data.message)
  } catch (error: any) {
    taskFlowStopRequestedId = ''
    taskFlowGenerationStopping.value = false
    taskFlowGenerationNote.value = error.response?.data?.detail || error.message || '停止生成失败。'
    message.error(taskFlowGenerationNote.value)
  } finally {
    if (stopAcknowledged && taskFlowGenerationId.value === generationId) taskFlowGenerationController?.abort()
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
    step.target_channel_id ||= defaultTaskChatChannelId()
    step.message_content ||= '请大家及时查看并处理当前项目事项。'
    step.owner_user_id = ''
    step.material = ''
    if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
    return
  }
  step.mentioned_user_ids = []
}

function handleTaskMentionModeChange(step: TaskFlowStepDraft) {
  if (step.mention_mode !== 'users') {
    step.mentioned_user_ids = []
    return
  }
  if (step.target_channel_id) void loadTaskChatMembers(step.target_channel_id)
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
  if (taskFlowSubmitting.value || taskFlowGenerating.value || !taskFlowCanSubmit.value) return
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
  taskFlowSubmitting.value = true
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
      selectTaskManagementTab('schedules')
    } else {
      message.success('任务流已创建，可在执行记录中查看。')
      selectTaskManagementTab('history')
      resetTaskFlowCreator()
    }
  } catch (error: any) {
    message.error(error.response?.data?.detail || '任务流创建失败，请检查填写内容后重试。')
  } finally {
    taskFlowSubmitting.value = false
  }
}

function projectQualityWbsLabel(item: QualityMetric) {
  const code = item.wbsCode || (item.wbsId ? store.getWbsName(item.wbsId) : '')
  return [code, item.wbsName].filter(Boolean).join(' · ') || '未关联'
}

function tasksByIds(ids: string[]) {
  return ids
    .map(id => store.tasks.find(task => task.id === id))
    .filter((task): task is Task => Boolean(task))
}

</script>

<style scoped src="./styles/AiWorkPlatformView.base.css"></style>
<style scoped src="./styles/AiWorkPlatformView.home-conversations.css"></style>
<style scoped src="./styles/AiWorkPlatformView.connectivity.css"></style>
<style scoped src="./styles/AiWorkPlatformView.tasks.css"></style>
<style scoped src="./styles/AiWorkPlatformView.project-status.css"></style>
