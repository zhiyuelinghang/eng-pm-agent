import type { ReactNode } from 'react';

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

interface PanelSummaryDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	identifier?: string;
	description?: string | null;
	children?: ReactNode;
}

/** Consistent full-text details for compact assignment-list items. */
export function PanelSummaryDialog({
	open,
	onOpenChange,
	title,
	identifier,
	description,
	children,
}: PanelSummaryDialogProps) {
	const { t } = useTranslation();
	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="grid max-h-[calc(100dvh-2rem)] !w-[min(680px,calc(100vw-2rem))] !max-w-[680px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
				<DialogHeader className="border-b px-6 py-5 pr-14">
					<DialogTitle className="text-xl leading-tight">{title}</DialogTitle>
					{identifier ? <DialogDescription>{identifier}</DialogDescription> : null}
				</DialogHeader>
				<div className="min-h-0 overflow-y-auto px-6 py-6">
					<p className="max-w-[65ch] whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
						{description || t('common.noData')}
					</p>
					{children ? <div className="mt-6 border-t pt-6">{children}</div> : null}
				</div>
				<DialogFooter className="m-0 rounded-none border-t bg-background px-6 py-4">
					<Button variant="outline" onClick={() => onOpenChange(false)}>
						{t('common.close')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
