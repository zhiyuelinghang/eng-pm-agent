import { CircleAlert, Loader2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { Skill, UpdateSkillRequest } from '@/api';
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

interface EditSkillDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	skill: Skill | null;
	onSave: (currentName: string, input: UpdateSkillRequest) => Promise<void>;
}

export function EditSkillDialog({ open, onOpenChange, skill, onSave }: EditSkillDialogProps) {
	const { t } = useTranslation();
	const [name, setName] = useState('');
	const [description, setDescription] = useState('');
	const [markdown, setMarkdown] = useState('');
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (!open || !skill) return;
		setName(skill.name);
		setDescription(skill.description);
		setMarkdown(skill.markdown);
		setError(null);
	}, [open, skill]);

	const canSave = Boolean(skill && name.trim() && description.trim() && !saving);
	const handleSave = async () => {
		if (!skill || !canSave) return;
		setSaving(true);
		setError(null);
		try {
			await onSave(skill.name, {
				name: name.trim(),
				description: description.trim(),
				markdown,
			});
			onOpenChange(false);
		} catch (caught) {
			setError((caught as Error).message);
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={saving ? undefined : onOpenChange}>
			<DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-3xl">
				<DialogHeader>
					<DialogTitle>{t('panel.skill.editTitle')}</DialogTitle>
					<DialogDescription>{t('panel.skill.editDescription')}</DialogDescription>
				</DialogHeader>

				<div className="grid min-h-0 flex-1 gap-4 overflow-y-auto py-1">
					<div className="grid gap-2">
						<Label htmlFor="edit-skill-name">{t('common.name')}</Label>
						<Input
							id="edit-skill-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							disabled={saving}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="edit-skill-description">
							{t('panel.skill.descriptionLabel')}
						</Label>
						<Textarea
							id="edit-skill-description"
							className="min-h-24 resize-y"
							value={description}
							onChange={(event) => setDescription(event.target.value)}
							disabled={saving}
						/>
					</div>

					<div className="grid min-h-0 gap-2">
						<Label htmlFor="edit-skill-markdown">
							{t('panel.skill.markdownLabel')}
						</Label>
						<Textarea
							id="edit-skill-markdown"
							className="min-h-72 resize-y font-mono text-sm"
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
					<Button onClick={handleSave} disabled={!canSave}>
						{saving ? <Loader2 className="animate-spin" /> : <Save />}
						{saving ? t('common.saving') : t('common.save')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
