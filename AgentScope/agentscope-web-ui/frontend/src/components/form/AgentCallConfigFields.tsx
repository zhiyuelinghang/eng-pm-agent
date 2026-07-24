import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { AgentCallConfig, AgentCallScope, AgentView } from '@/api';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';

interface Props {
	values: Partial<AgentCallConfig>;
	agents: AgentView[];
	currentAgentId?: string;
	onChange: (key: keyof AgentCallConfig, value: AgentCallScope | string[]) => void;
}

const SCOPES: AgentCallScope[] = ['all', 'selected', 'none'];

export function AgentCallConfigFields({ values, agents, currentAgentId, onChange }: Props) {
	const { t } = useTranslation();
	const scope = values.scope ?? 'all';
	const selectedIds = useMemo(() => values.allowed_agent_ids ?? [], [values.allowed_agent_ids]);
	const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

	const candidates = useMemo(
		() =>
			agents
				.filter(
					(agent) =>
						agent.id !== currentAgentId &&
						agent.data.invite_config.invitable &&
						(agent.data.invite_config.invite_description ?? '').trim().length > 0,
				)
				.sort((a, b) => a.data.name.localeCompare(b.data.name)),
		[agents, currentAgentId],
	);

	const toggleAgent = (agentId: string, checked: boolean) => {
		const next = checked
			? [...selectedIds, agentId]
			: selectedIds.filter((id) => id !== agentId);
		onChange('allowed_agent_ids', [...new Set(next)]);
	};

	return (
		<FieldGroup>
			<Field>
				<FieldLabel htmlFor="agent-form-call-config-scope">
					{t('agent-form.call-config.scope.label')}
				</FieldLabel>
				<Select
					value={scope}
					onValueChange={(value) => onChange('scope', value as AgentCallScope)}
				>
					<SelectTrigger id="agent-form-call-config-scope" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						{SCOPES.map((value) => (
							<SelectItem key={value} value={value}>
								{t(`agent-form.call-config.scope.options.${value}`)}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<FieldDescription>
					{t(`agent-form.call-config.scope.descriptions.${scope}`)}
				</FieldDescription>
			</Field>

			{scope === 'selected' && (
				<Field>
					<FieldLabel>{t('agent-form.call-config.allowed-agents.label')}</FieldLabel>
					{candidates.length === 0 ? (
						<FieldDescription>
							{t('agent-form.call-config.allowed-agents.empty')}
						</FieldDescription>
					) : (
						<div className="border-input divide-border max-h-56 overflow-y-auto rounded-md border">
							{candidates.map((agent) => {
								const description =
									agent.data.invite_config.invite_description?.trim();
								const checkboxId = `agent-call-target-${agent.id}`;
								return (
									<label
										key={agent.id}
										htmlFor={checkboxId}
										className="hover:bg-muted/50 flex cursor-pointer items-start gap-3 border-b p-3 last:border-b-0"
									>
										<Checkbox
											id={checkboxId}
											checked={selectedSet.has(agent.id)}
											onCheckedChange={(checked) =>
												toggleAgent(agent.id, checked === true)
											}
											className="mt-0.5"
										/>
										<span className="min-w-0 flex-1">
											<span className="block text-sm font-medium">
												{agent.data.name}
											</span>
											{description && (
												<span className="text-muted-foreground mt-0.5 block text-xs">
													{description}
												</span>
											)}
										</span>
										<span className="text-muted-foreground font-mono text-[10px]">
											{agent.id.slice(0, 8)}
										</span>
									</label>
								);
							})}
						</div>
					)}
					<FieldDescription>
						{t('agent-form.call-config.allowed-agents.description', {
							count: selectedIds.length,
						})}
					</FieldDescription>
				</Field>
			)}
		</FieldGroup>
	);
}
