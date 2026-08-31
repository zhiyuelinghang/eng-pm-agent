import {
	CircleAlert,
	FileX,
	Loader2,
	PlusCircle,
	RotateCcw,
	Save,
	Search,
	SearchX,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type {
	AgentSkillConfig,
	AgentView,
	ManagedSkillInput,
	ManagedSkillPackage,
	ManagedSkillVersion,
} from '@/api';
import { CreateSkillDialog } from '@/components/dialog/CreateSkillDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditSkillDialog } from '@/components/dialog/EditSkillDialog';
import { SkillDetailDialog } from '@/components/dialog/SkillDetailDialog';
import { SkillVersionsDialog } from '@/components/dialog/SkillVersionsDialog';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface SkillPanelProps {
	agent: AgentView | null;
	packages: ManagedSkillPackage[];
	loading?: boolean;
	loadError?: Error | null;
	onCreate: (input: ManagedSkillInput) => Promise<void>;
	onUpdate: (packageId: string, input: ManagedSkillInput) => Promise<void>;
	onRemove: (packageId: string) => Promise<void>;
	onListVersions: (packageId: string) => Promise<ManagedSkillVersion[]>;
	onDownloadVersion: (packageId: string, version: number) => Promise<void>;
	onSave: (agentId: string, config: AgentSkillConfig) => Promise<void>;
}

function assignedIds(agent: AgentView | null): string[] {
	return [...(agent?.data.skill_config?.allowed_skill_ids ?? [])];
}

function sameIds(left: string[], right: string[]): boolean {
	if (left.length !== right.length) return false;
	const rightSet = new Set(right);
	return left.every((id) => rightSet.has(id));
}

/** Platform skill catalogue, package maintenance, and agent assignment. */
export function SkillPanel({
	agent,
	packages,
	loading = false,
	loadError = null,
	onCreate,
	onUpdate,
	onRemove,
	onListVersions,
	onDownloadVersion,
	onSave,
}: SkillPanelProps) {
	const { t } = useTranslation();
	const [search, setSearch] = useState('');
	const [draftIds, setDraftIds] = useState<string[]>(() => assignedIds(agent));
	const [createOpen, setCreateOpen] = useState(false);
	const [detailTarget, setDetailTarget] = useState<ManagedSkillPackage | null>(null);
	const [editTarget, setEditTarget] = useState<ManagedSkillPackage | null>(null);
	const [deleteTarget, setDeleteTarget] = useState<ManagedSkillPackage | null>(null);
	const [versionTarget, setVersionTarget] = useState<ManagedSkillPackage | null>(null);
	const [submitting, setSubmitting] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');

	useEffect(() => {
		setDraftIds(assignedIds(agent));
		setErrorMsg('');
	}, [agent]);

	useEffect(() => {
		if (loading) return;
		const available = new Set(packages.map((item) => item.id));
		setDraftIds((current) => current.filter((id) => available.has(id)));
	}, [loading, packages]);

	const persistedIds = useMemo(() => {
		if (loading) return assignedIds(agent);
		const available = new Set(packages.map((item) => item.id));
		return assignedIds(agent).filter((id) => available.has(id));
	}, [agent, loading, packages]);
	const selectedSet = useMemo(() => new Set(draftIds), [draftIds]);
	const isDirty = !sameIds(draftIds, persistedIds);
	const query = search.trim().toLowerCase();
	const filtered = query
		? packages.filter((item) =>
				[item.name, item.description, `v${item.version}`]
					.join(' ')
					.toLowerCase()
					.includes(query),
			)
		: packages;

	const togglePackage = (packageId: string, checked: boolean) => {
		if (!agent?.editable || submitting) return;
		setErrorMsg('');
		setDraftIds((current) =>
			checked
				? [...new Set([...current, packageId])]
				: current.filter((id) => id !== packageId),
		);
	};

	const handleSave = async () => {
		if (!agent?.editable || !isDirty) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSave(agent.id, { allowed_skill_ids: draftIds });
			toast.success(t('panel.skill.saved'));
		} catch (reason) {
			setErrorMsg(formatApiErrorForAlert(reason));
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex-none space-y-3 pb-3">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div className="flex min-w-0 items-baseline gap-1.5">
						<span className="truncate text-sm font-medium">
							{t('panel.skill.catalogTitle')}
						</span>
						<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
							{t('panel.skill.countSummary', { count: packages.length })}
						</span>
					</div>
					<div className="flex items-center gap-2">
						<Button size="xs" variant="outline" onClick={() => setCreateOpen(true)}>
							<PlusCircle />
							{t('panel.skill.create')}
						</Button>
					</div>
				</div>
				<InputGroup>
					<InputGroupInput
						placeholder={t('panel.skill.searchPlaceholder')}
						value={search}
						onChange={(event) => setSearch(event.target.value)}
					/>
					<InputGroupAddon align="inline-end">
						<Search />
					</InputGroupAddon>
				</InputGroup>
				{loadError || errorMsg ? (
					<Alert variant="destructive">
						<CircleAlert />
						<AlertDescription>
							{errorMsg || formatApiErrorForAlert(loadError)}
						</AlertDescription>
					</Alert>
				) : null}
			</div>

			{loading ? (
				<div className="flex flex-1 items-center justify-center">
					<Loader2 className="size-5 animate-spin text-muted-foreground" />
				</div>
			) : filtered.length === 0 ? (
				<PanelEmpty
					icon={search ? SearchX : FileX}
					title={search ? t('panel.search.emptyTitle') : t('panel.skill.emptyTitle')}
					description={
						search
							? t('panel.search.emptyDescription', { query: search })
							: t('panel.skill.emptyDescription')
					}
				/>
			) : (
				<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-background">
					<div className="divide-y">
						{filtered.map((item) => {
							const checked = selectedSet.has(item.id);
							return (
								<PanelCatalogRow
									key={item.id}
									title={item.name}
									description={item.description}
									metadata={
										<span>{new Date(item.updated_at).toLocaleString()}</span>
									}
									badge={<Badge variant="secondary">v{item.version}</Badge>}
									selected={checked}
									checkbox={{
										checked,
										disabled: !agent?.editable || submitting,
										ariaLabel: t('panel.skill.assignLabel', { name: item.name }),
										onChange: (value) => togglePackage(item.id, value),
									}}
									onOpen={() => setDetailTarget(item)}
									openLabel={t('panel.skill.viewDetails', { name: item.name })}
								/>
							);
						})}
					</div>
				</div>
			)}

			<div className="mt-3 flex min-h-9 flex-none items-center justify-between gap-3 border-t pt-3">
				<span className="text-xs text-muted-foreground">
					{t('panel.skill.selectedSummary', { count: draftIds.length })}
				</span>
				<div className="flex gap-2">
					<Button
						size="xs"
						variant="ghost"
						onClick={() => setDraftIds(persistedIds)}
						disabled={!isDirty || submitting}
					>
						<RotateCcw />
						{t('panel.skill.discard')}
					</Button>
					<Button size="xs" onClick={handleSave} disabled={!isDirty || submitting}>
						{submitting ? <Loader2 className="animate-spin" /> : <Save />}
						{t('panel.skill.saveChanges')}
					</Button>
				</div>
			</div>

			<CreateSkillDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={onCreate} />
			<SkillDetailDialog
				open={detailTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDetailTarget(null);
				}}
				skill={detailTarget}
				version={detailTarget?.version}
				onVersions={() => {
					setVersionTarget(detailTarget);
					setDetailTarget(null);
				}}
				onEdit={(skill) => {
					setDetailTarget(null);
					setEditTarget(packages.find((item) => item.name === skill.name) ?? null);
				}}
				onDelete={(skill) => {
					setDetailTarget(null);
					setDeleteTarget(packages.find((item) => item.name === skill.name) ?? null);
				}}
			/>
			<SkillVersionsDialog
				open={versionTarget !== null}
				onOpenChange={(open) => {
					if (!open) setVersionTarget(null);
				}}
				skill={versionTarget}
				onLoad={onListVersions}
				onDownload={onDownloadVersion}
			/>
			<EditSkillDialog
				open={editTarget !== null}
				onOpenChange={(open) => {
					if (!open) setEditTarget(null);
				}}
				skill={editTarget}
				onSave={async (_currentName, input) => {
					if (!editTarget) return;
					await onUpdate(editTarget.id, input);
					toast.success(t('panel.skill.updated'));
				}}
			/>
			<DeleteDialog
				open={deleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteTarget(null);
				}}
				title={t('panel.skill.deleteTitle', { name: deleteTarget?.name ?? '' })}
				description={t('panel.skill.deleteDescription')}
				onConfirm={async () => {
					if (!deleteTarget) return;
					await onRemove(deleteTarget.id);
					toast.success(t('panel.skill.deleted'));
				}}
			/>
		</div>
	);
}
