// ─── Shared ───────────────────────────────────────────────────────────────────

export interface RecordBase {
	id: string;
	created_at: string;
	updated_at: string;
}

export interface ChatModelConfig {
	type: string;
	credential_id: string;
	model: string;
	parameters: Record<string, unknown>;
}

export interface TTSModelConfig {
	type: string;
	credential_id: string;
	model: string;
	parameters: Record<string, unknown>;
}

export interface ContextConfig {
	trigger_ratio?: number;
	reserve_ratio?: number;
	tool_result_limit?: number;
	compression_prompt?: string;
	summary_template?: string;
}

export interface ReActConfig {
	max_iters?: number;
	stop_on_reject?: boolean;
}

export interface InviteConfig {
	invitable?: boolean;
	invite_description?: string | null;
}

export type AgentCallScope = 'all' | 'selected' | 'none';

export interface AgentCallConfig {
	scope: AgentCallScope;
	allowed_agent_ids: string[];
}

export interface AgentToolConfig {
	/** null keeps the legacy/default behavior where every catalogue tool is assigned. */
	allowed_tool_names: string[] | null;
}

export interface AgentMCPConfig {
	/** Stable platform MCP package ids assigned to every session of the agent. */
	allowed_mcp_ids: string[];
}

export type DatabaseTableOperation = 'read' | 'create' | 'update' | 'delete';
export type DatabaseJoinType = 'left' | 'inner';
export type DatabaseScopeType = 'project' | 'user' | 'global_admin';
export type DatabaseInteractionAccessMode = 'agent' | 'workflow';
export type DatabaseConversationType = 'general' | 'business' | 'initialization';
export type DatabaseContextBindingSource =
	| 'project_id'
	| 'conversation_id'
	| 'user_id'
	| 'actor_agent_id';
export type DatabaseContextBindingMode = 'scope' | 'value';

export interface DatabaseTableColumn {
	name: string;
	type: string;
	nullable: boolean;
	primary_key: boolean;
	foreign_keys: string[];
	sensitive: boolean;
	system_managed: boolean;
}

export interface DatabaseTableInfo {
	name: string;
	columns: DatabaseTableColumn[];
	recommended_scope_type: DatabaseScopeType;
	recommended_scope_field: string | null;
}

export interface DatabaseTablePolicy {
	id: number;
	table_name: string;
	display_name: string;
	description: string;
	allowed_operations: DatabaseTableOperation[];
	readable_fields: string[];
	writable_fields: string[];
	filterable_fields: string[];
	scope_type: DatabaseScopeType;
	scope_field: string | null;
	minimum_role: 'member' | 'admin';
	enabled: boolean;
	created_at: string;
	updated_at: string;
}

export interface DatabaseInteractionJoin {
	alias: string;
	source_alias: string;
	source_field: string;
	target_policy_id: number;
	target_field: string;
	join_type: DatabaseJoinType;
	readable_fields: string[];
	filterable_fields: string[];
	policy: DatabaseTablePolicy | null;
}

export type DatabaseInteractionJoinRequest = Omit<
	DatabaseInteractionJoin,
	'policy'
>;

export interface DatabaseInteractionContextBinding {
	field: string;
	source: DatabaseContextBindingSource;
	mode: DatabaseContextBindingMode;
}

export interface DatabaseInteraction {
	id: number;
	key: string;
	display_name: string;
	description: string;
	table_policy_id: number;
	table_operation: DatabaseTableOperation;
	join_rules: DatabaseInteractionJoin[];
	context_bindings: DatabaseInteractionContextBinding[];
	allowed_conversation_types: DatabaseConversationType[];
	access_mode: DatabaseInteractionAccessMode;
	input_schema: Record<string, unknown>;
	read_only: boolean;
	requires_confirmation: boolean;
	enabled: boolean;
	default_assigned: boolean;
	sort_order: number;
	assigned: boolean;
	policy: DatabaseTablePolicy | null;
	created_at: string;
	updated_at: string;
}

