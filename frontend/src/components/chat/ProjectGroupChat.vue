<template>
  <section class="project-chat-shell" aria-label="智能协同会话">
    <aside class="channel-rail" aria-label="会话列表">
      <header class="rail-heading">
        <button class="new-private-chat" type="button" title="新建群" @click="openPrivateChatDialog">
          <n-icon :size="18"><Plus /></n-icon>
          <span>新建群</span>
        </button>
      </header>

      <label class="channel-search">
        <n-icon :size="17"><Search /></n-icon>
        <input v-model="channelSearch" type="search" aria-label="搜索会话" placeholder="搜索会话" />
      </label>

      <div class="channel-list">
        <div v-if="loadingChannels" class="channel-skeleton" aria-label="正在加载群聊">
          <i></i><span></span><small></small>
        </div>
        <template v-if="filteredChannels.length">
          <button
            v-for="channel in filteredChannels"
            :key="channel.id"
            type="button"
            :class="['channel-item', { active: channel.id === activeChannelId }]"
            :aria-pressed="channel.id === activeChannelId"
            @click="activateChannel(channel.id)"
          >
            <span class="channel-copy">
              <strong :title="channelDisplayTitle(channel)">{{ channelDisplayTitle(channel) }}</strong>
              <span v-if="channel.all_members || channel.channel_type !== 'private'" class="group-all-mark" aria-label="全体成员">ALL</span>
              <span v-if="unread.counts[String(channel.id)]" class="group-unread" :aria-label="`${unread.counts[String(channel.id)]} 条未读消息`">{{ unread.counts[String(channel.id)] > 99 ? '99+' : unread.counts[String(channel.id)] }}</span>
              <span v-if="channel.last_message_at" class="channel-meta">
                <time>{{ compactTime(channel.last_message_at) }}</time>
              </span>
            </span>
          </button>
        </template>
        <div v-if="!loadingChannels && !channels.length && !pageError" class="rail-empty">
          当前项目还没有会话
        </div>
        <div v-else-if="!loadingChannels && !filteredChannels.length && !pageError" class="rail-empty">
          没有匹配的会话
        </div>
      </div>
    </aside>

    <main class="chat-stage">
      <header class="chat-heading">
        <div class="chat-heading-main">
          <div class="chat-channel-mark">
            <n-icon :size="20"><Hash /></n-icon>
          </div>
          <div>
            <h1>{{ displayChannelTitle }}</h1>
            <p><span class="current-project-name">{{ channelScopeLabel }}</span><span aria-hidden="true">·</span>{{ members.length }} 位成员共享</p>
          </div>
        </div>
        <div :class="['connection-state', realtimeStatus]" :title="connectionDescription">
          <n-icon :size="16"><Wifi v-if="realtimeStatus === 'connected'" /><WifiOff v-else /></n-icon>
          <span>{{ connectionLabel }}</span>
        </div>
      </header>

      <div v-if="pageError" class="chat-alert" role="alert">
        <n-icon :size="18"><AlertCircle /></n-icon>
        <span>{{ pageError }}</span>
        <button type="button" @click="reloadProjectChat">重试</button>
      </div>

      <div ref="messageViewport" class="message-viewport" aria-live="polite" @scroll="markVisibleMessagesRead">
        <div v-if="loadingMessages" class="message-loading" aria-label="正在加载消息">
          <div v-for="index in 3" :key="index" :class="['message-placeholder', { own: index === 2 }]">
            <i></i><span></span>
          </div>
        </div>

        <div v-else-if="activeChannel && !messages.length" class="chat-empty">
          <div class="empty-robot"><n-icon :size="34"><Robot /></n-icon></div>
          <h3>群聊已经准备好</h3>
          <p>发一条消息开始协作。群文件会按群名称自动存入知识库，仅群成员和工程管理员可见。</p>
        </div>

        <article
          v-for="item in messages"
          :key="item.id"
          :ref="element => registerMessageElement(item, element)"
          :data-message-id="item.id"
          :class="[
            'chat-message',
            {
              own: isOwnMessage(item),
              agent: item.sender_type === 'agent',
              mentioned: isMentioningCurrentUser(item),
              'mention-pulse': pulsingMentionIds.has(item.id),
              failed: Boolean(item.metadata?.failed),
            },
          ]"
        >
          <div class="sender-avatar" aria-hidden="true">
            <n-icon v-if="item.sender_type === 'agent'" :size="18"><Robot /></n-icon>
            <span v-else>{{ senderInitial(item) }}</span>
          </div>
          <div class="message-body">
            <div class="message-meta">
              <strong>{{ senderName(item) }}</strong>
              <span v-if="item.sender_type === 'agent'" class="agent-label">智能体</span>
              <span v-if="agentRuntimeLabel(item)" class="runtime-label">{{ agentRuntimeLabel(item) }}</span>
              <time>{{ messageTime(item.created_at) }}</time>
            </div>
            <div
              v-if="item.message_type === 'task_draft'"
              class="message-content task-draft-history"
              v-html="renderTaskDraftContent(item.content)"
            ></div>
            <div v-else-if="item.message_type === 'task_event'" class="task-event-message">
              <span class="task-event-icon" aria-hidden="true"><n-icon :size="19"><CircleCheck /></n-icon></span>
              <span class="task-event-copy">
                <small>{{ item.content }}</small>
                <strong>{{ taskEventTitle(item) }}</strong>
                <em>{{ taskEventExecutionLabel(item) }}</em>
              </span>
              <router-link :to="taskEventRoute(item)">
                {{ taskEventLinkLabel(item) }}
              </router-link>
            </div>
            <ChatAgentRunControls v-else-if="item.sender_type === 'agent'" :item="item"
              :current-user-id="currentUserId" @updated="mergeMessages([$event])" />
            <div v-else class="message-content">
              <template v-for="(segment, segmentIndex) in messageSegments(item)" :key="`${item.id}-${segmentIndex}`">
                <span
                  v-if="segment.targetType"
                  :class="['message-mention', segment.targetType]"
                >{{ segment.text }}</span>
                <template v-else>{{ segment.text }}</template>
              </template>
            </div>
            <ChatMessageFiles :message="item" :project-id="store.currentProjectId" />
            <div v-if="item.message_type !== 'task_event' && item.task_ids?.length" class="message-task-links" aria-label="消息关联任务">
              <router-link v-for="taskId in item.task_ids" :key="taskId" :to="taskRoute(taskId)">
                <n-icon :size="14"><ListCheck /></n-icon>{{ taskTitle(taskId) }}
              </router-link>
            </div>
            <div v-if="businessMentionedAgentNames(item).length" class="agent-request-note">
              <n-icon :size="15"><Robot /></n-icon>
              已通知 {{ businessMentionedAgentNames(item).join('、') }}，处理结果会自动回复到当前会话
            </div>
          </div>
        </article>
      </div>

      <footer class="message-composer">
        <button
          v-if="activePrivateTaskDraft && !taskDraftDialogOpen"
          type="button"
          :class="['private-task-draft-launcher', `is-${activePrivateTaskDraft.status}`]"
          @click="openTaskDraftDialog"
        >
          <span class="private-task-draft-launcher-icon">
            <n-icon v-if="['generating', 'publishing'].includes(activePrivateTaskDraft.status)" :size="18" class="task-draft-spinner"><Loader /></n-icon>
            <n-icon v-else-if="activePrivateTaskDraft.status === 'ready'" :size="18"><ClipboardCheck /></n-icon>
            <n-icon v-else :size="18"><AlertCircle /></n-icon>
          </span>
          <span>
            <strong>{{ privateTaskDraftLauncherTitle }}</strong>
            <small>{{ privateTaskDraftLauncherDescription }}</small>
          </span>
          <em>打开</em>
        </button>
        <div v-if="contextTask" class="task-context-notice" role="status">
          <span><n-icon :size="17"><ListCheck /></n-icon></span>
          <div><strong>正在讨论：{{ contextTask.title }}</strong><small>{{ contextTask.triggerReason || '任务上下文已带入当前群聊' }}</small></div>
          <router-link :to="taskRoute(contextTask.id)">查看任务</router-link>
          <button type="button" aria-label="取消关联任务" @click="clearTaskContext"><X :size="16" /></button>
        </div>
        <div v-if="activeMentionNotice" class="mention-notice" role="status" aria-live="polite">
          <span class="mention-notice-icon" aria-hidden="true">
            <n-icon :size="17"><At /></n-icon>
          </span>
          <span class="mention-notice-copy">
            <strong>{{ activeMentionNoticeTitle }}</strong>
            <span>{{ activeMentionNoticeDescription }}</span>
          </span>
          <span v-if="mentionNotices.length > 1" class="mention-notice-count">
            {{ mentionNotices.length }} 条
          </span>
          <button
            type="button"
            class="mention-notice-locate"
            :disabled="locatingMentionNotice"
            @click="viewActiveMentionNotice"
          >
            {{ locatingMentionNotice ? '定位中' : '查看' }}
          </button>
        </div>
        <div v-if="realtimeStatus !== 'connected'" class="polling-note">
          实时通道暂未连接，页面会定时刷新；消息仍会正常保存。
          <button type="button" :disabled="manualRefreshing || loadingMessages" :aria-busy="manualRefreshing" @click="manualRefresh">
            <n-icon v-if="manualRefreshing" :size="14" class="task-draft-spinner"><Loader /></n-icon>
            {{ manualRefreshing ? '正在刷新…' : '立即刷新' }}
          </button>
        </div>
        <form class="project-chat-composer" @submit.prevent="sendMessage">
          <div v-if="mentionMenuOpen" class="mention-menu" role="listbox" aria-label="选择要提及的人员或智能体">
            <div v-if="filteredMentionOptions.length" class="mention-options">
              <button
                v-for="(option, optionIndex) in filteredMentionOptions"
                :key="option.key"
                type="button"
                role="option"
                :aria-selected="optionIndex === mentionActiveIndex"
                :class="['mention-option', option.type, { active: optionIndex === mentionActiveIndex }]"
                @mouseenter="mentionActiveIndex = optionIndex"
                @mousedown.prevent="selectMention(option)"
              >
                <span :class="['mention-avatar', option.type]">
                  <n-icon v-if="option.type === 'all'" :size="17"><At /></n-icon>
                  <n-icon v-else-if="option.type === 'agent'" :size="17"><Robot /></n-icon>
                  <n-icon v-else :size="17"><User /></n-icon>
                </span>
                <span class="mention-copy">
                  <strong>{{ option.name }}</strong>
                  <small>{{ option.subtitle }}</small>
                </span>
              </button>
            </div>
            <div v-else class="mention-empty">没有符合条件的可提及对象</div>
          </div>

          <ChatComposerSurface :busy="sending">
            <div
              ref="composerInput"
              :contenteditable="Boolean(activeChannel && !sending)"
              :class="['composer-editor', 'chat-composer-input', { disabled: !activeChannel || sending }]"
              :data-empty="!draft"
              :data-placeholder="activeChannel ? `发消息到${displayChannelTitle}；输入 @ 提及成员或智能体` : '请先选择会话'"
              role="textbox"
              aria-multiline="true"
              aria-label="群聊消息"
              @blur="deferCloseMentionMenu"
              @click="updateMentionState"
              @input="updateMentionState"
              @paste="handleComposerPaste"
              @keydown="handleComposerKeydown"
            ></div>
            <template #tools>
              <ChatGroupFileUpload :channel-id="activeChannelId" :disabled="sending" @uploaded="handleFileUploaded" />
              <button
                type="button"
                class="mention-trigger chat-composer-tool"
                :disabled="!activeChannel || sending"
                aria-label="提及成员或智能体"
                title="提及成员或智能体"
                @mousedown.prevent
                @click="openMentionMenu"
              >
                <n-icon :size="16"><At /></n-icon>
                <span>提及</span>
              </button>
            </template>
            <template #action>
              <button class="send-message chat-composer-action" type="submit" :disabled="!canSend">
              <n-icon :size="17"><Send /></n-icon>
              {{ sending ? '发送中' : '发送' }}
              </button>
            </template>
          </ChatComposerSurface>
        </form>
      </footer>
    </main>

    <aside class="chat-context" aria-label="群聊信息">
      <section class="context-section group-summary">
        <div class="context-eyebrow">{{ currentProjectName }}</div>
        <h2>{{ displayChannelTitle }} <span v-if="activeChannel && activeChannel.channel_type !== 'private'" class="group-all-mark">ALL</span></h2>
        <p>{{ activeChannel?.summary || '项目成员共享的实时协同群聊' }}</p>
        <dl>
          <div><dt>消息范围</dt><dd>群成员</dd></div>
          <div><dt>成员</dt><dd>{{ members.length }} 人</dd></div>
          <div><dt>消息记录</dt><dd>持续保存</dd></div>
        </dl>
      </section>

      <section class="context-section member-section">
        <header>
          <div>
            <span class="context-eyebrow">参与人</span>
            <h3>{{ activeChannel?.channel_type === 'private' ? '私聊成员' : '项目成员' }}</h3>
          </div>
          <span>{{ members.length }}</span>
        </header>
        <div class="member-list">
          <article v-for="member in members" :key="member.user_id" class="member-row">
            <div class="member-avatar">{{ member.name.slice(0, 1) }}</div>
            <div class="participant-picker-summary">
              <strong>{{ member.name }}<em v-if="member.user_id === currentUserId">我</em></strong>
              <small>{{ member.title }}</small>
            </div>
            <span v-if="member.member_role === 'owner'" class="owner-label">群主</span>
          </article>
        </div>
      </section>

      <section class="context-section agent-boundary">
        <div class="boundary-icon"><n-icon :size="20"><Robot /></n-icon></div>
        <div>
          <h3>智能体按需参与</h3>
          <p>输入 @ 可选择项目成员或已发布智能体。提及人员会定向提醒；只有明确提及智能体时，平台才传递当前项目与必要群聊上下文。</p>
        </div>
      </section>
    </aside>
  </section>

  <n-modal
    v-model:show="privateChatDialogOpen"
    :auto-focus="false"
    :mask-closable="!creatingPrivateChat"
    @after-enter="focusPrivateChatTitle"
  >
    <section class="private-chat-dialog" role="dialog" aria-modal="true" aria-labelledby="private-chat-dialog-title">
      <header>
        <div>
          <span>智能协同</span>
          <h2 id="private-chat-dialog-title">新建群</h2>
          <p>选择全体成员或指定成员，同一工程内群名称不能重复。</p>
        </div>
        <button type="button" aria-label="关闭" :disabled="creatingPrivateChat" @click="closePrivateChatDialog">
          <n-icon :size="20"><X /></n-icon>
        </button>
      </header>

      <div class="private-chat-form">
        <div class="private-chat-name">
          <label for="private-chat-title">群名称 <em>必填</em></label>
          <input
            id="private-chat-title"
            ref="privateChatTitleInput"
            v-model="privateChatTitle"
            type="text"
            maxlength="100"
            required
            aria-required="true"
            placeholder="请输入不重复的群名称"
          >
        </div>

        <label class="group-all-choice"><input v-model="allGroupMembers" type="checkbox">全体项目成员 <span class="group-all-mark">ALL</span></label>
        <section v-if="!allGroupMembers" class="participant-picker" aria-label="选择群成员">
          <div class="participant-picker-head">
            <div>
              <strong>选择参与人</strong>
              <span>已选 {{ selectedParticipantIds.length }} 人</span>
            </div>
            <div class="participant-search" @click="focusParticipantSearch">
              <n-icon :size="17"><Search /></n-icon>
              <input
                id="private-chat-participant-search"
                ref="participantSearchInput"
                v-model="participantSearch"
                type="search"
                aria-label="搜索参与人"
                placeholder="搜索姓名或岗位"
              >
            </div>
          </div>

          <div v-if="loadingParticipants" class="participant-loading">正在加载项目成员…</div>
          <div v-else-if="filteredParticipants.length" class="participant-results">
            <div class="participant-list" role="list" aria-label="可选项目成员">
              <div class="participant-list-head" aria-hidden="true">
                <span>选择</span>
                <span>姓名</span>
                <span>岗位</span>
              </div>
              <label
                v-for="participant in pagedParticipants"
                :key="participant.user_id"
                :class="['participant-option', { selected: selectedParticipantIds.includes(participant.user_id) }]"
                role="listitem"
              >
                <input v-model="selectedParticipantIds" type="checkbox" :value="participant.user_id">
                <strong>{{ participant.name }}</strong>
                <span>{{ participant.title }}</span>
              </label>
            </div>
            <nav class="participant-pagination" aria-label="参与人分页">
              <span>{{ participantRangeStart }}–{{ participantRangeEnd }} / {{ filteredParticipants.length }}</span>
              <div>
                <button
                  type="button"
                  :disabled="participantPage <= 1"
                  @click="setParticipantPage(participantPage - 1)"
                >上一页</button>
                <em>第 {{ participantPage }} / {{ participantPageCount }} 页</em>
                <button
                  type="button"
                  :disabled="participantPage >= participantPageCount"
                  @click="setParticipantPage(participantPage + 1)"
                >下一页</button>
              </div>
            </nav>
          </div>
          <div v-else class="participant-empty">没有符合条件的项目成员</div>
        </section>

        <p v-if="privateChatError" class="private-chat-error" role="alert">{{ privateChatError }}</p>
      </div>

      <footer>
        <span>你会自动加入该会话并成为群主</span>
        <div>
          <button type="button" class="dialog-cancel" :disabled="creatingPrivateChat" @click="closePrivateChatDialog">取消</button>
          <button type="button" class="dialog-submit" :disabled="!canCreatePrivateChat" @click="createPrivateChat">
            <n-icon v-if="creatingPrivateChat" :size="16" class="task-draft-spinner"><Loader /></n-icon>
            {{ creatingPrivateChat ? '创建中…' : '创建群' }}
          </button>
        </div>
      </footer>
    </section>
  </n-modal>

  <n-modal
    v-model:show="taskDraftDialogOpen"
    :auto-focus="true"
    :close-on-esc="!isTaskDraftPublishing"
    :mask-closable="false"
  >
    <section
      v-if="activePrivateTaskDraft || creatingTaskDraft || taskDraftStartError"
      class="task-draft-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="task-draft-dialog-title"
    >
      <header>
        <div class="task-draft-dialog-mark"><n-icon :size="22"><ClipboardCheck /></n-icon></div>
        <div>
          <h2 id="task-draft-dialog-title">布置任务</h2>
          <p>{{ privateTaskDraftRequestSummary }}</p>
        </div>
        <span :class="['task-draft-status', `is-${privateTaskDraftStatus}`]">{{ privateTaskDraftStatusLabel }}</span>
        <button type="button" aria-label="关闭" :disabled="isTaskDraftPublishing" @click="closeTaskDraftDialog">
          <n-icon :size="20"><X /></n-icon>
        </button>
      </header>

      <div v-if="isTaskDraftGenerating" class="task-draft-generation" role="status" aria-live="polite">
        <ol class="task-draft-generation-flow" aria-label="Dobby 任务分析进度">
          <li class="is-active"><i>1</i><span><strong>读取群聊上下文</strong><small>只读取当前会话必要内容</small></span></li>
          <li class="is-active"><i>2</i><span><strong>提取任务要素</strong><small>识别时间、对象与交付要求</small></span></li>
          <li class="is-active"><i>3</i><span><strong>整理任务草稿</strong><small>发布前仍由你确认和修改</small></span></li>
        </ol>
        <section class="task-draft-generation-stage">
          <span class="task-draft-generation-orbit" aria-hidden="true">
            <n-icon :size="28"><Robot /></n-icon>
          </span>
          <h3>任务助手正在分析任务需求</h3>
          <p>正在结合群聊上下文梳理任务要素，完成后会在这里显示可编辑草稿。</p>
          <div class="task-draft-generation-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
        </section>
      </div>

      <div v-else-if="isTaskDraftPublishing" class="task-draft-publishing" role="status" aria-live="polite">
        <span class="task-draft-generation-orbit" aria-hidden="true">
          <n-icon :size="28"><ClipboardCheck /></n-icon>
        </span>
        <h3>正在发布任务</h3>
        <p>正在写入任务中心并同步群内正式任务消息，请勿重复操作。</p>
      </div>

      <div v-else-if="isTaskDraftUnavailable" class="task-draft-unavailable" role="alert">
        <span><n-icon :size="28"><AlertCircle /></n-icon></span>
        <h3>{{ privateTaskDraftStatus === 'cancelled' ? '任务助手已停止分析' : '任务助手未能完成分析' }}</h3>
        <p>{{ taskDraftStartError || activePrivateTaskDraft?.error || '分析过程遇到问题，请重新尝试。' }}</p>
        <small>本次内容没有发送到群聊，也没有创建任务。</small>
      </div>

      <form v-else-if="taskDraftForm" class="task-draft-form" @submit.prevent="publishTaskDraft">
        <section class="task-draft-form-section">
          <h3>任务内容</h3>
          <label class="task-draft-field full">
            <span>任务名称</span>
            <input v-model.trim="taskDraftForm.title" type="text" maxlength="120" required>
          </label>
          <label class="task-draft-field full">
            <span>分析依据</span>
            <textarea v-model.trim="taskDraftForm.trigger_reason" rows="2" maxlength="1000"></textarea>
          </label>
        </section>

        <section class="task-draft-form-section">
          <h3>执行时间</h3>
          <div class="task-draft-field-grid three">
            <label class="task-draft-field">
              <span>执行方式</span>
              <select v-model="taskDraftForm.run_mode">
                <option value="immediate">立即执行</option>
                <option value="once">单次定时</option>
                <option value="recurring">周期执行</option>
              </select>
            </label>
            <label v-if="taskDraftForm.run_mode !== 'immediate'" class="task-draft-field">
              <span>首次日期</span>
              <input v-model="taskDraftForm.trigger_date" type="date" required>
            </label>
            <label v-if="taskDraftForm.run_mode !== 'immediate'" class="task-draft-field">
              <span>执行时间</span>
              <input v-model="taskDraftForm.trigger_time" type="time" required>
            </label>
          </div>
          <div v-if="taskDraftForm.run_mode === 'recurring'" class="task-draft-field-grid two compact-row">
            <label class="task-draft-field">
              <span>间隔</span>
              <input v-model.number="taskDraftForm.trigger_interval_value" type="number" min="1" max="999" required>
            </label>
            <label class="task-draft-field">
              <span>单位</span>
              <select v-model="taskDraftForm.trigger_interval_unit">
                <option value="minute">分钟</option>
                <option value="hour">小时</option>
                <option value="day">天</option>
                <option value="week">周</option>
                <option value="month">月</option>
              </select>
            </label>
          </div>
        </section>

        <section v-if="taskDraftForm.action_type === 'project_chat_message'" class="task-draft-form-section">
          <h3>群聊消息</h3>
          <div class="task-draft-field-grid two">
            <label class="task-draft-field">
              <span>目标群聊</span>
              <select v-model="taskDraftForm.target_channel_id" required>
                <option v-for="channel in channels" :key="channel.id" :value="channel.id">
                  {{ channelDisplayTitle(channel) }}
                </option>
              </select>
            </label>
            <label class="task-draft-field">
              <span>提醒范围</span>
              <select v-model="taskDraftForm.mention_mode">
                <option value="none">不艾特成员</option>
                <option value="all">全体成员</option>
                <option value="users">指定成员</option>
              </select>
            </label>
          </div>

          <div v-if="taskDraftForm.mention_mode === 'users'" class="task-draft-recipient-picker">
            <label class="task-draft-field">
              <span>添加成员</span>
              <select v-model="taskDraftMemberToAdd" @change="addTaskDraftMember">
                <option value="">选择要提醒的成员</option>
                <option
                  v-for="person in availableTaskDraftPeople"
                  :key="person.user_id"
                  :value="String(person.user_id)"
                >{{ person.name }} · {{ person.title }}</option>
              </select>
            </label>
            <div class="task-draft-recipient-cards" aria-label="已选择提醒成员">
              <span v-for="person in selectedTaskDraftPeople" :key="person.user_id">
                <b>{{ person.name }}</b>
                <button type="button" :aria-label="`移除${person.name}`" @click="removeTaskDraftMember(person.user_id)"><X :size="14" /></button>
              </span>
              <em v-if="!selectedTaskDraftPeople.length">还没有选择提醒成员</em>
            </div>
          </div>

          <label class="task-draft-field full">
            <span>消息正文</span>
            <textarea v-model.trim="taskDraftForm.message_content" rows="4" maxlength="8000" required></textarea>
          </label>
        </section>

        <section v-else class="task-draft-form-section">
          <h3>责任配置</h3>
          <div class="task-draft-field-grid two">
            <label class="task-draft-field">
              <span>默认责任人</span>
              <select v-model="taskDraftForm.assignee_user_id">
                <option :value="null">请选择</option>
                <option v-for="person in taskDraftPeople" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
              </select>
            </label>
            <label class="task-draft-field">
              <span>确认人</span>
              <select v-model="taskDraftForm.confirmer_user_id">
                <option :value="null">请选择</option>
                <option v-for="person in taskDraftPeople" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
              </select>
            </label>
            <label class="task-draft-field">
              <span>关联 WBS</span>
              <select v-model="taskDraftForm.wbs_item_id">
                <option :value="null">不关联</option>
                <option v-for="item in store.wbsItems" :key="item.id" :value="Number(item.id)">{{ item.name }}</option>
              </select>
            </label>
            <label class="task-draft-field">
              <span>关联风险源</span>
              <select v-model="taskDraftForm.risk_source_id">
                <option :value="null">不关联</option>
                <option v-for="risk in store.riskSources" :key="risk.id" :value="Number(risk.id)">{{ risk.name }}</option>
              </select>
            </label>
          </div>
          <div class="task-draft-steps">
            <article v-for="(step, index) in taskDraftForm.workflow_steps" :key="index">
              <div class="task-draft-step-number">{{ index + 1 }}</div>
              <label class="task-draft-field">
                <span>节点名称</span>
                <input v-model.trim="step.name" type="text" maxlength="80" required>
              </label>
              <label v-if="step.node_type === 'manual'" class="task-draft-field">
                <span>责任人</span>
                <select v-model="step.owner_user_id" required>
                  <option :value="null">请选择</option>
                  <option v-for="person in taskDraftPeople" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
                </select>
              </label>
              <label v-if="step.node_type === 'manual'" class="task-draft-field full">
                <span>交付材料</span>
                <input v-model.trim="step.material" type="text" maxlength="200">
              </label>
            </article>
          </div>
        </section>

        <p v-if="taskDraftError" class="task-draft-error" role="alert">{{ taskDraftError }}</p>
      </form>

      <footer v-if="isTaskDraftGenerating">
        <span>该过程仅你可见，可以关闭弹框后继续等待</span>
        <div>
          <button type="button" class="dialog-cancel" :disabled="taskDraftActionId !== null" @click="dismissTaskDraft">
            {{ taskDraftActionId !== null ? '正在取消…' : '取消本次' }}
          </button>
          <button type="button" class="dialog-submit secondary" @click="closeTaskDraftDialog">后台继续</button>
        </div>
      </footer>

      <footer v-else-if="isTaskDraftPublishing">
        <span>发布完成后，群内会出现一条正式任务卡片</span>
        <div><button type="button" class="dialog-submit" disabled>正在发布…</button></div>
      </footer>

      <footer v-else-if="isTaskDraftUnavailable">
        <span>重新分析仍会使用刚才的群聊上下文</span>
        <div>
          <button type="button" class="dialog-cancel" :disabled="taskDraftActionId !== null" @click="dismissTaskDraft">关闭本次</button>
          <button
            v-if="activePrivateTaskDraft"
            type="button"
            class="dialog-submit"
            :disabled="taskDraftActionId !== null"
            @click="retryTaskDraft"
          >
            <n-icon v-if="taskDraftActionId !== null" :size="16" class="task-draft-spinner"><Loader /></n-icon>
            {{ taskDraftActionId !== null ? 'Dobby 正在重新分析…' : '重新分析' }}
          </button>
        </div>
      </footer>

      <footer v-else-if="taskDraftForm">
        <span>草稿仅你可见，发布后群内才显示正式任务</span>
        <div>
          <button type="button" class="dialog-cancel" :disabled="publishingTaskDraft || dismissingTaskDraft" @click="dismissTaskDraft">
            {{ dismissingTaskDraft ? '正在取消…' : '取消本次' }}
          </button>
          <button type="button" class="dialog-submit" :disabled="!canPublishTaskDraft" @click="publishTaskDraft">
            <n-icon v-if="publishingTaskDraft" :size="16" class="task-draft-spinner"><Loader /></n-icon>
            {{ publishingTaskDraft ? '发布中…' : '确认发布任务' }}
          </button>
        </div>
      </footer>
    </section>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { NIcon, NModal, useMessage } from 'naive-ui'
