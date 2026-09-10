import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useUnsavedChanges } from './UnsavedChangesDialog';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { PlatformSettingsPage } from '@/pages/platform-settings';

export function InitializationValidationDialog({ onClose }: { onClose: () => void }) {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const [dirty, setDirty] = useState(false);
	const [busy, setBusy] = useState(false);
	const { leave, prompt } = useUnsavedChanges(dirty, busy);
	return (
		<>
			<Dialog
				open
				onOpenChange={(open) => {
					if (!open) leave(onClose);
				}}
			>
				<DialogContent
					className={`flex h-[min(660px,calc(100dvh-2rem))] !w-[min(960px,calc(100vw-2rem))] !max-w-[960px] flex-col gap-0 overflow-hidden p-0`}
				>
					<DialogHeader className="border-b px-6 py-5 pr-14">
						<DialogTitle>{zh ? '初始化核验' : 'Initialization validation'}</DialogTitle>
						<DialogDescription>
							{zh
								? '管理核验规则包及使用版本。'
								: 'Manage validation packages and the active version.'}
						</DialogDescription>
					</DialogHeader>
					<div className="min-h-0 flex-1">
						<PlatformSettingsPage
							embedded
							initialAssignment="initializer"
							validationOnly
							onDirtyChange={setDirty}
							onBusyChange={setBusy}
						/>
					</div>
				</DialogContent>
			</Dialog>
			{prompt}
		</>
	);
}
