import { useState } from 'react';
import type { ReactNode, Ref } from 'react';
import type { PanelImperativeHandle, PanelSize } from 'react-resizable-panels';

import { ResizablePanel } from '@/components/ui/resizable.tsx';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type PanelKey =
	| 'plan'
	| 'mcp'
	| 'skill'
	| 'tool'
	| 'database'
	| 'knowledge'
	| 'collaboration';

export interface PanelDescriptor {
	tabLabel: string;
	icon?: ReactNode;
	content: ReactNode;
	help: {
		description: ReactNode;
		note?: ReactNode;
	};
}

interface PanelDockProps {
	activeKey: PanelKey;
	panels: Record<PanelKey, PanelDescriptor>;
	onActiveChange: (key: PanelKey) => void;
	panelRef: Ref<PanelImperativeHandle | null>;
	onCollapsedChange: (collapsed: boolean) => void;
}

const PANEL_KEYS: PanelKey[] = [
	'plan',
	'mcp',
	'skill',
	'tool',
	'database',
	'knowledge',
	'collaboration',
];

/**
 * Persistent right-hand chat sidebar. All workspace tools remain mounted in
 * one stable location and are switched through tabs instead of opening
 * separate resizable dock columns.
 */
export const PanelDock = ({
	activeKey,
	panels,
	onActiveChange,
	panelRef,
	onCollapsedChange,
}: PanelDockProps) => {
	const [previewKey, setPreviewKey] = useState<PanelKey | null>(null);
	const activePanel = panels[activeKey];
	const previewPanel = previewKey ? panels[previewKey] : null;
	const handleResize = (size: PanelSize) => onCollapsedChange(size.inPixels <= 1);
	const clearPreview = (key: PanelKey) => {
		setPreviewKey((current) => (current === key ? null : current));
	};

	return (
		<ResizablePanel
			className="min-w-0 border-l bg-background"
			id="chat-tool-panel"
			minSize="18rem"
			defaultSize="22rem"
			maxSize="32rem"
			collapsedSize="0px"
			collapsible
			panelRef={panelRef}
			onResize={handleResize}
		>
			<Tabs
				value={activeKey}
				onValueChange={(value) => onActiveChange(value as PanelKey)}
				className="flex h-full min-h-0 flex-col gap-0"
			>
				<div className="relative z-20 shrink-0">
					<TabsList className="grid h-auto! w-full grid-cols-4 gap-1 rounded-none border-b bg-muted/25 p-2 group-data-horizontal/tabs:h-auto!">
						{PANEL_KEYS.map((key) => {
							const descriptor = panels[key];
							return (
								<TabsTrigger
									key={key}
									value={key}
									aria-describedby={
										previewKey === key ? `panel-tab-help-${key}` : undefined
									}
									onMouseEnter={() => setPreviewKey(key)}
									onMouseLeave={() => clearPreview(key)}
									onFocus={() => setPreviewKey(key)}
									onBlur={() => clearPreview(key)}
									onClick={() => clearPreview(key)}
									className={`h-9 min-w-0 justify-start px-2 text-xs ${
										key === 'database' ? 'col-span-2' : ''
									}`}
								>
									{descriptor.icon}
									<span className="truncate">{descriptor.tabLabel}</span>
								</TabsTrigger>
							);
						})}
					</TabsList>

					{previewKey && previewPanel ? (
						<div
							id={`panel-tab-help-${previewKey}`}
							role="tooltip"
							className="pointer-events-none absolute inset-x-3 top-full z-50 mt-1.5 animate-in rounded-md bg-foreground px-3 py-2 text-xs leading-relaxed text-background shadow-md fade-in-0 zoom-in-95"
						>
							<div>{previewPanel.help.description}</div>
							{previewPanel.help.note ? (
								<div className="mt-1.5 border-t border-background/20 pt-1.5 text-background/75">
									{previewPanel.help.note}
								</div>
							) : null}
						</div>
					) : null}
				</div>

				<div className="flex min-h-0 flex-1 flex-col overflow-auto p-3">
					{activePanel.content}
				</div>
			</Tabs>
		</ResizablePanel>
	);
};
