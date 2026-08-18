import {
	Cloud,
	Bot,
	Building2,
	CheckCircle2,
	ChevronLeft,
	ChevronRight,
	Database,
	Download,
	Eye,
	EyeOff,
	ExternalLink,
	FileText,
	Folder,
	FolderOpen,
	Globe,
	Link2,
	Loader2,
	LockKeyhole,
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
	WeKnoraFolderNode,
	WeKnoraFolderTreeResponse,
	WeKnoraKnowledgeBase,
	WeKnoraKnowledgeItem,
	WeKnoraProjectBinding,
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
import { useTranslation } from '@/i18n/useI18n';

type SectionKey = 'knowledge' | 'assignments' | 'connection';

type FolderSelection = string | null;

interface FolderTreeNodeProps {
	node: WeKnoraFolderNode;
	level: number;
	selectedPath: FolderSelection;
	expandedPaths: Set<string>;
	expandLabel: string;
	collapseLabel: string;
	onSelect: (path: string) => void;
	onToggle: (path: string) => void;
}

function FolderTreeNode({
	node,
	level,
	selectedPath,
	expandedPaths,
	expandLabel,
	collapseLabel,
	onSelect,
	onToggle,
}: FolderTreeNodeProps) {
	const hasChildren = node.children.length > 0;
	const expanded = expandedPaths.has(node.path);
	const selected = selectedPath === node.path;
	return (
		<div>
			<div
				className={`group flex min-w-0 items-center rounded-md pr-2 transition-colors ${
					selected ? 'bg-primary/10 text-primary' : 'hover:bg-muted/60'
				}`}
				style={{ paddingLeft: `${Math.max(level * 14, 0) + 4}px` }}
			>
				<button
					type="button"
					className="flex size-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30"
					disabled={!hasChildren}
					aria-label={`${expanded ? collapseLabel : expandLabel}: ${node.name}`}
					onClick={() => onToggle(node.path)}
				>
					<ChevronRight
						className={`size-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
					/>
				</button>
				<button
					type="button"
					className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left text-sm"
					onClick={() => {
						onSelect(node.path);
						if (hasChildren && !expanded) onToggle(node.path);
					}}
				>
					{expanded ? (
						<FolderOpen className="size-4 shrink-0" />
					) : (
						<Folder className="size-4 shrink-0" />
					)}
					<span className="min-w-0 flex-1 truncate" title={node.name}>
						{node.name}
					</span>
					<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
						{node.total_count}
					</span>
				</button>
			</div>
			{hasChildren && expanded && (
				<div>
					{node.children.map((child) => (
						<FolderTreeNode
							key={child.path}
							node={child}
							level={level + 1}
							selectedPath={selectedPath}
							expandedPaths={expandedPaths}
							expandLabel={expandLabel}
							collapseLabel={collapseLabel}
							onSelect={onSelect}
							onToggle={onToggle}
						/>
					))}
				</div>
			)}
		</div>
	);
}

const DEFAULT_WEKNORA_BASE_URL = 'http://uy8rk3wy.duankouyingshe.net';
const SAVED_API_KEY_MASK = '************';
const KNOWLEDGE_PAGE_SIZE = 50;

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
	const [folderTree, setFolderTree] =
		useState<WeKnoraFolderTreeResponse | null>(null);
	const [folderTreeLoading, setFolderTreeLoading] = useState(false);
	const [folderTreeError, setFolderTreeError] = useState('');
	const [selectedFolderPath, setSelectedFolderPath] =
		useState<FolderSelection>(null);
	const [expandedFolderPaths, setExpandedFolderPaths] = useState<Set<string>>(
		new Set(),
	);
	const [knowledgePage, setKnowledgePage] = useState(1);
	const [documentQuery, setDocumentQuery] = useState('');
	const [appliedDocumentQuery, setAppliedDocumentQuery] = useState('');
	const [searchQuery, setSearchQuery] = useState('');
	const [knowledgeSearchOpen, setKnowledgeSearchOpen] = useState(false);
	const [searching, setSearching] = useState(false);
	const [searchResults, setSearchResults] = useState<WeKnoraSearchReference[]>([]);
	const [uploading, setUploading] = useState(false);
	const uploadInputRef = useRef<HTMLInputElement>(null);
	const [urlDialogOpen, setUrlDialogOpen] = useState(false);
	const [urlValue, setUrlValue] = useState('');
	const [urlTitle, setUrlTitle] = useState('');
	const [submittingUrl, setSubmittingUrl] = useState(false);
	const [projectBindings, setProjectBindings] = useState<WeKnoraProjectBinding[]>([]);
	const [projectBindingDrafts, setProjectBindingDrafts] = useState<Record<number, string>>({});
	const [projectBindingsLoading, setProjectBindingsLoading] = useState(false);
	const [projectBindingsError, setProjectBindingsError] = useState('');
	const [savingProjectId, setSavingProjectId] = useState<number | null>(null);
	const knowledgeRequestIdRef = useRef(0);
	const folderTreeRequestIdRef = useRef(0);

	const loadKnowledge = useCallback(
		async (
			knowledgeBaseId: string,
			options: {
				folderPath?: FolderSelection;
				page?: number;
				keyword?: string;
			} = {},
		) => {
			const requestId = ++knowledgeRequestIdRef.current;
			setKnowledgeLoading(true);
			setKnowledgeError('');
			try {
				const folderPath = options.folderPath ?? null;
				const response = await agentApi.listWeKnoraKnowledge(knowledgeBaseId, {
					page: options.page ?? 1,
					page_size: KNOWLEDGE_PAGE_SIZE,
					...(folderPath !== null
						? { folder_path: folderPath, folder_recursive: false }
						: {}),
					keyword: options.keyword,
				});
				if (requestId !== knowledgeRequestIdRef.current) return;
				setKnowledge(response.knowledge);
				setKnowledgeTotal(response.total);
			} catch (error) {
				if (requestId !== knowledgeRequestIdRef.current) return;
				setKnowledge([]);
				setKnowledgeTotal(0);
				setKnowledgeError(
					error instanceof Error ? error.message : 'Unable to load knowledge',
				);
			} finally {
				if (requestId === knowledgeRequestIdRef.current) {
					setKnowledgeLoading(false);
				}
			}
		},
		[],
	);

	const loadFolderTree = useCallback(async (knowledgeBaseId: string) => {
		const requestId = ++folderTreeRequestIdRef.current;
		setFolderTreeLoading(true);
		setFolderTreeError('');
		try {
			const response = await agentApi.getWeKnoraFolderTree(knowledgeBaseId);
			if (requestId !== folderTreeRequestIdRef.current) return;
			setFolderTree(response);
		} catch (error) {
			if (requestId !== folderTreeRequestIdRef.current) return;
			setFolderTree(null);
			setFolderTreeError(
				error instanceof Error ? error.message : 'Unable to load folder tree',
			);
		} finally {
			if (requestId === folderTreeRequestIdRef.current) {
				setFolderTreeLoading(false);
			}
		}
	}, []);

	const loadKnowledgeBaseContent = useCallback(
		async (knowledgeBaseId: string) => {
			setSelectedFolderPath(null);
			setExpandedFolderPaths(new Set());
			setKnowledgePage(1);
			setDocumentQuery('');
			setAppliedDocumentQuery('');
			setSearchResults([]);
			setKnowledgeSearchOpen(false);
			await Promise.all([
				loadFolderTree(knowledgeBaseId),
				loadKnowledge(knowledgeBaseId),
			]);
		},
		[loadFolderTree, loadKnowledge],
	);

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
					await loadKnowledgeBaseContent(nextId);
				} else {
					setKnowledge([]);
					setKnowledgeTotal(0);
					setFolderTree(null);
				}
			} catch (error) {
				setKnowledgeBases([]);
				setKnowledge([]);
				setKnowledgeTotal(0);
				setFolderTree(null);
				setKnowledgeBasesError(
					error instanceof Error
						? error.message
						: 'Unable to load knowledge bases',
				);
			} finally {
				setKnowledgeBasesLoading(false);
			}
		},
		[loadKnowledgeBaseContent],
	);

	const loadProjectBindings = useCallback(async () => {
		setProjectBindingsLoading(true);
		setProjectBindingsError('');
		try {
			const response = await agentApi.listWeKnoraProjectBindings();
			setProjectBindings(response.projects);
			setProjectBindingDrafts(
				Object.fromEntries(
					response.projects.map((item) => [
						item.project_id,
						item.weknora_agent_id ?? '',
					]),
				),
			);
		} catch (error) {
			setProjectBindings([]);
			setProjectBindingsError(
				error instanceof Error
					? error.message
					: t('engineeringKnowledge.assignments.loadFailed'),
			);
		} finally {
			setProjectBindingsLoading(false);
		}
	}, [t]);

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

	useEffect(() => {
		void loadProjectBindings();
	}, [loadProjectBindings]);

	const connectionConfigured = connection?.api_key_configured ?? false;
	const apiKeyChanged = connectionConfigured
		? apiKey !== SAVED_API_KEY_MASK && apiKey !== savedApiKey
		: Boolean(apiKey);
	const connectionDirty = Boolean(
		apiKeyChanged ||
			baseUrl !== (connection?.base_url ?? '') ||
			apiPrefix !== (connection?.api_prefix ?? '/api/v1') ||
			authHeader !== (connection?.auth_header ?? 'X-API-Key'),
	);
	const connectionValid = Boolean(
		baseUrl.trim() &&
			apiPrefix.trim() &&
			authHeader.trim() &&
			(connectionConfigured || Boolean(apiKey)),
	);
	const connectionPayload = (): UpdateWeKnoraConnectionRequest => ({
		base_url: baseUrl.trim(),
		api_prefix: apiPrefix.trim(),
		auth_header: authHeader.trim(),
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

	const saveProjectBinding = async (project: WeKnoraProjectBinding) => {
		const weknoraAgentId = (projectBindingDrafts[project.project_id] ?? '').trim();
		setSavingProjectId(project.project_id);
		try {
			const updated = await agentApi.updateWeKnoraProjectBinding(
				project.project_id,
				{ weknora_agent_id: weknoraAgentId || null },
			);
			setProjectBindings((current) =>
				current.map((item) =>
					item.project_id === updated.project_id ? updated : item,
				),
			);
			setProjectBindingDrafts((current) => ({
				...current,
				[updated.project_id]: updated.weknora_agent_id ?? '',
			}));
			toast.success(t('engineeringKnowledge.assignments.saved'));
		} finally {
			setSavingProjectId(null);
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

	const refreshDocumentView = async () => {
		if (!selectedKnowledgeBaseId) return;
		await Promise.all([
			loadFolderTree(selectedKnowledgeBaseId),
			loadKnowledge(selectedKnowledgeBaseId, {
				folderPath: selectedFolderPath,
				page: knowledgePage,
				keyword: appliedDocumentQuery,
			}),
		]);
	};

	const selectFolder = (folderPath: FolderSelection) => {
		if (!selectedKnowledgeBaseId || selectedFolderPath === folderPath) return;
		setSelectedFolderPath(folderPath);
		setKnowledgePage(1);
		setDocumentQuery('');
		setAppliedDocumentQuery('');
		void loadKnowledge(selectedKnowledgeBaseId, {
			folderPath,
			page: 1,
		});
	};

	const toggleFolder = (folderPath: string) => {
		setExpandedFolderPaths((current) => {
			const next = new Set(current);
			if (next.has(folderPath)) next.delete(folderPath);
			else next.add(folderPath);
			return next;
		});
	};

	const applyDocumentSearch = () => {
		if (!selectedKnowledgeBaseId) return;
		const keyword = documentQuery.trim();
		setAppliedDocumentQuery(keyword);
		setKnowledgePage(1);
		void loadKnowledge(selectedKnowledgeBaseId, {
			folderPath: selectedFolderPath,
			page: 1,
			keyword,
		});
	};

	const clearDocumentSearch = () => {
		setDocumentQuery('');
		setAppliedDocumentQuery('');
		setKnowledgePage(1);
		if (selectedKnowledgeBaseId) {
			void loadKnowledge(selectedKnowledgeBaseId, {
				folderPath: selectedFolderPath,
				page: 1,
			});
		}
	};

	const changeKnowledgePage = (page: number) => {
		if (!selectedKnowledgeBaseId || page < 1) return;
		setKnowledgePage(page);
		void loadKnowledge(selectedKnowledgeBaseId, {
			folderPath: selectedFolderPath,
			page,
			keyword: appliedDocumentQuery,
		});
	};

	const uploadKnowledge = async (file: File) => {
		if (!selectedKnowledgeBaseId) return;
		setUploading(true);
		try {
			const result = await agentApi.uploadWeKnoraKnowledge(
				selectedKnowledgeBaseId,
				file,
				true,
				selectedFolderPath ?? '',
			);
			toast.success(result.message);
			await refreshDocumentView();
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
			setSelectedFolderPath(null);
			setKnowledgePage(1);
			setDocumentQuery('');
			setAppliedDocumentQuery('');
			await Promise.all([
				loadFolderTree(selectedKnowledgeBaseId),
				loadKnowledge(selectedKnowledgeBaseId),
			]);
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
		await refreshDocumentView();
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
			key: 'assignments' as const,
			icon: Bot,
			title: t('engineeringKnowledge.sections.assignments.title'),
			description: t('engineeringKnowledge.sections.assignments.description'),
			status: projectBindingsLoading
				? t('engineeringKnowledge.sections.assignments.loading')
				: t('engineeringKnowledge.sections.assignments.assigned', {
					count: projectBindings.filter((item) => item.weknora_agent_id).length,
					total: projectBindings.length,
				}),
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
	const totalDocumentCount = folderTree?.total_document_count ?? knowledgeTotal;
	const knowledgePageCount = Math.max(
		1,
		Math.ceil(knowledgeTotal / KNOWLEDGE_PAGE_SIZE),
	);

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
				<div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border bg-background">
					<aside className="shrink-0 border-b bg-muted/20 px-3 py-3">
						<div className="flex flex-col gap-3 lg:flex-row lg:items-center">
							<div className="min-w-0 px-1 lg:w-60 lg:shrink-0">
								<div className="flex items-center gap-2">
									<h2 className="font-semibold">
										{t('engineeringKnowledge.navigation.title')}
									</h2>
									<Badge variant="secondary">
										{t('engineeringKnowledge.navigation.phase')}
									</Badge>
								</div>
								<p className="mt-1 truncate text-xs text-muted-foreground">
									{t('engineeringKnowledge.navigation.description')}
								</p>
							</div>

							<nav
								aria-label={t('engineeringKnowledge.navigation.title')}
								className="grid min-w-0 flex-1 gap-2 sm:grid-cols-3"
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
											className={`group flex min-h-14 min-w-0 items-center gap-3 rounded-lg border px-3 py-2 text-left transition-all duration-200 active:translate-y-px ${
												active
													? 'border-primary/30 bg-background shadow-sm'
													: 'border-transparent hover:border-border hover:bg-background/70'
											}`}
										>
											<div
												className={`flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
													active
														? 'bg-primary text-primary-foreground'
														: 'bg-muted text-muted-foreground group-hover:text-foreground'
												}`}
											>
												<ItemIcon className="size-4" />
											</div>
											<div className="min-w-0 flex-1">
												<div className="flex min-w-0 items-center justify-between gap-2">
													<span className="truncate text-sm font-semibold">
														{item.title}
													</span>
													<span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
														<span className="size-1.5 rounded-full bg-amber-500" />
														<span className="max-w-32 truncate">{item.status}</span>
													</span>
												</div>
												<p className="mt-1 hidden truncate text-xs text-muted-foreground 2xl:block">
													{item.description}
												</p>
											</div>
										</button>
									);
								})}
							</nav>
						</div>
					</aside>

					<section className="flex min-h-0 flex-1 flex-col">
						{activeSection === 'knowledge' && (
							<div className="flex min-h-0 flex-1 flex-col">
								<div className="min-h-0 flex-1 overflow-hidden p-4 sm:p-5">
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
										<div className="h-full min-h-0">
											<section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-background">
												<div className="shrink-0 border-b px-4 py-3">
													<div className="flex flex-wrap items-center justify-between gap-3">
														<div className="min-w-0">
														<div className="flex items-center gap-2">
															<h3 className="text-base font-semibold tracking-tight">
																{t('engineeringKnowledge.knowledge.documentsTitle')}
															</h3>
															<Badge variant="secondary" className="font-mono tabular-nums">
																{totalDocumentCount}
															</Badge>
														</div>
														</div>
														<div className="flex flex-wrap items-center justify-end gap-2">
															<Select
																value={selectedKnowledgeBaseId}
																disabled={knowledgeBases.length === 0}
																onValueChange={(knowledgeBaseId) => {
																	setSelectedKnowledgeBaseId(knowledgeBaseId);
																	void loadKnowledgeBaseContent(knowledgeBaseId);
																}}
															>
																<SelectTrigger
																	aria-label={t('engineeringKnowledge.knowledge.switchBase')}
																	className="h-9 w-52 bg-background"
																>
																	<SelectValue placeholder={t('engineeringKnowledge.knowledge.currentBase')} />
																</SelectTrigger>
																<SelectContent>
																	{knowledgeBases.map((knowledgeBase) => (
																		<SelectItem key={knowledgeBase.id} value={knowledgeBase.id}>
																			{knowledgeBase.name || knowledgeBase.id}
																		</SelectItem>
																	))}
																</SelectContent>
															</Select>
															<Button
																variant="outline"
																disabled={!connectionConfigured || knowledgeBasesLoading}
																onClick={() =>
																	void loadKnowledgeBases(selectedKnowledgeBaseId || undefined)
																}
															>
																<RefreshCw className={knowledgeBasesLoading ? 'animate-spin' : ''} />
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
													</div>
													<div className="mt-3 flex flex-wrap items-center gap-2">
														<p className="min-w-0 flex-1 text-sm text-muted-foreground">
															{t('engineeringKnowledge.knowledge.documentsHint')}
														</p>
														<InputGroup className="h-9 bg-muted/20 sm:w-72">
															<InputGroupAddon>
																<Search />
															</InputGroupAddon>
															<InputGroupInput
																value={documentQuery}
																onChange={(event) => setDocumentQuery(event.target.value)}
																onKeyDown={(event) => {
																	if (event.key === 'Enter') applyDocumentSearch();
																}}
																placeholder={t('engineeringKnowledge.knowledge.searchPlaceholder')}
																aria-label={t('engineeringKnowledge.knowledge.searchPlaceholder')}
															/>
														</InputGroup>
														<Button
															variant={knowledgeSearchOpen ? 'secondary' : 'outline'}
															aria-expanded={knowledgeSearchOpen}
															aria-controls="weknora-hybrid-search"
															onClick={() => setKnowledgeSearchOpen((open) => !open)}
														>
															<Search />
															{t('engineeringKnowledge.knowledge.hybridSearchToggle')}
														</Button>
														<Button variant="outline" onClick={applyDocumentSearch}>
															<Search />
															{t('engineeringKnowledge.knowledge.filterAction')}
														</Button>
													</div>
												</div>
												{knowledgeSearchOpen && (
													<div
														id="weknora-hybrid-search"
														className="max-h-80 shrink-0 overflow-y-auto border-b bg-muted/10 px-5 py-3"
													>
														<div className="flex flex-col gap-2 sm:flex-row sm:items-center">
															<p className="shrink-0 text-sm font-medium">
																{t('engineeringKnowledge.knowledge.hybridSearchToggle')}
															</p>
															<InputGroup className="min-w-0 flex-1 bg-background">
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
															<Button
																disabled={!searchQuery.trim() || searching}
																onClick={() => void runKnowledgeSearch()}
															>
																{searching ? <Loader2 className="animate-spin" /> : <Search />}
																{t('engineeringKnowledge.knowledge.searchAction')}
															</Button>
														</div>

														{searchResults.length > 0 && (
															<div className="mt-3 space-y-3 border-t pt-3">
																{searchResults.map((reference, index) => (
																	<div
																		key={`${reference.knowledge_id}-${reference.chunk_index}-${index}`}
																		className="rounded-lg border bg-background p-4"
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
																		{reference.folder_path && (
																			<p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
																				<Folder className="size-3.5 shrink-0" />
																				<span className="truncate">{reference.folder_path}</span>
																			</p>
																		)}
																		<p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
																			{reference.content}
																		</p>
																	</div>
																))}
															</div>
														)}
													</div>
												)}

												<div className="grid min-h-0 flex-1 grid-rows-[minmax(12rem,16rem)_minmax(0,1fr)] lg:grid-cols-[18rem_minmax(0,1fr)] lg:grid-rows-1">
													<aside className="flex min-h-0 min-w-0 flex-col border-b bg-muted/15 lg:border-r lg:border-b-0">
														<div className="shrink-0 border-b px-4 py-3">
															<p className="text-sm font-semibold">
																{t('engineeringKnowledge.knowledge.folderTreeTitle')}
															</p>
															<p className="mt-1 text-xs text-muted-foreground">
																{t('engineeringKnowledge.knowledge.folderTreeHint')}
															</p>
														</div>
														<div className="min-h-0 flex-1 overflow-y-auto p-2">
															<button
																type="button"
																className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
																	selectedFolderPath === null
																		? 'bg-primary/10 font-medium text-primary'
																		: 'hover:bg-muted/60'
																}`}
																onClick={() => selectFolder(null)}
															>
																<Database className="size-4 shrink-0" />
																<span className="min-w-0 flex-1 truncate">
																	{t('engineeringKnowledge.knowledge.allDocuments')}
																</span>
																<span className="text-xs tabular-nums text-muted-foreground">
																	{totalDocumentCount}
																</span>
															</button>

															{folderTreeLoading && !folderTree ? (
																<div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground">
																	<Loader2 className="size-4 animate-spin" />
																	{t('engineeringKnowledge.knowledge.loadingFolders')}
																</div>
															) : folderTreeError ? (
																<div className="m-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
																	<p>{folderTreeError}</p>
																	<Button
																		variant="ghost"
																		size="sm"
																		className="mt-2"
																		onClick={() => void loadFolderTree(selectedKnowledgeBaseId)}
																	>
																		<RefreshCw />
																		{t('engineeringKnowledge.knowledge.retry')}
																	</Button>
																</div>
															) : (
																folderTree?.folders.map((folder) => (
																	<FolderTreeNode
																		key={folder.path}
																		node={folder}
																		level={0}
																		selectedPath={selectedFolderPath}
																		expandedPaths={expandedFolderPaths}
																		expandLabel={t('engineeringKnowledge.knowledge.expandFolder')}
																		collapseLabel={t('engineeringKnowledge.knowledge.collapseFolder')}
																		onSelect={(path) => selectFolder(path)}
																		onToggle={toggleFolder}
																	/>
																))
															)}
														</div>
													</aside>

													<div className="flex min-h-0 min-w-0 flex-col">
														<div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-muted/10 px-5 py-3">
															<div className="flex min-w-0 items-center gap-2">
																<FolderOpen className="size-4 shrink-0 text-primary" />
																<div className="min-w-0">
																	<p className="truncate text-sm font-medium" title={selectedFolderPath ?? undefined}>
																		{selectedFolderPath || t('engineeringKnowledge.knowledge.allDocuments')}
																	</p>
																	<p className="text-xs text-muted-foreground">
																		{selectedFolderPath
																			? t('engineeringKnowledge.knowledge.directFilesHint')
																			: t('engineeringKnowledge.knowledge.allFilesHint')}
																	</p>
																</div>
															</div>
															<Badge variant="outline" className="bg-background font-mono tabular-nums">
																{knowledgeTotal}
															</Badge>
														</div>

														<div className="min-h-0 flex-1 overflow-y-auto">
														{knowledgeLoading ? (
															<div className="flex items-center justify-center gap-2 px-5 py-16 text-sm text-muted-foreground">
																<Loader2 className="animate-spin" />
																{t('engineeringKnowledge.knowledge.loadingDocuments')}
															</div>
														) : knowledgeError ? (
															<div className="p-4">
																<Alert variant="destructive">
																	<WifiOff />
																	<AlertTitle>{t('engineeringKnowledge.knowledge.documentsLoadFailed')}</AlertTitle>
																	<AlertDescription className="space-y-3">
																		<p>{knowledgeError}</p>
																		<Button variant="outline" onClick={() => void refreshDocumentView()}>
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
																		{appliedDocumentQuery ? <Search /> : <FileText />}
																	</EmptyMedia>
																	<EmptyTitle>
																		{appliedDocumentQuery
																			? t('engineeringKnowledge.knowledge.noSearchResultsTitle')
																			: t('engineeringKnowledge.knowledge.noDocumentsTitle')}
																	</EmptyTitle>
																	<EmptyDescription>
																		{appliedDocumentQuery
																			? t('engineeringKnowledge.knowledge.noSearchResultsDescription')
																			: t('engineeringKnowledge.knowledge.noDocumentsDescription')}
																	</EmptyDescription>
																</EmptyHeader>
																{appliedDocumentQuery && (
																	<Button variant="outline" onClick={clearDocumentSearch}>
																		{t('engineeringKnowledge.knowledge.clearSearch')}
																	</Button>
																)}
															</Empty>
														) : (
															<div className="divide-y">
																{knowledge.map((item) => {
																	const title = item.file_name || item.title || item.id;
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
																			{item.folder_path && (
																				<p className="mt-1.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
																					<Folder className="size-3.5 shrink-0" />
																					<span className="truncate" title={item.folder_path}>{item.folder_path}</span>
																				</p>
																			)}
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
														</div>
														{knowledgePageCount > 1 && !knowledgeLoading && !knowledgeError && (
															<div className="flex shrink-0 items-center justify-between gap-3 border-t px-5 py-3">
														<p className="text-sm text-muted-foreground">
															{t('engineeringKnowledge.knowledge.pageStatus', {
																page: knowledgePage,
																pages: knowledgePageCount,
															})}
														</p>
														<div className="flex items-center gap-2">
															<Button
																variant="outline"
																size="sm"
																disabled={knowledgePage <= 1}
																onClick={() => changeKnowledgePage(knowledgePage - 1)}
															>
																<ChevronLeft />
																{t('engineeringKnowledge.knowledge.previousPage')}
															</Button>
															<Button
																variant="outline"
																size="sm"
																disabled={knowledgePage >= knowledgePageCount}
																onClick={() => changeKnowledgePage(knowledgePage + 1)}
															>
																{t('engineeringKnowledge.knowledge.nextPage')}
																<ChevronRight />
															</Button>
														</div>
													</div>
												)}
													</div>
												</div>
											</section>
										</div>
									)}
								</div>
							</div>
						)}

						{activeSection === 'assignments' && (
							<div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 sm:px-8">
								<div className="mx-auto max-w-5xl space-y-5">
									<div className="flex items-start gap-3">
										<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted">
											<Bot className="size-5" />
										</div>
										<div>
											<p className="text-xs font-medium tracking-wide text-muted-foreground">
												{t('engineeringKnowledge.assignments.eyebrow')}
											</p>
											<h2 className="mt-1 text-xl font-semibold">
												{t('engineeringKnowledge.assignments.title')}
											</h2>
											<p className="mt-1 text-sm leading-relaxed text-muted-foreground">
												{t('engineeringKnowledge.assignments.description')}
											</p>
										</div>
									</div>

									{!connectionConfigured && (
										<Alert>
											<Server />
											<AlertTitle>
												{t('engineeringKnowledge.assignments.connectionRequiredTitle')}
											</AlertTitle>
											<AlertDescription>
												{t('engineeringKnowledge.assignments.connectionRequiredDescription')}
											</AlertDescription>
										</Alert>
									)}

									{projectBindingsError ? (
										<Alert variant="destructive">
											<WifiOff />
											<AlertTitle>
												{t('engineeringKnowledge.assignments.loadFailedTitle')}
											</AlertTitle>
											<AlertDescription className="space-y-3">
												<p>{projectBindingsError}</p>
												<Button variant="outline" onClick={() => void loadProjectBindings()}>
													<RefreshCw />
													{t('engineeringKnowledge.assignments.retry')}
												</Button>
											</AlertDescription>
										</Alert>
									) : projectBindingsLoading && projectBindings.length === 0 ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon"><Loader2 className="animate-spin" /></EmptyMedia>
												<EmptyTitle>{t('engineeringKnowledge.assignments.loading')}</EmptyTitle>
											</EmptyHeader>
										</Empty>
									) : projectBindings.length === 0 ? (
										<Empty className="rounded-xl border border-dashed py-14">
											<EmptyHeader>
												<EmptyMedia variant="icon"><Building2 /></EmptyMedia>
												<EmptyTitle>{t('engineeringKnowledge.assignments.emptyTitle')}</EmptyTitle>
												<EmptyDescription>{t('engineeringKnowledge.assignments.emptyDescription')}</EmptyDescription>
											</EmptyHeader>
										</Empty>
									) : (
										<section className="overflow-hidden rounded-xl border bg-background">
											<div className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-3">
												<div>
													<h3 className="font-semibold">{t('engineeringKnowledge.assignments.listTitle')}</h3>
													<p className="mt-1 text-xs text-muted-foreground">{t('engineeringKnowledge.assignments.listDescription')}</p>
												</div>
												<Button variant="outline" disabled={projectBindingsLoading} onClick={() => void loadProjectBindings()}>
													<RefreshCw className={projectBindingsLoading ? 'animate-spin' : ''} />
													{t('engineeringKnowledge.assignments.refresh')}
												</Button>
											</div>
											<div className="divide-y">
												{projectBindings.map((project) => {
													const draft = projectBindingDrafts[project.project_id] ?? '';
													const saved = project.weknora_agent_id ?? '';
													const saving = savingProjectId === project.project_id;
													return (
														<div key={project.project_id} className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,1fr)_auto] lg:items-end">
															<div className="min-w-0">
																<div className="flex items-center gap-2">
																	<Building2 className="size-4 shrink-0 text-muted-foreground" />
																	<strong className="truncate text-sm" title={project.project_name}>{project.project_name}</strong>
																	<Badge variant={saved ? 'secondary' : 'outline'}>
																		{saved ? t('engineeringKnowledge.assignments.bound') : t('engineeringKnowledge.assignments.unbound')}
																	</Badge>
																</div>
																<p className="mt-1 text-xs text-muted-foreground">ID: {project.project_id}</p>
															</div>
															<label className="grid gap-2 text-sm font-medium">
																{t('engineeringKnowledge.assignments.robotId')}
																<Input
																	value={draft}
																	placeholder={t('engineeringKnowledge.assignments.robotIdPlaceholder')}
																	onChange={(event) => setProjectBindingDrafts((current) => ({ ...current, [project.project_id]: event.target.value }))}
																	disabled={saving}
																/>
															</label>
															<Button
																disabled={saving || draft.trim() === saved || (!connectionConfigured && Boolean(draft.trim()))}
																onClick={() => void saveProjectBinding(project)}
															>
																{saving ? <Loader2 className="animate-spin" /> : <Save />}
																{t('engineeringKnowledge.assignments.save')}
															</Button>
														</div>
													);
												})}
											</div>
										</section>
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