import dayjs from 'dayjs'
import MarkdownIt from 'markdown-it'
import {
  AlertCircle, At, CircleCheck, ClipboardCheck, Hash, ListCheck, Loader, Lock,
  Plus, Robot, Search, Send, User, Wifi, WifiOff, X,
} from '@vicons/tabler'

import {
  claimProjectChatMention,
  connectProjectChatRealtime,
  createPrivateProjectChatChannel,
  createProjectChatTaskDraft,
  dismissPrivateProjectChatTaskDraft,
  getProjectChatMessage,
  getProjectChatTaskDraft,
  listProjectChatAgents,
  listProjectChatChannels,
  listProjectChatMembers,
  listProjectChatMessages,
  listProjectChatMentionNotices,
  listProjectChatParticipants,
  listProjectChatTaskDrafts,
  publishPrivateProjectChatTaskDraft,
  retryPrivateProjectChatTaskDraft,
  sendProjectChatMessage,
  stopPrivateProjectChatTaskDraft,
  type ProjectChatAgent,
  type ProjectChatChannel,
  type ProjectChatMember,
  type ProjectChatMessage,
  type ProjectChatParticipant,
  type ProjectChatPrivateTaskDraft,
  type ProjectChatRealtimeStatus,
  type ProjectChatTaskDraft,
} from '@/api/projectChat'
import ChatComposerSurface from '@/components/chat/ChatComposerSurface.vue'
import ChatAgentRunControls from '@/components/chat/ChatAgentRunControls.vue'
import ChatGroupFileUpload from '@/components/chat/ChatGroupFileUpload.vue'
import ChatMessageFiles from '@/components/chat/ChatMessageFiles.vue'
import { useChatUnreadStore } from '@/stores/chatUnread'
import {
  useProjectChatComposer,
  type ProjectChatMentionOption as MentionOption,
} from '@/composables/useProjectChatComposer'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const unread = useChatUnreadStore()
const allGroupMembers = ref(false)
function handleFileUploaded(item: ProjectChatMessage) {
  if (item.channel_id === activeChannelId.value) mergeMessages([item], true)
  void unread.refresh(store.currentProjectId)
}
const acknowledgedMessages = new Map<number, number>()
let markingRead = false
async function markVisibleMessagesRead() {
  await nextTick()
  const channelId = activeChannelId.value, projectId = store.currentProjectId, lastId = messages.value[messages.value.length - 1]?.id
  if (!channelId || !lastId || markingRead || loadingMessages.value || document.visibilityState !== 'visible' || !isNearMessageBottom() || (acknowledgedMessages.get(channelId) || 0) >= lastId) return
  markingRead = true
  try { await unread.markRead(projectId, channelId, lastId); acknowledgedMessages.set(channelId, lastId) }
  catch { /* 保留未读数字，下次可见时重试。 */ }
  finally { markingRead = false }
}
const notice = useMessage()
const route = useRoute()
const router = useRouter()

const taskDraftMarkdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: false,
})
const taskDraftLinkOpen = taskDraftMarkdown.renderer.rules.link_open
taskDraftMarkdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return taskDraftLinkOpen
    ? taskDraftLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}
const taskDraftMarkdownCache = new Map<string, string>()

const channels = ref<ProjectChatChannel[]>([])
const channelSearch = ref('')
const activeChannelId = ref<number | null>(null)
const members = ref<ProjectChatMember[]>([])
const messages = ref<ProjectChatMessage[]>([])
const draft = ref('')
const loadingChannels = ref(false)
const loadingMessages = ref(false)
const manualRefreshing = ref(false)
const sending = ref(false)
const pageError = ref('')
const realtimeStatus = ref<ProjectChatRealtimeStatus>('connecting')
const messageViewport = ref<HTMLElement | null>(null)
const projectParticipants = ref<ProjectChatParticipant[]>([])
const mentionAgents = ref<ProjectChatAgent[]>([])
const mentionAgentsLoading = ref(false)
const mentionAgentsLoaded = ref(false)
const privateChatDialogOpen = ref(false)
const privateChatTitle = ref('')
const privateChatTitleInput = ref<HTMLInputElement | null>(null)
const participantSearch = ref('')
const participantSearchInput = ref<HTMLInputElement | null>(null)
const participantPage = ref(1)
const selectedParticipantIds = ref<number[]>([])
const loadingParticipants = ref(false)
const creatingPrivateChat = ref(false)
const privateChatError = ref('')
const pulsingMentionIds = ref<Set<number>>(new Set())
const mentionNotices = ref<ProjectChatMessage[]>([])
const locatingMentionNotice = ref(false)
const taskDraftDialogOpen = ref(false)
const activePrivateTaskDraft = ref<ProjectChatPrivateTaskDraft | null>(null)
const taskDraftForm = ref<ProjectChatTaskDraft | null>(null)
const taskDraftMemberToAdd = ref('')
const taskDraftError = ref('')
const taskDraftStartError = ref('')
const creatingTaskDraft = ref(false)
const cancelPendingTaskDraftCreation = ref(false)
const taskDraftRequestPreview = ref('')
const taskDraftActionId = ref<number | null>(null)
const publishingTaskDraft = ref(false)
const dismissingTaskDraft = ref(false)

