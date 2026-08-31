import { CircleAlert, Download, FileText, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { ManagedSkillPackage, ManagedSkillVersion } from '@/api';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface SkillVersionsDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	skill: ManagedSkillPackage | null;
	onLoad: (packageId: string) => Promise<ManagedSkillVersion[]>;
	onDownload: (packageId: string, version: number) => Promise<void>;
}

/** Version history and exact-package download for one managed skill. */
export function SkillVersionsDialog({
	open,
	onOpenChange,
	skill,
	onLoad,
	onDownload,
}: SkillVersionsDialogProps) {
	const { t } = useTranslation();
	const [versions, setVersions] = useState<ManagedSkillVersion[]>([]);
	const [loading, setLoading] = useState(false);
	const [downloading, setDownloading] = useState<number | null>(null);
	const [error, setError] = useState('');

	useEffect(() => {
		if (!open || !skill) return;
		let active = true;
		setLoading(true);
		setError('');
		void onLoad(skill.id)
			.then((items) => {
				if (active) setVersions(items);
			})
			.catch((reason) => {
				if (active) setError(formatApiErrorForAlert(reason));
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [open, skill, onLoad]);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			{skill ? (
				<DialogContent className="flex max-h-[min(720px,calc(100dvh-2rem))] flex-col sm:max-w-2xl">
					<DialogHeader>
						<DialogTitle>{t('panel.skill.versionTitle')}</DialogTitle>
						<DialogDescription>{skill.name}</DialogDescription>
					</DialogHeader>
					{error ? (
						<Alert variant="destructive">
							<CircleAlert />
							<AlertDescription>{error}</AlertDescription>
						</Alert>
					) : null}
					<div className="min-h-64 flex-1 overflow-y-auto rounded-xl border bg-background">
						{loading ? (
							<div className="flex min-h-64 items-center justify-center">
								<Loader2 className="size-5 animate-spin text-muted-foreground" />
							</div>
						) : versions.length === 0 ? (
							<div className="flex min-h-64 items-center justify-center px-6 text-center text-sm text-muted-foreground">
								{t('panel.skill.noVersions')}
							</div>
						) : (
							<div className="divide-y">
								{versions.map((item) => (
									<div
										key={item.version}
										className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-4 py-3"
									>
										<div className="min-w-0">
											<div className="flex items-center gap-2">
												<FileText className="size-4 text-muted-foreground" />
												<span className="font-medium">v{item.version}</span>
												{item.version === skill.version ? (
													<Badge>{t('panel.skill.currentVersion')}</Badge>
												) : null}
											</div>
											<p className="mt-1 truncate text-xs text-muted-foreground">
												{new Date(item.updated_at).toLocaleString()}
											</p>
										</div>
										<Button
											size="sm"
											variant="outline"
											disabled={downloading !== null}
											onClick={async () => {
												setDownloading(item.version);
												setError('');
												try {
													await onDownload(skill.id, item.version);
												} catch (reason) {
													setError(formatApiErrorForAlert(reason));
												} finally {
													setDownloading(null);
												}
											}}
										>
											{downloading === item.version ? (
												<Loader2 className="animate-spin" />
											) : (
												<Download />
											)}
											{t('panel.skill.downloadVersion')}
										</Button>
									</div>
								))}
							</div>
						)}
					</div>
				</DialogContent>
			) : null}
		</Dialog>
	);
}
