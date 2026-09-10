import type { Duty } from './agent-workbench';
import type {
	CreateAgentRequest,
	CreateAgentResponse,
	PlatformSettings,
	UpdateAgentRequest,
	UpdatePlatformSettingsRequest,
} from '../api/types';

type SetupApi = {
	getPlatformSettings: () => Promise<PlatformSettings>;
	create: (
		body: CreateAgentRequest,
		options: { silent: boolean },
	) => Promise<CreateAgentResponse>;
	update: (
		id: string,
		body: UpdateAgentRequest,
		options: { silent: boolean },
	) => Promise<unknown>;
	updatePlatformSettings: (body: UpdatePlatformSettingsRequest) => Promise<PlatformSettings>;
};

/** Keeps the first saved object when finishing a fixed entry needs a retry. */
export async function saveFixedAgentSetup(
	duty: Duty,
	body: CreateAgentRequest,
	pending: { agentId: string | null },
	api: SetupApi,
): Promise<string> {
	if (body.model_policy?.mode !== 'fixed' || !body.model_policy.chat_model_config)
		throw new Error('请为主智能体配置固定模型。');
	if (!body.platform_config?.enabled) throw new Error('请启用当前主智能体。');
	const settings = await api.getPlatformSettings();
	const existingId = settings[duty.field];
	if (existingId && existingId !== pending.agentId)
		throw new Error('该主智能体已有配置，请关闭弹窗并刷新页面后编辑。');
	if (duty.key === 'initializer' && !settings.project_initializer_validation_mcp)
		throw new Error('请先在初始化核验中配置规则版本，再保存智能体。');
	if (pending.agentId) {
		await api.update(pending.agentId, body, { silent: true });
	} else {
		pending.agentId = (await api.create(body, { silent: true })).agent_id;
	}
	const agentId = pending.agentId;
	try {
		await api.updatePlatformSettings({ [duty.field]: agentId });
	} catch (error) {
		// A response can fail after persistence; verify before repeating the save.
		const saved = await api.getPlatformSettings().catch(() => null);
		if (saved?.[duty.field] !== agentId) throw error;
	}
	pending.agentId = null;
	return agentId;
}