export interface DatabaseTableInteractionRequest {
	key: string;
	display_name: string;
	description: string;
	table_policy_id: number;
	table_operation: DatabaseTableOperation;
	join_rules: DatabaseInteractionJoinRequest[];
	context_bindings: DatabaseInteractionContextBinding[];
	allowed_conversation_types: DatabaseConversationType[];
	access_mode: DatabaseInteractionAccessMode;
	requires_confirmation: boolean;
	enabled: boolean;
	sort_order: number;
}

export type AgentModelPolicyMode = 'inherit_session' | 'fixed';

export interface AgentModelPolicy {
	mode: AgentModelPolicyMode;
	chat_model_config: ChatModelConfig | null;
}

export type PlatformAgentRole = 'global_main' | 'business' | 'system_internal';

export interface PlatformAgentConfig {
	role: PlatformAgentRole;
	enabled: boolean;
	published: boolean;
	allow_global_main_call: boolean;
	description: string | null;
	category: string;
	sort_order: number;
	permission_mode: PermissionMode;
	knowledge_config: SessionKnowledgeConfig | null;
}

// ─── Agent ────────────────────────────────────────────────────────────────────

export interface AgentData {
	id: string;
	name: string;
	system_prompt: string;
	context_config: ContextConfig;
	react_config: ReActConfig;
	model_policy: AgentModelPolicy;
	platform_config: PlatformAgentConfig;
	invite_config: InviteConfig;
	call_config: AgentCallConfig;
	tool_config: AgentToolConfig;
	mcp_config: AgentMCPConfig;
}

export interface AgentView extends RecordBase {
	user_id: string;
	data: AgentData;
	/**
	 * Whether the current viewer may PATCH/DELETE this agent. `false`
	 * for agents shared to the viewer with read-only permission.
	 */
	editable: boolean;
}

export interface CreateAgentRequest {
	name: string;
	system_prompt?: string;
	context_config?: ContextConfig;
	react_config?: ReActConfig;
	model_policy?: AgentModelPolicy;
	platform_config?: PlatformAgentConfig;
	invite_config?: InviteConfig;
	call_config?: AgentCallConfig;
	mcp_config?: AgentMCPConfig;
}

export interface CreateAgentResponse {
	agent_id: string;
}

export interface UpdateAgentRequest {
	name?: string;
	system_prompt?: string;
	context_config?: ContextConfig;
	react_config?: ReActConfig;
	model_policy?: AgentModelPolicy;
	platform_config?: PlatformAgentConfig;
	invite_config?: InviteConfig;
	call_config?: AgentCallConfig;
	mcp_config?: AgentMCPConfig;
}

export interface AgentListResponse {
	agents: AgentView[];
	total: number;
}

export interface PlatformSettings {
	global_main_agent_id: string | null;
	project_initializer_agent_id: string | null;
}

export interface UpdatePlatformSettingsRequest {
	global_main_agent_id?: string;
	project_initializer_agent_id?: string | null;
}

/**
 * @deprecated Superseded by {@link AgentSchemaV2Response}. Kept only for
 * legacy consumers still calling `GET /agent/schema`. The new form flow
 * uses `GET /agent/schema/v2`, which returns the full `AgentData` JSON
 * Schema in a single `schema` field.
 */
export interface AgentSchemaResponse {
	identity: JSONSchema;
	context_config: JSONSchema;
	react_config: JSONSchema;
}

/**
 * Response of `GET /agent/schema/v2`. `schema` is the full `AgentData`
 * JSON Schema (with `$ref`s inlined, `id` filtered out, and
 * `context_config.summary_schema` filtered out). The frontend derives
 * its section grouping directly from `schema.properties`:
 *   - top-level scalar/textarea/boolean properties → "identity" section
 *   - top-level `object`-typed properties (currently `context_config`,
 *     `react_config`, `invite_config`, and `call_config`) → one section each
 */
