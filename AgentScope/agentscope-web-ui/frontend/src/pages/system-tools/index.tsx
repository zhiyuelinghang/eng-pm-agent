import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';

import { workspaceApi, type WorkspaceTool } from '@/api';
import { ToolPanel } from '@/components/panel/ToolPanel';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';

export function SystemToolsPage() {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const [tools, setTools] = useState<WorkspaceTool[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState('');
	const [revision, setRevision] = useState(0);

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError('');
		void workspaceApi.tool
			.listSystem()
			.then(
				(items) => {
					if (active) setTools(items);
				},
				(reason) => {
					if (active) setError(reason instanceof Error ? reason.message : String(reason));
				},
			)
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [revision]);

	return (
		<div className="flex h-full min-h-0 flex-col bg-background">
			<header className="flex min-h-20 shrink-0 items-center justify-between gap-4 border-b px-6 py-4">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">
						{zh ? '系统工具' : 'System tools'}
					</h1>
					<p className="mt-1 text-sm text-muted-foreground">
						{zh
							? '系统提供的基础能力，无需逐个分配。'
							: 'Built-in capabilities that require no per-agent assignment.'}
					</p>
				</div>
				<Button
					variant="outline"
					disabled={loading}
					onClick={() => setRevision((value) => value + 1)}
				>
					<RefreshCw className={loading ? 'animate-spin' : ''} />
					{zh ? '刷新' : 'Refresh'}
				</Button>
			</header>
			<main className="flex min-h-0 flex-1 flex-col gap-4 px-6 py-5">
				<p className="text-sm text-muted-foreground">
					{zh
						? '实际可用范围由智能体职责、运行环境和权限配置决定。'
						: 'Availability follows the agent’s role, runtime environment and permission settings.'}
				</p>
				{error ? (
					<div role="alert" className="space-y-3 text-sm">
						<p>{error}</p>
						<Button variant="outline" onClick={() => setRevision((value) => value + 1)}>
							{zh ? '重新加载' : 'Retry'}
						</Button>
					</div>
				) : (
					<ToolPanel tools={tools} loading={loading} />
				)}
			</main>
		</div>
	);
}
