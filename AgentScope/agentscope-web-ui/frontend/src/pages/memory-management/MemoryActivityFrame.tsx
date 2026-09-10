import { CircleAlert, Sparkles, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';

interface Props {
	title: string;
	total: number;
	unit: string;
	offset?: number;
	loading: boolean;
	hasData: boolean;
	error: string;
	description: ReactNode;
	descriptionLabel?: string;
	loadingLabel?: string;
	emptyIcon?: LucideIcon;
	toolbar?: ReactNode;
	preface?: ReactNode;
	emptyTitle: string;
	emptyDescription: string;
	children: ReactNode;
	onRetry: () => void;
	onPage?: (offset: number) => void;
}

export function MemoryActivityFrame({
	title,
	total,
	unit,
	offset = 0,
	loading,
	hasData,
	error,
	description,
	descriptionLabel = '学习说明',
	loadingLabel = '正在读取学习记录',
	emptyIcon: EmptyIcon = Sparkles,
	toolbar,
	preface,
	emptyTitle,
	emptyDescription,
	children,
	onRetry,
	onPage,
}: Props) {
	return (
		<section
			aria-label={title}
			className="flex min-h-0 min-w-0 flex-1 flex-col bg-background text-sm"
		>
			<div className="shrink-0 space-y-3 border-b px-4 py-3 sm:px-6">
				<div className="flex flex-wrap items-center justify-between gap-3">
					<h2 className="font-medium">{title}</h2>
					<span role="status" className="text-xs tabular-nums text-muted-foreground">
						{loading ? '正在读取…' : error ? '读取失败' : `${total} ${unit}`}
					</span>
				</div>
				{toolbar}
				<details className="text-xs leading-6 text-muted-foreground">
					<summary className="w-fit cursor-pointer rounded-sm focus-visible:outline-2">
						{descriptionLabel}
					</summary>
					<div className="mt-2 max-w-3xl space-y-1">{description}</div>
				</details>
			</div>
			{error && (
				<div
					role="alert"
					className="flex shrink-0 flex-wrap items-center gap-2 border-b border-destructive/30 px-4 py-3 text-destructive sm:px-6"
				>
					<CircleAlert className="size-4 shrink-0" />
					<span className="min-w-0 break-words">{error}</span>
					<Button variant="ghost" size="sm" disabled={loading} onClick={onRetry}>
						重新读取
					</Button>
				</div>
			)}
			<div
				key={offset}
				aria-busy={loading}
				className="flex min-h-0 flex-1 flex-col overflow-y-auto"
			>
				{loading && !hasData ? (
					<div className="space-y-4 px-4 py-5 sm:px-6" aria-label={loadingLabel}>
						{[1, 2, 3].map((row) => (
							<div key={row} className="h-24 animate-pulse rounded bg-muted" />
						))}
					</div>
				) : !error && hasData ? (
					<>
						{preface}
						{total === 0 ? (
							<div className="flex min-h-60 flex-1 flex-col items-center justify-center px-6 py-12 text-center">
								<EmptyIcon
									aria-hidden="true"
									className="mb-4 size-8 text-muted-foreground/60"
								/>
								<h3 className="font-medium">{emptyTitle}</h3>
								<p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
									{emptyDescription}
								</p>
							</div>
						) : (
							children
						)}
					</>
				) : null}
			</div>
			{onPage && (
				<footer className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground sm:px-6">
					<span className="tabular-nums">第 {Math.floor(offset / 30) + 1} 页</span>
					<div className="flex gap-2">
						<Button
							size="sm"
							variant="outline"
							disabled={offset === 0 || loading}
							onClick={() => onPage(Math.max(0, offset - 30))}
						>
							上一页
						</Button>
						<Button
							size="sm"
							variant="outline"
							disabled={loading || !!error || !hasData || offset + 30 >= total}
							onClick={() => onPage(offset + 30)}
						>
							下一页
						</Button>
					</div>
				</footer>
			)}
		</section>
	);
}
