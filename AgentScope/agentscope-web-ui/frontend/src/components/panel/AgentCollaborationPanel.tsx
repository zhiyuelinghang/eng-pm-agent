import { Ban, CircleAlert, Loader2, RotateCcw, Save, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type { AgentCallConfig, AgentCallScope, AgentView } from '@/api';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { PanelSummaryDialog } from '@/components/panel/PanelSummaryDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface AgentCollaborationPanelProps {
	/** The agent whose global collaboration allowlist is being edited. */
	agent: AgentView | null;
	/** All agents visible to the current user, used as selectable targets. */
	agents: AgentView[];
	/** Whether the agent list is still loading. */
	loading?: boolean;
	/** Persist the complete call configuration for the selected agent. */
	onSave: (agentId: string, config: AgentCallConfig) => Promise<void>;
}

const EMPTY_CONFIG: AgentCallConfig = {
	scope: 'all',
	allowed_agent_ids: [],
};

function cloneConfig(config: AgentCallConfig | undefined): AgentCallConfig {
	return {
		scope: config?.scope ?? EMPTY_CONFIG.scope,
		allowed_agent_ids: [...(config?.allowed_agent_ids ?? EMPTY_CONFIG.allowed_agent_ids)],
	};
}

function configsEqual(left: AgentCallConfig, right: AgentCallConfig): boolean {
	if (left.scope !== right.scope) return false;
	if (left.allowed_agent_ids.length !== right.allowed_agent_ids.length) return false;
	const rightIds = new Set(right.allowed_agent_ids);
	return left.allowed_agent_ids.every((id) => rightIds.has(id));
}

/**
 * Dock-panel editor for the current agent's global collaboration allowlist.
 *
 * The underlying value is the same `AgentData.call_config` used by the
 * create/edit dialogs. Changes remain local until Save is clicked so a single
 * checkbox does not unexpectedly affect every session of the agent.
 */
