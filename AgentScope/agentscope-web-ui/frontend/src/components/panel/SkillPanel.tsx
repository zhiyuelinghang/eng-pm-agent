import { FileX, PlusCircle, Search, SearchX } from 'lucide-react';
import { useState } from 'react';

import type { Skill, UpdateSkillRequest } from '@/api';
import { AddSkillDialog } from '@/components/dialog/AddSkillDialog.tsx';
import { DeleteDialog } from '@/components/dialog/DeleteDialog.tsx';
import { EditSkillDialog } from '@/components/dialog/EditSkillDialog';
import { SkillDetailDialog } from '@/components/dialog/SkillDetailDialog';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n.ts';
import { getSkillDisplayName } from '@/lib/skill-display';

interface SkillPanelProps {
	/** The skills equipped in the workspace. */
	skills: Skill[];
	/** Whether the skill list is still loading. */
	loading?: boolean;
	/**
	 * Add a skill to the workspace.
	 *
	 * @param skillPath - Path of the skill to add.
	 */
	onAdd: (skillPath: string) => Promise<void>;
	/** Save editable SKILL.md fields. */
	onUpdate: (currentName: string, input: UpdateSkillRequest) => Promise<void>;
	/**
	 * Remove a skill by name.
	 *
	 * @param name - The skill name to remove.
	 */
	onRemove: (name: string) => Promise<void>;
}

/**
 * Pure content body for the Skill dock panel: a search box, the list
 * of equipped skills, and add/edit/remove actions. Holds only local UI
 * state (search text and dialog targets); all data arrives via props so
 * it owns no data fetching.
 *
 * @param skills - The skills to list.
 * @param loading - Whether the list is loading.
 * @param onAdd - Add-skill callback.
 * @param onUpdate - Update-skill callback.
 * @param onRemove - Remove-skill callback.
 * @returns The skill panel body.
 */
export function SkillPanel({
	skills,
	loading = false,
	onAdd,
	onUpdate,
	onRemove,
}: SkillPanelProps) {
	const { t } = useTranslation();
	const [search, setSearch] = useState('');
	const [deleteOpen, setDeleteOpen] = useState(false);
	const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
	const [detailTarget, setDetailTarget] = useState<Skill | null>(null);
	const [editTarget, setEditTarget] = useState<Skill | null>(null);

	const normalizedSearch = search.trim().toLowerCase();
	const filtered = normalizedSearch
		? skills.filter((skill) =>
				[getSkillDisplayName(skill), skill.name, skill.description].some((value) =>
					value.toLowerCase().includes(normalizedSearch),
				),
			)
		: skills;

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex-none space-y-3 pb-3">
				<div className="flex items-center justify-between gap-3">
					<div className="flex min-w-0 items-baseline gap-1.5">
						<span className="truncate text-sm font-medium">
							{t('panel.skill.catalogTitle')}
						</span>
						<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
							{t('panel.skill.countSummary', { count: skills.length })}
						</span>
					</div>
					<AddSkillDialog onAdd={onAdd}>
						<Button size="xs">
							<PlusCircle />
							{t('panel.skill.add')}
						</Button>
					</AddSkillDialog>
				</div>
			<InputGroup>
				<InputGroupInput
					placeholder={t('panel.skill.searchPlaceholder')}
					value={search}
					onChange={(e) => setSearch(e.target.value)}
				/>
				<InputGroupAddon align="inline-end">
					<Search />
				</InputGroupAddon>
			</InputGroup>
			</div>

			{loading ? (
				<div className="flex flex-1 items-center justify-center">
					<p className="text-muted-foreground text-sm">{t('panel.loading')}</p>
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
					{filtered.map((skill) => {
						const displayName = getSkillDisplayName(skill);
						return (
							<PanelCatalogRow
								key={skill.name}
								title={displayName}
								description={skill.description}
								onOpen={() => setDetailTarget(skill)}
								openLabel={t('panel.skill.viewDetails', { name: displayName })}
							/>
						);
					})}
					</div>
				</div>
			)}

			<SkillDetailDialog
				open={detailTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDetailTarget(null);
				}}
				skill={detailTarget}
				onEdit={(skill) => {
					setDetailTarget(null);
					setEditTarget(skill);
				}}
				onDelete={(skill) => {
					setDetailTarget(null);
					setDeleteTarget(skill.name);
					setDeleteOpen(true);
				}}
			/>

			<EditSkillDialog
				open={editTarget !== null}
				onOpenChange={(open) => {
					if (!open) setEditTarget(null);
				}}
				skill={editTarget}
				onSave={onUpdate}
			/>

			<DeleteDialog
				open={deleteOpen}
				onOpenChange={setDeleteOpen}
				title={t('common.deleteTitle', {
					entity: t('dialog-mcp-delete.skillEntity'),
					name: deleteTarget ?? '',
				})}
				description={t('dialog-mcp-delete.skillDescription')}
				onConfirm={async () => {
					if (deleteTarget) await onRemove(deleteTarget);
				}}
			/>
		</div>
	);
}
