import {
	Bot,
	Eye,
	FolderKanban,
	Loader2,
	MessageSquareText,
	RefreshCw,
	UserRound,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { platformAuditApi } from '@/api/platformAudit';
import type {
	Msg,
	PlatformAuditMessagesResponse,
	PlatformAuditTreeResponse,
} from '@/api/types';
import { MessageBubble } from '@/components/chat/MessageBubble';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

type MessageWithMetadata = Msg & {
	metadata?: {
		platform_initialization_files?: Array<{
			id: number | string;
			name: string;
			size: number;
		}>;
	};
};

function formatDateTime(value: string) {
	return new Intl.DateTimeFormat(undefined, {
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
	}).format(new Date(value));
}

function formatFileSize(size: number) {
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
	return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function PlatformAuditPage() {
	const { t } = useTranslation();
	const [tree, setTree] = useState<PlatformAuditTreeResponse | null>(null);
	const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
	const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
	const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
	const [transcript, setTranscript] = useState<PlatformAuditMessagesResponse | null>(null);
	const [treeLoading, setTreeLoading] = useState(true);
	const [messagesLoading, setMessagesLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const loadTree = useCallback(async () => {
		setTreeLoading(true);
		try {
			setTree(await platformAuditApi.tree());
			setError(null);
		} catch (requestError) {
			setError(requestError instanceof Error ? requestError.message : String(requestError));
		} finally {
			setTreeLoading(false);
		}
	}, []);

	const loadMessages = useCallback(async (sessionId: string, quiet = false) => {
		if (!quiet) setMessagesLoading(true);
		try {
			const response = await platformAuditApi.messages(sessionId);
			setTranscript(response);
			setError(null);
		} catch (requestError) {
			setError(requestError instanceof Error ? requestError.message : String(requestError));
		} finally {
			if (!quiet) setMessagesLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadTree();
	}, [loadTree]);

	useEffect(() => {
		if (!selectedSessionId || !transcript?.is_running) return;
		const interval = window.setInterval(() => {
			void loadMessages(selectedSessionId, true);
			void loadTree();
		}, 3000);
		return () => window.clearInterval(interval);
	}, [loadMessages, loadTree, selectedSessionId, transcript?.is_running]);

	const selectedUser = useMemo(
		() => tree?.users.find((item) => item.user_id === selectedUserId) ?? null,
		[tree, selectedUserId],
	);
	const selectedProject = useMemo(
		() =>
			selectedUser?.projects.find((item) => item.project_id === selectedProjectId) ?? null,
		[selectedProjectId, selectedUser],
	);
	const selectedConversation = useMemo(
		() =>
			selectedProject?.conversations.find(
				(item) => item.session_id === selectedSessionId,
			) ?? null,
		[selectedProject, selectedSessionId],
	);

	const refresh = async () => {
		await loadTree();
		if (selectedSessionId) await loadMessages(selectedSessionId, true);
	};

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex h-16 shrink-0 items-center justify-between border-b bg-background px-5">
				<div>
					<div className="flex items-center gap-2">
						<Eye className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">{t('platformAudit.title')}</h1>
					</div>
					<p className="mt-1 text-xs text-muted-foreground">
						{t('platformAudit.description')}
					</p>
				</div>
				<div className="flex items-center gap-3">
					<span className="rounded-full border bg-muted/60 px-3 py-1 text-xs text-muted-foreground">
						{t('platformAudit.total', {
							count: tree?.total_conversations ?? 0,
						})}
					</span>
					<Button variant="outline" size="sm" onClick={() => void refresh()}>
						<RefreshCw className={cn('size-4', treeLoading && 'animate-spin')} />
						{t('platformAudit.refresh')}
					</Button>
				</div>
			</header>

			{error && (
				<div className="mx-5 mt-4 rounded-lg border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
					{error}
				</div>
			)}

			<div className="grid min-h-0 flex-1 grid-cols-[minmax(180px,0.72fr)_minmax(200px,0.85fr)_minmax(240px,1fr)_minmax(440px,2fr)] gap-3 overflow-x-auto p-4">
				<section className="flex min-h-0 min-w-[180px] flex-col overflow-hidden rounded-xl border bg-background">
					<div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 text-sm font-semibold">
						<UserRound className="size-4 text-muted-foreground" />
						{t('platformAudit.users')}
					</div>
					<div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
						{treeLoading && !tree ? (
							<div className="flex justify-center py-8">
								<Loader2 className="size-5 animate-spin text-muted-foreground" />
							</div>
						) : tree?.users.length ? (
							tree.users.map((user) => (
								<button
									type="button"
									key={user.user_id}
									onClick={() => {
										setSelectedUserId(user.user_id);
										setSelectedProjectId(null);
										setSelectedSessionId(null);
										setTranscript(null);
									}}
									className={cn(
										'w-full rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors',
										selectedUserId === user.user_id
											? 'border-primary/20 bg-primary/8'
											: 'hover:bg-muted/70',
									)}
								>
									<div className="truncate text-sm font-medium">{user.display_name}</div>
									<div className="mt-1 truncate text-xs text-muted-foreground">
										{user.username} ·{' '}
										{t('platformAudit.projectCount', {
											count: user.projects.length,
										})}
									</div>
								</button>
							))
						) : (
							<p className="px-3 py-8 text-center text-xs text-muted-foreground">
								{t('platformAudit.empty')}
							</p>
						)}
					</div>
				</section>

				<section className="flex min-h-0 min-w-[200px] flex-col overflow-hidden rounded-xl border bg-background">
					<div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 text-sm font-semibold">
						<FolderKanban className="size-4 text-muted-foreground" />
						{t('platformAudit.projects')}
					</div>
					<div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
						{selectedUser ? (
							selectedUser.projects.map((project) => (
								<button
									type="button"
									key={project.project_id}
									onClick={() => {
										setSelectedProjectId(project.project_id);
										setSelectedSessionId(null);
										setTranscript(null);
									}}
									className={cn(
										'w-full rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors',
										selectedProjectId === project.project_id
											? 'border-primary/20 bg-primary/8'
											: 'hover:bg-muted/70',
									)}
								>
									<div className="line-clamp-2 text-sm font-medium">
										{project.project_name}
									</div>
									<div className="mt-1 text-xs text-muted-foreground">
										{t('platformAudit.conversationCount', {
											count: project.conversations.length,
										})}
									</div>
								</button>
							))
						) : (
							<p className="px-3 py-8 text-center text-xs text-muted-foreground">
								{t('platformAudit.selectUser')}
							</p>
						)}
					</div>
				</section>

				<section className="flex min-h-0 min-w-[240px] flex-col overflow-hidden rounded-xl border bg-background">
					<div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 text-sm font-semibold">
						<MessageSquareText className="size-4 text-muted-foreground" />
						{t('platformAudit.conversations')}
					</div>
					<div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
						{selectedProject ? (
							selectedProject.conversations.map((conversation) => (
								<button
									type="button"
									key={conversation.session_id}
									onClick={() => {
										setSelectedSessionId(conversation.session_id);
										setTranscript(null);
										void loadMessages(conversation.session_id);
									}}
									className={cn(
										'w-full rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors',
										selectedSessionId === conversation.session_id
											? 'border-primary/20 bg-primary/8'
											: 'hover:bg-muted/70',
									)}
								>
									<div className="flex items-start justify-between gap-2">
										<div className="line-clamp-2 text-sm font-medium">
											{conversation.title}
										</div>
										<span
											className={cn(
												'mt-1 size-2 shrink-0 rounded-full',
												conversation.is_running
													? 'animate-pulse bg-emerald-500'
													: 'bg-muted-foreground/35',
											)}
										/>
									</div>
									<div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
										<Bot className="size-3.5" />
										<span className="truncate">{conversation.agent_name}</span>
									</div>
									<div className="mt-1 text-xs text-muted-foreground">
										{formatDateTime(conversation.updated_at)}
									</div>
								</button>
							))
						) : (
							<p className="px-3 py-8 text-center text-xs text-muted-foreground">
								{t('platformAudit.selectProject')}
							</p>
						)}
					</div>
				</section>

				<section className="flex min-h-0 min-w-[440px] flex-col overflow-hidden rounded-xl border bg-background">
					<div className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b px-4 py-3">
						<div className="min-w-0">
							<h2 className="truncate text-sm font-semibold">
								{selectedConversation?.title ?? t('platformAudit.transcript')}
							</h2>
							<p className="mt-1 truncate text-xs text-muted-foreground">
								{selectedConversation
									? `${selectedUser?.display_name} · ${selectedProject?.project_name} · ${selectedConversation.agent_name}`
									: t('platformAudit.selectConversation')}
							</p>
						</div>
						<span className="shrink-0 rounded-full border bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground">
							{t('platformAudit.readOnly')}
						</span>
					</div>

					<div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
						{messagesLoading ? (
							<div className="flex h-full items-center justify-center">
								<Loader2 className="size-6 animate-spin text-muted-foreground" />
							</div>
						) : transcript ? (
							transcript.messages.length ? (
								<div className="mx-auto w-full max-w-4xl">
									{transcript.messages.map((message) => {
										const files = (message as MessageWithMetadata).metadata
											?.platform_initialization_files;
										return (
											<div key={message.id}>
												<MessageBubble message={message} />
												{message.role === 'user' && files?.length ? (
													<div className="mb-4 ml-auto flex max-w-[82%] flex-wrap justify-end gap-2 px-2">
														{files.map((file) => (
															<span
																key={file.id}
																className="rounded-md border bg-muted/45 px-2.5 py-1.5 text-xs text-muted-foreground"
															>
																{file.name} · {formatFileSize(file.size)}
															</span>
														))}
													</div>
												) : null}
											</div>
										);
									})}
									{transcript.is_running && (
										<div className="flex items-center justify-center gap-2 py-3 text-xs text-emerald-700">
											<Loader2 className="size-4 animate-spin" />
											{t('platformAudit.running')}
										</div>
									)}
								</div>
							) : (
								<div className="flex h-full items-center justify-center text-sm text-muted-foreground">
									{t('platformAudit.noMessages')}
								</div>
							)
						) : (
							<div className="flex h-full flex-col items-center justify-center text-center">
								<div className="rounded-2xl bg-muted p-4">
									<MessageSquareText className="size-7 text-muted-foreground" />
								</div>
								<p className="mt-4 text-sm font-medium">
									{t('platformAudit.selectConversation')}
								</p>
								<p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
									{t('platformAudit.selectConversationHint')}
								</p>
							</div>
						)}
					</div>
				</section>
			</div>
		</div>
	);
}