export function AgentCollaborationPanel({
	agent,
	agents,
	loading = false,
	onSave,
}: AgentCollaborationPanelProps) {
	const { t } = useTranslation();
	const [draft, setDraft] = useState<AgentCallConfig>(cloneConfig(agent?.data.call_config));
	const [submitting, setSubmitting] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');
	const [detailTarget, setDetailTarget] = useState<AgentView | null>(null);

	const candidates = useMemo(
		() =>
			agents
				.filter(
					(candidate) =>
						candidate.id !== agent?.id &&
						candidate.data.invite_config.invitable &&
						(candidate.data.invite_config.invite_description ?? '').trim().length > 0,
				)
				.sort((left, right) => left.data.name.localeCompare(right.data.name)),
		[agents, agent?.id],
	);

	useEffect(() => {
		setDraft(cloneConfig(agent?.data.call_config));
		setErrorMsg('');
	}, [agent]);

	const persisted = useMemo(
		() => cloneConfig(agent?.data.call_config),
		[agent?.data.call_config],
	);
	const isDirty = !configsEqual(draft, persisted);
	const selectedIds = useMemo(() => new Set(draft.allowed_agent_ids), [draft.allowed_agent_ids]);
	const selectedCandidateCount = candidates.filter((candidate) =>
		selectedIds.has(candidate.id),
	).length;

	const handleChange = (key: keyof AgentCallConfig, value: AgentCallScope | string[]) => {
		setErrorMsg('');
		setDraft((current) => ({ ...current, [key]: value }));
	};

	const toggleAgent = (agentId: string, checked: boolean) => {
		if (!agent?.editable || submitting) return;
		const next = checked
			? [...draft.allowed_agent_ids, agentId]
			: draft.allowed_agent_ids.filter((id) => id !== agentId);
		handleChange('allowed_agent_ids', [...new Set(next)]);
	};

	const resetDraft = () => {
		setDraft(cloneConfig(agent?.data.call_config));
		setErrorMsg('');
	};

	const handleSave = async () => {
		if (!agent || !agent.editable || !isDirty) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSave(agent.id, draft);
			toast.success(t('panel.collaboration.saved'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSubmitting(false);
		}
	};

	if (loading && !agent) {
		return (
			<div className="flex flex-1 items-center justify-center">
				<p className="text-muted-foreground text-sm">{t('panel.loading')}</p>
			</div>
		);
	}

	if (!agent) {
		return (
			<PanelEmpty
				icon={Users}
				title={t('panel.collaboration.emptyTitle')}
				description={t('panel.collaboration.emptyDescription')}
			/>
		);
	}

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex-none space-y-3 pb-3">
				<div
					role="radiogroup"
					aria-label={t('panel.collaboration.scopeLabel')}
					className="bg-muted grid h-9 grid-cols-3 rounded-lg p-[3px]"
				>
					{(['all', 'selected', 'none'] as AgentCallScope[]).map((scope) => (
						<Button
							key={scope}
							type="button"
							role="radio"
							aria-checked={draft.scope === scope}
							variant="ghost"
							size="sm"
							disabled={!agent.editable || submitting}
							className={
								draft.scope === scope
									? 'bg-background text-foreground shadow-sm hover:bg-background'
									: 'text-muted-foreground'
							}
							onClick={() => handleChange('scope', scope)}
						>
							{t(`panel.collaboration.scope.${scope}`)}
						</Button>
					))}
				</div>
			</div>

			<div className="flex min-h-0 flex-1 flex-col">
				{draft.scope === 'selected' ? (
					<>
						<div className="flex items-center justify-between pb-2">
							<div className="flex items-baseline gap-1.5">
								<span className="text-sm font-medium">
									{t('panel.collaboration.candidatesTitle')}
								</span>
								<span className="text-muted-foreground text-xs tabular-nums">
									{t('panel.collaboration.selectedSummary', {
										selected: selectedCandidateCount,
										total: candidates.length,
									})}
								</span>
							</div>
							<div className="flex items-center gap-0.5">
								<Button
									variant="ghost"
									size="xs"
									disabled={
										!agent.editable ||
										submitting ||
										selectedCandidateCount === candidates.length
									}
									onClick={() =>
										handleChange(
											'allowed_agent_ids',
											candidates.map((candidate) => candidate.id),
										)
									}
								>
									{t('panel.collaboration.selectAll')}
								</Button>
								<Button
									variant="ghost"
									size="xs"
									disabled={
										!agent.editable ||
										submitting ||
										draft.allowed_agent_ids.length === 0
									}
									onClick={() => handleChange('allowed_agent_ids', [])}
								>
									{t('panel.collaboration.clear')}
								</Button>
							</div>
						</div>

						{candidates.length === 0 ? (
							<PanelEmpty
								icon={Users}
								title={t('panel.collaboration.noCandidatesTitle')}
								description={t('panel.collaboration.noCandidatesDescription')}
							/>
						) : (
							<div className="bg-background min-h-0 flex-1 overflow-hidden rounded-lg border">
								<div className="divide-border h-full overflow-y-auto divide-y">
									{candidates.map((candidate) => {
										const checked = selectedIds.has(candidate.id);
										return (
											<PanelCatalogRow
												key={candidate.id}
												title={candidate.data.name}
												description={candidate.data.invite_config.invite_description}
												selected={checked}
												checkbox={{
													checked,
													disabled: !agent.editable || submitting,
													ariaLabel: t('panel.collaboration.toggleAssignment', { name: candidate.data.name }),
													onChange: (value) => toggleAgent(candidate.id, value),
												}}
												onOpen={() => setDetailTarget(candidate)}
												openLabel={t('panel.collaboration.viewDetails', { name: candidate.data.name })}
											/>
										);
									})}
								</div>
							</div>
						)}
					</>
				) : (
					<div className="bg-muted/30 flex items-start gap-3 rounded-lg px-3 py-3.5">
						<div className="bg-background flex size-8 shrink-0 items-center justify-center rounded-md border">
							{draft.scope === 'all' ? (
								<Users className="size-4" />
							) : (
								<Ban className="size-4" />
							)}
						</div>
						<div className="min-w-0">
							<p className="text-sm font-medium">
								{t(
									draft.scope === 'all'
										? 'panel.collaboration.allTitle'
										: 'panel.collaboration.noneTitle',
								)}
							</p>
							<p className="text-muted-foreground mt-1 text-xs leading-relaxed">
								{t(
									draft.scope === 'all'
										? 'panel.collaboration.allDescription'
										: 'panel.collaboration.noneDescription',
								)}
							</p>
						</div>
					</div>
				)}
			</div>

			<div className="flex-none space-y-2 pt-3">
				{!agent.editable && (
					<Alert>
						<CircleAlert />
						<AlertDescription>{t('panel.collaboration.readOnly')}</AlertDescription>
					</Alert>
				)}

				{errorMsg && (
					<Alert variant="destructive">
						<CircleAlert />
						<AlertDescription className="whitespace-pre-wrap">
							{errorMsg}
						</AlertDescription>
					</Alert>
				)}

				<div className="border-border flex items-center justify-between border-t pt-3">
					<Button
						variant="ghost"
						size="sm"
						onClick={resetDraft}
						disabled={!isDirty || submitting}
					>
						<RotateCcw />
						{t('panel.collaboration.discard')}
					</Button>
					<Button
						size="sm"
						onClick={handleSave}
						disabled={!agent.editable || !isDirty || submitting}
					>
						{submitting ? <Loader2 className="animate-spin" /> : <Save />}
						{submitting ? t('common.saving') : t('panel.collaboration.saveChanges')}
					</Button>
				</div>
			</div>

			<PanelSummaryDialog
				open={detailTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDetailTarget(null);
				}}
				title={detailTarget?.data.name ?? ''}
				identifier={detailTarget?.id}
				description={detailTarget?.data.invite_config.invite_description}
			/>
		</div>
	);
}
