import type { TaskContext } from '@agentscope-ai/agentscope/state';
import { UserRoundKey } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import type {
	AgentCallConfig,
	AgentMCPConfig,
	AgentSkillConfig,
	AgentView,
	ChatModelConfig,
	PermissionMode,
	TTSModelConfig,
} from '@/api';
import { sessionApi } from '@/api';
import { ChatContent } from '@/components/chat/ChatContent.tsx';
import { SubagentHitlCard } from '@/components/chat/SubagentHitlCard';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { ModelParametersPopover } from '@/components/popover/ModelParametersPopover';
import { LlmSelect } from '@/components/select/LlmSelect';
import { Badge } from '@/components/ui/badge';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { useMessages } from '@/hooks/useMessages';
import { useSessions } from '@/hooks/useSessions';
import { useTranslation } from '@/i18n/useI18n';
import { availableChatModel, chatAttachmentBlock, resolveSessionChatModel } from '@/lib/chat-input';

const ATTACHMENT_PARSER_INPUT_TYPES = [
	'.txt',
	'.md',
	'.csv',
	'.xls',
	'.xlsx',
	'.docx',
	'.pptx',
	'.pdf',
	'.png',
	'.jpg',
	'.jpeg',
	'.jp2',
	'.webp',
	'.gif',
	'.bmp',
	'.tif',
	'.tiff',
];

interface ChatViewportProps {
	/**
	 * The agent that owns the session being viewed. May be the
	 * user-facing leader agent or — when drilled into a team member
	 * via the URL's `:memberId` slot — a worker agent.
	 */
	agentId: string | null;
	/**
	 * The session whose messages, model config, permission mode, and
	 * workspace drive every control rendered here.
	 */
	sessionId: string | null;
	/** All agents visible to the user, including shared read-only agents. */
	agents: AgentView[];
	/** Whether the visible-agent list is still loading. */
	agentsLoading?: boolean;
	/** Persist the current agent's global collaboration configuration. */
	onUpdateAgentCallConfig?: (agentId: string, config: AgentCallConfig) => Promise<void>;
	/** Persist the current agent's global managed-MCP assignment. */
	onUpdateAgentMCPConfig?: (agentId: string, config: AgentMCPConfig) => Promise<void>;
	/** Persist the current agent's global managed-skill assignment. */
	onUpdateAgentSkillConfig?: (agentId: string, config: AgentSkillConfig) => Promise<void>;
	/**
	 * Optional hook invoked when a team membership change arrives on
	 * this viewport's SSE stream. The outer page owns the session list
	 * that backs the team sidebar, so it must be told to refetch too;
	 * passing this callback wires that signal up.
	 */
	onTeamUpdated?: () => void;
}

/**
 * The right-hand main panel of the chat page — every UI element that
 * operates on a single `(agentId, sessionId)` pair lives here:
 * model selector, permission mode select, message stream, workspace
 * drawer, and the team sidebar.
 *
 * Self-contained by design. The outer page passes in the
 * `(agentId, sessionId)` it wants displayed (which may be the leader
 * session or a focused team member's session) and this component
 * does the rest — fetching the session view, syncing local UI state
 * with it, and writing changes back to the same session. Switching
 * between leader and member is just a prop change; no internal
 * branching is needed.
 *
 * @param agentId - The agent to operate on. `null` while no agent is
 *   selected yet (renders an empty / disabled state).
 * @param sessionId - The session to operate on. `null` while no
 *   session is selected yet.
 * @returns The right-side main JSX of the chat page.
 */
