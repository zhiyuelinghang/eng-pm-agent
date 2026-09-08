import { Crown, Info, Network, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type {
	PermissionMode,
	PlatformAgentConfig,
	MemoryScopeType,
	PlatformAgentRole,
	SessionKnowledgeConfig,
} from '@/api';
import { KnowledgeBasePanel } from '@/components/panel/KnowledgeBasePanel';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useKnowledgeBases } from '@/hooks/useKnowledgeBases';

interface Props {
	values: Partial<PlatformAgentConfig>;
	onChange: (key: keyof PlatformAgentConfig, value: unknown) => void;
}

const ROLES: PlatformAgentRole[] = ['business', 'system_internal'];
const PERMISSION_MODES: PermissionMode[] = [
	'auto',
	'default',
	'accept_edits',
	'explore',
	'dont_ask',
	'bypass',
];

export function AgentPlatformConfigFields({ values, onChange }: Props) {
	const { t, i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const { knowledgeBases, loading } = useKnowledgeBases();
	const role = values.role ?? 'business';
	const agentLevel = values.agent_level ?? 'worker';
	const knowledgeConfig = values.knowledge_config ?? null;

	const updateKnowledgeConfig = (next: SessionKnowledgeConfig | null) => {
		if (next && Object.keys(next.parameters ?? {}).length === 0) {
			next = {
				...next,
				parameters: { mode: 'agentic', top_k: 5 },
			};
		}
		onChange('knowledge_config', next);
	};

	const updateKnowledgeParameter = (key: string, value: string | number) => {
		if (!knowledgeConfig) return;
		onChange('knowledge_config', {
			...knowledgeConfig,
			parameters: {
				...knowledgeConfig.parameters,
				[key]: value,
			},
		});
	};

	return (
		<FieldGroup>
			<Field>
				<FieldLabel htmlFor="agent-platform-role">
					{t('agent-form.platform-config.role.label')}
				</FieldLabel>
				<Select
					value={role}
					disabled={role === 'global_main'}
					onValueChange={(value) => onChange('role', value as PlatformAgentRole)}
				>
					<SelectTrigger id="agent-platform-role" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						{role === 'global_main' && (
							<SelectItem value="global_main" disabled>
								{t('agent-form.platform-config.role.options.global_main')}
							</SelectItem>
						)}
						{ROLES.map((value) => (
							<SelectItem key={value} value={value}>
								{t(`agent-form.platform-config.role.options.${value}`)}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<FieldDescription>
					{t(`agent-form.platform-config.role.descriptions.${role}`)}
				</FieldDescription>
			</Field>

			{role === 'global_main' && (
				<Alert>
					<Crown />
					<AlertDescription>
						{t('agent-form.platform-config.globalMainNotice')}
					</AlertDescription>
				</Alert>
			)}

			<Field>
				<FieldLabel htmlFor="agent-platform-level">
					{t('agent-form.platform-config.agentLevel.label')}
				</FieldLabel>
				<Select
					value={agentLevel}
					disabled={role === 'global_main'}
					onValueChange={(value) =>
						onChange('agent_level', value as 'management' | 'worker')
					}
				>
					<SelectTrigger id="agent-platform-level" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						<SelectItem value="management">
							{t('agent-form.platform-config.agentLevel.management')}
						</SelectItem>
						<SelectItem value="worker">
							{t('agent-form.platform-config.agentLevel.worker')}
						</SelectItem>
					</SelectContent>
				</Select>
				<FieldDescription>
					{t(`agent-form.platform-config.agentLevel.${agentLevel}Description`)}
				</FieldDescription>
			</Field>

			<section className="space-y-3 rounded-lg border p-4 text-sm">
				<h3 className="font-medium">{zh ? '长期记忆权限' : 'Long-term memory access'}</h3>
				{role === 'global_main' && <p className="text-xs leading-6 text-muted-foreground">{zh ? '全局主智能体的写入抽屉、记录与提炼开关同时约束群聊后台学习。群聊成员均可贡献证据；成果归属由实际群可见范围决定。触发频率和预算在记忆设置中调整。' : 'The global main agent policy also governs background group learning. All members can contribute; source visibility determines ownership.'}</p>}
				<p className="text-xs leading-5 text-muted-foreground">{agentLevel === 'worker'
					? (zh ? '执行级智能体通过任务上下文工作，不直接读写长期记忆。下面的设置在切换为管理级后生效。' : 'Worker agents use task context. These settings apply when the agent becomes a management agent.')
					: (zh ? '以下范围仍受当前用户、项目权限限制。群聊不读取私人抽屉，项目共享写入须有平台授权。' : 'Current user and project permissions still apply. Group conversations cannot read private drawers; shared writes require platform authorization.')}</p>
				{(['memory_read_scopes', 'memory_write_scopes'] as const).map((key) => <div key={key} className="space-y-2">
					<p className="text-xs font-medium">{key === 'memory_read_scopes' ? (zh ? '允许读取' : 'Allow reading') : (zh ? '允许写入' : 'Allow writing')}</p>
					<div className="flex flex-wrap gap-4">{(['user', 'user_project', 'project'] as MemoryScopeType[]).map((scope) => {
						const selected = values[key] ?? ['user', 'user_project', 'project'];
						return <label key={scope} className="flex items-center gap-2 text-sm"><Checkbox disabled={agentLevel === 'worker'} checked={selected.includes(scope)} onCheckedChange={(checked) => onChange(key, checked === true ? [...selected, scope] : selected.filter((s) => s !== scope))} />
							{({ user: zh ? '用户级' : 'User', user_project: zh ? '用户＋项目级' : 'User + project', project: zh ? '项目级' : 'Project' })[scope]}</label>;
					})}</div>
				</div>)}
				<div className="space-y-3 border-t pt-3"><h4 className="text-sm font-medium">{zh ? '学习能力' : 'Learning capabilities'}</h4>{([
					['learning_capture', zh ? '记录纠正与任务证据' : 'Capture corrections and task evidence'],
					['learning_process', zh ? '后台自动整理经验与技能' : 'Generate candidate lessons and skills'],
					['learning_use', zh ? '使用已验证的经验与技能' : 'Use verified lessons and skills'],
				] as const).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-sm"><Checkbox disabled={agentLevel === 'worker'} checked={values[key] ?? true} onCheckedChange={(checked) => onChange(key, checked === true)} />{label}</label>)}<p className="text-xs leading-5 text-muted-foreground">{zh ? '关闭提炼后仍可保留素材；有价值的成果经系统校验后自动启用，无需人工审核。执行层的结果由管理层在授权任务上下文中复盘。' : 'Capture can remain enabled when generation is paused. Results are checked and published automatically. Worker outcomes are reviewed by the manager within the authorized task context.'}</p></div>
			</section>

			<div className="grid grid-cols-2 gap-3">
				<Field orientation="horizontal">
					<Checkbox
						id="agent-platform-enabled"
						checked={values.enabled ?? true}
						disabled={role === 'global_main'}
						onCheckedChange={(checked) => onChange('enabled', checked === true)}
					/>
					<FieldLabel htmlFor="agent-platform-enabled" className="font-normal">
						{t('agent-form.platform-config.enabled')}
					</FieldLabel>
				</Field>
				<Field orientation="horizontal">
					<Checkbox
						id="agent-platform-published"
						checked={role !== 'system_internal' && (values.published ?? true)}
						disabled={role === 'system_internal'}
						onCheckedChange={(checked) => onChange('published', checked === true)}
					/>
					<FieldLabel htmlFor="agent-platform-published" className="font-normal">
						{t('agent-form.platform-config.published')}
					</FieldLabel>
				</Field>
			</div>

			<Field orientation="horizontal">
				<Checkbox
					id="agent-platform-global-main-call"
					checked={values.allow_global_main_call ?? false}
					disabled={role === 'global_main'}
					onCheckedChange={(checked) =>
						onChange('allow_global_main_call', checked === true)
					}
				/>
				<div className="grid gap-1">
					<FieldLabel
						htmlFor="agent-platform-global-main-call"
						className="font-normal"
					>
						{t('agent-form.platform-config.allowGlobalMainCall')}
					</FieldLabel>
					<FieldDescription>
						{t(
							'agent-form.platform-config.allowGlobalMainCallDescription',
						)}
					</FieldDescription>
				</div>
			</Field>

			<Field orientation="horizontal">
				<Checkbox
					id="agent-platform-project-knowledge"
					checked={values.project_knowledge_enabled ?? false}
					onCheckedChange={(checked) =>
						onChange('project_knowledge_enabled', checked === true)
					}
				/>
				<div className="grid gap-1">
					<FieldLabel htmlFor="agent-platform-project-knowledge" className="font-normal">
						{t('agent-form.platform-config.projectKnowledge')}
					</FieldLabel>
					<FieldDescription>
						{t('agent-form.platform-config.projectKnowledgeDescription')}
					</FieldDescription>
				</div>
			</Field>

			<Field>
				<FieldLabel htmlFor="agent-platform-description">
					{t('agent-form.platform-config.catalogDescription')}
				</FieldLabel>
				<Textarea
					id="agent-platform-description"
					rows={3}
					value={values.description ?? ''}
					onChange={(event) => onChange('description', event.target.value || null)}
					placeholder={t('agent-form.platform-config.descriptionPlaceholder')}
				/>
			</Field>

			<div className="grid grid-cols-[minmax(0,1fr)_120px] gap-3">
				<Field>
					<FieldLabel htmlFor="agent-platform-category">
						{t('agent-form.platform-config.category')}
					</FieldLabel>
					<Input
						id="agent-platform-category"
						value={values.category ?? '通用'}
						onChange={(event) => onChange('category', event.target.value)}
					/>
				</Field>
				<Field>
					<FieldLabel htmlFor="agent-platform-sort-order">
						{t('agent-form.platform-config.sortOrder')}
					</FieldLabel>
					<Input
						id="agent-platform-sort-order"
						type="number"
						min={0}
						max={9999}
						value={values.sort_order ?? 100}
						onChange={(event) =>
							onChange('sort_order', Number(event.target.value || 0))
						}
					/>
				</Field>
			</div>

			<Field>
				<FieldLabel htmlFor="agent-platform-permission-mode">
					{t('agent-form.platform-config.permissionMode')}
				</FieldLabel>
				<Select
					value={values.permission_mode ?? 'auto'}
					onValueChange={(value) =>
						onChange('permission_mode', value as PermissionMode)
					}
				>
					<SelectTrigger id="agent-platform-permission-mode" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						{PERMISSION_MODES.map((value) => (
							<SelectItem key={value} value={value}>
								{t(`agent-form.platform-config.permissionOptions.${value}`)}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<FieldDescription>
					{t('agent-form.platform-config.permissionModeDescription')}
				</FieldDescription>
			</Field>

			<Field>
				<FieldLabel className="flex items-center gap-2">
					<Network className="size-4" />
					{t('agent-form.platform-config.knowledge.label')}
				</FieldLabel>
				<FieldDescription>
					{t('agent-form.platform-config.knowledge.description')}
				</FieldDescription>
				<div className="mt-2 h-64 rounded-lg border p-3">
					<KnowledgeBasePanel
						knowledgeBases={knowledgeBases}
						loading={loading}
						value={knowledgeConfig}
						onChange={updateKnowledgeConfig}
					/>
				</div>
			</Field>

			{knowledgeConfig && (
				<div className="grid grid-cols-2 gap-3 rounded-lg border p-3">
					<Field>
						<FieldLabel htmlFor="agent-platform-kb-mode">
							{t('agent-form.platform-config.knowledge.mode')}
						</FieldLabel>
						<Select
							value={String(knowledgeConfig.parameters.mode ?? 'agentic')}
							onValueChange={(value) =>
								updateKnowledgeParameter('mode', value)
							}
						>
							<SelectTrigger id="agent-platform-kb-mode" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="agentic">
									{t('agent-form.platform-config.knowledge.agentic')}
								</SelectItem>
								<SelectItem value="static">
									{t('agent-form.platform-config.knowledge.static')}
								</SelectItem>
							</SelectContent>
						</Select>
					</Field>
					<Field>
						<FieldLabel htmlFor="agent-platform-kb-top-k">
							{t('agent-form.platform-config.knowledge.topK')}
						</FieldLabel>
						<Input
							id="agent-platform-kb-top-k"
							type="number"
							min={1}
							max={50}
							value={Number(knowledgeConfig.parameters.top_k ?? 5)}
							onChange={(event) =>
								updateKnowledgeParameter(
									'top_k',
									Math.max(1, Number(event.target.value || 1)),
								)
							}
						/>
					</Field>
				</div>
			)}

			<Alert>
				{role === 'business' ? <Wrench /> : <Info />}
				<AlertDescription>
					{t('agent-form.platform-config.visibilityNotice')}
				</AlertDescription>
			</Alert>
		</FieldGroup>
	);
}
