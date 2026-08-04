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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
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
	const [transcript, setTranscript] =
		useState<PlatformAuditMessagesResponse | null>(null);
	const [treeLoading, setTreeLoading] = useState(true);
	const [messagesLoading, setMessagesLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const loadTree = useCallback(async () => {
		setTreeLoading(true);
		try {
			setTree(await platformAuditApi.tree());
			setError(null);
		} catch (requestError) {
			setError(
				requestError instanceof Error ? requestError.message : String(requestError),
			);
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
			setError(
				requestError instanceof Error ? requestError.message : String(requestError),
			);
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
			selectedUser?.projects.find(
				(item) => item.project_id === selectedProjectId,
			) ?? null,
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

	const selectUser = (userId: string) => {
		setSelectedUserId(userId);
		setSelectedProjectId(null);
		setSelectedSessionId(null);
		setTranscript(null);
	};

	const selectProject = (projectId: string) => {
		setSelectedProjectId(projectId);
		setSelectedSessionId(null);
		setTranscript(null);
	};

	const selectConversation = (sessionId: string) => {
		setSelectedSessionId(sessionId);
		setTranscript(null);
		void loadMessages(sessionId);
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
				<div className="mx-4 mt-4 rounded-lg border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive">
					{error}
				</div>
			)}

			<main className="grid min-h-0 flex-1 grid-cols-[19rem_minmax(28rem,1fr)] gap-3 overflow-x-auto p-4">
				<aside className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-background">
					<div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
						<div className="flex items-center gap-2 text-sm font-semibold">
							<Eye className="size-4 text-muted-foreground" />
							{t('platformAudit.scope')}
						</div>
						{treeLoading && !tree && (
							<Loader2 className="size-4 animate-spin text-muted-foreground" />
						)}
					</div>

					<div className="space-y-3 border-b bg-muted/20 p-3">
						<div className="space-y-1.5">
							<label
								htmlFor="audit-user"
								className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
							>
								<UserRound className="size-3.5" />
								{t('platformAudit.users')}
							</label>
							<Select
								value={selectedUserId ?? ''}
								onValueChange={selectUser}
								disabled={!tree?.users.length}
							>
								<SelectTrigger id="audit-user" className="w-full">
									<SelectValue placeholder={t('platformAudit.selectUser')} />
								</SelectTrigger>
								<SelectContent
									position="popper"
									align="start"
									sideOffset={4}
									className="w-max min-w-(--radix-select-trigger-width) [&_[data-position=popper]]:h-auto"
								>
									{tree?.users.map((user) => (
										<SelectItem
											key={user.user_id}
											value={user.user_id}
											textValue={`${user.display_name} · ${user.username}`}
										>
											<span className="whitespace-nowrap">
												{user.display_name} · {user.username}
											</span>
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="space-y-1.5">
							<label
								htmlFor="audit-project"
								className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
							>
								<FolderKanban className="size-3.5" />
								{t('platformAudit.projects')}
							</label>
							<Select
								value={selectedProjectId ?? ''}
								onValueChange={selectProject}
								disabled={!selectedUser || !selectedUser.projects.length}
							>
								<SelectTrigger
									id="audit-project"
									className="min-h-12 w-full py-1.5 data-[size=default]:h-auto *:data-[slot=select-value]:line-clamp-none"
								>
									<SelectValue placeholder={t('platformAudit.selectProject')}>
										{selectedProject ? (
											<span className="line-clamp-2 min-w-0 flex-1 whitespace-normal text-left leading-5">
												{selectedProject.project_name}
											</span>
										) : undefined}
									</SelectValue>
								</SelectTrigger>
								<SelectContent
									position="popper"
									align="start"
									sideOffset={4}
									className="w-max min-w-(--radix-select-trigger-width) [&_[data-position=popper]]:h-auto"
								>
									{selectedUser?.projects.map((project) => (
										<SelectItem
											key={project.project_id}
											value={project.project_id}
											textValue={project.project_name}
										>
											<span className="whitespace-nowrap">
												{project.project_name}
											</span>
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
					</div>

					<section className="flex min-h-0 flex-1 flex-col">
						<div className="flex h-11 shrink-0 items-center justify-between border-b px-3">
							<div className="flex items-center gap-2 text-sm font-semibold">
								<MessageSquareText className="size-4 text-muted-foreground" />
								{t('platformAudit.conversations')}
							</div>
							{selectedProject && (
								<span className="text-xs tabular-nums text-muted-foreground">
									{selectedProject.conversations.length}
								</span>
							)}
						</div>

						<div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
							{treeLoading && !tree ? (
								<div className="flex justify-center py-8">
									<Loader2 className="size-5 animate-spin text-muted-foreground" />
								</div>
							) : !tree?.users.length ? (
								<p className="px-3 py-8 text-center text-xs text-muted-foreground">
									{t('platformAudit.empty')}
								</p>
							) : selectedProject ? (
								selectedProject.conversations.length ? (
									selectedProject.conversations.map((conversation) => (
										<button
											type="button"
											key={conversation.session_id}
											onClick={() => selectConversation(conversation.session_id)}
											className={cn(
												'w-full rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors active:translate-y-px',
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
											<div className="mt-1 text-xs tabular-nums text-muted-foreground">
												{formatDateTime(conversation.updated_at)}
											</div>
										</button>
									))
								) : (
									<p className="px-3 py-8 text-center text-xs text-muted-foreground">
										{t('platformAudit.noConversations')}
									</p>
								)
							) : (
								<p className="px-3 py-8 text-center text-xs text-muted-foreground">
									{selectedUser
										? t('platformAudit.selectProject')
										: t('platformAudit.selectUser')}
								</p>
							)}
						</div>
					</section>
				</aside>

				<section className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-background">
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
			</main>
		</div>
	);
}
