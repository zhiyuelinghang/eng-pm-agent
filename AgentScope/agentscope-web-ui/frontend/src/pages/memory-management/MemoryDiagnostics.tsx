import { Activity } from 'lucide-react';

import { MemoryActivityFrame } from './MemoryActivityFrame';
import type { MemoryIndexJob } from '@/api/types';

interface Props {
	jobs: MemoryIndexJob[] | null;
	loading: boolean;
	error: string;
	locale: string;
	onRefresh: () => void;
}

const states = { pending: '等待索引', running: '正在建立索引', failed: '索引失败' };

export function MemoryDiagnostics({ jobs, loading, error, locale, onRefresh }: Props) {
	return (
		<MemoryActivityFrame
			title="后台索引任务"
			total={jobs?.length ?? 0}
			unit="项"
			loading={loading}
			hasData={jobs !== null}
			error={error}
			onRetry={onRefresh}
			descriptionLabel="索引说明"
			loadingLabel="正在读取索引任务"
			description={
				<p>
					正文独立保存。索引建立后可参与搜索；暂时失败会自动延后重试，任务在服务重启后继续。
				</p>
			}
			emptyIcon={Activity}
			emptyTitle="暂无待处理或失败的索引任务"
			emptyDescription="有任务等待处理或需要自动重试时，会显示在这里。"
		>
			{jobs?.map((job) => (
				<article
					key={`${job.memory_id}:${job.version}`}
					className="shrink-0 space-y-3 border-b px-4 py-5 sm:px-6"
				>
					<div className="flex flex-wrap items-center justify-between gap-3">
						<h3 className="font-semibold">{states[job.state]}</h3>
						<span className="text-xs tabular-nums text-muted-foreground">
							已尝试 {job.attempts} 次
						</span>
					</div>
					{job.error_code && (
						<p className="break-words text-sm leading-6 text-amber-700 dark:text-amber-400">
							{job.error_code}
						</p>
					)}
					<details className="text-xs text-muted-foreground">
						<summary className="w-fit cursor-pointer rounded-sm focus-visible:outline-2">
							任务信息
						</summary>
						<dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 leading-6">
							<dt>记忆 ID</dt>
							<dd className="break-all">{job.memory_id}</dd>
							<dt>版本</dt>
							<dd>{job.version}</dd>
							<dt>更新时间</dt>
							<dd>
								{job.updated_at
									? new Date(job.updated_at).toLocaleString(locale)
									: '—'}
							</dd>
						</dl>
					</details>
				</article>
			))}
		</MemoryActivityFrame>
	);
}
