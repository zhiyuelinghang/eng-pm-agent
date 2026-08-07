import { Check, CircleAlert, Database, Loader2, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import type {
	DatabaseTableColumn,
	DatabaseTableInfo,
	DatabaseTablePolicy,
} from '@/api';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	policies: DatabaseTablePolicy[];
	tables: DatabaseTableInfo[];
	loadTables: () => Promise<DatabaseTableInfo[]>;
}

interface PolicyColumnView extends Pick<DatabaseTableColumn, 'name' | 'type'> {
	readable: boolean;
	writable: boolean;
	filterable: boolean;
}

function policyColumns(
	policy: DatabaseTablePolicy,
	table: DatabaseTableInfo | null,
): PolicyColumnView[] {
	const readable = new Set(policy.readable_fields);
	const writable = new Set(policy.writable_fields);
	const filterable = new Set(policy.filterable_fields);
	const configured = new Set([...readable, ...writable, ...filterable]);
	const source = table?.columns.length
		? table.columns
		: [...configured].sort().map((name) => ({ name, type: '—' }));
	return source.map((column) => ({
		name: column.name,
		type: column.type,
		readable: readable.has(column.name),
		writable: writable.has(column.name),
		filterable: filterable.has(column.name),
	}));
}

function PermissionMark({ allowed }: { allowed: boolean }) {
	return allowed ? (
		<Check className="mx-auto size-4 text-foreground" aria-label="允许" />
	) : (
		<span className="block text-center text-muted-foreground" aria-label="不允许">—</span>
	);
}

