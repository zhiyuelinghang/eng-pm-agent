import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';

export function useUnsavedChanges(dirty: boolean, busy = false) {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const [open, setOpen] = useState(false);
	const action = useRef<(() => void) | null>(null);
	const leave = (next: () => void) => {
		if (busy) return;
		if (!dirty) {
			next();
			return;
		}
		action.current = next;
		setOpen(true);
	};
	const prompt = (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{zh ? '更改尚未保存' : 'Unsaved changes'}</DialogTitle>
					<DialogDescription>
						{zh
							? '离开后，本次未保存的更改将被放弃。'
							: 'Leaving will discard your unsaved changes.'}
					</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button variant="outline" onClick={() => setOpen(false)}>
						{zh ? '继续编辑' : 'Keep editing'}
					</Button>
					<Button
						variant="destructive"
						onClick={() => {
							setOpen(false);
							action.current?.();
							action.current = null;
						}}
					>
						{zh ? '放弃更改' : 'Discard changes'}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
	return { leave, prompt };
}
