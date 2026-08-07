import type { TaskContext } from '@agentscope-ai/agentscope/state';
import {
	BookOpen,
	BookText,
	ChevronLeft,
	ChevronRight,
	Database,
	ListTodo,
	Users,
	Wrench,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePanelRef } from 'react-resizable-panels';

import type {
	AgentCallConfig,
	AgentMCPConfig,
	AgentView,
	ChatModelConfig,
	PermissionMode,
	SessionKnowledgeConfig,
	TTSModelConfig,
} from '@/api';
import { credentialApi, sessionApi } from '@/api';
import MCPSvg from '@/assets/images/mcp.svg?react';
import { ChatContent } from '@/components/chat/ChatContent.tsx';
import { SubagentHitlCard } from '@/components/chat/SubagentHitlCard';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { AgentCollaborationPanel } from '@/components/panel/AgentCollaborationPanel';
import { DatabaseInteractionPanel } from '@/components/panel/DatabaseInteractionPanel';
import { KnowledgeBasePanel } from '@/components/panel/KnowledgeBasePanel';
import { McpPanel } from '@/components/panel/McpPanel';
import { PanelDock, type PanelDescriptor, type PanelKey } from '@/components/panel/PanelDock.tsx';
import { SkillPanel } from '@/components/panel/SkillPanel';
import { TaskPanel } from '@/components/panel/TaskPanel';
import { ToolPanel } from '@/components/panel/ToolPanel';
import { KnowledgeBaseParametersPopover } from '@/components/popover/KnowledgeBaseParametersPopover';
import { ModelParametersPopover } from '@/components/popover/ModelParametersPopover';
import { LlmSelect } from '@/components/select/LlmSelect';
import { PermissionModeSelect } from '@/components/select/PermissionModeSelect.tsx';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from '@/components/ui/resizable.tsx';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { useKnowledgeBaseMiddlewareSchema } from '@/hooks/useKnowledgeBaseMiddlewareSchema';
import { useKnowledgeBases } from '@/hooks/useKnowledgeBases';
import { useMcpRegistry } from '@/hooks/useMcpRegistry';
import { useMessages } from '@/hooks/useMessages';
import { useSessions } from '@/hooks/useSessions';
import { useWorkspace } from '@/hooks/useWorkspace.ts';
import { useTranslation } from '@/i18n/useI18n';

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
	onUpdateAgentCallConfig: (agentId: string, config: AgentCallConfig) => Promise<void>;
	/** Persist the current agent's global managed-MCP assignment. */
	onUpdateAgentMCPConfig: (agentId: string, config: AgentMCPConfig) => Promise<void>;
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
export function ChatViewport({
	agentId,
	sessionId,
	agents,
	agentsLoading = false,
	onUpdateAgentCallConfig,
	onUpdateAgentMCPConfig,
	onTeamUpdated,
}: ChatViewportProps) {
	const { t } = useTranslation();
	const { sessions, refetch: refetchSessions } = useSessions(agentId);
	const { groups, loading: modelsLoading } = useAvailableModels();

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
	const [selectedFallbackModel, setSelectedFallbackModel] = useState<ChatModelConfig | null>(
		null,
	);
	const [selectedTTSModel, setSelectedTTSModel] = useState<TTSModelConfig | null>(null);
	const [selectedKnowledgeConfig, setSelectedKnowledgeConfig] =
		useState<SessionKnowledgeConfig | null>(null);
	const [selectedPermissionMode, setSelectedPermissionMode] = useState<PermissionMode>('default');
	const [permissionReviewerEnabled, setPermissionReviewerEnabled] = useState<boolean | null>(
		null,
	);
	const [credentialOpen, setCredentialOpen] = useState(false);
	const [credentialRefetchTrigger, setCredentialRefetchTrigger] = useState(0);
	const [tasksContext, setTasksContext] = useState<TaskContext | null>(null);
	const [activePanel, setActivePanel] = useState<PanelKey>('plan');
	const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
	const panelDockRef = usePanelRef();
	const togglePanelDock = useCallback(() => {
		if (panelDockRef.current?.isCollapsed()) {
			panelDockRef.current.expand();
			return;
		}
		panelDockRef.current?.collapse();
	}, [panelDockRef]);

	useEffect(() => {
		let active = true;
		void credentialApi
			.permissionReviewer()
			.then((response) => {
				if (active) setPermissionReviewerEnabled(response.config.enabled);
			})
			.catch(() => {
				if (active) setPermissionReviewerEnabled(null);
			});
		return () => {
			active = false;
		};
	}, []);

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
	const { skills, skillsLoading, addSkill, updateSkill, removeSkill, tools, toolsLoading } =
		useWorkspace(agentId, sessionId);
	const {
		packages: mcpPackages,
		loading: mcpsLoading,
		uploading: mcpUploading,
		error: mcpError,
		uploadPackage,
		removePackage,
	} = useMcpRegistry(agentId);
	const { knowledgeBases, loading: knowledgeBasesLoading } = useKnowledgeBases();
	const { schema: kbMiddlewareSchema } = useKnowledgeBaseMiddlewareSchema();
	const activeAgent = useMemo(
		() => agents.find((agent) => agent.id === agentId) ?? null,
		[agents, agentId],
	);
	const agentFixedModel =
		activeAgent?.data.model_policy?.mode === 'fixed'
			? activeAgent.data.model_policy.chat_model_config
			: null;
	const effectiveSelectedModel = agentFixedModel ?? selectedModel;

	/**
	 * Persist a knowledge-base attachment change. `null` detaches every
	 * knowledge base from this session, removing the `RAGMiddleware`.
	 *
	 * Declared above `panels` (rather than alongside the other model
	 * handlers below) because `panels` is built inside `useMemo` and
	 * references this handler eagerly — a later `const` would still be
	 * in the temporal dead zone when the memo factory runs on first
	 * render.
	 *
	 * @param config - New attachment, or `null` to detach all.
	 */
	const handleKnowledgeConfigChange = useCallback(
		async (config: SessionKnowledgeConfig | null) => {
			if (!sessionId || !agentId) return;
			setSelectedKnowledgeConfig(config);
			await sessionApi.update(sessionId, agentId, { knowledge_config: config });
			await refetchSessions();
		},
		[sessionId, agentId, refetchSessions],
	);

	// Build the panel descriptors with live data. Rebuilt on every
	// data change so the dock always renders the latest state — the
	// dock itself stays free of any data dependency.
	const panels = useMemo<Record<PanelKey, PanelDescriptor>>(
		() => ({
			plan: {
				tabLabel: t('panel.plan.title'),
				icon: <ListTodo className="size-4" />,
				help: {
					description: t('panel.plan.description'),
				},
				content: <TaskPanel tasksContext={tasksContext} />,
			},
			mcp: {
				tabLabel: 'MCP',
				icon: <MCPSvg className="size-4" />,
				help: {
					description: t('panel.mcp.description'),
					note: t('panel.mcp.globalNotice'),
				},
				content: (
					<McpPanel
						agent={activeAgent}
						packages={mcpPackages}
						loading={mcpsLoading}
						uploading={mcpUploading}
						loadError={mcpError}
						onUpload={uploadPackage}
						onRemove={removePackage}
						onSave={onUpdateAgentMCPConfig}
					/>
				),
			},
			skill: {
				tabLabel: t('panel.skill.title'),
				icon: <BookText className="size-4" />,
				help: {
					description: t('panel.skill.description'),
				},
				content: (
					<SkillPanel
						skills={skills}
						loading={skillsLoading}
						onAdd={addSkill}
						onUpdate={updateSkill}
						onRemove={removeSkill}
					/>
				),
			},
			tool: {
				tabLabel: t('panel.tool.title'),
				icon: <Wrench className="size-4" />,
				help: {
					description: t('panel.tool.description'),
					note: t('panel.tool.globalNotice'),
				},
				content: (
					<ToolPanel
						agent={activeAgent}
						tools={tools}
						loading={toolsLoading}
					/>
				),
			},
			database: {
				tabLabel: t('panel.database.title'),
				icon: <Database className="size-4" />,
				help: {
					description: t('panel.database.description'),
					note: t('panel.database.globalNotice'),
				},
				content: (
					<DatabaseInteractionPanel agent={activeAgent} />
				),
			},
			knowledge: {
				tabLabel: t('panel.knowledge.title'),
				icon: <BookOpen className="size-4" />,
				help: {
					description: t('panel.knowledge.description'),
				},
				content: (
					<KnowledgeBasePanel
						knowledgeBases={knowledgeBases}
						loading={knowledgeBasesLoading}
						value={selectedKnowledgeConfig}
						onChange={handleKnowledgeConfigChange}
						disabled={!sessionId}
						actions={
							<KnowledgeBaseParametersPopover
								value={selectedKnowledgeConfig}
								schema={kbMiddlewareSchema}
								onChange={handleKnowledgeConfigChange}
								disabled={!sessionId}
							/>
						}
					/>
				),
			},
			collaboration: {
				tabLabel: t('panel.collaboration.title'),
				icon: <Users className="size-4" />,
				help: {
					description: t('panel.collaboration.description'),
					note: t('panel.collaboration.globalNotice'),
				},
				content: (
					<AgentCollaborationPanel
						agent={activeAgent}
						agents={agents}
						loading={agentsLoading}
						onSave={onUpdateAgentCallConfig}
					/>
				),
			},
		}),
		[
			t,
			tasksContext,
			mcpPackages,
			mcpsLoading,
			mcpUploading,
			mcpError,
			uploadPackage,
			removePackage,
			onUpdateAgentMCPConfig,
			skills,
			skillsLoading,
			addSkill,
			updateSkill,
			removeSkill,
			tools,
			toolsLoading,
			knowledgeBases,
			knowledgeBasesLoading,
			selectedKnowledgeConfig,
			kbMiddlewareSchema,
			handleKnowledgeConfigChange,
			sessionId,
			activeAgent,
			agents,
			agentsLoading,
			onUpdateAgentCallConfig,
		],
	);

	const view = sessions.find((v) => v.session.id === sessionId) ?? null;

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
		setSelectedKnowledgeConfig(null);
	}, [sessionId]);

	const selectedModelCard = useMemo(() => {
		if (!effectiveSelectedModel) return null;
		const items = groups[effectiveSelectedModel.type];
		if (!items) return null;
		for (const { credential, models } of items) {
			if (credential.id !== effectiveSelectedModel.credential_id) continue;
			const card = models.find((m) => m.name === effectiveSelectedModel.model);
			if (card) return card;
		}
		return null;
	}, [effectiveSelectedModel, groups]);

	/**
	 * Pick the first model the available-models endpoint surfaces, used
	 * as a sensible default when the current session has no model
	 * configured yet.
	 *
	 * @returns The first available `ChatModelConfig`, or `null` when
	 *   no credentials / models are configured.
	 */
	const getFirstAvailableModel = useCallback((): ChatModelConfig | null => {
		const firstType = Object.keys(groups)[0];
		if (!firstType) return null;
		const items = groups[firstType];
		if (!items || items.length === 0) return null;
		const firstItem = items[0];
		const firstModel = (firstItem.models as { name?: string; id?: string }[])[0];
		if (!firstModel) return null;
		const modelName = firstModel.name ?? firstModel.id ?? null;
		if (!modelName) return null;
		return {
			type: firstType,
			credential_id: firstItem.credential.id,
			model: modelName,
			parameters: {},
		};
	}, [groups]);

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
		if (!view) return;
		const sessionModel = view.session.config.chat_model_config;

		if (sessionModel) {
			setSelectedModel(sessionModel);
		} else if (agentFixedModel) {
			setSelectedModel(null);
		} else {
			const firstModel = getFirstAvailableModel();
			if (firstModel) {
				setSelectedModel(firstModel);
				if (sessionId && agentId) {
					sessionApi
						.update(sessionId, agentId, { chat_model_config: firstModel })
						.then(() => refetchSessions())
						.catch(() => {});
				}
			} else {
				setSelectedModel(null);
			}
		}

		setSelectedFallbackModel(view.session.config.fallback_chat_model_config ?? null);
		setSelectedTTSModel(view.session.config.tts_model_config ?? null);
		setSelectedKnowledgeConfig(view.session.config.knowledge_config ?? null);
	}, [view, sessionId, agentId, agentFixedModel, getFirstAvailableModel, refetchSessions]);

	// Sync selectedPermissionMode when the session changes. Same
	// loading-window guard as above — don't reset the displayed mode
	// to "default" while the new session view is still on the wire.
	useEffect(() => {
		if (!view) return;
		const mode = (view.session.state?.permission_context as Record<string, unknown>)
			?.mode as PermissionMode;
		setSelectedPermissionMode(mode ?? 'default');
	}, [sessionId, view]);

	/**
	 * Persist a model change to the session and refetch so the local
	 * view picks up the new value.
	 *
	 * @param config - New chat model config; `null` is ignored
	 *   because the primary selector does not allow clearing.
	 */
	const handleLlmChange = async (config: ChatModelConfig | null) => {
		if (agentFixedModel || !config || !sessionId || !agentId) return;
		setSelectedModel(config);
		await sessionApi.update(sessionId, agentId, { chat_model_config: config });
		await refetchSessions();
	};

	/**
	 * Persist a parameter change on the currently selected model.
	 *
	 * @param parameters - New parameter map (model-provider specific).
	 */
	const handleParametersChange = async (parameters: Record<string, unknown>) => {
		if (!selectedModel || !sessionId || !agentId) return;
		const updated = { ...selectedModel, parameters };
		setSelectedModel(updated);
		await sessionApi.update(sessionId, agentId, { chat_model_config: updated });
		await refetchSessions();
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

	/**
	 * Persist a permission-mode change.
	 *
	 * @param mode - New permission mode (e.g. `default`, `explore`).
	 */
	const handlePermissionModeChange = useCallback(
		async (mode: PermissionMode) => {
			if (!sessionId || !agentId) return;
			const previousMode = selectedPermissionMode;
			setSelectedPermissionMode(mode);
			try {
				await sessionApi.update(sessionId, agentId, { permission_mode: mode });
				await refetchSessions();
			} catch (error) {
				setSelectedPermissionMode(previousMode);
				throw error;
			}
		},
		[agentId, refetchSessions, selectedPermissionMode, sessionId],
	);

	useEffect(() => {
		if (permissionReviewerEnabled !== false || selectedPermissionMode !== 'auto') return;
		void handlePermissionModeChange('default').catch(() => undefined);
	}, [handlePermissionModeChange, permissionReviewerEnabled, selectedPermissionMode]);

	return (
		<>
			<main className="flex size-full">
				<ResizablePanelGroup orientation="horizontal">
					<ResizablePanel className="flex flex-1" minSize="24rem">
						<div className="flex flex-col flex-1 min-h-0 min-w-0 overflow-x-hidden p-2">
							<div className="flex flex-row gap-x-2 justify-between">
								<div
									id="tour-llm-select"
									className="flex flex-row items-center gap-x-1"
								>
									<SidebarTrigger className="md:hidden" />
									<LlmSelect
										value={effectiveSelectedModel}
										onChange={handleLlmChange}
										onAddCredential={() => setCredentialOpen(true)}
										refetchTrigger={credentialRefetchTrigger}
										disabled={agentFixedModel !== null}
									/>
									{agentFixedModel && (
										<Badge variant="secondary">
											{t('chat.model.agentFixed')}
										</Badge>
									)}
									{!modelsLoading &&
										effectiveSelectedModel &&
										!selectedModelCard && (
											<Badge variant="destructive">
												{t('chat.model.unavailable')}
											</Badge>
										)}
									<ModelParametersPopover
										selectedModel={effectiveSelectedModel}
										modelCard={selectedModelCard}
										onChange={handleParametersChange}
										selectedFallbackModel={selectedFallbackModel}
										onFallbackChange={handleFallbackChange}
										selectedTTSModel={selectedTTSModel}
										onTTSChange={handleTTSChange}
									/>
								</div>
								<div id="tour-permission-mode" className="flex flex-row gap-x-1">
									<PermissionModeSelect
										value={selectedPermissionMode}
										disabled={!sessionId}
										autoEnabled={permissionReviewerEnabled === true}
										onChange={handlePermissionModeChange}
									/>
								</div>
							</div>
							<div className="flex flex-1 justify-center min-h-0 overflow-hidden relative [--chat-content-w:48rem]">
								<ChatContent
									className={'max-w-[var(--chat-content-w)] w-full'}
									msgs={msgs}
									phase={phase}
									disabled={effectiveSelectedModel === null}
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
										const base64 = dataUrl.split(',', 2)[1] ?? '';
										return {
											id: crypto.randomUUID(),
											type: 'data' as const,
											source: {
												type: 'base64' as const,
												media_type: file.type || 'application/octet-stream',
												data: base64,
											},
											name: file.name,
										};
									}}
								/>
							</div>
						</div>
					</ResizablePanel>
					<ResizableHandle className="bg-transparent">
						<Button
							type="button"
							variant="outline"
							size="icon-xs"
							className="absolute top-24 right-0 z-20 size-7 bg-background shadow-sm"
							onPointerDown={(event) => event.stopPropagation()}
							onClick={togglePanelDock}
							aria-label={t(
								isPanelCollapsed ? 'panel.expandSidebar' : 'panel.collapseSidebar',
							)}
							title={t(
								isPanelCollapsed ? 'panel.expandSidebar' : 'panel.collapseSidebar',
							)}
						>
							{isPanelCollapsed ? <ChevronLeft /> : <ChevronRight />}
						</Button>
					</ResizableHandle>
					<PanelDock
						activeKey={activePanel}
						onActiveChange={setActivePanel}
						panels={panels}
						panelRef={panelDockRef}
						onCollapsedChange={setIsPanelCollapsed}
					/>
				</ResizablePanelGroup>
			</main>
			<CreateCredentialDialog
				open={credentialOpen}
				onOpenChange={setCredentialOpen}
				onCreated={() => setCredentialRefetchTrigger((n) => n + 1)}
			/>
		</>
	);
}
