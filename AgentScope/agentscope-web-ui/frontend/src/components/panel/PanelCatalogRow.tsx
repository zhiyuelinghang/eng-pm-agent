import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

interface PanelCatalogCheckbox {
	checked: boolean;
	disabled?: boolean;
	ariaLabel: string;
	onChange: (checked: boolean) => void;
}

interface PanelCatalogRowProps {
	title: string;
	description?: string | null;
	metadata?: ReactNode;
	badge?: ReactNode;
	selected?: boolean;
	muted?: boolean;
	checkbox?: PanelCatalogCheckbox;
	onOpen?: () => void;
	openLabel?: string;
}

/** Shared compact list row used by every assignable capability panel. */
export function PanelCatalogRow({
	title,
	description,
	metadata,
	badge,
	selected = false,
	muted = false,
	checkbox,
	onOpen,
	openLabel,
}: PanelCatalogRowProps) {
	const { i18n } = useTranslation();
	const content = (
		<>
			<span className="flex min-w-0 items-center gap-2">
				<span
					className="block min-w-0 flex-1 break-words text-sm font-medium"
					title={title}
				>
					{title}
				</span>
				{badge ? <span className="shrink-0">{badge}</span> : null}
			</span>
			{description ? (
				<span
					className="mt-1 line-clamp-2 block text-xs leading-relaxed text-muted-foreground"
					title={description}
				>
					{description}
				</span>
			) : null}
			{metadata ? (
				<span className="mt-1.5 block truncate text-xs text-muted-foreground">
					{metadata}
				</span>
			) : null}
		</>
	);

	return (
		<div
			data-selected={selected || undefined}
			data-muted={muted || undefined}
			className="group flex items-start gap-3 px-3 py-3 transition-colors hover:bg-muted/30 data-[selected=true]:bg-primary/[0.04] data-[muted=true]:opacity-60"
		>
			{checkbox ? (
				<Checkbox
					checked={checkbox.checked}
					disabled={checkbox.disabled}
					onCheckedChange={(value) => checkbox.onChange(value === true)}
					aria-label={checkbox.ariaLabel}
					className="mt-0.5"
				/>
			) : null}
			<div className="min-w-0 flex-1">{content}</div>
			{onOpen && (
				<Button
					variant="ghost"
					size="sm"
					className="shrink-0 text-[#c95622]"
					onClick={onOpen}
					aria-label={`${i18n.language.startsWith('zh') ? '查看详情' : 'View details'} · ${openLabel ?? title}`}
				>
					{i18n.language.startsWith('zh') ? '查看详情' : 'View details'}
				</Button>
			)}
		</div>
	);
}