let loadGeneration = 0
let pollTimer: number | null = null
let realtimeClient: Awaited<ReturnType<typeof connectProjectChatRealtime>> | null = null
let refreshingChannelList = false
let mentionObserver: IntersectionObserver | null = null
const messageElements = new Map<number, HTMLElement>()
const claimingMentionIds = new Set<number>()
const resolvedMentionIds = new Set<number>()
const mentionPulseTimers = new Map<number, number>()

type MessageSegment = {
  text: string
  targetType: 'all' | 'user' | 'agent' | null
}

const {
  composerInput,
  mentionMenuOpen,
  mentionQuery,
  mentionActiveIndex,
  selectedMentions,
  renderComposer,
  syncDraftFromEditor,
  clearComposer,
  closeMentionMenu,
  deferCloseMentionMenu,
  updateMentionState,
  selectMention,
  openMentionMenu,
  handleComposerPaste,
  handleComposerKeydown,
} = useProjectChatComposer({
  draft,
  filteredMentionOptions: () => filteredMentionOptions.value,
  loadMentionAgents,
  sendMessage,
  warn: value => notice.warning(value),
})

const activeChannel = computed(() => (
  channels.value.find(item => item.id === activeChannelId.value) || null
))
const contextTaskId = computed(() => queryNumberOrString(route.query.taskId))
const contextTask = computed(() => (
  store.tasks.find(task => task.id === contextTaskId.value) || null
))
const activeMentionNotice = computed(() => mentionNotices.value[0] || null)
const activeMentionNoticeTitle = computed(() => {
  const item = activeMentionNotice.value
  return item ? `${senderName(item)} 提到了你` : ''
})
const activeMentionNoticeDescription = computed(() => {
  const item = activeMentionNotice.value
  if (!item) return ''
  const channel = channels.value.find(candidate => candidate.id === item.channel_id)
  const channelTitle = channel ? channelDisplayTitle(channel) : '项目会话'
  const preview = item.content.replace(/\s+/g, ' ').trim().slice(0, 72)
  return `来自「${channelTitle}」${preview ? ` · ${preview}` : ''}`
})
const currentProjectName = computed(() => store.currentProject?.name || '当前项目')
const currentUserId = computed(() => Number(sessionStorage.getItem('current_user_id') || 0))
const canSend = computed(() => Boolean(activeChannel.value && draft.value.trim() && !sending.value))
const filteredChannels = computed(() => {
  const keyword = channelSearch.value.trim().toLowerCase()
  if (!keyword) return channels.value
  return channels.value.filter(channel => [
    channelDisplayTitle(channel),
    channel.summary,
    channel.last_message?.content,
  ].some(value => value?.toLowerCase().includes(keyword)))
})
const displayChannelTitle = computed(() => {
  if (loadingChannels.value) return '正在加载群聊'
  return activeChannel.value ? channelDisplayTitle(activeChannel.value) : '群聊'
})
const channelScopeLabel = computed(() => (
  activeChannel.value?.channel_type === 'private'
    ? '仅所选成员可见'
    : currentProjectName.value
))
const filteredParticipants = computed(() => {
  const keyword = participantSearch.value.trim().toLowerCase()
  return projectParticipants.value.filter(participant => {
    if (participant.user_id === currentUserId.value) return false
    if (!keyword) return true
    return `${participant.name} ${participant.title}`.toLowerCase().includes(keyword)
  })
})
const PARTICIPANTS_PER_PAGE = 10
const participantPageCount = computed(() => Math.max(
  1,
  Math.ceil(filteredParticipants.value.length / PARTICIPANTS_PER_PAGE),
))
const pagedParticipants = computed(() => {
  const start = (participantPage.value - 1) * PARTICIPANTS_PER_PAGE
  return filteredParticipants.value.slice(start, start + PARTICIPANTS_PER_PAGE)
})
const participantRangeStart = computed(() => (
  filteredParticipants.value.length
    ? (participantPage.value - 1) * PARTICIPANTS_PER_PAGE + 1
    : 0
))
const participantRangeEnd = computed(() => Math.min(
  participantPage.value * PARTICIPANTS_PER_PAGE,
  filteredParticipants.value.length,
))
const mentionOptions = computed<MentionOption[]>(() => [
  {
    key: 'all',
    type: 'all' as const,
    id: 'all',
    name: '全体成员',
    subtitle: '通知当前会话所有成员',
  },
  ...members.value
    .filter(member => member.user_id !== currentUserId.value)
    .map(member => ({
      key: `user:${member.user_id}`,
      type: 'user' as const,
      id: member.user_id,
      name: member.name,
      subtitle: member.title,
    })),
  ...mentionAgents.value
    .filter(agent => agent.enabled && agent.published && agent.model_ready)
    .map(agent => ({
      key: `agent:${agent.id}`,
      type: 'agent' as const,
      id: agent.id,
      name: agent.name,
      subtitle: agent.description || agent.category || '业务智能体',
    })),
])
const filteredMentionOptions = computed(() => {
  const keyword = mentionQuery.value.trim().toLowerCase()
  if (!keyword) return mentionOptions.value
  return mentionOptions.value.filter(option => (
    `${option.name} ${option.subtitle}`.toLowerCase().includes(keyword)
  ))
})
const canCreatePrivateChat = computed(() => (
  privateChatTitle.value.trim().length > 0
  && (allGroupMembers.value || selectedParticipantIds.value.length > 0)
  && !creatingPrivateChat.value
))
const taskDraftPeople = computed(() => {
  const people = new Map<number, ProjectChatParticipant>()
  projectParticipants.value.forEach(person => people.set(person.user_id, person))
  members.value.forEach(member => people.set(member.user_id, {
    user_id: member.user_id,
    name: member.name,
    title: member.title,
  }))
  return [...people.values()].sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
})
const selectedTaskDraftPeople = computed(() => {
  const selected = new Set(taskDraftForm.value?.mentioned_user_ids || [])
  return taskDraftPeople.value.filter(person => selected.has(person.user_id))
})
const availableTaskDraftPeople = computed(() => {
  const selected = new Set(taskDraftForm.value?.mentioned_user_ids || [])
  return taskDraftPeople.value.filter(person => !selected.has(person.user_id))
})
const canPublishTaskDraft = computed(() => {
  const form = taskDraftForm.value
  if (
    !form
    || activePrivateTaskDraft.value?.status !== 'ready'
    || publishingTaskDraft.value
    || dismissingTaskDraft.value
  ) return false
  if (!form.title.trim()) return false
  if (form.run_mode !== 'immediate' && (!form.trigger_date || !form.trigger_time)) return false
  if (form.run_mode === 'recurring' && form.trigger_interval_value < 1) return false
  if (form.action_type === 'project_chat_message') {
    return Boolean(
      form.target_channel_id
      && form.message_content?.trim()
      && (form.mention_mode !== 'users' || form.mentioned_user_ids.length),
    )
  }
  const fallbackOwner = form.assignee_user_id
  return Boolean(
    form.confirmer_user_id
    && form.wbs_item_id
    && form.workflow_steps.length
    && form.workflow_steps.every(step => (
      step.node_type !== 'manual' || step.owner_user_id || fallbackOwner
    )),
  )
})
const privateTaskDraftStatus = computed(() => {
  if (publishingTaskDraft.value) return 'publishing'
  if (creatingTaskDraft.value) return 'generating'
  if (taskDraftStartError.value) return 'failed'
  return activePrivateTaskDraft.value?.status || 'generating'
})
const privateTaskDraftStatusLabel = computed(() => ({
  generating: '任务助手分析中',
  ready: '待你确认',
  publishing: '正在发布',
  published: '已经发布',
  dismissed: '已经关闭',
  cancelled: '已停止',
  failed: '分析失败',
}[privateTaskDraftStatus.value] || '处理中'))
const isTaskDraftGenerating = computed(() => (
  creatingTaskDraft.value || activePrivateTaskDraft.value?.status === 'generating'
))
const isTaskDraftPublishing = computed(() => (
  publishingTaskDraft.value || activePrivateTaskDraft.value?.status === 'publishing'
))
const isTaskDraftUnavailable = computed(() => Boolean(
  taskDraftStartError.value
  || ['failed', 'cancelled'].includes(activePrivateTaskDraft.value?.status || ''),
))
const privateTaskDraftRequestSummary = computed(() => {
  const source = (
    activePrivateTaskDraft.value?.request_text
    || taskDraftRequestPreview.value
    || '正在读取当前群聊上下文'
  ).replace(/\s+/g, ' ').trim()
  return source.length > 110 ? `${source.slice(0, 110)}…` : source
})
const privateTaskDraftLauncherTitle = computed(() => ({
  generating: '任务助手正在分析任务需求',
  ready: '任务草稿等待确认',
  publishing: '任务正在发布',
  failed: '任务助手未能完成分析',
  cancelled: 'Dobby 已停止分析',
} as Record<string, string>)[activePrivateTaskDraft.value?.status || ''] || '继续处理任务草稿')
const privateTaskDraftLauncherDescription = computed(() => {
  const row = activePrivateTaskDraft.value
  if (!row) return ''
  if (row.status === 'ready') return row.draft?.title || '打开后检查内容并决定是否发布'
  if (row.status === 'publishing') return '正在写入任务中心，请勿重复操作'
  if (row.status === 'failed') return row.error || '打开后可让 Dobby 重新分析'
  if (row.status === 'cancelled') return '打开后可重新分析或关闭本次草稿'
  return `正在根据「${row.channel_title || '当前会话'}」整理任务要求`
})
const connectionLabel = computed(() => ({
  connected: '实时连接',
  connecting: '正在连接',
  polling: '定时刷新',
  disconnected: '连接恢复中',
}[realtimeStatus.value]))
const connectionDescription = computed(() => (
  realtimeStatus.value === 'connected'
    ? '新消息会实时到达当前页面'
    : '消息保存不受影响，页面会通过定时刷新补齐新消息'
))

