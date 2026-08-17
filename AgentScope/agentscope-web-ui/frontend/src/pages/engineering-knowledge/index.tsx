import {
	Cloud,
	CheckCircle2,
	Bot,
	Database,
	Download,
	Eye,
	EyeOff,
	ExternalLink,
	FileText,
	Globe,
	Link2,
	Loader2,
	LockKeyhole,
	MessageSquareText,
	RefreshCw,
	Save,
	Search,
	Server,
	ShieldCheck,
	Trash2,
	TriangleAlert,
	Upload,
	WifiOff,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { agentApi } from '@/api';
import type {
	UpdateWeKnoraConnectionRequest,
	WeKnoraConnection,
	WeKnoraKnowledgeBase,
	WeKnoraKnowledgeItem,
	WeKnoraSearchReference,
} from '@/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import {
	Empty,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import {
	InputGroup,
	InputGroupAddon,
	InputGroupInput,
} from '@/components/ui/input-group';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';

type SectionKey = 'knowledge' | 'assistant' | 'connection';

const DEFAULT_WEKNORA_BASE_URL = 'http://uy8rk3wy.duankouyingshe.net';
const DEFAULT_WEKNORA_AGENT_ID = 'be4c1c12-2c0f-4fd1-ac5c-0663bc86d356';
const SAVED_API_KEY_MASK = '************';

function formatFileSize(size: number | null) {
	if (size === null || size < 0) return '';
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
	if (size < 1024 * 1024 * 1024) {
		return `${(size / 1024 / 1024).toFixed(1)} MB`;
	}
	return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatTimestamp(value: string | null) {
	if (!value) return '';
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return date.toLocaleString();
}

export function EngineeringKnowledgePage() {
	const { t } = useTranslation();
	const [activeSection, setActiveSection] =
		useState<SectionKey>('knowledge');
	const [connection, setConnection] = useState<WeKnoraConnection | null>(null);
	const [baseUrl, setBaseUrl] = useState(DEFAULT_WEKNORA_BASE_URL);
	const [apiPrefix, setApiPrefix] = useState('/api/v1');
	const [authHeader, setAuthHeader] = useState('X-API-Key');
	const [agentId, setAgentId] = useState(DEFAULT_WEKNORA_AGENT_ID);
	const [apiKey, setApiKey] = useState('');
	const [savedApiKey, setSavedApiKey] = useState<string | null>(null);
	const [showApiKey, setShowApiKey] = useState(false);
	const [revealingApiKey, setRevealingApiKey] = useState(false);
	const [connectionLoading, setConnectionLoading] = useState(true);
	const [savingConnection, setSavingConnection] = useState(false);
	const [testingConnection, setTestingConnection] = useState(false);
	const [lastTestMessage, setLastTestMessage] = useState('');
	const [knowledgeBases, setKnowledgeBases] = useState<WeKnoraKnowledgeBase[]>([]);
	const [knowledgeBasesLoading, setKnowledgeBasesLoading] = useState(false);
	const [knowledgeBasesError, setKnowledgeBasesError] = useState('');
	const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState('');
	const [knowledge, setKnowledge] = useState<WeKnoraKnowledgeItem[]>([]);
	const [knowledgeTotal, setKnowledgeTotal] = useState(0);
	const [knowledgeLoading, setKnowledgeLoading] = useState(false);
	const [knowledgeError, setKnowledgeError] = useState('');
	const [documentQuery, setDocumentQuery] = useState('');
	const [searchQuery, setSearchQuery] = useState('');
	const [searching, setSearching] = useState(false);
	const [searchResults, setSearchResults] = useState<WeKnoraSearchReference[]>([]);
	const [uploading, setUploading] = useState(false);
	const uploadInputRef = useRef<HTMLInputElement>(null);
	const [urlDialogOpen, setUrlDialogOpen] = useState(false);
	const [urlValue, setUrlValue] = useState('');
	const [urlTitle, setUrlTitle] = useState('');
	const [submittingUrl, setSubmittingUrl] = useState(false);
	const [agentQuery, setAgentQuery] = useState('');
	const [agentAnswer, setAgentAnswer] = useState('');
	const [agentReferences, setAgentReferences] = useState<Record<string, unknown>[]>([]);
	const [agentSessionId, setAgentSessionId] = useState('');
	const [agentQuerying, setAgentQuerying] = useState(false);

	const loadKnowledge = useCallback(async (knowledgeBaseId: string) => {
		setKnowledgeLoading(true);
		setKnowledgeError('');
		try {
			const response = await agentApi.listWeKnoraKnowledge(knowledgeBaseId, {
				page: 1,
				page_size: 50,
			});
			setKnowledge(response.knowledge);
			setKnowledgeTotal(response.total);
		} catch (error) {
			setKnowledge([]);
			setKnowledgeTotal(0);
			setKnowledgeError(
				error instanceof Error ? error.message : 'Unable to load knowledge',
			);
		} finally {
			setKnowledgeLoading(false);
		}
	}, []);

	const loadKnowledgeBases = useCallback(
		async (preferredId?: string) => {
			setKnowledgeBasesLoading(true);
			setKnowledgeBasesError('');
			try {
				const response = await agentApi.listWeKnoraKnowledgeBases();
				setKnowledgeBases(response.knowledge_bases);
				const nextId =
					response.knowledge_bases.find(
						(item) => item.id === preferredId,
					)?.id ??
					response.knowledge_bases[0]?.id ??
					'';
				setSelectedKnowledgeBaseId(nextId);
				if (nextId) {
					await loadKnowledge(nextId);
				} else {
					setKnowledge([]);
					setKnowledgeTotal(0);
				}
			} catch (error) {
				setKnowledgeBases([]);
				setKnowledge([]);
				setKnowledgeTotal(0);
				setKnowledgeBasesError(
					error instanceof Error
						? error.message
						: 'Unable to load knowledge bases',
				);
			} finally {
				setKnowledgeBasesLoading(false);
			}
		},
		[loadKnowledge],
	);

	useEffect(() => {
		let active = true;
		agentApi
			.getWeKnoraConnection()
			.then((value) => {
				if (!active) return;
				setConnection(value);
				setBaseUrl(value.base_url || DEFAULT_WEKNORA_BASE_URL);
				setApiPrefix(value.api_prefix);
				setAuthHeader(value.auth_header);
				setAgentId(value.agent_id || DEFAULT_WEKNORA_AGENT_ID);
				setApiKey(value.api_key_configured ? SAVED_API_KEY_MASK : '');
				setSavedApiKey(null);
				setShowApiKey(false);
				if (value.api_key_configured) void loadKnowledgeBases();
			})
			.catch(() => undefined)
			.finally(() => {
				if (active) setConnectionLoading(false);
			});
		return () => {
			active = false;
		};
	}, [loadKnowledgeBases]);

	const connectionConfigured = connection?.api_key_configured ?? false;
	const apiKeyChanged = connectionConfigured
		? apiKey !== SAVED_API_KEY_MASK && apiKey !== savedApiKey
		: Boolean(apiKey);
	const connectionDirty = Boolean(
		apiKeyChanged ||
			baseUrl !== (connection?.base_url ?? '') ||
			apiPrefix !== (connection?.api_prefix ?? '/api/v1') ||
			authHeader !== (connection?.auth_header ?? 'X-API-Key') ||
			agentId !== (connection?.agent_id ?? ''),
	);
	const connectionValid = Boolean(
		baseUrl.trim() &&
			apiPrefix.trim() &&
			authHeader.trim() &&
			agentId.trim() &&
			(connectionConfigured || Boolean(apiKey)),
	);
	const connectionPayload = (): UpdateWeKnoraConnectionRequest => ({
		base_url: baseUrl.trim(),
		api_prefix: apiPrefix.trim(),
		auth_header: authHeader.trim(),
		agent_id: agentId.trim(),
		...(apiKeyChanged ? { api_key: apiKey } : {}),
	});

	const toggleApiKeyVisibility = async () => {
		if (showApiKey) {
			if (connectionConfigured && savedApiKey !== null && apiKey === savedApiKey) {
				setApiKey(SAVED_API_KEY_MASK);
				setSavedApiKey(null);
			}
			setShowApiKey(false);
			return;
		}
		if (connectionConfigured && apiKey === SAVED_API_KEY_MASK) {
			setRevealingApiKey(true);
			try {
				const result = await agentApi.revealWeKnoraApiKey();
				setApiKey(result.api_key);
				setSavedApiKey(result.api_key);
				setShowApiKey(true);
			} finally {
				setRevealingApiKey(false);
			}
			return;
		}
		setShowApiKey(true);
	};

	const saveConnection = async () => {
		if (!connectionValid) return;
		setSavingConnection(true);
		try {
			const updated = await agentApi.updateWeKnoraConnection(
				connectionPayload(),
			);
			setConnection(updated);
			setBaseUrl(updated.base_url);
			setApiPrefix(updated.api_prefix);
			setAuthHeader(updated.auth_header);
			setAgentId(updated.agent_id);
			setApiKey(SAVED_API_KEY_MASK);
			setSavedApiKey(null);
			setShowApiKey(false);
			setLastTestMessage('');
			toast.success(t('engineeringKnowledge.connection.saved'));
			await loadKnowledgeBases(selectedKnowledgeBaseId || undefined);
		} finally {
			setSavingConnection(false);
		}
	};

	const testConnection = async () => {
		if (!connectionValid) return;
		setTestingConnection(true);
		setLastTestMessage('');
		try {
			const result = await agentApi.testWeKnoraConnection(connectionPayload());
			setLastTestMessage(result.message);
			toast.success(result.message);
		} finally {
			setTestingConnection(false);
		}
	};

	const runKnowledgeSearch = async () => {
		const query = searchQuery.trim();
		if (!selectedKnowledgeBaseId || !query) return;
		setSearching(true);
		try {
			const result = await agentApi.searchWeKnoraKnowledge(
				selectedKnowledgeBaseId,
				{ query, top_k: 5, vector_threshold: 0.5, keyword_threshold: 0.3 },
			);
			setSearchResults(result.references);
			if (result.references.length === 0) {
				toast.info(t('engineeringKnowledge.knowledge.searchEmpty'));
			}
		} finally {
			setSearching(false);
		}
	};

	const uploadKnowledge = async (file: File) => {
		if (!selectedKnowledgeBaseId) return;
		setUploading(true);
		try {
			const result = await agentApi.uploadWeKnoraKnowledge(
				selectedKnowledgeBaseId,
				file,
			);
			toast.success(result.message);
			await loadKnowledge(selectedKnowledgeBaseId);
		} catch (error) {
			toast.error(
				error instanceof Error
					? error.message
					: t('engineeringKnowledge.knowledge.uploadFailed'),
			);
		} finally {
			setUploading(false);
			if (uploadInputRef.current) uploadInputRef.current.value = '';
		}
	};

	const submitUrlKnowledge = async () => {
		if (!selectedKnowledgeBaseId || !urlValue.trim()) return;
		setSubmittingUrl(true);
		try {
			const result = await agentApi.createWeKnoraUrlKnowledge(
				selectedKnowledgeBaseId,
				{
					url: urlValue.trim(),
					title: urlTitle.trim() || undefined,
					enable_multimodel: true,
				},
			);
			toast.success(result.message);
			setUrlDialogOpen(false);
			setUrlValue('');
			setUrlTitle('');
			await loadKnowledge(selectedKnowledgeBaseId);
		} finally {
			setSubmittingUrl(false);
		}
	};

	const deleteKnowledge = async (item: WeKnoraKnowledgeItem) => {
		const label = item.file_name || item.title || item.id;
		if (!window.confirm(t('engineeringKnowledge.knowledge.deleteConfirm', { name: label }))) {
			return;
		}
		await agentApi.deleteWeKnoraKnowledge(item.id);
		toast.success(t('engineeringKnowledge.knowledge.deleted'));
		await loadKnowledge(selectedKnowledgeBaseId);
	};

	const openKnowledgeContent = async (
		knowledgeId: string,
		mode: 'download' | 'preview',
		filename = '',
	) => {
		const response =
			mode === 'download'
				? await agentApi.downloadWeKnoraKnowledge(knowledgeId)
				: await agentApi.previewWeKnoraKnowledge(knowledgeId);
		const blob = await response.blob();
		const objectUrl = URL.createObjectURL(blob);
		if (mode === 'download') {
			const anchor = document.createElement('a');
			anchor.href = objectUrl;
			anchor.download = filename || knowledgeId;
			anchor.click();
		} else {
			window.open(objectUrl, '_blank', 'noopener,noreferrer');
		}
		window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
	};

	const runAgentQuery = async () => {
		const query = agentQuery.trim();
		if (!query) return;
		setAgentQuerying(true);
		try {
			const result = await agentApi.askWeKnoraAgent({
				query,
				knowledge_base_ids: selectedKnowledgeBaseId
					? [selectedKnowledgeBaseId]
					: undefined,
				session_id: agentSessionId || undefined,
			});
			setAgentSessionId(result.session_id);
			setAgentAnswer(result.answer);
			setAgentReferences(result.references);
		} finally {
			setAgentQuerying(false);
		}
	};

	const sectionItems = [
		{
			key: 'knowledge' as const,
			icon: Database,
			title: t('engineeringKnowledge.sections.knowledge.title'),
			description: t('engineeringKnowledge.sections.knowledge.description'),
			status: !connectionConfigured
				? t('engineeringKnowledge.sections.knowledge.status')
				: knowledgeBasesLoading
					? t('engineeringKnowledge.sections.knowledge.loading')
					: knowledgeBasesError
						? t('engineeringKnowledge.sections.knowledge.failed')
						: t('engineeringKnowledge.sections.knowledge.synced', {
							count: knowledgeBases.length,
						}),
		},
		{
			key: 'assistant' as const,
			icon: Bot,
			title: t('engineeringKnowledge.sections.assistant.title'),
			description: t('engineeringKnowledge.sections.assistant.description'),
			status:
				connectionConfigured && agentId.trim()
					? t('engineeringKnowledge.sections.assistant.ready')
					: t('engineeringKnowledge.sections.assistant.status'),
		},
		{
			key: 'connection' as const,
			icon: Server,
			title: t('engineeringKnowledge.sections.connection.title'),
			description: t('engineeringKnowledge.sections.connection.description'),
			status: connectionConfigured
				? t('engineeringKnowledge.sections.connection.configured')
				: t('engineeringKnowledge.sections.connection.status'),
		},
	];
	const selectedKnowledgeBase = knowledgeBases.find(
		(item) => item.id === selectedKnowledgeBaseId,
	);
	const normalisedDocumentQuery = documentQuery.trim().toLocaleLowerCase();
	const visibleKnowledge = normalisedDocumentQuery
		? knowledge.filter((item) =>
				[
					item.title,
					item.file_name,
					item.description,
					item.file_type,
					item.type,
					item.source,
				]
					.join(' ')
					.toLocaleLowerCase()
					.includes(normalisedDocumentQuery),
			)
		: knowledge;

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-background px-5 py-3">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<Database className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">
							{t('engineeringKnowledge.title')}
						</h1>
						<Badge variant="outline">WeKnora</Badge>
					</div>
					<p className="mt-1 text-xs text-muted-foreground">
						{t('engineeringKnowledge.subtitle')}
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Badge variant="secondary" className="gap-1.5">
						<Cloud className="size-3.5" />
						{t('engineeringKnowledge.independentSource')}
					</Badge>
					<Badge variant="outline" className="gap-1.5">
						<ShieldCheck className="size-3.5" />
						HTTP(S)
					</Badge>
				</div>
			</header>

			<main className="flex min-h-0 flex-1 p-4">
				<div className="grid min-h-0 min-w-0 flex-1 overflow-hidden rounded-xl border bg-background lg:grid-cols-[18rem_minmax(0,1fr)]">
					<aside className="flex min-h-0 flex-col border-b bg-muted/20 lg:border-r lg:border-b-0">
						<div className="border-b px-5 py-5">
							<div className="flex items-center justify-between gap-3">
								<h2 className="font-semibold">
									{t('engineeringKnowledge.navigation.title')}
								</h2>
								<Badge variant="secondary">
									{t('engineeringKnowledge.navigation.phase')}
								</Badge>
							</div>
							<p className="mt-1 text-sm leading-relaxed text-muted-foreground">
								{t('engineeringKnowledge.navigation.description')}
							</p>
						</div>

						<nav
							aria-label={t('engineeringKnowledge.navigation.title')}
							className="grid gap-2 overflow-y-auto p-3 sm:grid-cols-2 lg:grid-cols-1"
						>
							{sectionItems.map((item) => {
								const ItemIcon = item.icon;
								const active = activeSection === item.key;
								return (
									<button
										key={item.key}
										type="button"
										aria-pressed={active}
										onClick={() => setActiveSection(item.key)}
										className={`group rounded-xl border px-3.5 py-3 text-left transition-all duration-200 active:translate-y-px ${
											active
												? 'border-primary/30 bg-primary/5 shadow-sm'
												: 'border-transparent hover:border-border hover:bg-background'
										}`}
									>
										<div className="flex items-start gap-3">
											<div
												className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
													active
														? 'bg-primary text-primary-foreground'
														: 'bg-muted text-muted-foreground group-hover:text-foreground'
												}`}
											>
												<ItemIcon className="size-4" />
											</div>
											<div className="min-w-0 flex-1">
												<span className="block truncate text-sm font-semibold">
													{item.title}
												</span>
												<p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
													{item.description}
												</p>
												<div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
													<span className="size-1.5 rounded-full bg-amber-500" />
													{item.status}
												</div>
											</div>
										</div>
									</button>
								);
							})}
						</nav>
					</aside>

					<section className="flex min-h-0 flex-col">
						{activeSection === 'knowledge' && (
							<div className="flex min-h-0 flex-1 flex-col">
								<header className="flex flex-wrap items-start justify-between gap-4 border-b px-6 py-5 sm:px-8 sm:py-6">
									<div className="flex min-w-0 items-start gap-3">
										<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted">
											<Database className="size-5" />
										</div>
										<div>
											<p className="text-xs font-medium tracking-wide text-muted-foreground">
												{t('engineeringKnowledge.knowledge.eyebrow')}
											</p>
											<h2 className="mt-1 text-xl font-semibold">
												{t('engineeringKnowledge.knowledge.title')}
											</h2>
											<p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
												{t('engineeringKnowledge.knowledge.description')}
											</p>
										</div>
									</div>
									<div className="flex items-center gap-2">
										<Button
											variant="outline"
											disabled={!connectionConfigured || knowledgeBasesLoading}
											onClick={() =>
												void loadKnowledgeBases(
													selectedKnowledgeBaseId || undefined,
												)
											}
										>
											<RefreshCw
												className={knowledgeBasesLoading ? 'animate-spin' : ''}
											/>
											{t('engineeringKnowledge.knowledge.refresh')}
										</Button>
										<Button
											variant="outline"
											disabled={!selectedKnowledgeBaseId}
											onClick={() => setUrlDialogOpen(true)}
										>
											<Globe />
											{t('engineeringKnowledge.knowledge.addUrl')}
										</Button>
										<Button
											disabled={!selectedKnowledgeBaseId || uploading}
											onClick={() => uploadInputRef.current?.click()}
										>
											{uploading ? <Loader2 className="animate-spin" /> : <Upload />}
											{t('engineeringKnowledge.knowledge.upload')}
										</Button>
										<input
											ref={uploadInputRef}
											type="file"
											className="hidden"
											onChange={(event) => {
												const file = event.target.files?.[0];
												if (file) void uploadKnowledge(file);
											}}
										/>
									</div>
								</header>

								<div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 sm:px-8">
									{!connectionConfigured ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon">
													<Server />
												</EmptyMedia>
												<EmptyTitle>
													{t('engineeringKnowledge.knowledge.connectTitle')}
												</EmptyTitle>
												<EmptyDescription>
													{t('engineeringKnowledge.knowledge.connectDescription')}
												</EmptyDescription>
											</EmptyHeader>
											<Button onClick={() => setActiveSection('connection')}>
												<Link2 />
												{t('engineeringKnowledge.knowledge.connectAction')}
											</Button>
										</Empty>
									) : knowledgeBasesLoading && knowledgeBases.length === 0 ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon">
													<Loader2 className="animate-spin" />
												</EmptyMedia>
												<EmptyTitle>
													{t('engineeringKnowledge.knowledge.loadingTitle')}
												</EmptyTitle>
												<EmptyDescription>
													{t('engineeringKnowledge.knowledge.loadingDescription')}
												</EmptyDescription>
											</EmptyHeader>
										</Empty>
									) : knowledgeBasesError ? (
										<Alert variant="destructive">
											<WifiOff />
											<AlertTitle>
												{t('engineeringKnowledge.knowledge.loadFailedTitle')}
											</AlertTitle>
											<AlertDescription className="space-y-3">
												<p>{knowledgeBasesError}</p>
												<Button
													variant="outline"
													onClick={() => void loadKnowledgeBases()}
												>
													<RefreshCw />
													{t('engineeringKnowledge.knowledge.retry')}
												</Button>
											</AlertDescription>
										</Alert>
									) : knowledgeBases.length === 0 ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon">
													<Database />
												</EmptyMedia>
												<EmptyTitle>
													{t('engineeringKnowledge.knowledge.remoteEmptyTitle')}
												</EmptyTitle>
												<EmptyDescription>
													{t(
														'engineeringKnowledge.knowledge.remoteEmptyDescription',
													)}
												</EmptyDescription>
											</EmptyHeader>
										</Empty>
									) : (
										<div className="space-y-4">
											<section className="rounded-xl border bg-background">
												<div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
													<div className="flex min-w-0 items-start gap-3.5">
														<div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/8 text-primary ring-1 ring-primary/10">
															<Database className="size-5" />
														</div>
														<div className="min-w-0">
															<div className="flex flex-wrap items-center gap-2">
																<p className="text-xs font-medium tracking-wide text-muted-foreground">
																	{t('engineeringKnowledge.knowledge.currentBase')}
																</p>
																<Badge variant="outline" className="bg-muted/30 font-normal">
																	WeKnora
																</Badge>
															</div>
															<h3 className="mt-1 truncate text-base font-semibold tracking-tight">
																{selectedKnowledgeBase?.name || selectedKnowledgeBaseId}
															</h3>
															<p className="mt-1 line-clamp-1 max-w-2xl text-sm text-muted-foreground">
																{selectedKnowledgeBase?.description ||
																	t('engineeringKnowledge.knowledge.remoteManaged')}
															</p>
														</div>
													</div>
													<div className="flex shrink-0 items-center gap-2">
														<div className="hidden items-baseline gap-1.5 border-r pr-3 sm:flex">
															<span className="font-mono text-base font-semibold tabular-nums">
																{knowledgeBases.length}
															</span>
															<span className="text-xs text-muted-foreground">
																{t('engineeringKnowledge.knowledge.availableBases')}
															</span>
														</div>
														<Select
															value={selectedKnowledgeBaseId}
															onValueChange={(knowledgeBaseId) => {
																setSelectedKnowledgeBaseId(knowledgeBaseId);
																setDocumentQuery('');
																void loadKnowledge(knowledgeBaseId);
															}}
														>
															<SelectTrigger
																aria-label={t('engineeringKnowledge.knowledge.switchBase')}
																className="h-9 w-full bg-background sm:w-72"
															>
																<SelectValue />
															</SelectTrigger>
															<SelectContent>
																{knowledgeBases.map((knowledgeBase) => (
																	<SelectItem key={knowledgeBase.id} value={knowledgeBase.id}>
																		{knowledgeBase.name || knowledgeBase.id}
																	</SelectItem>
																))}
															</SelectContent>
														</Select>
													</div>
												</div>
											</section>

											<section className="rounded-xl border bg-background p-5">
												<div className="flex flex-col gap-3 sm:flex-row sm:items-end">
													<div className="min-w-0 flex-1">
														<Label htmlFor="weknora-search">
															{t('engineeringKnowledge.knowledge.searchTitle')}
														</Label>
														<p className="mt-1 text-sm text-muted-foreground">
															{t('engineeringKnowledge.knowledge.searchDescription')}
														</p>
														<InputGroup className="mt-3 bg-muted/20">
															<InputGroupAddon>
																<Search />
															</InputGroupAddon>
															<InputGroupInput
																id="weknora-search"
																value={searchQuery}
																onChange={(event) => setSearchQuery(event.target.value)}
																onKeyDown={(event) => {
																	if (event.key === 'Enter') void runKnowledgeSearch();
																}}
																placeholder={t('engineeringKnowledge.knowledge.searchQueryPlaceholder')}
															/>
														</InputGroup>
													</div>
													<Button
														disabled={!searchQuery.trim() || searching}
														onClick={() => void runKnowledgeSearch()}
													>
														{searching ? <Loader2 className="animate-spin" /> : <Search />}
														{t('engineeringKnowledge.knowledge.searchAction')}
													</Button>
												</div>
												{searchResults.length > 0 && (
													<div className="mt-4 space-y-3 border-t pt-4">
														{searchResults.map((reference, index) => (
															<div
																key={`${reference.knowledge_id}-${reference.chunk_index}-${index}`}
																className="rounded-lg border bg-muted/20 p-4"
															>
																<div className="flex flex-wrap items-center justify-between gap-2">
																	<div className="flex min-w-0 items-center gap-2">
																		<FileText className="size-4 shrink-0 text-primary" />
																		<span className="truncate text-sm font-semibold">
																			{reference.filename || reference.title || reference.knowledge_id}
																		</span>
																		<Badge variant="secondary">
																			{reference.score.toFixed(3)}
																		</Badge>
																	</div>
																	<div className="flex items-center gap-1">
																		<Button
																			variant="ghost"
																			size="sm"
																			onClick={() => void openKnowledgeContent(reference.knowledge_id, 'preview')}
																		>
																			<ExternalLink />
																			{t('engineeringKnowledge.knowledge.preview')}
																		</Button>
																		<Button
																			variant="ghost"
																			size="sm"
																			onClick={() => void openKnowledgeContent(reference.knowledge_id, 'download', reference.filename)}
																		>
																			<Download />
																			{t('engineeringKnowledge.knowledge.download')}
																		</Button>
																	</div>
																</div>
																<p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
																	{reference.content}
																</p>
															</div>
														))}
													</div>
												)}
											</section>

											<section className="min-w-0 overflow-hidden rounded-xl border bg-background">
												<div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
													<div className="min-w-0">
														<div className="flex items-center gap-2">
															<h3 className="text-base font-semibold tracking-tight">
																{t('engineeringKnowledge.knowledge.documentsTitle')}
															</h3>
															<Badge variant="secondary" className="font-mono tabular-nums">
																{knowledgeTotal}
															</Badge>
														</div>
														<p className="mt-1 text-sm text-muted-foreground">
															{t('engineeringKnowledge.knowledge.documentsHint')}
														</p>
													</div>
													<InputGroup className="h-9 bg-muted/20 sm:w-80">
														<InputGroupAddon>
															<Search />
														</InputGroupAddon>
														<InputGroupInput
															value={documentQuery}
															onChange={(event) => setDocumentQuery(event.target.value)}
															placeholder={t('engineeringKnowledge.knowledge.searchPlaceholder')}
															aria-label={t('engineeringKnowledge.knowledge.searchPlaceholder')}
														/>
													</InputGroup>
												</div>

												{knowledgeLoading ? (
													<div className="flex items-center justify-center gap-2 px-5 py-16 text-sm text-muted-foreground">
														<Loader2 className="animate-spin" />
														{t('engineeringKnowledge.knowledge.loadingDocuments')}
													</div>
												) : knowledgeError ? (
													<div className="p-4">
														<Alert variant="destructive">
															<WifiOff />
															<AlertTitle>
																{t('engineeringKnowledge.knowledge.documentsLoadFailed')}
															</AlertTitle>
															<AlertDescription className="space-y-3">
																<p>{knowledgeError}</p>
																<Button
																	variant="outline"
																	onClick={() => void loadKnowledge(selectedKnowledgeBaseId)}
																>
																	<RefreshCw />
																	{t('engineeringKnowledge.knowledge.retry')}
																</Button>
															</AlertDescription>
														</Alert>
													</div>
												) : knowledge.length === 0 ? (
													<Empty className="py-12">
														<EmptyHeader>
															<EmptyMedia variant="icon">
																<FileText />
															</EmptyMedia>
															<EmptyTitle>
																{t('engineeringKnowledge.knowledge.noDocumentsTitle')}
															</EmptyTitle>
															<EmptyDescription>
																{t('engineeringKnowledge.knowledge.noDocumentsDescription')}
															</EmptyDescription>
														</EmptyHeader>
													</Empty>
												) : visibleKnowledge.length === 0 ? (
													<Empty className="py-12">
														<EmptyHeader>
															<EmptyMedia variant="icon">
																<Search />
															</EmptyMedia>
															<EmptyTitle>
																{t('engineeringKnowledge.knowledge.noSearchResultsTitle')}
															</EmptyTitle>
															<EmptyDescription>
																{t('engineeringKnowledge.knowledge.noSearchResultsDescription')}
															</EmptyDescription>
														</EmptyHeader>
														<Button variant="outline" onClick={() => setDocumentQuery('')}>
															{t('engineeringKnowledge.knowledge.clearSearch')}
														</Button>
													</Empty>
												) : (
													<div className="divide-y">
														{visibleKnowledge.map((item) => {
															const title = item.title || item.file_name || item.id;
															const itemType = item.file_type || item.type;
															const statusName = item.parse_status.toLocaleLowerCase();
															const statusLabel = ['completed', 'pending', 'processing', 'finalizing', 'failed'].includes(
																statusName,
															)
																? t(`engineeringKnowledge.knowledge.parseStatus.${statusName}`)
																: item.parse_status;
															const statusClass =
																statusName === 'completed'
																	? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
																	: statusName === 'failed'
																		? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
																		: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300';
															const timestamp = formatTimestamp(
																item.processed_at || item.created_at,
															);
															const ItemIcon = item.type === 'url' ? Globe : FileText;
															return (
																<article
																	key={item.id}
																	className="group flex gap-4 px-5 py-4 transition-colors duration-200 hover:bg-muted/25"
																>
																	<div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/60 transition-colors group-hover:bg-background group-hover:text-foreground">
																		<ItemIcon className="size-4" />
																	</div>
																	<div className="min-w-0 flex-1">
																		<div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
																			<h4 className="min-w-0 flex-1 break-words text-sm font-semibold leading-5">
																				{title}
																			</h4>
																			<div className="flex flex-wrap items-center gap-1.5">
																				{itemType && (
																					<Badge variant="outline" className="bg-background font-mono uppercase">
																						{itemType}
																					</Badge>
																				)}
																				{item.parse_status && (
																					<Badge variant="outline" className={statusClass}>
																						<span className="mr-1 size-1.5 rounded-full bg-current" />
																						{statusLabel}
																					</Badge>
																				)}
																			</div>
																		</div>
																		{(item.description || item.source) && (
																			<p className="mt-1.5 line-clamp-2 break-words text-sm leading-6 text-muted-foreground">
																				{item.description || item.source}
																			</p>
																		)}
																		<div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
																			{formatFileSize(item.file_size) && (
																				<span>{formatFileSize(item.file_size)}</span>
																			)}
																			{formatFileSize(item.file_size) && item.channel && (
																				<span className="size-1 rounded-full bg-border" />
																			)}
																			{item.channel && <span>{item.channel}</span>}
																			{(formatFileSize(item.file_size) || item.channel) && timestamp && (
																				<span className="size-1 rounded-full bg-border" />
																			)}
																			{timestamp && <span>{timestamp}</span>}
																		</div>
																	</div>
																	<div className="flex shrink-0 items-start gap-1 opacity-80 transition-opacity group-hover:opacity-100">
																		<Button
																			variant="ghost"
																			size="icon-sm"
																			title={t('engineeringKnowledge.knowledge.preview')}
																			onClick={() => void openKnowledgeContent(item.id, 'preview')}
																		>
																			<ExternalLink />
																		</Button>
																		<Button
																			variant="ghost"
																			size="icon-sm"
																			title={t('engineeringKnowledge.knowledge.download')}
																			onClick={() => void openKnowledgeContent(item.id, 'download', item.file_name || item.title)}
																		>
																			<Download />
																		</Button>
																		<Button
																			variant="ghost"
																			size="icon-sm"
																			className="text-destructive hover:text-destructive"
																			title={t('engineeringKnowledge.knowledge.delete')}
																			onClick={() => void deleteKnowledge(item)}
																		>
																			<Trash2 />
																		</Button>
																	</div>
																</article>
															);
														})}
													</div>
												)}
											</section>
										</div>
									)}
								</div>
							</div>
						)}

						{activeSection === 'assistant' && (
							<div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 sm:px-8">
								<div className="mx-auto max-w-4xl space-y-5">
									<div className="flex items-start gap-3">
										<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted">
											<Bot className="size-5" />
										</div>
										<div>
											<p className="text-xs font-medium tracking-wide text-muted-foreground">
												{t('engineeringKnowledge.assistant.eyebrow')}
											</p>
											<h2 className="mt-1 text-xl font-semibold">
												{t('engineeringKnowledge.assistant.title')}
											</h2>
											<p className="mt-1 text-sm leading-relaxed text-muted-foreground">
												{t('engineeringKnowledge.assistant.description')}
											</p>
										</div>
									</div>

									{!connectionConfigured || !agentId.trim() ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon">
													<Bot />
												</EmptyMedia>
												<EmptyTitle>
													{t('engineeringKnowledge.assistant.notConfiguredTitle')}
												</EmptyTitle>
												<EmptyDescription>
													{t('engineeringKnowledge.assistant.notConfiguredDescription')}
												</EmptyDescription>
											</EmptyHeader>
											<Button onClick={() => setActiveSection('connection')}>
												<Link2 />
												{t('engineeringKnowledge.knowledge.connectAction')}
											</Button>
										</Empty>
									) : (
										<>
											<section className="rounded-xl border bg-background p-5">
												<div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_18rem]">
													<div>
														<Label htmlFor="weknora-agent-query">
															{t('engineeringKnowledge.assistant.queryLabel')}
														</Label>
														<Textarea
															id="weknora-agent-query"
															value={agentQuery}
															onChange={(event) => setAgentQuery(event.target.value)}
															placeholder={t('engineeringKnowledge.assistant.queryPlaceholder')}
															className="mt-2 min-h-28"
														/>
													</div>
													<div>
														<Label>{t('engineeringKnowledge.assistant.knowledgeBase')}</Label>
														<Select
															value={selectedKnowledgeBaseId}
															onValueChange={(value) => {
																setSelectedKnowledgeBaseId(value);
																setAgentSessionId('');
															}}
														>
															<SelectTrigger className="mt-2 w-full">
																<SelectValue placeholder={t('engineeringKnowledge.assistant.allKnowledgeBases')} />
															</SelectTrigger>
															<SelectContent>
																{knowledgeBases.map((knowledgeBase) => (
																	<SelectItem key={knowledgeBase.id} value={knowledgeBase.id}>
																		{knowledgeBase.name || knowledgeBase.id}
																	</SelectItem>
																))}
															</SelectContent>
														</Select>
														<div className="mt-4 rounded-lg bg-muted/40 p-3 text-sm text-muted-foreground">
															{t('engineeringKnowledge.assistant.agentId')}
															<span className="mt-1 block break-all font-mono text-foreground">
																{agentId}
															</span>
														</div>
													</div>
												</div>
												<div className="mt-4 flex justify-end">
													<Button
														disabled={!agentQuery.trim() || agentQuerying}
														onClick={() => void runAgentQuery()}
													>
														{agentQuerying ? <Loader2 className="animate-spin" /> : <MessageSquareText />}
														{t('engineeringKnowledge.assistant.ask')}
													</Button>
												</div>
											</section>

											{agentAnswer && (
												<section className="rounded-xl border bg-background p-5">
													<div className="flex items-center gap-2">
														<Bot className="size-4 text-primary" />
														<h3 className="text-base font-semibold">
															{t('engineeringKnowledge.assistant.answerTitle')}
														</h3>
													</div>
													<p className="mt-4 whitespace-pre-wrap text-sm leading-7">
														{agentAnswer}
													</p>
													{agentReferences.length > 0 && (
														<div className="mt-5 border-t pt-4">
															<p className="text-sm font-semibold">
																{t('engineeringKnowledge.assistant.referencesTitle')}
															</p>
															<div className="mt-2 space-y-2">
																{agentReferences.map((reference, index) => {
																	const title =
																		typeof reference.knowledge_title === 'string'
																			? reference.knowledge_title
																			: typeof reference.title === 'string'
																				? reference.title
																				: `${t('engineeringKnowledge.assistant.reference')} ${index + 1}`;
																	const content =
																		typeof reference.content === 'string' ? reference.content : '';
																	return (
																		<div key={`${title}-${index}`} className="rounded-lg bg-muted/40 p-3">
																			<p className="text-sm font-medium">{title}</p>
																			{content && (
																				<p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
																					{content}
																				</p>
																			)}
																		</div>
																	);
																})}
															</div>
														</div>
													)}
												</section>
											)}
										</>
									)}
								</div>
							</div>
						)}

						{activeSection === 'connection' && (
							<div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 sm:px-8">
								<div className="mx-auto max-w-3xl space-y-6">
									<div className="flex items-start gap-3">
										<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted">
											<Server className="size-5" />
										</div>
										<div>
											<p className="text-xs font-medium tracking-wide text-muted-foreground">
												{t('engineeringKnowledge.connection.eyebrow')}
											</p>
											<h2 className="mt-1 text-xl font-semibold">
												{t('engineeringKnowledge.connection.title')}
											</h2>
											<p className="mt-1 text-sm leading-relaxed text-muted-foreground">
												{t('engineeringKnowledge.connection.description')}
											</p>
										</div>
									</div>

									<Alert>
										<ShieldCheck />
										<AlertTitle>
											{t('engineeringKnowledge.connection.previewTitle')}
										</AlertTitle>
										<AlertDescription>
											{t('engineeringKnowledge.connection.previewDescription')}
										</AlertDescription>
									</Alert>
									{baseUrl.trim().toLowerCase().startsWith('http://') && (
										<Alert variant="destructive">
											<TriangleAlert />
											<AlertTitle>
												{t('engineeringKnowledge.connection.httpWarningTitle')}
											</AlertTitle>
											<AlertDescription>
												{t('engineeringKnowledge.connection.httpWarningDescription')}
											</AlertDescription>
										</Alert>
									)}
									{lastTestMessage && (
										<Alert>
											<CheckCircle2 />
											<AlertTitle>
												{t('engineeringKnowledge.connection.testPassed')}
											</AlertTitle>
											<AlertDescription>{lastTestMessage}</AlertDescription>
										</Alert>
									)}

									<section className="rounded-xl border bg-muted/20 p-5">
										<div className="flex flex-wrap items-center justify-between gap-3">
											<div>
												<h3 className="font-semibold">
													{t('engineeringKnowledge.connection.cardTitle')}
												</h3>
												<p className="mt-1 text-xs text-muted-foreground">
													{t('engineeringKnowledge.connection.cardDescription')}
												</p>
											</div>
											<Badge variant="outline" className="gap-1.5 bg-background">
												{connectionConfigured ? (
													<CheckCircle2 className="size-3.5 text-emerald-600" />
												) : (
													<WifiOff className="size-3.5" />
												)}
												{connectionConfigured
													? t('engineeringKnowledge.connection.configured')
													: t('engineeringKnowledge.connection.notConfigured')}
											</Badge>
										</div>

										<div className="mt-5 grid gap-4">
											<label className="grid gap-2 text-sm font-medium">
												{t('engineeringKnowledge.connection.baseUrl')}
												<Input
													placeholder="https://weknora.example.com"
													value={baseUrl}
													onChange={(event) => setBaseUrl(event.target.value)}
													disabled={connectionLoading || savingConnection}
												/>
											</label>
											<label className="grid gap-2 text-sm font-medium">
												{t('engineeringKnowledge.connection.agentId')}
												<Input
													placeholder={DEFAULT_WEKNORA_AGENT_ID}
													value={agentId}
													onChange={(event) => setAgentId(event.target.value)}
													disabled={connectionLoading || savingConnection}
												/>
												<span className="text-xs font-normal text-muted-foreground">
													{t('engineeringKnowledge.connection.agentIdHelp')}
												</span>
											</label>
											<label className="grid gap-2 text-sm font-medium">
												{t('engineeringKnowledge.connection.apiKey')}
												<div className="relative">
													<LockKeyhole className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
													<Input
														type={
															apiKey === SAVED_API_KEY_MASK && !showApiKey
																? 'text'
																: showApiKey
																	? 'text'
																	: 'password'
														}
														value={apiKey}
														onChange={(event) => setApiKey(event.target.value)}
														onFocus={(event) => {
															if (apiKey === SAVED_API_KEY_MASK) {
																event.currentTarget.select();
															}
														}}
														placeholder={t(
															connectionConfigured
																? 'engineeringKnowledge.connection.apiKeyConfiguredPlaceholder'
																: 'engineeringKnowledge.connection.apiKeyPlaceholder',
														)}
														className="pr-10 pl-9"
														autoComplete="new-password"
														disabled={connectionLoading || savingConnection}
													/>
													<Button
														type="button"
														variant="ghost"
														size="icon"
														className="absolute top-1/2 right-1 -translate-y-1/2"
														aria-label={t(
															showApiKey
																? 'engineeringKnowledge.connection.hideApiKey'
																: 'engineeringKnowledge.connection.showApiKey',
														)}
														tooltip={t(
															showApiKey
																? 'engineeringKnowledge.connection.hideApiKey'
																: 'engineeringKnowledge.connection.showApiKey',
														)}
														disabled={
															connectionLoading ||
															savingConnection ||
															revealingApiKey ||
															(!apiKey && !connectionConfigured)
														}
														onClick={() => void toggleApiKeyVisibility()}
													>
														{revealingApiKey ? (
															<Loader2 className="animate-spin" />
														) : showApiKey ? (
															<EyeOff />
														) : (
															<Eye />
														)}
													</Button>
												</div>
												<span className="text-xs font-normal text-muted-foreground">
													{t('engineeringKnowledge.connection.apiKeyHelp')}
												</span>
											</label>
											<div className="grid gap-4 sm:grid-cols-2">
												<label className="grid gap-2 text-sm font-medium">
													{t('engineeringKnowledge.connection.apiPrefix')}
													<Input
														value={apiPrefix}
														onChange={(event) => setApiPrefix(event.target.value)}
														disabled={connectionLoading || savingConnection}
													/>
												</label>
												<label className="grid gap-2 text-sm font-medium">
													{t('engineeringKnowledge.connection.authentication')}
													<Input
														value={authHeader}
														onChange={(event) => setAuthHeader(event.target.value)}
														disabled={connectionLoading || savingConnection}
													/>
												</label>
											</div>
										</div>

										<div className="mt-5 flex justify-end gap-2 border-t pt-4">
											<Button
												variant="outline"
												disabled={
													connectionLoading || testingConnection || !connectionValid
												}
												onClick={() => void testConnection()}
											>
												{testingConnection ? (
													<Loader2 className="animate-spin" />
												) : (
													<Link2 />
												)}
												{t('engineeringKnowledge.connection.test')}
											</Button>
											<Button
												disabled={
													connectionLoading ||
													savingConnection ||
													!connectionValid ||
													!connectionDirty
												}
												onClick={() => void saveConnection()}
											>
												{savingConnection ? (
													<Loader2 className="animate-spin" />
												) : (
													<Save />
												)}
												{t('engineeringKnowledge.connection.save')}
											</Button>
										</div>
									</section>
								</div>
							</div>
						)}
					</section>
				</div>
			</main>

			<Dialog open={urlDialogOpen} onOpenChange={setUrlDialogOpen}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('engineeringKnowledge.knowledge.urlDialogTitle')}</DialogTitle>
						<DialogDescription>
							{t('engineeringKnowledge.knowledge.urlDialogDescription')}
						</DialogDescription>
					</DialogHeader>
					<div className="grid gap-4 py-2">
						<div className="grid gap-2">
							<Label htmlFor="weknora-url">{t('engineeringKnowledge.knowledge.url')}</Label>
							<Input
								id="weknora-url"
								value={urlValue}
								onChange={(event) => setUrlValue(event.target.value)}
								placeholder="https://example.com/document"
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="weknora-url-title">
								{t('engineeringKnowledge.knowledge.urlTitle')}
							</Label>
							<Input
								id="weknora-url-title"
								value={urlTitle}
								onChange={(event) => setUrlTitle(event.target.value)}
								placeholder={t('engineeringKnowledge.knowledge.urlTitlePlaceholder')}
							/>
						</div>
					</div>
					<DialogFooter>
						<Button variant="outline" onClick={() => setUrlDialogOpen(false)}>
							{t('common.cancel')}
						</Button>
						<Button
							disabled={!urlValue.trim() || submittingUrl}
							onClick={() => void submitUrlKnowledge()}
						>
							{submittingUrl ? <Loader2 className="animate-spin" /> : <Globe />}
							{t('engineeringKnowledge.knowledge.addUrl')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
