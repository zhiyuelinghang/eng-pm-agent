import type { ReactNode, Ref } from 'react';
import type { PanelImperativeHandle, PanelSize } from 'react-resizable-panels';

import { ResizablePanel } from '@/components/ui/resizable.tsx';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type PanelKey = 'plan' | 'mcp' | 'skill' | 'tool' | 'knowledge' | 'collaboration';

export interface PanelDescriptor {
	tabLabel: ReactNode;
	icon?: ReactNode;
	content: ReactNode;
}

interface PanelDockProps {
	activeKey: PanelKey;
	panels: Record<PanelKey, PanelDescriptor>;
	onActiveChange: (key: PanelKey) => void;
	panelRef: Ref<PanelImperativeHandle | null>;
	onCollapsedChange: (collapsed: boolean) => void;
}

const PANEL_KEYS: PanelKey[] = ['plan', 'mcp', 'skill', 'tool', 'knowledge', 'collaboration'];

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
	const activePanel = panels[activeKey];
	const handleResize = (size: PanelSize) => onCollapsedChange(size.inPixels <= 1);

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
				<TabsList className="grid h-auto! w-full shrink-0 grid-cols-3 gap-1 rounded-none border-b bg-muted/25 p-2 group-data-horizontal/tabs:h-auto!">
					{PANEL_KEYS.map((key) => {
						const descriptor = panels[key];
						return (
							<TabsTrigger
								key={key}
								value={key}
								className="h-9 min-w-0 justify-start px-2 text-xs"
							>
								{descriptor.icon}
								<span className="truncate">{descriptor.tabLabel}</span>
							</TabsTrigger>
						);
					})}
				</TabsList>

				<div className="flex min-h-0 flex-1 flex-col overflow-auto p-3">
					{activePanel.content}
				</div>
			</Tabs>
		</ResizablePanel>
	);
};