export function DatabasePolicyDialog({
	open,
	onOpenChange,
	policies,
	tables,
	loadTables,
}: Props) {
	const { t } = useTranslation();
	const [selectedId, setSelectedId] = useState<number | null>(null);
	const [loadingTables, setLoadingTables] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');

	useEffect(() => {
		if (!open) return;
		if (!policies.some((policy) => policy.id === selectedId)) {
			setSelectedId(policies[0]?.id ?? null);
		}
	}, [open, policies, selectedId]);

	useEffect(() => {
		if (!open || !policies.length) return;
		setLoadingTables(true);
		setErrorMsg('');
		void loadTables()
			.catch((error) => setErrorMsg(formatApiErrorForAlert(error)))
			.finally(() => setLoadingTables(false));
	}, [loadTables, open, policies.length]);

	const selectedPolicy = useMemo(
		() => policies.find((policy) => policy.id === selectedId) ?? null,
		[policies, selectedId],
	);
	const selectedTable = useMemo(
		() => tables.find((table) => table.name === selectedPolicy?.table_name) ?? null,
		[tables, selectedPolicy?.table_name],
	);
	const columns = useMemo(
		() => selectedPolicy ? policyColumns(selectedPolicy, selectedTable) : [],
		[selectedPolicy, selectedTable],
	);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="flex h-[min(760px,calc(100dvh-2rem))] flex-col sm:max-w-5xl">
				<DialogHeader>
					<div className="flex items-center gap-2">
						<DialogTitle>{t('panel.database.policy.title')}</DialogTitle>
						<Badge variant="outline" className="gap-1">
							<ShieldCheck className="size-3.5" />
							{t('panel.database.policy.platformManaged')}
						</Badge>
					</div>
					<DialogDescription>{t('panel.database.policy.description')}</DialogDescription>
				</DialogHeader>

				<div className="grid min-h-0 flex-1 overflow-hidden rounded-lg border md:grid-cols-[14rem_minmax(0,1fr)]">
					<aside className="flex min-h-0 flex-col border-b bg-muted/20 md:border-r md:border-b-0">
						<div className="border-b px-3 py-2.5 text-sm font-medium">
							{t('panel.database.policy.directory')}
						</div>
						<div className="min-h-0 flex-1 overflow-y-auto p-2">
							{policies.length ? policies.map((policy) => (
								<button
									type="button"
									key={policy.id}
									onClick={() => setSelectedId(policy.id)}
									data-active={selectedId === policy.id || undefined}
									className="mb-1 w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-muted data-[active=true]:bg-accent data-[active=true]:text-accent-foreground"
								>
									<span className="block truncate text-sm font-medium">{policy.display_name}</span>
									<code className="block truncate text-xs text-muted-foreground">{policy.table_name}</code>
								</button>
							)) : (
								<div className="flex h-full min-h-40 flex-col items-center justify-center px-3 text-center">
									<Database className="mb-2 size-7 text-muted-foreground" />
									<p className="text-sm font-medium">{t('panel.database.policy.emptyTitle')}</p>
									<p className="mt-1 text-sm text-muted-foreground">{t('panel.database.policy.emptyDescription')}</p>
								</div>
							)}
						</div>
					</aside>

					<section className="min-h-0 overflow-y-auto p-4">
						{!selectedPolicy ? (
							<div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground">
								<Database className="mb-3 size-8" />
								<p className="text-sm">{t('panel.database.policy.emptyDescription')}</p>
							</div>
						) : (
							<div className="space-y-5">
								<div className="flex items-start justify-between gap-3">
									<div className="min-w-0">
										<h3 className="text-base font-semibold">{selectedPolicy.display_name}</h3>
										<code className="mt-1 block text-xs text-muted-foreground">{selectedPolicy.table_name}</code>
									</div>
									<Badge variant={selectedPolicy.enabled ? 'secondary' : 'outline'}>
										{selectedPolicy.enabled ? t('panel.database.policy.enabled') : t('panel.database.disabled')}
									</Badge>
								</div>

								<p className="text-sm leading-6 text-muted-foreground">
									{selectedPolicy.description || t('panel.database.noDescription')}
								</p>

								<div className="grid gap-3 sm:grid-cols-3">
									<div className="rounded-lg border p-3">
										<div className="text-xs text-muted-foreground">{t('panel.database.policy.scope')}</div>
										<div className="mt-1 text-sm font-medium">{t(`panel.database.scopes.${selectedPolicy.scope_type}`)}</div>
									</div>
									<div className="rounded-lg border p-3">
										<div className="text-xs text-muted-foreground">{t('panel.database.policy.scopeField')}</div>
										<code className="mt-1 block text-sm font-medium">{selectedPolicy.scope_field ?? t('panel.database.policy.noScopeField')}</code>
									</div>
									<div className="rounded-lg border p-3">
										<div className="text-xs text-muted-foreground">{t('panel.database.policy.minimumRole')}</div>
										<div className="mt-1 text-sm font-medium">{t(`panel.database.roles.${selectedPolicy.minimum_role}`)}</div>
									</div>
								</div>

								<div>
									<h3 className="mb-2 text-sm font-medium">{t('panel.database.policy.operations')}</h3>
									<div className="flex flex-wrap gap-2">
										{selectedPolicy.allowed_operations.map((operation) => (
											<Badge key={operation} variant="secondary">{t(`panel.database.operations.${operation}`)}</Badge>
										))}
									</div>
								</div>

								<div>
									<div className="mb-2 flex items-center justify-between gap-3">
										<h3 className="text-sm font-medium">{t('panel.database.policy.fields')}</h3>
										{loadingTables ? <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />{t('panel.database.policy.loadingTables')}</span> : null}
									</div>
									<div className="overflow-hidden rounded-lg border">
										<div className="grid grid-cols-[minmax(0,1fr)_4rem_4rem_4rem] border-b bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground">
											<span>{t('panel.database.policy.fieldName')}</span>
											<span className="text-center">{t('panel.database.policy.readable')}</span>
											<span className="text-center">{t('panel.database.policy.writable')}</span>
											<span className="text-center">{t('panel.database.policy.filterable')}</span>
										</div>
										<div className="max-h-72 divide-y overflow-y-auto">
											{columns.map((column) => (
												<div key={column.name} className="grid grid-cols-[minmax(0,1fr)_4rem_4rem_4rem] items-center px-3 py-2.5 text-sm">
													<div className="min-w-0">
														<code className="block truncate text-xs">{column.name}</code>
														<span className="block truncate text-xs text-muted-foreground">{column.type}</span>
													</div>
													<PermissionMark allowed={column.readable} />
													<PermissionMark allowed={column.writable} />
													<PermissionMark allowed={column.filterable} />
												</div>
											))}
										</div>
									</div>
								</div>

								{errorMsg ? <Alert variant="destructive"><CircleAlert /><AlertDescription className="whitespace-pre-wrap">{errorMsg}</AlertDescription></Alert> : null}
							</div>
						)}
					</section>
				</div>

				<DialogFooter>
					<Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.close')}</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
