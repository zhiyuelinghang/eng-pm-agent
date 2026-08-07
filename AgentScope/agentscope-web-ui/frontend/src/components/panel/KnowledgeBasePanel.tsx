import { FileX, Search, SearchX } from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';

import type { KnowledgeBaseView, SessionKnowledgeConfig } from '@/api';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { PanelSummaryDialog } from '@/components/panel/PanelSummaryDialog';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n';

interface KnowledgeBasePanelProps {
	/** The user's knowledge bases. */
	knowledgeBases: KnowledgeBaseView[];
	/** Whether the KB list is still loading. */
	loading?: boolean;
	/**
	 * Current attachment for this session. `null` means no KBs attached
	 * and the panel renders with an empty selection.
	 */
	value: SessionKnowledgeConfig | null;
	/**
	 * Persist a new attachment to the session. The owner is responsible
	 * for awaiting the backend round-trip and refreshing session state.
	 * Pass `null` to detach every KB.
	 */
	onChange: (next: SessionKnowledgeConfig | null) => void;
	/** Disable the entire panel — e.g. when no session is selected. */
	disabled?: boolean;
	/** Knowledge-specific controls rendered beside the search field. */
	actions?: ReactNode;
}

/**
 * Pure content body for the Knowledge Base dock panel: a search box and
 * a checkbox list of the user's KBs.
 *
 * Middleware parameter editing is supplied through the compact `actions`
 * slot beside the search field, keeping controls on one row above the list.
 */
export function KnowledgeBasePanel({
	knowledgeBases,
	loading = false,
	value,
	onChange,
	disabled = false,
	actions,
}: KnowledgeBasePanelProps) {
	const { t } = useTranslation();
	const [search, setSearch] = useState('');
	const [detailTarget, setDetailTarget] = useState<KnowledgeBaseView | null>(null);

	const selectedIds = useMemo(() => new Set(value?.knowledge_base_ids ?? []), [value]);

	const filtered = search
		? knowledgeBases.filter((kb) =>
				`${kb.name} ${kb.description}`.toLowerCase().includes(search.toLowerCase()),
			)
		: knowledgeBases;

	const toggleKb = (kbId: string, checked: boolean) => {
		const next = new Set(selectedIds);
		if (checked) next.add(kbId);
		else next.delete(kbId);
		const ids = Array.from(next);
		if (ids.length === 0) {
			onChange(null);
			return;
		}
		onChange({
			knowledge_base_ids: ids,
			parameters: value?.parameters ?? {},
		});
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex-none space-y-3 pb-3">
				<div className="flex items-center justify-between gap-3">
					<div className="flex min-w-0 items-baseline gap-1.5">
						<span className="truncate text-sm font-medium">
							{t('panel.knowledge.catalogTitle')}
						</span>
						<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
							{t('panel.knowledge.selectedSummary', {
								selected: selectedIds.size,
								total: knowledgeBases.length,
							})}
						</span>
					</div>
					{actions ? <div className="shrink-0">{actions}</div> : null}
				</div>
				<InputGroup>
					<InputGroupInput
						placeholder={t('panel.knowledge.searchPlaceholder')}
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						disabled={disabled}
					/>
					<InputGroupAddon align="inline-end">
						<Search />
					</InputGroupAddon>
				</InputGroup>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-background">
				{loading ? (
					<div className="flex flex-1 items-center justify-center">
						<p className="text-muted-foreground text-sm">{t('panel.loading')}</p>
					</div>
				) : filtered.length === 0 ? (
					<PanelEmpty
						icon={search ? SearchX : FileX}
						title={
							search ? t('panel.search.emptyTitle') : t('panel.knowledge.emptyTitle')
						}
						description={
							search
								? t('panel.search.emptyDescription', { query: search })
								: t('panel.knowledge.emptyDescription')
						}
					/>
				) : (
					<div className="divide-y">
						{filtered.map((kb) => {
							const isSelected = selectedIds.has(kb.id);
							return (
								<PanelCatalogRow
									key={kb.id}
									title={kb.name}
									description={kb.description}
									metadata={<>{kb.embedding_model_config.model} · {kb.embedding_model_config.dimensions}d</>}
									selected={isSelected}
									checkbox={{
										checked: isSelected,
										disabled,
										ariaLabel: kb.name,
										onChange: (checked) => toggleKb(kb.id, checked),
									}}
									onOpen={() => setDetailTarget(kb)}
									openLabel={t('panel.knowledge.viewDetails', { name: kb.name })}
								/>
							);
						})}
					</div>
				)}
			</div>

			<PanelSummaryDialog
				open={detailTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDetailTarget(null);
				}}
				title={detailTarget?.name ?? ''}
				identifier={detailTarget?.id}
				description={detailTarget?.description}
			>
				{detailTarget ? (
					<p className="text-sm text-muted-foreground">
						{detailTarget.embedding_model_config.model} ·{' '}
						{detailTarget.embedding_model_config.dimensions}d
					</p>
				) : null}
			</PanelSummaryDialog>
		</div>
	);
}