export interface AgentSchemaV2Response {
	schema: JSONSchema;
}

// ─── Session ──────────────────────────────────────────────────────────────────

export type SessionSource = 'user' | 'schedule' | 'platform';

export interface PlatformSessionContext {
	user_id: string;
	username: string;
	display_name: string;
	project_id: string;
	project_name: string;
	conversation_id: string;
	conversation_title: string;
	conversation_type: string;
	agent_name: string;
	session_role: 'primary' | 'worker';
	root_session_id: string | null;
}

export interface SessionConfig {
	name: string;
	chat_model_config: ChatModelConfig;
	/** Fallback model used when the primary model fails. */
	fallback_chat_model_config: ChatModelConfig | null;
	/** TTS model configuration. null means TTS is not enabled. */
	tts_model_config: TTSModelConfig | null;
	/** Knowledge bases attached to this session + KB middleware parameters. */
	knowledge_config: SessionKnowledgeConfig | null;
	/** Platform grouping snapshot. null for management/testing sessions. */
	platform_context: PlatformSessionContext | null;
	workspace_id: string;
}

// TODO: update when Python side is finalised
export type AgentState = Record<string, unknown>;

export interface SessionRecord extends RecordBase {
	user_id: string;
	agent_id: string;
	source: SessionSource;
	source_schedule_id: string | null;
	/**
	 * The team this session participates in, if any. Set when the
	 * session is the leader of a team (the session that called
	 * `TeamCreate`) or a worker spawned by `AgentCreate`. `null` for
	 * regular standalone sessions.
	 */
	team_id: string | null;
	config: SessionConfig;
	state: AgentState;
}

export interface CreateSessionRequest {
	agent_id: string;
	workspace_id?: string;
	chat_model_config?: ChatModelConfig | null;
	/** Optional fallback model. Omit (or pass null) for no fallback. */
	fallback_chat_model_config?: ChatModelConfig | null;
	/** Optional TTS model. Omit (or pass null) for no TTS. */
	tts_model_config?: TTSModelConfig | null;
	/** Optional knowledge base attachment. Omit (or null) for none. */
	knowledge_config?: SessionKnowledgeConfig | null;
}

export interface CreateSessionResponse {
	session_id: string;
}

export interface InterruptSessionResponse {
	session_id: string;
}

export interface UpdateSessionRequest {
	name?: string;
	chat_model_config?: ChatModelConfig;
	/**
	 * New fallback model. PATCH semantics:
	 *   - omit the field → leave unchanged
	 *   - set to `null`  → clear the existing fallback
	 *   - set to a value → replace the existing fallback
	 */
	fallback_chat_model_config?: ChatModelConfig | null;
	/**
	 * New TTS model. PATCH semantics:
	 *   - omit the field → leave unchanged
	 *   - set to `null`  → disable TTS
	 *   - set to a value → replace the existing TTS config
	 */
	tts_model_config?: TTSModelConfig | null;
	/**
	 * New knowledge base attachment. PATCH semantics:
	 *   - omit the field → leave unchanged
	 *   - set to `null`  → detach every knowledge base
	 *   - set to a value → replace the existing attachment
	 */
	knowledge_config?: SessionKnowledgeConfig | null;
	permission_mode?: PermissionMode;
}

export interface SessionListResponse {
	sessions: SessionView[];
	total: number;
}

/**
 * Response body for `GET /schedule/{id}/sessions`. Returns plain
 * `SessionRecord[]` (no team / is_running enrichment) because
 * scheduled-execution sessions are listed for audit purposes only,
 * not for opening in the chat UI.
 */
export interface ScheduleSessionsResponse {
	sessions: SessionRecord[];
	total: number;
}

// ─── Platform interaction audit ──────────────────────────────────────────────

export interface PlatformAuditConversation {
	session_id: string;
	conversation_id: string;
	title: string;
	conversation_type: string;
	agent_id: string;
	agent_name: string;
	is_running: boolean;
	created_at: string;
	updated_at: string;
}

