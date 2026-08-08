import type { Task, TaskContext } from '@agentscope-ai/agentscope/state';
import { Check, ChevronDown, Circle, ListTodo, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

interface PlanTimelineCardProps {
	tasksContext: TaskContext;
}

function TaskStateIcon({ state }: { state: Task['state'] }) {
	if (state === 'completed') {
		return <Check className="size-4 shrink-0" />;
	}
	if (state === 'in_progress') {
		return <Loader2 className="size-4 shrink-0 animate-spin" />;
	}
	return <Circle className="size-3 shrink-0" />;
}

/**
 * Chronological plan summary shown in the conversation where the plan began.
 * Live task updates patch this single card; expanding it reveals every step.
 */
export function PlanTimelineCard({ tasksContext }: PlanTimelineCardProps) {
	const { t } = useTranslation();
	const [expanded, setExpanded] = useState(false);
	const { tasks } = tasksContext;
	const completed = tasks.filter((task) => task.state === 'completed').length;
	const isCompleted = tasks.length > 0 && completed === tasks.length;
	const currentTask =
		tasks.find((task) => task.state === 'in_progress') ??
		tasks.find((task) => task.state === 'pending') ??
		null;
	const visibleTasks = expanded ? tasks : currentTask ? [currentTask] : [];
	const progress = tasks.length > 0 ? Math.round((completed / tasks.length) * 100) : 0;

	useEffect(() => {
		if (isCompleted) setExpanded(false);
	}, [isCompleted]);

	if (tasks.length === 0) return null;

	return (
		<section
			aria-label={t('panel.plan.timelineTitle')}
			aria-live="polite"
			className="w-full rounded-lg border bg-muted/20 px-3 py-3"
		>
			<header className="flex items-center gap-3">
				<div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-background text-foreground shadow-xs">
					<ListTodo className="size-4" />
				</div>
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 items-center gap-2">
						<h3 className="truncate text-sm font-medium">
							{t('panel.plan.timelineTitle')}
						</h3>
						<span
							className={cn(
								'shrink-0 text-xs font-medium',
								isCompleted ? 'text-muted-foreground' : 'text-foreground',
							)}
						>
							{isCompleted
								? t('panel.plan.timelineCompleted')
								: t('panel.plan.timelineRunning')}
						</span>
					</div>
					<p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
						{t('panel.plan.timelineProgress', {
							completed,
							total: tasks.length,
						})}
					</p>
				</div>
				<Button
					type="button"
					variant="ghost"
					size="icon-xs"
					aria-expanded={expanded}
					aria-label={
						expanded
							? t('panel.plan.timelineCollapse')
							: t('panel.plan.timelineExpand')
					}
					onClick={() => setExpanded((value) => !value)}
				>
					<ChevronDown
						className={cn('size-4 transition-transform', expanded && 'rotate-180')}
					/>
				</Button>
			</header>

			<div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
				<div
					className="h-full rounded-full bg-foreground transition-[width] duration-300"
					style={{ width: `${progress}%` }}
				/>
			</div>

			{visibleTasks.length > 0 ? (
				<ul className="mt-3 divide-y rounded-md border bg-background/75">
					{visibleTasks.map((task) => (
						<li key={task.id} className="flex items-start gap-2 px-3 py-2.5">
							<span
								className={cn(
									'mt-0.5 text-muted-foreground',
									task.state === 'in_progress' && 'text-foreground',
								)}
							>
								<TaskStateIcon state={task.state} />
							</span>
							<div className="min-w-0 flex-1">
								<p
									className={cn(
										'text-sm leading-5',
										task.state === 'completed' &&
											'text-muted-foreground line-through',
									)}
								>
									{task.subject}
								</p>
								{task.blocked_by.length > 0 ? (
									<p className="mt-0.5 text-xs text-muted-foreground">
										{t('task-panel.blockedBy')}{' '}
										{task.blocked_by.map((id) => `#${id}`).join(', ')}
									</p>
								) : null}
							</div>
						</li>
					))}
				</ul>
			) : null}
		</section>
	);
}
