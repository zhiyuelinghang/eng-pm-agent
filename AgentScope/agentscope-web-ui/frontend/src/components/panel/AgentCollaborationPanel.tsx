import { CircleAlert, Loader2, RotateCcw, Save, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type { AgentView, PlatformSettings } from '@/api';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { PanelSummaryDialog } from '@/components/panel/PanelSummaryDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { collaborationCandidates, collaborationSelection } from '@/lib/agent-collaboration';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface AgentCollaborationPanelProps {
	agent: AgentView | null;
	agents: AgentView[];
	mainDuty?: boolean;
	settings: PlatformSettings;
	loading?: boolean;
	onDirtyChange?: (dirty: boolean) => void;
	onSave: (agentId: string, selectedIds: string[]) => Promise<void>;
}

export function AgentCollaborationPanel({
	agent,
	agents,
	mainDuty = false,
	settings,
	loading = false,
	onDirtyChange,
	onSave,
}: AgentCollaborationPanelProps) {
	const { t, i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const isMain = mainDuty;
	const [selectedIds, setSelectedIds] = useState(() =>
		collaborationSelection(agent?.data.call_config),
	);
	const [submitting, setSubmitting] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');
	const [detailTarget, setDetailTarget] = useState<AgentView | null>(null);
	const candidates = useMemo(
		() => (agent ? collaborationCandidates(agent, agents, isMain, settings) : []),
		[agent, agents, isMain, settings],
	);
	const persisted = useMemo(
		() => collaborationSelection(agent?.data.call_config),
		[agent?.data.call_config],
	);
	const isDirty =
		!isMain &&
		(selectedIds.length !== persisted.length ||
			selectedIds.some((id) => !persisted.includes(id)));
	const selectedCount = candidates.filter((candidate) =>
		selectedIds.includes(candidate.id),
	).length;
	const reset = () => {
		setSelectedIds(collaborationSelection(agent?.data.call_config));
		setErrorMsg('');
	};
	useEffect(() => {
		setSelectedIds(collaborationSelection(agent?.data.call_config));
		setErrorMsg('');
		setDetailTarget(null);
	}, [agent]);
	useEffect(() => {
		onDirtyChange?.(isDirty);
	}, [isDirty, onDirtyChange]);
	const save = async () => {
		if (!agent?.editable || isMain || !isDirty) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSave(agent.id, selectedIds);
			toast.success(t('panel.collaboration.saved'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSubmitting(false);
		}
	};
	if (!agent)
		return (
			<PanelEmpty
				icon={Users}
				title={loading ? t('panel.loading') : t('panel.collaboration.emptyTitle')}
			/>
		);
	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="space-y-2 pb-4">
				<p className="text-sm font-medium">
					{isMain
						? zh
							? '总控可调用的智能体'
							: 'Agents available to the orchestrator'
						: zh
							? '选择协作智能体'
							: 'Select collaborators'}
				</p>
				<p className="text-sm leading-6 text-muted-foreground">
					{isMain
						? zh
							? '任务助手和知识库助手按固定职责供总控调用；其他智能体须开启“允许总控调用”。项目初始化仅用于初始化页面，不参与此处协作。'
							: 'Task and knowledge assistants are available by fixed duty. Other agents must allow orchestrator calls. Project initialization is restricted to its dedicated page.'
						: zh
							? '候选仅包含已启用且允许其他智能体邀请的智能体，总控和项目初始化不接受调用。勾选并保存后才可调用，未选择时独立工作。'
							: 'Candidates must be enabled and allow invitations from other agents. Select and save to authorize calls. With no selection, this agent works independently.'}
				</p>
			</div>
			<div className="flex items-center justify-between pb-2 text-xs text-muted-foreground">
				<span>
					{isMain
						? zh
							? '共 ' + candidates.length + ' 个'
							: candidates.length + ' agents'
						: t('panel.collaboration.selectedSummary', {
								selected: selectedCount,
								total: candidates.length,
							})}
				</span>
				{!isMain && (
					<Button
						variant="ghost"
						size="xs"
						disabled={!agent.editable || submitting || !selectedIds.length}
						onClick={() => setSelectedIds([])}
					>
						{t('panel.collaboration.clear')}
					</Button>
				)}
			</div>
			{candidates.length ? (
				<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-background">
					<div className="divide-y divide-border">
						{candidates.map((candidate) => (
							<PanelCatalogRow
								key={candidate.id}
								title={candidate.data.name}
								description={
									candidate.data.invite_config.invite_description ||
									candidate.data.platform_config.description
								}
								selected={!isMain && selectedIds.includes(candidate.id)}
								checkbox={
									isMain
										? undefined
										: {
												checked: selectedIds.includes(candidate.id),
												disabled: !agent.editable || submitting,
												ariaLabel: t(
													'panel.collaboration.toggleAssignment',
													{ name: candidate.data.name },
												),
												onChange: (checked) =>
													setSelectedIds((ids) =>
														checked
															? [...new Set([...ids, candidate.id])]
															: ids.filter(
																	(id) => id !== candidate.id,
																),
													),
											}
								}
								onOpen={() => setDetailTarget(candidate)}
							/>
						))}
					</div>
				</div>
			) : (
				<PanelEmpty
					icon={Users}
					title={
						isMain
							? zh
								? '暂无允许总控调用的已启用智能体'
								: 'No enabled agents allow orchestrator calls'
							: zh
								? '暂无已启用的协作智能体'
								: 'No enabled collaborators'
					}
				/>
			)}
			{errorMsg && (
				<Alert variant="destructive" className="mt-3">
					<CircleAlert />
					<AlertDescription>{errorMsg}</AlertDescription>
				</Alert>
			)}
			{!isMain && (
				<div className="mt-3 flex shrink-0 items-center justify-between border-t pt-3">
					<Button
						variant="ghost"
						size="sm"
						onClick={reset}
						disabled={!isDirty || submitting}
					>
						<RotateCcw />
						{t('panel.collaboration.discard')}
					</Button>
					<Button
						size="sm"
						onClick={save}
						disabled={!agent.editable || !isDirty || submitting}
					>
						{submitting ? <Loader2 className="animate-spin" /> : <Save />}
						{submitting ? t('common.saving') : t('panel.collaboration.saveChanges')}
					</Button>
				</div>
			)}
			<PanelSummaryDialog
				open={detailTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDetailTarget(null);
				}}
				title={detailTarget?.data.name ?? ''}
				identifier={detailTarget?.id}
				description={
					detailTarget?.data.invite_config.invite_description ||
					detailTarget?.data.platform_config.description
				}
			/>
		</div>
	);
}
