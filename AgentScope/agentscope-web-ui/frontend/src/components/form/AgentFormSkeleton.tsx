import { useTranslation } from 'react-i18next';

import { Skeleton } from '@/components/ui/skeleton';

export function AgentFormSkeleton() {
	const { t } = useTranslation();

	return (
		<div role="status" aria-busy="true" className="h-full min-h-0">
			<span className="sr-only">{t('common.loading')}</span>
			<div
				aria-hidden="true"
				className="grid h-full min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[12rem_minmax(0,1fr)] md:grid-rows-1"
			>
				<div className="flex gap-1 overflow-hidden border-b bg-muted/20 p-3 md:flex-col md:border-r md:border-b-0 md:py-5">
					{['w-16', 'w-20', 'w-16', 'w-20'].map((width, index) => (
						<div
							key={index}
							className="flex h-11 shrink-0 items-center gap-3 rounded-lg px-3 motion-safe:animate-pulse"
						>
							<Skeleton className="size-1.5 animate-none rounded-full" />
							<Skeleton className={`h-4 animate-none ${width}`} />
						</div>
					))}
				</div>
				<div className="min-h-0 overflow-hidden px-6 py-6 sm:px-8">
					<div className="mx-auto max-w-2xl space-y-6 motion-safe:animate-pulse">
						<div className="space-y-2">
							<Skeleton className="h-6 w-28 animate-none" />
							<Skeleton className="h-4 w-56 max-w-full animate-none" />
						</div>
						<div className="space-y-2">
							<Skeleton className="h-4 w-16 animate-none" />
							<Skeleton className="h-9 w-full animate-none rounded-lg" />
						</div>
						<div className="space-y-2">
							<Skeleton className="h-4 w-24 animate-none" />
							<Skeleton className="h-48 w-full animate-none rounded-lg" />
						</div>
						<div className="space-y-2">
							<Skeleton className="h-4 w-20 animate-none" />
							<Skeleton className="h-20 w-full animate-none rounded-lg" />
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}
