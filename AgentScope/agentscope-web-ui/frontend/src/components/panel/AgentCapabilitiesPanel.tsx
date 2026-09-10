import { BookText, Database, Paperclip, Users } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBeforeUnload, useBlocker } from 'react-router-dom';

import { agentApi, type AgentView, type PlatformSettings, type UpdateAgentRequest } from '@/api';
import { useUnsavedChanges } from '@/components/dialog/UnsavedChangesDialog';
import { AgentCollaborationPanel } from '@/components/panel/AgentCollaborationPanel';
import { DatabaseInteractionPanel } from '@/components/panel/DatabaseInteractionPanel';
import { McpPanel } from '@/components/panel/McpPanel';
import { SkillPanel } from '@/components/panel/SkillPanel';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
	DialogFooter,
} from '@/components/ui/dialog';
import { useMcpRegistry } from '@/hooks/useMcpRegistry';
import { useSkillRegistry } from '@/hooks/useSkillRegistry';
import { collaborationUpdate } from '@/lib/agent-collaboration';
import type { Duty } from '@/lib/agent-workbench';

export type CapabilityKey = 'collaboration' | 'skill' | 'mcp' | 'database';

export function AgentCapabilitiesPanel({
	agent,
	agents,
	primaryDuty,
	settings,
	initialTab = 'collaboration',
	onUpdated,
}: {
	agent: AgentView;
	agents: AgentView[];
	primaryDuty?: Duty;
	settings: PlatformSettings;
	initialTab?: CapabilityKey;
	onUpdated: () => Promise<void>;
}) {
	const { t, i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const [tab, setTab] = useState(initialTab);
	const [dirty, setDirty] = useState(false);
	const [busy, setBusy] = useState(false);
	const { leave, prompt } = useUnsavedChanges(dirty, busy);
	const blocker = useBlocker(
		({ currentLocation, nextLocation }) =>
			(dirty || busy) && currentLocation.pathname !== nextLocation.pathname,
	);
	useBeforeUnload(
		useCallback(
			(event) => {
				if (dirty || busy) {
					event.preventDefault();
					event.returnValue = '';
				}
			},
			[dirty, busy],
		),
	);
	const mcp = useMcpRegistry(tab === 'mcp' ? agent.id : null);
	const skill = useSkillRegistry(tab === 'skill' ? agent.id : null);
	const save = async (id: string, body: UpdateAgentRequest) => {
		setBusy(true);
		try {
			await agentApi.update(id, body, { silent: true });
			await onUpdated();
			setDirty(false);
		} finally {
			setBusy(false);
		}
	};
	const tabs = [
		{ key: 'collaboration' as const, label: t('panel.collaboration.title'), icon: Users },
		{ key: 'skill' as const, label: t('panel.skill.title'), icon: BookText },
		{ key: 'mcp' as const, label: 'MCP', icon: Paperclip },
		{ key: 'database' as const, label: t('panel.database.title'), icon: Database },
	];
	return (
		<>
			<section
				className="flex min-h-0 flex-1 flex-col"
				aria-label={zh ? '能力配置' : 'Capabilities'}
			>
				<nav
					aria-label={zh ? '能力分类' : 'Capability categories'}
					className="flex shrink-0 gap-1 overflow-x-auto border-b pt-2"
					role="tablist"
					onKeyDown={(event) => {
						if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
						const buttons = Array.from(
							event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
						);
						const index = buttons.indexOf(event.target as HTMLButtonElement);
						if (index < 0) return;
						event.preventDefault();
						const next =
							event.key === 'Home'
								? 0
								: event.key === 'End'
									? buttons.length - 1
									: (index +
											(event.key === 'ArrowRight' ? 1 : -1) +
											buttons.length) %
										buttons.length;
						buttons[next].focus();
						buttons[next].click();
					}}
				>
					{tabs.map(({ key, label, icon: Icon }) => (
						<button
							key={key}
							type="button"
							role="tab"
							tabIndex={tab === key ? 0 : -1}
							id={`capability-tab-${key}`}
							aria-selected={tab === key}
							aria-controls="capability-content"
							onClick={() =>
								tab !== key &&
								leave(() => {
									setDirty(false);
									setTab(key);
								})
							}
							className={`flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium ${tab === key ? 'border-[#c95622] text-[#c95622]' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
						>
							<Icon className="size-4" />
							{label}
						</button>
					))}
				</nav>
				<div
					id="capability-content"
					role="tabpanel"
					aria-labelledby={`capability-tab-${tab}`}
					className="flex min-h-0 flex-1 flex-col pt-5"
				>
					{tab === 'mcp' && (
						<McpPanel
							agent={agent}
							packages={mcp.packages}
							loading={mcp.loading}
							uploading={mcp.uploading}
							loadError={mcp.error}
							onUpload={mcp.uploadPackage}
							onRemove={mcp.removePackage}
							onSave={(id, config) => save(id, { mcp_config: config })}
							onDirtyChange={setDirty}
						/>
					)}
					{tab === 'skill' && (
						<SkillPanel
							agent={agent}
							packages={skill.packages}
							loading={skill.loading}
							loadError={skill.error}
							onCreate={skill.createPackage}
							onUpdate={skill.updatePackage}
							onRemove={skill.removePackage}
							onListVersions={skill.listVersions}
							onDownloadVersion={skill.downloadVersion}
							onSave={(id, config) => save(id, { skill_config: config })}
							onDirtyChange={setDirty}
						/>
					)}
					{tab === 'database' && (
						<DatabaseInteractionPanel
							agent={agent}
							onDirtyChange={setDirty}
							onBusyChange={setBusy}
						/>
					)}
					{tab === 'collaboration' && (
						<AgentCollaborationPanel
							settings={settings}
							agent={agent}
							agents={agents}
							mainDuty={primaryDuty?.key === 'main'}
							onSave={(id, selectedIds) => save(id, collaborationUpdate(selectedIds))}
							onDirtyChange={setDirty}
						/>
					)}
				</div>
			</section>
			{prompt}
			<Dialog
				open={blocker.state === 'blocked'}
				onOpenChange={(open) => {
					if (!open && blocker.state === 'blocked') blocker.reset();
				}}
			>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{zh ? '更改尚未保存' : 'Unsaved changes'}</DialogTitle>
						<DialogDescription>
							{busy
								? zh
									? '正在保存，请稍候。'
									: 'Saving. Please wait.'
								: zh
									? '离开页面会放弃当前未保存的能力配置。'
									: 'Leaving discards the unsaved capability settings.'}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							onClick={() => blocker.state === 'blocked' && blocker.reset()}
						>
							{zh ? '继续编辑' : 'Keep editing'}
						</Button>
						<Button
							variant="destructive"
							disabled={busy}
							onClick={() => blocker.state === 'blocked' && blocker.proceed()}
						>
							{zh ? '放弃更改' : 'Discard changes'}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
}