export function ChatViewport({ agentId, sessionId, agents, onTeamUpdated }: ChatViewportProps) {
	const { t } = useTranslation();
	const { sessions, refetch: refetchSessions } = useSessions(agentId);
	const modelCatalogue = useAvailableModels();
	const { groups, loading: modelsLoading, error: modelsError } = modelCatalogue;

	// When the viewport agent differs from the outer page's selected
	// agent (i.e. user drilled into a team member), `refetchSessions`
	// only refreshes the member's session list. The team sidebar is
	// driven by the leader's session list owned by the outer page, so
	// we also fire the parent's refetch to keep that in sync.
	const handleTeamUpdated = useCallback(() => {
		refetchSessions();
		onTeamUpdated?.();
	}, [refetchSessions, onTeamUpdated]);

	const [selectedModel, setSelectedModel] = useState<ChatModelConfig | null>(null);
	const [modelSaving, setModelSaving] = useState(false);
	const [selectedFallbackModel, setSelectedFallbackModel] = useState<ChatModelConfig | null>(
		null,
	);
	const [selectedTTSModel, setSelectedTTSModel] = useState<TTSModelConfig | null>(null);
	const [credentialOpen, setCredentialOpen] = useState(false);
	const [credentialRefetchTrigger, setCredentialRefetchTrigger] = useState(0);
	const [tasksContext, setTasksContext] = useState<TaskContext | null>(null);

	const handleStateUpdated = useCallback((value: Record<string, unknown>) => {
		if (value.tasks_context) {
			setTasksContext(value.tasks_context as TaskContext);
		}
	}, []);

	const { msgs, phase, send, onUserConfirm, onSubagentConfirm, subagentHitl, interrupt } =
		useMessages(agentId, sessionId, {
			onTeamUpdated: handleTeamUpdated,
			onStateUpdated: handleStateUpdated,
		});
	const activeAgent = useMemo(
		() => agents.find((agent) => agent.id === agentId) ?? null,
		[agents, agentId],
	);
	const agentFixedModel =
		activeAgent?.data.model_policy?.mode === 'fixed'
			? activeAgent.data.model_policy.chat_model_config
			: null;
	const effectiveSelectedModel = agentFixedModel ?? selectedModel;

	const view = sessions.find((v) => v.session.id === sessionId) ?? null;
	const usesAgentPermissions =
		view?.session.source === 'user' && !view.session.config.platform_context;
	const permissionMode = usesAgentPermissions
		? activeAgent?.data.platform_config?.permission_mode
		: ((view?.session.state?.permission_context as Record<string, unknown>)?.mode as
				| PermissionMode
				| undefined);

	// ChatViewport keeps its own `useSessions(agentId)` instance (the
	// outer page has a separate one). Its built-in fetch only fires on
	// `agentId` change, so when the outer page creates a new session
	// under the same agent, this list doesn't auto-refresh. Without
	// this refetch, `view` would stay `null` for the brand-new session
	// id and every effect below would early-return on `!view`,
	// leaving the model select and friends pinned to whatever the
	// previously-viewed session had configured.
	useEffect(() => {
		if (!sessionId) return;
		if (view) return;
		refetchSessions();
	}, [sessionId, view, refetchSessions]);

	// Reset local UI state when the target session changes. Otherwise
	// the model select (and disabled-state guards on `send`) would
	// show the previous session's model during the in-flight window
	// before `view` repopulates — and an immediate send would post to
	// a session whose backend config doesn't actually have that model.
	useEffect(() => {
		setSelectedModel(null);
		setSelectedFallbackModel(null);
		setSelectedTTSModel(null);
	}, [sessionId]);

	const selectedModelCard = useMemo(() => {
		return availableChatModel(groups, effectiveSelectedModel);
	}, [effectiveSelectedModel, groups]);

	// Sync tasksContext from the session snapshot. Real-time updates
	// arrive via the CustomEvent(name="state_updated") → the
	// onStateUpdated callback above. We always mirror the snapshot
	// (including clearing to null when the session is gone or has no
	// tasks yet) so that switching sessions doesn't leak stale tasks
	// from the previous one.
	useEffect(() => {
		if (!view) {
			setTasksContext(null);
			return;
		}
		const tc = (view.session.state as Record<string, unknown>)?.tasks_context as
			| TaskContext
			| undefined;
		setTasksContext(tc ?? null);
	}, [view]);

	// Sync selectedModel + selectedFallbackModel from the session
	// record. If the session has no model configured yet, auto-pick
	// the first available one and persist it back so subsequent
	// reasoning has a model to call.
	//
	// Important: skip while `view` is still loading. Otherwise the
	// in-flight window between "agentId changed" and "useSessions
	// returned the new list" looks like "session has no model" and
	// we would racily auto-select + persist the first available
	// model, clobbering whatever the user had configured.
	useEffect(() => {
		let current = true;
		setModelSaving(false);
		if (!view) return;
		const sessionModel = view.session.config.chat_model_config;

		if (agentFixedModel) {
			setSelectedModel(null);
		} else if (modelsLoading || modelsError) {
			setSelectedModel(sessionModel ?? null);
		} else {
			const nextModel = resolveSessionChatModel(groups, sessionModel);
			setSelectedModel(nextModel);
			if (nextModel && nextModel !== sessionModel) {
				if (sessionId && agentId) {
					setModelSaving(true);
					sessionApi
						.update(sessionId, agentId, { chat_model_config: nextModel })
						.then(() => {
							if (current) return refetchSessions();
						})
						.catch(() => {
							if (current) setSelectedModel(sessionModel ?? null);
						})
						.finally(() => {
							if (current) setModelSaving(false);
						});
				}
			}
		}

		setSelectedFallbackModel(view.session.config.fallback_chat_model_config ?? null);
		setSelectedTTSModel(view.session.config.tts_model_config ?? null);
		return () => {
			current = false;
		};
	}, [
		view,
		sessionId,
		agentId,
		agentFixedModel,
		groups,
		modelsLoading,
		modelsError,
		refetchSessions,
	]);

	/**
	 * Persist a model change to the session and refetch so the local
	 * view picks up the new value.
	 *
	 * @param config - New chat model config; `null` is ignored
	 *   because the primary selector does not allow clearing.
	 */
	const handleLlmChange = async (config: ChatModelConfig | null) => {
		if (agentFixedModel || !config || !sessionId || !agentId || modelSaving) return;
		setModelSaving(true);
		try {
			await sessionApi.update(sessionId, agentId, { chat_model_config: config });
			setSelectedModel(config);
			await refetchSessions();
		} finally {
			setModelSaving(false);
		}
	};

	/**
	 * Persist a fallback-model change. `null` clears the fallback.
	 *
	 * @param config - New fallback config or `null` to clear.
	 */
	const handleFallbackChange = async (config: ChatModelConfig | null) => {
		if (!sessionId || !agentId) return;
		setSelectedFallbackModel(config);
		await sessionApi.update(sessionId, agentId, { fallback_chat_model_config: config });
		await refetchSessions();
	};

	/**
	 * Persist a TTS model change. `null` disables TTS.
	 *
	 * @param config - New TTS config or `null` to disable.
	 */
	const handleTTSChange = async (config: TTSModelConfig | null) => {
		if (!sessionId || !agentId) return;
		setSelectedTTSModel(config);
		await sessionApi.update(sessionId, agentId, { tts_model_config: config });
		await refetchSessions();
	};

	return (
		<>
			<main className="flex size-full">
				<div className="flex flex-col flex-1 min-h-0 min-w-0 overflow-x-hidden p-2">
					<div className="flex flex-row gap-x-2 justify-between">
						<div id="tour-llm-select" className="flex flex-row items-center gap-x-1">
							<SidebarTrigger className="md:hidden" />
							<LlmSelect
								value={effectiveSelectedModel}
								onChange={handleLlmChange}
								onAddCredential={() => setCredentialOpen(true)}
								refetchTrigger={credentialRefetchTrigger}
								catalogue={modelCatalogue}
								disabled={agentFixedModel !== null || modelSaving}
							/>
							{agentFixedModel && (
								<Badge variant="secondary">{t('chat.model.agentFixed')}</Badge>
							)}
							{!modelsLoading && effectiveSelectedModel && !selectedModelCard && (
								<Badge variant="destructive">{t('chat.model.unavailable')}</Badge>
							)}
							<ModelParametersPopover
								selectedModel={effectiveSelectedModel}
								selectedFallbackModel={selectedFallbackModel}
								onFallbackChange={handleFallbackChange}
								selectedTTSModel={selectedTTSModel}
								onTTSChange={handleTTSChange}
							/>
						</div>
						<div id="tour-permission-mode" className="flex items-center">
							{permissionMode && (
								<Badge
									variant="outline"
									className="gap-2 py-1 text-xs font-normal"
									title={t(
										usesAgentPermissions
											? 'permission-mode.followsAgent'
											: 'permission-mode.followsSession',
									)}
								>
									<UserRoundKey className="size-4" />
									{t(
										`agent-form.platform-config.permissionOptions.${permissionMode}`,
									)}
									<span className="text-muted-foreground">
										{t('permission-mode.configured')}
									</span>
								</Badge>
							)}
						</div>
					</div>
					<div className="flex flex-1 justify-center min-h-0 overflow-hidden relative [--chat-content-w:48rem]">
						<ChatContent
							className={'max-w-[var(--chat-content-w)] w-full'}
							msgs={msgs}
							tasksContext={tasksContext}
							phase={phase}
							disabled={
								!sessionId ||
								!view ||
								!selectedModelCard ||
								modelsLoading ||
								modelSaving
							}
							onSend={send}
							onUserConfirm={onUserConfirm}
							onInterrupt={interrupt}
							footerSlot={
								subagentHitl.length > 0 ? (
									<div className="space-y-2 pb-2">
										{subagentHitl.map((entry) => (
											<SubagentHitlCard
												key={`${entry.worker_session_id}:${entry.reply_id}`}
												entry={entry}
												onConfirm={(toolCall, confirm, rules) =>
													onSubagentConfirm(
														entry,
														toolCall,
														confirm,
														rules,
													)
												}
											/>
										))}
									</div>
								) : null
							}
							allowedInputTypes={ATTACHMENT_PARSER_INPUT_TYPES}
							fileProcessor={async (file) => {
								const dataUrl = await new Promise<string>((resolve, reject) => {
									const reader = new FileReader();
									reader.onload = () => resolve(String(reader.result));
									reader.onerror = () => reject(reader.error);
									reader.readAsDataURL(file);
								});
								return chatAttachmentBlock(file, dataUrl, crypto.randomUUID());
							}}
						/>
					</div>
				</div>
			</main>
			<CreateCredentialDialog
				open={credentialOpen}
				onOpenChange={setCredentialOpen}
				onCreated={() => setCredentialRefetchTrigger((n) => n + 1)}
			/>
		</>
	);
}