export interface PlatformAuditProject {
	project_id: string;
	project_name: string;
	conversations: PlatformAuditConversation[];
}

export interface PlatformAuditUser {
	user_id: string;
	username: string;
	display_name: string;
	projects: PlatformAuditProject[];
}

export interface PlatformAuditTreeResponse {
	users: PlatformAuditUser[];
	total_conversations: number;
}

export interface PlatformAuditMessagesResponse {
	session_id: string;
	messages: Msg[];
	is_running: boolean;
}

// ─── Team ─────────────────────────────────────────────────────────────────────

export interface TeamData {
	name: string;
	description: string;
	/** Worker agent ids belonging to the team. */
	member_ids: string[];
	work_revision: number;
	leader_completed_revision: number;
	settlement_revision: number;
}

export interface TeamRecord extends RecordBase {
	user_id: string;
	/** The leader session id — the session that called `TeamCreate`. */
	session_id: string;
	data: TeamData;
}

/**
 * One member entry inside `TeamDetailResponse.members`. Pairs the
 * worker's `AgentView` with its single `session_id` so the UI can
 * navigate straight to the worker's chat.
 */
export interface TeamMemberInfo {
	agent: AgentView;
	/** `null` if the agent is in an inconsistent state (no session). */
	session_id: string | null;
	work_revision: number;
	settled_revision: number;
	active_revision: number;
	work_status:
		| 'idle'
		| 'queued'
		| 'running'
		| 'reported'
		| 'completed'
		| 'failed'
		| 'interrupted';
	assigned_at: string | null;
	started_at: string | null;
	settled_at: string | null;
	last_reply_id: string | null;
	last_error: string | null;
}

/**
 * Resolved team detail returned inline inside `SessionView.team`.
 *
 * The leader's `AgentView` is looked up from the team's
 * `session_id` → `session.agent_id` chain on the server side.
 */
export interface TeamDetailResponse {
	team: TeamRecord;
	leader_agent: AgentView | null;
	members: TeamMemberInfo[];
}

/**
 * Per-session bundle returned by `GET /sessions/?agent_id=...`.
 *
 * Bundles three pieces of information so the chat UI can render a
 * session without follow-up requests: the persisted record (incl.
 * `state`), whether a chat run is active, and — when the session
 * participates in a team — the resolved team detail.
 *
 * Messages are intentionally separate (`GET /sessions/{id}/messages`)
 * since they paginate independently.
 */
export interface SessionView {
	session: SessionRecord;
	is_running: boolean;
	team: TeamDetailResponse | null;
}

// ─── JSON Schema ──────────────────────────────────────────────────────────────

/**
 * Subset of JSON Schema property fields the frontend renders. Sourced from
 * Pydantic's `model_json_schema()` output, including the `format: textarea`
 * hint we add via `json_schema_extra` for multi-line strings.
 */
export interface JSONSchemaProperty {
	type?: string;
	format?: string;
	description?: string;
	default?: unknown;
	const?: unknown;
	anyOf?: Array<{ type: string }>;
	enum?: unknown[];
	title?: string;
	writeOnly?: boolean;
	minimum?: number;
	maximum?: number;
	exclusiveMinimum?: number;
	exclusiveMaximum?: number;
}

export interface JSONSchema {
	title?: string;
	type?: string;
	properties: Record<string, JSONSchemaProperty>;
	required?: string[];
}

// ─── Credential ───────────────────────────────────────────────────────────────

export type CredentialSchemaProperty = JSONSchemaProperty;

// Credential schemas always include title + type (Pydantic always emits them
// for credential data classes); we narrow the generic JSONSchema here so call
// sites that read `schema.title` don't have to do null-checks.
export interface CredentialSchema extends JSONSchema {
	title: string;
	type: string;
}

export interface CredentialSchemasResponse {
	schemas: CredentialSchema[];
}

