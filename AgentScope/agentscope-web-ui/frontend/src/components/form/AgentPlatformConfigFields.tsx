import { Crown, Info, Network, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type {
	PermissionMode,
	PlatformAgentConfig,
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

const ROLES: PlatformAgentRole[] = ['global_main', 'business', 'system_internal'];
const PERMISSION_MODES: PermissionMode[] = [
	'auto',
	'default',
	'accept_edits',
	'explore',
	'dont_ask',
	'bypass',
];

export function AgentPlatformConfigFields({ values, onChange }: Props) {
	const { t } = useTranslation();
	const { knowledgeBases, loading } = useKnowledgeBases();
	const role = values.role ?? 'business';
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
					onValueChange={(value) => onChange('role', value as PlatformAgentRole)}
				>
					<SelectTrigger id="agent-platform-role" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
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

			<div className="grid grid-cols-2 gap-3">
				<Field orientation="horizontal">
					<Checkbox
						id="agent-platform-enabled"
						checked={values.enabled ?? true}
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
