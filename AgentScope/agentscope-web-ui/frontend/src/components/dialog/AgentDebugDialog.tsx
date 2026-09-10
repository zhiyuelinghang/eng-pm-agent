import { Loader2, Maximize2, Minimize2, Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { DeleteDialog } from './DeleteDialog';
import { RenameSessionDialog } from './RenameSessionDialog';
import type { AgentView, SessionRecord } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { SidebarProvider } from '@/components/ui/sidebar';
import { AudioProvider } from '@/context/AudioContext';
import { useSessions } from '@/hooks/useSessions';
import { ChatViewport } from '@/pages/chat/ChatViewport';

export function AgentDebugDialog({
	agent,
	agents,
	onClose,
}: {
	agent: AgentView;
	agents: AgentView[];
	onClose: () => void;
	onUpdated?: () => Promise<void>;
}) {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const { sessions, loading, error, refetch, create, remove, update } = useSessions(agent.id);
	const [sessionId, setSessionId] = useState<string | null>(null);
	const [memberId, setMemberId] = useState<string | null>(null);
	const [creating, setCreating] = useState(false);
	const [actionError, setActionError] = useState('');
	const [maximized, setMaximized] = useState(false);
	const [rename, setRename] = useState<SessionRecord | null>(null);
	const [deleting, setDeleting] = useState<SessionRecord | null>(null);
	const view = sessions.find((v) => v.session.id === sessionId) ?? sessions[0] ?? null;
	const member = view?.team?.members.find((m) => m.agent.id === memberId && m.session_id);
	const activeAgentId = member?.agent.id ?? agent.id;
	const activeSessionId = member?.session_id ?? view?.session.id ?? null;
	const createSession = async () => {
		if (creating) return;
		setCreating(true);
		setActionError('');
		try {
			const config = view?.session.config;
			const result = await create({
				agent_id: agent.id,
				...(config?.chat_model_config
					? { chat_model_config: config.chat_model_config }
					: {}),
				...(config?.fallback_chat_model_config
					? { fallback_chat_model_config: config.fallback_chat_model_config }
					: {}),
			});
			setMemberId(null);
			setSessionId(result.session_id);
		} catch (e) {
			setActionError(e instanceof Error ? e.message : '创建会话失败');
		} finally {
			setCreating(false);
		}
	};
	return (
		<Dialog
			open
			onOpenChange={(open) => {
				if (!open) onClose();
			}}
		>
			<DialogContent
				onInteractOutside={(e) => e.preventDefault()}
				className={`flex flex-col gap-0 overflow-hidden p-0 ${maximized ? '!h-[calc(100dvh-1rem)] !w-[calc(100vw-1rem)] !max-w-none' : 'h-[min(860px,calc(100dvh-2rem))] !w-[min(1320px,calc(100vw-2rem))] !max-w-[1320px]'}`}
			>
				<DialogHeader className="flex-row items-center justify-between border-b px-6 py-4 pr-14">
					<div className="space-y-1">
						<DialogTitle className="text-xl">
							{zh ? '调试' : 'Debug'} · {agent.data.name}
						</DialogTitle>
						<DialogDescription>
							{zh ? '使用当前已保存的配置。' : 'Uses the saved agent configuration.'}
						</DialogDescription>
					</div>
					<Button
						size="icon"
						variant="ghost"
						aria-label={
							maximized ? (zh ? '还原窗口' : 'Restore') : zh ? '最大化' : 'Maximize'
						}
						onClick={() => setMaximized((v) => !v)}
					>
						{maximized ? <Minimize2 /> : <Maximize2 />}
					</Button>
				</DialogHeader>
				<div className="flex min-h-0 flex-1 flex-col md:flex-row">
					<aside className="flex shrink-0 flex-col border-b bg-muted/10 md:w-60 md:border-r md:border-b-0">
						<div className="p-4">
							<Button
								className="w-full"
								variant="outline"
								disabled={creating}
								onClick={createSession}
							>
								{creating ? <Loader2 className="animate-spin" /> : <Plus />}
								{zh ? '新建调试会话' : 'New debug session'}
							</Button>
						</div>
						<div className="max-h-40 flex-1 space-y-1 overflow-y-auto px-3 pb-4 md:max-h-none">
							<p className="px-2 pb-2 text-xs text-muted-foreground">
								{zh ? '调试会话' : 'Sessions'}
							</p>
							{loading && !sessions.length && (
								<p className="px-2 text-sm text-muted-foreground">
									{zh ? '正在加载…' : 'Loading…'}
								</p>
							)}
							{error && (
								<div role="alert" className="space-y-2 px-2 text-sm">
									<p>{error.message}</p>
									<Button variant="outline" onClick={refetch}>
										{zh ? '重试' : 'Retry'}
									</Button>
								</div>
							)}
							{sessions.map((v) => (
								<div
									key={v.session.id}
									className={`group flex items-center rounded-lg ${v.session.id === view?.session.id ? 'bg-[#c95622]/8' : 'hover:bg-muted/60'}`}
								>
									<button
										type="button"
										aria-current={
											view?.session.id === v.session.id ? 'page' : undefined
										}
										className="min-w-0 flex-1 truncate px-3 py-3 text-left text-sm"
										onClick={() => {
											setMemberId(null);
											setSessionId(v.session.id);
										}}
									>
										{v.session.config.name || (zh ? '未命名会话' : 'Untitled')}
									</button>
									<Button
										size="icon-xs"
										variant="ghost"
										aria-label={zh ? '重命名会话' : 'Rename session'}
										onClick={() => setRename(v.session)}
									>
										<Pencil />
									</Button>
									<Button
										size="icon-xs"
										variant="ghost"
										disabled={v.is_running}
										aria-label={zh ? '删除会话' : 'Delete session'}
										onClick={() => setDeleting(v.session)}
									>
										<Trash2 />
									</Button>
								</div>
							))}
						</div>
					</aside>
					<div className="flex min-h-0 min-w-0 flex-1 flex-col">
						{actionError && (
							<p role="alert" className="px-4 py-3 text-sm text-destructive">
								{actionError}
							</p>
						)}
						{view?.team && (
							<nav
								aria-label={zh ? '协同成员' : 'Team members'}
								className="flex gap-2 overflow-x-auto border-b p-2"
							>
								<Button
									size="sm"
									variant={!member ? 'secondary' : 'ghost'}
									onClick={() => setMemberId(null)}
								>
									{agent.data.name}
								</Button>
								{view.team.members.map((m) => (
									<Button
										key={m.agent.id}
										size="sm"
										variant={
											member?.agent.id === m.agent.id ? 'secondary' : 'ghost'
										}
										disabled={!m.session_id}
										onClick={() => setMemberId(m.agent.id)}
									>
										{m.agent.data.name}
									</Button>
								))}
							</nav>
						)}
						{activeSessionId ? (
							<div className="min-h-0 flex-1">
								<AudioProvider>
									<SidebarProvider className="h-full min-h-0">
										<ChatViewport
											key={`${activeAgentId}:${activeSessionId}`}
											agentId={activeAgentId}
											sessionId={activeSessionId}
											agents={agents}
											onTeamUpdated={refetch}
										/>
									</SidebarProvider>
								</AudioProvider>
							</div>
						) : (
							!loading &&
							!error && (
								<div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-sm text-muted-foreground">
									<p>
										{zh
											? '新建会话，开始调试。'
											: 'Create a session to start debugging.'}
									</p>
									<Button disabled={creating} onClick={createSession}>
										<Plus />
										{zh ? '新建调试会话' : 'New debug session'}
									</Button>
								</div>
							)
						)}
					</div>
				</div>
				{rename && (
					<RenameSessionDialog
						open
						currentName={rename.config.name ?? ''}
						onOpenChange={(open) => {
							if (!open) setRename(null);
						}}
						onConfirm={async (name) => {
							await update(rename.id, { name });
						}}
					/>
				)}
				{deleting && (
					<DeleteDialog
						open
						title={zh ? '删除调试会话' : 'Delete debug session'}
						description={
							zh
								? '此会话的消息将被删除。'
								: 'Messages in this session will be deleted.'
						}
						onOpenChange={(open) => {
							if (!open) setDeleting(null);
						}}
						onConfirm={async () => {
							await remove(deleting.id);
							if (sessionId === deleting.id) setSessionId(null);
						}}
					/>
				)}
			</DialogContent>
		</Dialog>
	);
}
