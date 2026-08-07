import {
	CircleAlert,
	Database,
	Loader2,
	Plus,
	RotateCcw,
	Save,
	Search,
	SearchX,
	ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type {
	AgentView,
	DatabaseInteraction,
	DatabaseTableInteractionRequest,
} from '@/api';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import {
	DatabaseInteractionDialog,
	type DatabaseInteractionDialogMode,
} from '@/components/panel/DatabaseInteractionDialog';
import { DatabasePolicyDialog } from '@/components/panel/DatabasePolicyDialog';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useDatabaseInteractions } from '@/hooks/useDatabaseInteractions';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface Props {
	agent: AgentView | null;
}

function sameIds(left: number[], right: number[]): boolean {
	if (left.length !== right.length) return false;
	const rightSet = new Set(right);
	return left.every((id) => rightSet.has(id));
}

export function DatabaseInteractionPanel({ agent }: Props) {
	const { t } = useTranslation();
	const {
		interactions,
		policies,
		tables,
		loading,
		catalogError,
		refetch,
		loadTables,
		assign,
		createInteraction,
		updateTableInteraction,
		removeInteraction,
	} = useDatabaseInteractions(agent?.id ?? null);
	const [search, setSearch] = useState('');
	const [draftIds, setDraftIds] = useState<number[]>([]);
	const [savingAssignments, setSavingAssignments] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');
	const [dialogOpen, setDialogOpen] = useState(false);
	const [dialogMode, setDialogMode] = useState<DatabaseInteractionDialogMode>('view');
	const [activeInteraction, setActiveInteraction] = useState<DatabaseInteraction | null>(null);
	const [policyOpen, setPolicyOpen] = useState(false);
	const [deleteTarget, setDeleteTarget] = useState<DatabaseInteraction | null>(null);

	const persistedIds = useMemo(
		() => interactions.filter((item) => item.assigned).map((item) => item.id),
		[interactions],
	);
	useEffect(() => {
		setDraftIds(persistedIds);
		setErrorMsg('');
	}, [persistedIds]);

	const selectedSet = useMemo(() => new Set(draftIds), [draftIds]);
	const isDirty = !sameIds(draftIds, persistedIds);
	const query = search.trim().toLowerCase();
	const filtered = interactions.filter((item) => {
		if (!query) return true;
		return (
			item.display_name.toLowerCase().includes(query) ||
			item.key.toLowerCase().includes(query) ||
			item.description.toLowerCase().includes(query) ||
			(item.policy?.display_name.toLowerCase().includes(query) ?? false)
		);
	});

	const toggleAssignment = (id: number, checked: boolean) => {
		if (!agent?.editable || savingAssignments) return;
		setDraftIds((current) =>
			checked ? [...new Set([...current, id])] : current.filter((item) => item !== id),
		);
	};

	const saveAssignments = async () => {
		if (!agent?.editable || !isDirty) return;
		setSavingAssignments(true);
		setErrorMsg('');
		try {
			await assign(draftIds);
			toast.success(t('panel.database.saved'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSavingAssignments(false);
		}
	};

	const openCreate = () => {
		setActiveInteraction(null);
		setDialogMode('create');
		setDialogOpen(true);
	};
	const openDetail = (item: DatabaseInteraction) => {
		setActiveInteraction(item);
		setDialogMode('view');
		setDialogOpen(true);
	};

	if (loading && !agent) {
		return <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">{t('panel.loading')}</div>;
	}
	if (!agent) {
		return <PanelEmpty icon={Database} title={t('panel.database.noAgentTitle')} description={t('panel.database.noAgentDescription')} />;
	}

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex-none space-y-3 pb-3">
				<div className="flex items-center justify-between gap-2">
					<div className="min-w-0">
						<div className="flex items-baseline gap-1.5">
							<span className="text-sm font-medium">{t('panel.database.catalogTitle')}</span>
							<span className="text-xs tabular-nums text-muted-foreground">
								{t('panel.database.selectedSummary', { selected: draftIds.length, total: interactions.length })}
							</span>
						</div>
					</div>
					<div className="flex shrink-0 gap-1">
						<Button variant="outline" size="xs" onClick={() => setPolicyOpen(true)}>
							<ShieldCheck />
							{t('panel.database.managePolicies')}
						</Button>
						{agent.editable ? (
							<Button size="xs" onClick={openCreate} disabled={!policies.length}>
								<Plus />
								{t('panel.database.create')}
							</Button>
						) : null}
					</div>
				</div>
				<InputGroup>
					<InputGroupInput placeholder={t('panel.database.searchPlaceholder')} value={search} onChange={(event) => setSearch(event.target.value)} />
					<InputGroupAddon align="inline-end"><Search /></InputGroupAddon>
				</InputGroup>
			</div>

			{catalogError ? (
				<Alert variant="destructive" className="mb-3 flex-none items-center">
					<CircleAlert />
					<AlertDescription className="flex min-w-0 items-center justify-between gap-2">
						<span className="min-w-0">{formatApiErrorForAlert(catalogError)}</span>
						<Button
							type="button"
							variant="outline"
							size="xs"
							className="shrink-0"
							onClick={() => void refetch()}
						>
							<RotateCcw />
							{t('error.retry')}
						</Button>
					</AlertDescription>
				</Alert>
			) : null}

			<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border">
				{loading ? (
					<div className="flex h-full items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 size-4 animate-spin" />{t('panel.loading')}</div>
				) : filtered.length === 0 ? (
					<PanelEmpty
						icon={search ? SearchX : Database}
						title={search ? t('panel.search.emptyTitle') : t('panel.database.emptyTitle')}
						description={search ? t('panel.search.emptyDescription', { query: search }) : t('panel.database.emptyDescription')}
					/>
				) : (
					<div className="divide-y">
						{filtered.map((item) => {
							const checked = selectedSet.has(item.id);
							return (
								<PanelCatalogRow
									key={item.id}
									title={item.display_name}
									description={item.description}
									metadata={
										<>{item.policy?.display_name} · {item.read_only ? t('panel.database.readOnly') : t('panel.database.write')}</>
									}
									badge={!item.enabled ? <Badge variant="outline">{t('panel.database.disabled')}</Badge> : null}
									selected={checked}
									muted={!item.enabled}
									checkbox={{
										checked,
										disabled: !agent.editable || savingAssignments || !item.enabled,
										ariaLabel: t('panel.database.toggleAssignment', { name: item.display_name }),
										onChange: (value) => toggleAssignment(item.id, value),
									}}
									onOpen={() => openDetail(item)}
									openLabel={t('panel.database.viewDetails', { name: item.display_name })}
								/>
							);
						})}
					</div>
				)}
			</div>

			<div className="flex-none space-y-2 pt-3">
				{!agent.editable ? <Alert><CircleAlert /><AlertDescription>{t('panel.database.readOnlyNotice')}</AlertDescription></Alert> : null}
				{errorMsg ? <Alert variant="destructive"><CircleAlert /><AlertDescription className="whitespace-pre-wrap">{errorMsg}</AlertDescription></Alert> : null}
				<div className="flex items-center justify-between border-t pt-3">
					<Button variant="ghost" size="sm" onClick={() => setDraftIds(persistedIds)} disabled={!isDirty || savingAssignments}><RotateCcw />{t('panel.database.discard')}</Button>
					<Button size="sm" onClick={() => void saveAssignments()} disabled={!agent.editable || !isDirty || savingAssignments}>{savingAssignments ? <Loader2 className="animate-spin" /> : <Save />}{t('panel.database.saveChanges')}</Button>
				</div>
			</div>

			<DatabaseInteractionDialog
				open={dialogOpen}
				onOpenChange={setDialogOpen}
				mode={dialogMode}
				onModeChange={setDialogMode}
				interaction={activeInteraction}
				policies={policies}
				tables={tables}
				loadTables={loadTables}
				editable={agent.editable}
				onSaveTable={async (id: number | null, payload: DatabaseTableInteractionRequest) => { if (id === null) await createInteraction(payload); else await updateTableInteraction(id, payload); }}
				onRequestDelete={(item) => { setDialogOpen(false); setDeleteTarget(item); }}
			/>

			<DatabasePolicyDialog open={policyOpen} onOpenChange={setPolicyOpen} policies={policies} tables={tables} loadTables={loadTables} />

			<DeleteDialog open={deleteTarget !== null} onOpenChange={(value) => { if (!value) setDeleteTarget(null); }} title={t('panel.database.deleteTitle')} description={t('panel.database.deleteDescription')} onConfirm={async () => { if (!deleteTarget) return; await removeInteraction(deleteTarget.id); setDeleteTarget(null); }} />
		</div>
	);
}