export interface CredentialView extends RecordBase {
	user_id: string;
	/**
	 * Credential payload. When the current viewer is not the owner
	 * (shared credential), only `type` and `name` are populated —
	 * secret fields are stripped server-side.
	 */
	data: Record<string, unknown>;
	/**
	 * Whether the current viewer may PATCH/DELETE this credential.
	 * `false` for credentials shared with read-only permission.
	 */
	editable: boolean;
}

export interface CreateCredentialRequest {
	data: Record<string, unknown>;
}

export interface CreateCredentialResponse {
	credential_id: string;
}

export interface UpdateCredentialRequest {
	data: Record<string, unknown>;
}

export interface CredentialListResponse {
	credentials: CredentialView[];
	total: number;
}

export interface CredentialModelDefinition {
	model_type: 'chat' | 'embedding';
	name: string;
	label: string | null;
	context_size: number;
	output_size: number;
	input_types: string[];
	output_types: string[];
	dimensions: number | null;
}

export interface CredentialModelEntry extends ModelCard {
	source: 'builtin' | 'discovered' | 'manual';
	enabled: boolean;
	default_parameters: Record<string, unknown>;
}

export interface CredentialEmbeddingModelEntry extends EmbeddingModelCard {
	source: 'builtin' | 'discovered' | 'manual';
	enabled: boolean;
}

export interface CredentialModelCatalogResponse {
	models: CredentialModelEntry[];
	embedding_models: CredentialEmbeddingModelEntry[];
	manual_models: CredentialModelDefinition[];
	hidden_model_ids: string[];
	hidden_embedding_model_ids: string[];
	model_default_parameters: Record<string, Record<string, unknown>>;
	total: number;
	discovery_supported: boolean;
	last_discovery_at: string | null;
	last_discovery_error: string | null;
}

export interface UpdateCredentialModelCatalogRequest {
	manual_models: CredentialModelDefinition[];
	hidden_model_ids: string[];
	hidden_embedding_model_ids: string[];
	model_default_parameters: Record<string, Record<string, unknown>>;
}

export type CredentialModelTestErrorType =
	| 'authentication'
	| 'permission'
	| 'rate_limit'
	| 'invalid_request'
	| 'upstream'
	| 'connection'
	| 'internal'
	| 'unknown';

export interface TestCredentialModelRequest {
	model: string;
	model_type: 'chat' | 'embedding';
}

export interface CredentialModelTestResponse {
	success: boolean;
	model: string;
	model_type: 'chat' | 'embedding';
	latency_ms: number;
	dimensions: number | null;
	error_type: CredentialModelTestErrorType | null;
	message: string;
	status_code: number | null;
	raw_response: string | null;
}

export interface PermissionReviewerConfig {
	enabled: boolean;
	credential_id: string | null;
	model: string | null;
	parameters: Record<string, unknown>;
	fallback_credential_id: string | null;
	fallback_model: string | null;
	fallback_parameters: Record<string, unknown>;
	confidence_threshold: number;
	max_auto_risk: 'low' | 'medium';
	timeout_seconds: number;
}

export interface PermissionReviewerConfigResponse {
	config: PermissionReviewerConfig;
	updated_at: string | null;
}

export interface PermissionReviewerTestResponse {
	success: boolean;
	latency_ms: number;
	action: 'allow_once' | 'deny' | 'human_required' | null;
	risk: 'low' | 'medium' | 'high' | 'critical' | null;
	confidence: number | null;
	reason: string | null;
	model: string | null;
	error: string | null;
}

export interface PermissionReviewAudit {
	id: string;
	created_at: string;
	updated_at: string;
	user_id: string;
	agent_id: string;
	session_id: string;
	tool_name: string;
	action: 'allow_once' | 'deny' | 'human_required';
	risk: 'low' | 'medium' | 'high' | 'critical';
	confidence: number;
	reason: string;
	source: string;
	model: string | null;
	tool_input: Record<string, unknown>;
}

