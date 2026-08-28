import { CircleAlert, Loader2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { ManagedSkillInput } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface CreateSkillDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreate: (input: ManagedSkillInput) => Promise<void>;
}

const INITIAL_MARKDOWN = `# 使用说明

说明智能体应在什么情况下使用该技能，以及需要遵循的步骤。

## 执行步骤

1. 明确输入与目标。
2. 按业务规则完成处理。
3. 输出可核验的结果。`;

/** Browser editor for creating a pure SKILL.md package. */
export function CreateSkillDialog({
	open,
	onOpenChange,
	onCreate,
}: CreateSkillDialogProps) {
	const { t } = useTranslation();
	const [name, setName] = useState('');
	const [description, setDescription] = useState('');
	const [markdown, setMarkdown] = useState(INITIAL_MARKDOWN);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState('');

	useEffect(() => {
		if (!open) return;
		setName('');
		setDescription('');
		setMarkdown(INITIAL_MARKDOWN);
		setError('');
	}, [open]);

	const canSave = Boolean(name.trim() && description.trim() && markdown.trim() && !saving);
	const handleCreate = async () => {
		if (!canSave) return;
		setSaving(true);
		setError('');
		try {
			await onCreate({
				name: name.trim(),
				description: description.trim(),
				markdown: markdown.trim(),
			});
			onOpenChange(false);
		} catch (reason) {
			setError(formatApiErrorForAlert(reason));
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={saving ? undefined : onOpenChange}>
			<DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-3xl">
				<DialogHeader>
					<DialogTitle>{t('panel.skill.createTitle')}</DialogTitle>
					<DialogDescription>{t('panel.skill.createDescription')}</DialogDescription>
				</DialogHeader>
				<div className="grid min-h-0 flex-1 gap-4 overflow-y-auto py-1">
					<div className="grid gap-2">
						<Label htmlFor="create-skill-name">{t('common.name')}</Label>
						<Input
							id="create-skill-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder={t('panel.skill.namePlaceholder')}
							disabled={saving}
						/>
					</div>
					<div className="grid gap-2">
						<Label htmlFor="create-skill-description">
							{t('panel.skill.descriptionLabel')}
						</Label>
						<Textarea
							id="create-skill-description"
							className="min-h-20 resize-y"
							value={description}
							onChange={(event) => setDescription(event.target.value)}
							placeholder={t('panel.skill.descriptionPlaceholder')}
							disabled={saving}
						/>
					</div>
					<div className="grid min-h-0 gap-2">
						<Label htmlFor="create-skill-markdown">
							{t('panel.skill.markdownLabel')}
						</Label>
						<Textarea
							id="create-skill-markdown"
							className="min-h-72 resize-y font-mono text-sm leading-6"
							value={markdown}
							onChange={(event) => setMarkdown(event.target.value)}
							disabled={saving}
							spellCheck={false}
						/>
					</div>
					{error ? (
						<p className="flex items-start gap-2 text-sm text-destructive" role="alert">
							<CircleAlert className="mt-0.5 size-4 shrink-0" />
							{error}
						</p>
					) : null}
				</div>
				<DialogFooter>
					<Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
						{t('common.cancel')}
					</Button>
					<Button onClick={handleCreate} disabled={!canSave}>
						{saving ? <Loader2 className="animate-spin" /> : <Save />}
						{saving ? t('common.saving') : t('panel.skill.createAction')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