function errorDetail(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

function queryNumberOrString(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function queryPositiveInt(value: unknown) {
  const parsed = Number(queryNumberOrString(value))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function replaceChatQuery(patch: Record<string, string | undefined>) {
  const query = { ...route.query }
  Object.entries(patch).forEach(([key, value]) => {
    if (value) query[key] = value
    else delete query[key]
  })
  void router.replace({ path: '/ai', query })
}

function taskTitle(taskId: string) {
  return store.tasks.find(task => task.id === taskId)?.title || `任务 ${taskId}`
}

function taskRoute(taskId: string): RouteLocationRaw {
  return { path: '/tasks', query: { tab: 'history', taskId, view: 'history' } }
}

async function applyTaskContextDraft() {
  const task = contextTask.value
  if (!task || draft.value.trim()) return
  draft.value = `关于任务“${task.title}”（${task.id}）：`
  await nextTick()
  renderComposer()
}

function clearTaskContext() {
  const task = contextTask.value
  if (task && draft.value === `关于任务“${task.title}”（${task.id}）：`) clearComposer()
  replaceChatQuery({ taskId: undefined, messageId: undefined })
}

function channelDisplayTitle(channel: ProjectChatChannel) {
  return channel.title?.trim() || '未命名群'
}

function compactTime(value: string) {
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

function messageTime(value: string | null) {
  if (!value) return ''
  const time = dayjs(value)
  return time.isSame(dayjs(), 'day') ? time.format('HH:mm') : time.format('M月D日 HH:mm')
}

function isOwnMessage(item: ProjectChatMessage) {
  return item.sender_type === 'user' && item.sender_user_id === currentUserId.value
}

function senderName(item: ProjectChatMessage) {
  if (item.sender_type === 'agent') {
    const name = String(item.metadata?.agent_name || item.sender?.name || item.sender_agent_id || '项目智能体').trim()
    if (item.sender_agent_id === 'dobby-task-engine' || /^Dobby\s*(?:（任务引擎）|\(任务引擎\))?$/.test(name)) {
      return 'Dobby'
    }
    return name
  }
  if (item.sender_type === 'system') return '系统消息'
  return item.sender?.name || '项目成员'
}

function senderInitial(item: ProjectChatMessage) {
  return senderName(item).slice(0, 1)
}

function isMentioningCurrentUser(item: ProjectChatMessage) {
  return item.mentions.some(mention => (
    mention.target_type === 'all'
    || (mention.target_type === 'user' && mention.target_user_id === currentUserId.value)
  ))
}

function shouldClaimMentionAttention(item: ProjectChatMessage) {
  return currentUserId.value > 0
    && !isOwnMessage(item)
    && isMentioningCurrentUser(item)
    && !resolvedMentionIds.has(item.id)
}

function startMentionPulse(messageId: number) {
  const pulsing = new Set(pulsingMentionIds.value)
  pulsing.add(messageId)
  pulsingMentionIds.value = pulsing
  const previousTimer = mentionPulseTimers.get(messageId)
  if (previousTimer !== undefined) window.clearTimeout(previousTimer)
  mentionPulseTimers.set(
    messageId,
    window.setTimeout(() => {
      const remaining = new Set(pulsingMentionIds.value)
      remaining.delete(messageId)
      pulsingMentionIds.value = remaining
      mentionPulseTimers.delete(messageId)
    }, 2800),
  )
}

function removeMentionNotice(messageId: number) {
  mentionNotices.value = mentionNotices.value.filter(item => item.id !== messageId)
}

function queueMentionNotice(item: ProjectChatMessage) {
  if (
    item.sender_user_id === currentUserId.value
    || resolvedMentionIds.has(item.id)
  ) return
  mentionNotices.value = [
    item,
    ...mentionNotices.value.filter(existing => existing.id !== item.id),
  ].slice(0, 20)
}

async function viewActiveMentionNotice() {
  const item = activeMentionNotice.value
  if (!item || locatingMentionNotice.value) return
  locatingMentionNotice.value = true
  try {
    if (activeChannelId.value !== item.channel_id) {
      await activateChannel(item.channel_id)
    }
    if (!messages.value.some(message => message.id === item.id)) {
      mergeMessages([await getProjectChatMessage(item.id)])
    }
    await nextTick()
    const element = messageElements.get(item.id)
    const viewport = messageViewport.value
    if (!element || !viewport) return
    const viewportRect = viewport.getBoundingClientRect()
    const messageRect = element.getBoundingClientRect()
    const targetTop = viewport.scrollTop
      + messageRect.top
      - viewportRect.top
      - Math.max(0, (viewport.clientHeight - messageRect.height) / 2)
    viewport.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
  } catch (error: any) {
    notice.error(errorDetail(error, '无法定位这条艾特消息。'))
  } finally {
    locatingMentionNotice.value = false
  }
}

async function claimMentionAttention(item: ProjectChatMessage, element: HTMLElement) {
  if (
    document.visibilityState !== 'visible'
    || claimingMentionIds.has(item.id)
    || !shouldClaimMentionAttention(item)
  ) return
  claimingMentionIds.add(item.id)
  try {
    const result = await claimProjectChatMention(item.id)
    resolvedMentionIds.add(item.id)
    removeMentionNotice(item.id)
    mentionObserver?.unobserve(element)
    if (result.first_seen) startMentionPulse(item.id)
  } catch {
    window.setTimeout(() => {
      if (!mentionObserver || !element.isConnected) return
      mentionObserver.unobserve(element)
      mentionObserver.observe(element)
    }, 1200)
  } finally {
    claimingMentionIds.delete(item.id)
  }
}

function registerMessageElement(item: ProjectChatMessage, element: unknown) {
  const previousElement = messageElements.get(item.id)
  if (!(element instanceof HTMLElement)) {
    if (previousElement) mentionObserver?.unobserve(previousElement)
    messageElements.delete(item.id)
    return
  }
  if (previousElement && previousElement !== element) {
    mentionObserver?.unobserve(previousElement)
  }
  messageElements.set(item.id, element)
  if (shouldClaimMentionAttention(item)) mentionObserver?.observe(element)
}

function refreshVisibleMentionAttention() {
  if (document.visibilityState !== 'visible' || !mentionObserver) return
  messageElements.forEach((element, messageId) => {
    const item = messages.value.find(message => message.id === messageId)
    if (!item || !shouldClaimMentionAttention(item)) return
    mentionObserver?.unobserve(element)
    mentionObserver?.observe(element)
  })
}

function agentRuntimeLabel(item: ProjectChatMessage) {
  if (item.sender_type !== 'agent') return ''
  const status = String(item.metadata?.runtime_status || '')
  return ({
    awaiting_permission: '等待确认',
    awaiting_external_result: '等待外部结果',
    interrupted: '已停止',
    exceed_max_iters: '本次处理未完成',
    error: '处理失败',
  } as Record<string, string>)[status] || ''
}


function renderTaskDraftContent(content: string) {
  const source = content || ''
  const cached = taskDraftMarkdownCache.get(source)
  if (cached !== undefined) return cached
  const rendered = taskDraftMarkdown.render(source)
  if (taskDraftMarkdownCache.size >= 128) {
    const oldest = taskDraftMarkdownCache.keys().next().value
    if (oldest !== undefined) taskDraftMarkdownCache.delete(oldest)
  }
  taskDraftMarkdownCache.set(source, rendered)
  return rendered
}

function taskDraftExecutionLabel(value: ProjectChatTaskDraft | null) {
  if (!value) return ''
  if (value.run_mode === 'immediate') return '立即执行'
  const at = [value.trigger_date, value.trigger_time].filter(Boolean).join(' ')
  if (value.run_mode === 'recurring') {
    const unit = ({ minute: '分钟', hour: '小时', day: '天', week: '周', month: '月' } as Record<string, string>)[value.trigger_interval_unit]
    return `${at} 起，每 ${value.trigger_interval_value} ${unit || value.trigger_interval_unit}`
  }
  return at || '单次定时'
}

function taskEventTitle(item: ProjectChatMessage) {
  return String(item.metadata?.task_title || item.content || '新任务')
}

function taskEventExecutionLabel(item: ProjectChatMessage) {
  const runMode = String(item.metadata?.run_mode || '')
  return ({
    immediate: '立即执行',
    once: '单次定时',
    recurring: '周期执行',
    calendar: '日历触发',
  } as Record<string, string>)[runMode] || '已进入任务中心'
}

function taskEventRoute(item: ProjectChatMessage): RouteLocationRaw {
  if (item.task_ids?.[0]) return taskRoute(item.task_ids[0])
  return { path: '/tasks', query: { tab: 'schedules' } }
}

function taskEventLinkLabel(item: ProjectChatMessage) {
  return item.task_ids?.[0] ? '查看任务' : '查看计划'
}

function businessMentionedAgentNames(item: ProjectChatMessage) {
  const taskAssistantIds = new Set(
    Array.isArray(item.metadata?.task_assistant_ids)
      ? item.metadata.task_assistant_ids.map(String)
      : [],
  )
  return item.mentions
    .filter(mention => (
      mention.target_type === 'agent'
      && !taskAssistantIds.has(String(mention.target_agent_id || ''))
    ))
    .map(mention => mention.display_name)
}

async function ensureTaskDraftPeople() {
  const projectId = store.currentProjectId
  if (!projectId || projectParticipants.value.length) return
  projectParticipants.value = await listProjectChatParticipants(projectId)
}

function cloneTaskDraft(value: ProjectChatTaskDraft) {
  return {
    ...value,
    required_materials: [...(value.required_materials || [])],
    mentioned_user_ids: [...(value.mentioned_user_ids || [])],
    workflow_steps: (value.workflow_steps || []).map(step => ({
      ...step,
      action: step.action ? {
        ...step.action,
        mentioned_user_ids: [...(step.action.mentioned_user_ids || [])],
      } : undefined,
    })),
    target_channel_id: value.target_channel_id
      || channels.value.find(channel => channel.channel_type === 'project')?.id
      || activeChannelId.value,
  }
}

function resetPrivateTaskDraft() {
  activePrivateTaskDraft.value = null
  taskDraftForm.value = null
  taskDraftMemberToAdd.value = ''
  taskDraftError.value = ''
  taskDraftStartError.value = ''
  taskDraftRequestPreview.value = ''
}

function applyPrivateTaskDraft(row: ProjectChatPrivateTaskDraft, open = false) {
  const previous = activePrivateTaskDraft.value
  if (
    previous?.id === row.id
    && previous.updated_at
    && row.updated_at
    && dayjs(row.updated_at).isBefore(dayjs(previous.updated_at))
  ) return
  if (row.status === 'published' || row.status === 'dismissed') {
    if (!previous || previous.id === row.id) {
      resetPrivateTaskDraft()
      taskDraftDialogOpen.value = false
    }
    return
  }
  activePrivateTaskDraft.value = row
  taskDraftRequestPreview.value = row.request_text
  taskDraftStartError.value = ''
  if (row.status === 'ready' && row.draft) {
    if (
      !taskDraftForm.value
      || previous?.id !== row.id
      || previous?.status !== 'ready'
    ) {
      taskDraftForm.value = cloneTaskDraft(row.draft)
    }
    void ensureTaskDraftPeople().catch((error: any) => {
      taskDraftError.value = errorDetail(error, '无法加载可选项目成员。')
    })
  } else {
    taskDraftForm.value = null
  }
  if (open) taskDraftDialogOpen.value = true
}

function openTaskDraftDialog() {
  taskDraftError.value = ''
  taskDraftDialogOpen.value = true
  const row = activePrivateTaskDraft.value
  if (row?.status === 'ready' && row.draft && !taskDraftForm.value) {
    taskDraftForm.value = cloneTaskDraft(row.draft)
  }
}

function closeTaskDraftDialog() {
  if (publishingTaskDraft.value || dismissingTaskDraft.value) return
  taskDraftDialogOpen.value = false
}

function addTaskDraftMember() {
  const form = taskDraftForm.value
  const userId = Number(taskDraftMemberToAdd.value)
  if (!form || !userId) return
  form.mentioned_user_ids = [...new Set([...form.mentioned_user_ids, userId])]
  taskDraftMemberToAdd.value = ''
}

function removeTaskDraftMember(userId: number) {
  const form = taskDraftForm.value
  if (!form) return
  form.mentioned_user_ids = form.mentioned_user_ids.filter(id => id !== userId)
}

async function retryTaskDraft() {
  const row = activePrivateTaskDraft.value
  if (!row || taskDraftActionId.value !== null) return
  taskDraftActionId.value = row.id
  taskDraftError.value = ''
  try {
    const updated = await retryPrivateProjectChatTaskDraft(row.id)
    applyPrivateTaskDraft(updated, true)
  } catch (error: any) {
    taskDraftError.value = errorDetail(error, 'Dobby 重新分析任务失败。')
  } finally {
    taskDraftActionId.value = null
  }
}

async function dismissTaskDraft() {
  const row = activePrivateTaskDraft.value
  if (dismissingTaskDraft.value || publishingTaskDraft.value) return
  if (!row) {
    cancelPendingTaskDraftCreation.value = creatingTaskDraft.value
    taskDraftDialogOpen.value = false
    taskDraftStartError.value = ''
    return
  }
  dismissingTaskDraft.value = true
  taskDraftActionId.value = row.id
  taskDraftError.value = ''
  try {
    if (row.status === 'generating') {
      await stopPrivateProjectChatTaskDraft(row.id)
    }
    await dismissPrivateProjectChatTaskDraft(row.id)
    taskDraftDialogOpen.value = false
    resetPrivateTaskDraft()
  } catch (error: any) {
    taskDraftError.value = errorDetail(error, '取消任务草稿失败。')
  } finally {
    dismissingTaskDraft.value = false
    taskDraftActionId.value = null
  }
}

async function publishTaskDraft() {
  const item = activePrivateTaskDraft.value
  const form = taskDraftForm.value
  if (!item || !form || !canPublishTaskDraft.value) return
  publishingTaskDraft.value = true
  taskDraftError.value = ''
  try {
    const payload: ProjectChatTaskDraft = {
      ...form,
      title: form.title.trim(),
      trigger_reason: form.trigger_reason?.trim() || null,
      message_content: form.message_content?.trim() || null,
      workflow_steps: form.workflow_steps.map(step => ({
        ...step,
        owner_user_id: step.node_type === 'manual'
          ? step.owner_user_id || form.assignee_user_id || null
          : null,
        material: step.material?.trim() || '',
      })),
    }
    const response = await publishPrivateProjectChatTaskDraft(item.id, payload)
    if (response.data.message) mergeMessages([response.data.message], true)
    notice.success(response.message || '任务已发布。')
    taskDraftDialogOpen.value = false
    resetPrivateTaskDraft()
    await store.loadProjectData()
  } catch (error: any) {
    taskDraftError.value = errorDetail(error, '发布任务失败。')
  } finally {
    publishingTaskDraft.value = false
  }
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function messageSegments(item: ProjectChatMessage): MessageSegment[] {
  const mentionsByToken = new Map<string, 'all' | 'user' | 'agent'>()
  item.mentions.forEach(mention => {
    mentionsByToken.set(`@${mention.display_name}`, mention.target_type)
  })
  const tokens = [...mentionsByToken.keys()].sort((left, right) => right.length - left.length)
  if (!tokens.length) return [{ text: item.content, targetType: null }]
  const pattern = new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'g')
  return item.content.split(pattern).filter(Boolean).map(text => ({
    text,
    targetType: mentionsByToken.get(text) || null,
  }))
}

function isNearMessageBottom() {
  const viewport = messageViewport.value
  if (!viewport) return true
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120
}

async function scrollMessagesToBottom(smooth = false) {
  await nextTick()
  const viewport = messageViewport.value
  if (!viewport) return
  viewport.scrollTo({
    top: viewport.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto',
  })
}

function mergeMessages(incoming: ProjectChatMessage[], forceScroll = false) {
  if (!incoming.length) return
  const shouldScroll = forceScroll || isNearMessageBottom()
  const byId = new Map(messages.value.map(item => [item.id, item]))
  incoming.forEach(item => byId.set(item.id, item))
  messages.value = [...byId.values()].sort((left, right) => left.id - right.id)
  const latest = messages.value[messages.value.length - 1]
  channels.value = channels.value.map(channel => (
    channel.id === latest.channel_id
      ? { ...channel, last_message: latest, last_message_at: latest.created_at }
      : channel
  ))
  if (shouldScroll) void scrollMessagesToBottom(forceScroll)
}

async function fetchMessages(channelId: number, replace = false, refreshExisting = false) {
  const latestId = replace || refreshExisting
    ? undefined
    : messages.value[messages.value.length - 1]?.id
  const rows = await listProjectChatMessages(channelId, { afterId: latestId, limit: 100 })
  if (activeChannelId.value !== channelId) return
  if (replace) {
    messages.value = rows
    await scrollMessagesToBottom()
  } else {
    mergeMessages(rows)
  }
}

async function activateChannel(channelId: number, syncRoute = true) {
  if (activeChannelId.value === channelId && messages.value.length) {
    if (syncRoute) replaceChatQuery({ channelId: String(channelId), messageId: undefined })
    await applyTaskContextDraft()
    return
  }
  if (activeChannelId.value !== channelId) {
    clearComposer()
  }
  if (syncRoute) replaceChatQuery({ channelId: String(channelId), messageId: undefined })
  activeChannelId.value = channelId
  loadingMessages.value = true
  pageError.value = ''
  messages.value = []
  members.value = []
  try {
    const [loadedMessages, loadedMembers] = await Promise.all([
      listProjectChatMessages(channelId, { limit: 100 }),
      listProjectChatMembers(channelId),
    ])
    if (activeChannelId.value !== channelId) return
    messages.value = loadedMessages
    members.value = loadedMembers
    await scrollMessagesToBottom()
    await applyTaskContextDraft()
  } catch (error: any) {
    pageError.value = errorDetail(error, '无法加载项目群聊。')
  } finally {
    if (activeChannelId.value === channelId) loadingMessages.value = false
  }
}

async function focusRouteMessage() {
  const messageId = queryPositiveInt(route.query.messageId)
  if (!messageId) return
  let item = messages.value.find(message => message.id === messageId)
  if (!item) item = await getProjectChatMessage(messageId)
  if (!channels.value.some(channel => channel.id === item.channel_id)) return
  if (activeChannelId.value !== item.channel_id) {
    await activateChannel(item.channel_id, false)
  }
  if (!messages.value.some(message => message.id === item.id)) mergeMessages([item])
  await nextTick()
  const element = messageElements.get(item.id)
  const viewport = messageViewport.value
  if (!element || !viewport) return
  const viewportRect = viewport.getBoundingClientRect()
  const messageRect = element.getBoundingClientRect()
  const targetTop = viewport.scrollTop
    + messageRect.top
    - viewportRect.top
    - Math.max(0, (viewport.clientHeight - messageRect.height) / 2)
  viewport.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
  startMentionPulse(item.id)
}

async function syncChatRouteContext() {
  if (!channels.value.length) {
    await applyTaskContextDraft()
    return
  }
  const requestedChannelId = queryPositiveInt(route.query.channelId)
  const targetChannel = channels.value.find(channel => channel.id === requestedChannelId)
  if (targetChannel && targetChannel.id !== activeChannelId.value) {
    await activateChannel(targetChannel.id, false)
  }
  try {
    await focusRouteMessage()
  } catch (error: any) {
    notice.error(errorDetail(error, '无法定位任务来源消息。'))
  }
  await applyTaskContextDraft()
}

async function loadPrivateChatParticipants() {
  const projectId = store.currentProjectId
  if (!projectId || loadingParticipants.value) return
  loadingParticipants.value = true
  privateChatError.value = ''
  try {
    projectParticipants.value = await listProjectChatParticipants(projectId)
  } catch (error: any) {
    privateChatError.value = errorDetail(error, '无法加载项目成员。')
  } finally {
    loadingParticipants.value = false
  }
}

async function loadMentionAgents() {
  if (mentionAgentsLoaded.value || mentionAgentsLoading.value) return
  mentionAgentsLoading.value = true
  try {
    mentionAgents.value = await listProjectChatAgents()
    mentionAgentsLoaded.value = true
  } catch {
    mentionAgents.value = []
  } finally {
    mentionAgentsLoading.value = false
  }
}

function focusPrivateChatTitle() {
  privateChatTitleInput.value?.focus()
}

function focusParticipantSearch() {
  participantSearchInput.value?.focus()
}

function setParticipantPage(page: number) {
  participantPage.value = Math.min(Math.max(1, page), participantPageCount.value)
}

function openPrivateChatDialog() {
  allGroupMembers.value = false
  privateChatTitle.value = ''
  participantSearch.value = ''
  participantPage.value = 1
  selectedParticipantIds.value = []
  privateChatError.value = ''
  privateChatDialogOpen.value = true
  void loadPrivateChatParticipants()
}

function closePrivateChatDialog() {
  if (creatingPrivateChat.value) return
  privateChatDialogOpen.value = false
}

async function createPrivateChat() {
  const projectId = store.currentProjectId
  if (!projectId || !canCreatePrivateChat.value) return
  if (channels.value.some(channel => channel.title.trim().toLowerCase() === privateChatTitle.value.trim().toLowerCase())) {
    privateChatError.value = '当前工程已存在同名群聊，请更换群名称。'
    return
  }
  creatingPrivateChat.value = true
  privateChatError.value = ''
  try {
    const created = await createPrivateProjectChatChannel(projectId, {
      title: privateChatTitle.value.trim(),
      participant_user_ids: selectedParticipantIds.value,
      all_members: allGroupMembers.value,
    })
    channels.value = await listProjectChatChannels(projectId)
    privateChatDialogOpen.value = false
    await activateChannel(created.id)
    stopRealtime()
    realtimeStatus.value = 'connecting'
    void startRealtime(projectId, loadGeneration)
    notice.success('群聊已创建。')
  } catch (error: any) {
    privateChatError.value = errorDetail(error, '创建群聊失败。')
  } finally {
    creatingPrivateChat.value = false
  }
}

function stopRealtime() {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = null
  realtimeClient?.disconnect()
  realtimeClient = null
}

function startPolling() {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(() => {
    void markVisibleMessagesRead()
    // The timer is only a degraded-mode safety net. A healthy realtime
    // subscription already delivers every new message and must not keep
    // hitting the history API in parallel.
    if (
      realtimeStatus.value !== 'connected'
      && activeChannelId.value
      && !loadingMessages.value
    ) {
      void fetchMessages(
        activeChannelId.value,
        false,
        true,
      ).catch(() => undefined)
      const draftId = activePrivateTaskDraft.value?.id
      if (draftId && ['generating', 'publishing'].includes(activePrivateTaskDraft.value?.status || '')) {
        void getProjectChatTaskDraft(draftId)
          .then(row => applyPrivateTaskDraft(row))
          .catch(() => undefined)
      }
    }
  }, 5000)
}

async function refreshChannelListFromRealtime(projectId: string, generation: number) {
  if (refreshingChannelList || generation !== loadGeneration) return
  refreshingChannelList = true
  try {
    const rows = await listProjectChatChannels(projectId)
    if (generation !== loadGeneration) return
    channels.value = rows
    const activeStillVisible = rows.some(channel => channel.id === activeChannelId.value)
    if (!activeStillVisible && rows[0]) await activateChannel(rows[0].id)
    stopRealtime()
    realtimeStatus.value = 'connecting'
    await startRealtime(projectId, generation)
  } catch {
    if (generation === loadGeneration) realtimeStatus.value = 'polling'
  } finally {
    refreshingChannelList = false
  }
}

async function startRealtime(projectId: string, generation: number) {
  try {
    const client = await connectProjectChatRealtime(projectId, {
      onMessage: incoming => {
        if (generation !== loadGeneration) return
        channels.value = channels.value.map(channel => channel.id === incoming.channel_id ? { ...channel, last_message: incoming, last_message_at: incoming.created_at } : channel)
        void unread.refresh(projectId)
        if (incoming.channel_id === activeChannelId.value) mergeMessages([incoming])
      },
      onStatus: status => {
        if (generation === loadGeneration) realtimeStatus.value = status
      },
      onChannelsChanged: () => {
        if (generation === loadGeneration) {
          void refreshChannelListFromRealtime(projectId, generation)
        }
      },
      onMention: incoming => {
        if (generation !== loadGeneration || incoming.sender_user_id === currentUserId.value) return
        if (incoming.channel_id === activeChannelId.value) mergeMessages([incoming])
        queueMentionNotice(incoming)
      },
      onTaskDraft: incoming => {
        if (generation !== loadGeneration) return
        const previousStatus = activePrivateTaskDraft.value?.status
        applyPrivateTaskDraft(incoming)
        if (incoming.status === 'ready' && previousStatus === 'generating') {
          notice.success('Dobby 已完成分析，请确认任务草稿后发布。')
        }
      },
    })
    if (generation !== loadGeneration) {
      client?.disconnect()
      return
    }
    realtimeClient = client
  } catch {
    if (generation === loadGeneration) realtimeStatus.value = 'polling'
  }
  if (generation === loadGeneration) startPolling()
}

async function loadProjectChat(projectId: string) {
  const generation = ++loadGeneration
  stopRealtime()
  privateChatDialogOpen.value = false
  taskDraftDialogOpen.value = false
  creatingTaskDraft.value = false
  resetPrivateTaskDraft()
  projectParticipants.value = []
  selectedParticipantIds.value = []
  channels.value = []
  activeChannelId.value = null
  members.value = []
  messages.value = []
  mentionNotices.value = []
  locatingMentionNotice.value = false
  clearComposer()
  pageError.value = ''
  realtimeStatus.value = 'connecting'
  if (!projectId) return
  loadingChannels.value = true
  try {
    const [rows, unseenNotices, privateDrafts] = await Promise.all([
      listProjectChatChannels(projectId),
      listProjectChatMentionNotices(projectId),
      listProjectChatTaskDrafts(projectId),
    ])
    if (generation !== loadGeneration) return
    channels.value = rows
    mentionNotices.value = unseenNotices
    if (privateDrafts[0]) applyPrivateTaskDraft(privateDrafts[0])
    const requestedChannelId = queryPositiveInt(route.query.channelId)
    const firstChannel = rows.find(channel => channel.id === requestedChannelId) || rows[0]
    if (firstChannel) await activateChannel(firstChannel.id, !requestedChannelId)
    await syncChatRouteContext()
    if (generation === loadGeneration) void startRealtime(projectId, generation)
  } catch (error: any) {
    if (generation === loadGeneration) {
      pageError.value = errorDetail(error, '无法初始化项目群聊。')
      realtimeStatus.value = 'polling'
    }
  } finally {
    if (generation === loadGeneration) loadingChannels.value = false
  }
}

function reloadProjectChat() {
  void loadProjectChat(store.currentProjectId)
}

async function manualRefresh() {
  if (!activeChannelId.value || manualRefreshing.value || loadingMessages.value) return
  manualRefreshing.value = true
  try {
    await fetchMessages(activeChannelId.value)
    notice.success('已刷新群聊消息。')
  } catch (error: any) {
    notice.error(errorDetail(error, '刷新消息失败。'))
  } finally {
    manualRefreshing.value = false
  }
}

async function sendMessage() {
  syncDraftFromEditor()
  const content = draft.value.trim()
  const channelId = activeChannelId.value
  if (!content || !channelId || sending.value) return
  const selectedAgentMentions = selectedMentions.value
    .filter(mention => mention.type === 'agent')
  const selectedAgentIds = selectedAgentMentions
    .map(mention => String(mention.id))
  if (new Set(selectedAgentIds).size > 1) {
    notice.warning('每条消息最多只能提及一个智能体。')
    return
  }
  const taskAssistantMention = selectedAgentMentions.find(
    mention => mention.name === '任务助手',
  )
  const invokesTaskAssistant = Boolean(taskAssistantMention)
  if (invokesTaskAssistant) {
    const otherAgentIds = selectedAgentIds.filter(
      id => id !== String(taskAssistantMention?.id || ''),
    )
    if (otherAgentIds.length) {
      notice.warning('任务助手需要单独使用，请移除其他智能体后再发送。')
      return
    }
    if (activePrivateTaskDraft.value) {
      openTaskDraftDialog()
      notice.warning('请先处理当前任务草稿。')
      return
    }
    const requirement = content.replace('@任务助手', '').trim()
    if (requirement.length < 4) {
      notice.warning('请在 @任务助手 后说明要布置的任务。')
      return
    }
    sending.value = true
    creatingTaskDraft.value = true
    cancelPendingTaskDraftCreation.value = false
    taskDraftRequestPreview.value = requirement
    taskDraftStartError.value = ''
    taskDraftDialogOpen.value = true
    try {
      const created = await createProjectChatTaskDraft(channelId, content)
      clearComposer()
      if (cancelPendingTaskDraftCreation.value) {
        if (created.status === 'generating') await stopPrivateProjectChatTaskDraft(created.id)
        await dismissPrivateProjectChatTaskDraft(created.id)
        resetPrivateTaskDraft()
      } else {
        applyPrivateTaskDraft(created, true)
      }
    } catch (error: any) {
      if (!cancelPendingTaskDraftCreation.value) {
        if (error?.response?.status === 409 && store.currentProjectId) {
          try {
            const existing = await listProjectChatTaskDrafts(store.currentProjectId)
            if (existing[0]) {
              applyPrivateTaskDraft(existing[0], true)
              notice.warning('已为你打开尚未处理的任务草稿。')
            } else {
              taskDraftStartError.value = errorDetail(error, '无法启动 Dobby 任务分析。')
            }
          } catch {
            taskDraftStartError.value = errorDetail(error, '无法启动 Dobby 任务分析。')
          }
        } else {
          taskDraftStartError.value = errorDetail(error, '无法启动 Dobby 任务分析。')
        }
      }
    } finally {
      creatingTaskDraft.value = false
      cancelPendingTaskDraftCreation.value = false
      sending.value = false
    }
    return
  }
  sending.value = true
  try {
    const created = await sendProjectChatMessage(channelId, content, {
      mentionAll: selectedMentions.value.some(mention => mention.type === 'all'),
      mentionedUserIds: selectedMentions.value
        .filter(mention => mention.type === 'user')
        .map(mention => Number(mention.id)),
      mentionedAgentIds: selectedMentions.value
        .filter(mention => mention.type === 'agent')
        .map(mention => String(mention.id)),
    })
    clearComposer()
    mergeMessages([created], true)
  } catch (error: any) {
    notice.error(errorDetail(error, '发送消息失败。'))
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  mentionObserver = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return
        const element = entry.target as HTMLElement
        const messageId = Number(element.dataset.messageId || 0)
        const item = messages.value.find(message => message.id === messageId)
        if (item) void claimMentionAttention(item, element)
      })
    },
    {
      root: messageViewport.value,
      threshold: 0.01,
    },
  )
  messageElements.forEach((element, messageId) => {
    const item = messages.value.find(message => message.id === messageId)
    if (item && shouldClaimMentionAttention(item)) mentionObserver?.observe(element)
  })
  document.addEventListener('visibilitychange', refreshVisibleMentionAttention)
  document.addEventListener('visibilitychange', markVisibleMessagesRead)
})

watch(
  () => store.currentProjectId,
  projectId => void loadProjectChat(projectId),
  { immediate: true },
)

watch(
  () => [route.query.channelId, route.query.messageId, route.query.taskId] as const,
  () => void syncChatRouteContext(),
)

watch(contextTask, () => void applyTaskContextDraft())
watch([() => messages.value[messages.value.length - 1]?.id, loadingMessages], () => void markVisibleMessagesRead(), { flush: 'post' })
watch(participantSearch, () => { participantPage.value = 1 })
watch(participantPageCount, pageCount => {
  if (participantPage.value > pageCount) participantPage.value = pageCount
})

onBeforeUnmount(() => {
  loadGeneration += 1
  stopRealtime()
  document.removeEventListener('visibilitychange', refreshVisibleMentionAttention)
  document.removeEventListener('visibilitychange', markVisibleMessagesRead)
  mentionObserver?.disconnect()
  mentionObserver = null
  messageElements.clear()
  mentionPulseTimers.forEach(timer => window.clearTimeout(timer))
  mentionPulseTimers.clear()
})
</script>

<style scoped src="./ProjectGroupChat.css"></style>