export interface PermissionReviewAuditListResponse {
	audits: PermissionReviewAudit[];
	total: number;
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export type { Msg, ContentBlock } from '@agentscope-ai/agentscope/message';
export type { AgentEvent } from '@agentscope-ai/agentscope/event';
import type {
	UserConfirmResultEvent,
	ExternalExecutionResultEvent,
} from '@agentscope-ai/agentscope/event';
import type { Msg } from '@agentscope-ai/agentscope/message';

export interface ChatRequest {
	agent_id: string;
	session_id: string;
	input: Msg | Msg[] | UserConfirmResultEvent | ExternalExecutionResultEvent | null;
}

// ─── MCP ──────────────────────────────────────────────────────────────────────

export interface StdioMCPConfig {
	type: 'stdio_mcp';
	command: string;
	args?: string[] | null;
	env?: Record<string, string> | null;
	cwd?: string | null;
	encoding_error_handler?: 'strict' | 'ignore' | 'replace';
}

export interface HttpMCPConfig {
	type: 'http_mcp';
	url: string;
	headers?: Record<string, string> | null;
	timeout?: number | null;
}

export interface MCPClient {
	name: string;
	is_stateful: boolean;
	mcp_config: StdioMCPConfig | HttpMCPConfig;
}

export interface ToolInfo {
	name: string;
	description?: string | null;
}

export interface WorkspaceTool extends ToolInfo {
	source: 'platform' | 'workspace';
	category: 'database' | 'workspace' | 'general';
	display_name?: string | null;
	assigned: boolean;
	read_only: boolean;
	input_schema: Record<string, unknown>;
}

export interface MCPClientStatus extends MCPClient {
	is_healthy: boolean;
	tools: ToolInfo[];
}

export interface ManagedMCPTool {
	name: string;
	display_name?: string | null;
	description: string;
	input_schema: Record<string, unknown>;
	read_only: boolean;
}

export interface ManagedMCPPackage {
	id: string;
	name: string;
	display_name: string;
	version: string;
	description: string;
	transport: 'stdio';
	status: 'ready';
	tools: ManagedMCPTool[];
	assigned: boolean;
	active_instances: number;
	created_at: string;
	updated_at: string;
}

// ─── Skill ────────────────────────────────────────────────────────────────────

export interface Skill {
	name: string;
	description: string;
	dir: string;
	markdown: string;
	updated_at: number;
}

export interface AddSkillRequest {
	skill_path: string;
}

export interface UpdateSkillRequest {
	name: string;
	description: string;
	markdown: string;
}

// ─── Schedule ─────────────────────────────────────────────────────────────────

export type PermissionMode =
	| 'default'
	| 'auto'
	| 'accept_edits'
	| 'explore'
	| 'bypass'
	| 'dont_ask'
	| (string & {});

export type ScheduleSource = 'USER' | 'AGENT';

export interface ScheduleData {
	name: string;
	description: string;
	enabled: boolean;
	timezone: string;
	cron_expression: string;
	started_at: string;
	ended_at: string | null;
	chat_model_config: ChatModelConfig;
	stateful: boolean;
	permission_mode: PermissionMode;
	source: ScheduleSource;
	source_session_id: string;
}

export interface ScheduleRecord extends RecordBase {
	user_id: string;
	agent_id: string;
	data: ScheduleData;
}

export interface CreateScheduleRequest {
	name: string;
	description?: string;
	cron_expression: string;
	timezone?: string;
	agent_id: string;
	chat_model_config: ChatModelConfig;
	enabled?: boolean;
	stateful?: boolean;
	permission_mode?: PermissionMode;
}

export interface CreateScheduleResponse {
	schedule_id: string;
}

export interface UpdateScheduleRequest {
	name?: string;
	description?: string;
	cron_expression?: string;
	timezone?: string;
	enabled?: boolean;
	stateful?: boolean;
	permission_mode?: PermissionMode;
}

export interface ScheduleListResponse {
	schedules: ScheduleRecord[];
	total: number;
}

// ─── Model ────────────────────────────────────────────────────────────────────

export interface ModelCard {
	type: 'chat_model';
	name: string;
	label: string;
	status: 'active' | 'deprecated' | 'sunset';
	deprecated_at: string | null;
	input_types: string[];
	output_types: string[];
	context_size: number;
	output_size: number;
	parameter_schema: Record<string, unknown>;
	parameters_overrides: Record<string, Record<string, unknown>>;
	/** Credential-scoped defaults; absent on provider-only model endpoints. */
	default_parameters?: Record<string, unknown>;
}

export interface ListModelRequest {
	provider: string;
}

export interface ListModelResponse {
	models: ModelCard[];
	total: number;
}

// ─── Embedding ────────────────────────────────────────────────────────────────

export interface EmbeddingModelConfig {
	type: string;
	credential_id: string;
	model: string;
	/**
	 * Output vector dimensions, pinned at config time. Required because
	 * the backend uses it to size the vector store collection and to
	 * validate against the manager's `DimensionPolicy`.
	 */
	dimensions: number;
	parameters: Record<string, unknown>;
}

export interface EmbeddingModelCard {
	type: 'embedding_model';
	name: string;
	label: string;
	status: 'active' | 'deprecated' | 'sunset';
	input_types: string[];
	output_types: string[];
	context_size: number | null;
	/** Default output dimensions for this model. */
	dimensions: number;
	/**
	 * If set, the only dimensions this model can produce (Matryoshka).
	 * `null` means the model is fixed-dim at `dimensions`.
	 */
	supported_dimensions: number[] | null;
	parameter_schema: Record<string, unknown>;
	parameter_overrides: Record<string, Record<string, unknown>>;
}

// ─── Knowledge Base ───────────────────────────────────────────────────────────

/**
 * Knowledge base view as exposed by the API. Mirrors
 * :class:`agentscope.app._service.KnowledgeBaseView`.
 */
export interface KnowledgeBaseView {
	id: string;
	name: string;
	description: string;
	embedding_model_config: EmbeddingModelConfig;
	created_at: string;
	updated_at: string;
	/**
	 * Whether the current viewer may modify this knowledge base (edit
	 * metadata, add/delete documents). `false` for knowledge bases
	 * shared with read-only permission.
	 */
	editable: boolean;
}

export interface ListKnowledgeBasesResponse {
	knowledge_bases: KnowledgeBaseView[];
	total: number;
}

export interface CreateKnowledgeBaseRequest {
	name: string;
	description?: string;
	embedding_model_config: EmbeddingModelConfig;
}

export interface CreateKnowledgeBaseResponse {
	knowledge_base_id: string;
}

/**
 * Body for `PATCH /knowledge_bases/{id}`. Only mutable fields can be
 * sent; the embedding model is pinned at creation time and cannot
 * change because the underlying collection is sized to its dimension.
 */
export interface UpdateKnowledgeBaseRequest {
	name?: string;
	description?: string;
}

/**
 * Lifecycle states a document can be in. Mirrors
 * :class:`agentscope.app.storage.KnowledgeDocumentStatus`.
 *
 * - `pending` — accepted, blob stored, indexing not yet started.
 * - `parsing` / `chunking` / `indexing` — worker phases.
 * - `ready` — chunks committed to the vector store.
 * - `error` — terminal failure; `error` field carries the reason.
 */
export type KnowledgeDocumentStatus =
	| 'pending'
	| 'parsing'
	| 'chunking'
	| 'indexing'
	| 'ready'
	| 'error';

/**
 * Document view returned by `/knowledge_bases/{id}/documents` and
 * `/knowledge_bases/{id}/documents/status`. Mirrors
 * :class:`agentscope.app._router._schema.KnowledgeDocumentView`.
 */
export interface KnowledgeDocumentView {
	id: string;
	filename: string;
	size: number;
	content_type: string | null;
	status: KnowledgeDocumentStatus;
	error: string | null;
	chunk_count: number;
	created_at: string;
	updated_at: string;
}

export interface ListKnowledgeDocumentsResponse {
	documents: KnowledgeDocumentView[];
	total: number;
}

export interface ListKnowledgeDocumentStatusResponse {
	items: KnowledgeDocumentView[];
}

export interface UploadKnowledgeDocumentResponse {
	document_id: string;
	filename: string;
	status: KnowledgeDocumentStatus;
}

export interface SearchKnowledgeBaseRequest {
	query: string;
	top_k?: number;
}

/**
 * Lightweight chunk shape returned inside `VectorSearchResult`. Mirrors
 * :class:`agentscope.rag.Chunk` — content is the raw `TextBlock` /
 * `DataBlock` discriminated union the backend ships.
 */
export interface KnowledgeChunk {
	content: { type: 'text'; text: string; id?: string } | { type: string; [key: string]: unknown };
	source: string;
	chunk_index: number;
	total_chunks: number;
	metadata: Record<string, unknown>;
}

/**
 * One vector search hit returned by the knowledge base search endpoint.
 * Mirrors :class:`agentscope.rag.VectorSearchResult` on the backend.
 */
export interface VectorSearchResult {
	score: number;
	document_id: string;
	chunk: KnowledgeChunk;
}

export interface SearchKnowledgeBaseResponse {
	results: VectorSearchResult[];
	total: number;
}

/**
 * Mirrors :class:`agentscope.app.rag.knowledge_base_manager.DimensionPolicyKind`.
 */
export type DimensionPolicyKind = 'any' | 'fixed' | 'locked_by_existing';

/**
 * Mirrors :class:`agentscope.app.rag.knowledge_base_manager.DimensionPolicy`.
 */
export interface DimensionPolicy {
	kind: DimensionPolicyKind;
	dimension: number | null;
}

/** One credential and the embedding models it can serve, post-policy. */
export interface KbEmbeddingProvider {
	credential: CredentialView;
	models: EmbeddingModelCard[];
}

/**
 * Response of `GET /knowledge_bases/embedding_models`.
 *
 * Server-side already filtered models by the manager's
 * :class:`DimensionPolicy` and narrowed matryoshka cards to the
 * locked dimension when applicable. The policy is included so the
 * UI can render an explanatory banner.
 */
export interface ListKbEmbeddingModelsResponse {
	providers: KbEmbeddingProvider[];
	policy: DimensionPolicy;
}

/**
 * Session-level knowledge base attachment. Persisted on
 * :class:`SessionConfig.knowledge_config` and translated into a
 * `KnowledgeBaseMiddleware` at chat-run time.
 *
 * `parameters` holds the user-tunable middleware fields verbatim — its
 * accepted keys/values are described by the JSON Schema returned from
 * `GET /knowledge_bases/middleware/parameters_schema`.
 */
export interface SessionKnowledgeConfig {
	knowledge_base_ids: string[];
	parameters: Record<string, unknown>;
}

/** Response of `GET /knowledge_bases/middleware/parameters_schema`. */
export interface KbMiddlewareParametersSchemaResponse {
	parameter_schema: Record<string, unknown>;
}

/** Response of `GET /knowledge_bases/supported_content_types`. */
export interface ListSupportedContentTypesResponse {
	/** Union of IANA media types every registered parser handles. */
	media_types: string[];
	/** Union of filename extensions (each starting with `.`). */
	extensions: string[];
}

// ─── TTS ──────────────────────────────────────────────────────────────────────

export interface TTSModelCard {
	type: 'tts_model';
	name: string;
	label: string;
	status: 'active' | 'deprecated' | 'sunset';
	deprecated_at: string | null;
	input_types: string[];
	output_types: string[];
	realtime: boolean;
	parameter_schema: Record<string, unknown>;
	parameters_overrides: Record<string, Record<string, unknown>>;
}

export interface ListTTSModelResponse {
	models: TTSModelCard[];
	total: number;
}
