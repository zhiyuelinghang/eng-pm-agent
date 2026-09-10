import {
	ChevronLeft,
	ChevronRight,
	Clock3,
	FlaskConical,
	Loader2,
	RefreshCw,
	Save,
	ShieldCheck,
	TriangleAlert,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { credentialApi } from '@/api';
import type {
	CredentialModelEntry,
	CredentialView,
	PermissionReviewAudit,
	PermissionReviewerConfig,
	PermissionReviewerTestResponse,
} from '@/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardAction,
	CardContent,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';

const EMPTY_CONFIG: PermissionReviewerConfig = {
	credential_id: null,
	model: null,
	parameters: {},
	confidence_threshold: 0.85,
	max_auto_risk: 'low',
	timeout_seconds: 30,
};

const AUDIT_FETCH_LIMIT = 100;
const AUDIT_PAGE_SIZE = 5;

function reviewConfig(value: PermissionReviewerConfig): PermissionReviewerConfig {
	return {
		credential_id: value.credential_id,
		model: value.model,
		parameters: value.parameters,
		confidence_threshold: value.confidence_threshold,
		max_auto_risk: value.max_auto_risk,
		timeout_seconds: value.timeout_seconds,
	};
}

function credentialName(credential: CredentialView): string {
	return (credential.data.name as string | undefined) ?? credential.id;
}

function modelName(model: CredentialModelEntry): string {
	return model.label && model.label !== model.name
		? `${model.label} · ${model.name}`
		: model.name;
}

function actionVariant(action: PermissionReviewAudit['action']) {
	if (action === 'allow_once') return 'default' as const;
	if (action === 'deny') return 'destructive' as const;
	return 'secondary' as const;
}

function PermissionTestResult({ result }: { result: PermissionReviewerTestResponse }) {
	const { t } = useTranslation();
	return (
		<Alert variant={result.success ? 'default' : 'destructive'}>
			{result.success ? <ShieldCheck /> : <TriangleAlert />}
			<AlertTitle>
				{result.success
					? t('credential.permissionReviewer.testPassed', {
							latency: result.latency_ms,
						})
					: t('credential.permissionReviewer.testFailed')}
			</AlertTitle>
			<AlertDescription>
				{result.success ? (
					<div className="flex flex-wrap items-center gap-2">
						<Badge variant="outline">{result.model}</Badge>
						<Badge variant="outline">
							{t(
								`credential.permissionReviewer.actions.${result.action ?? 'human_required'}`,
							)}
						</Badge>
						<Badge variant="outline">
							{t(`credential.permissionReviewer.risks.${result.risk ?? 'high'}`)}
						</Badge>
						<span>{Math.round((result.confidence ?? 0) * 100)}%</span>
						<span className="basis-full">{result.reason}</span>
					</div>
				) : (
					result.error
				)}
			</AlertDescription>
		</Alert>
	);
}

export function PermissionReviewPage() {
	const { t } = useTranslation();
	const { credentials } = useCredentials();
	const [config, setConfig] = useState<PermissionReviewerConfig>(EMPTY_CONFIG);
	const [primaryModels, setPrimaryModels] = useState<CredentialModelEntry[]>([]);
	const [audits, setAudits] = useState<PermissionReviewAudit[]>([]);
	const [auditPage, setAuditPage] = useState(1);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState(false);
	const [loadVersion, setLoadVersion] = useState(0);
	const [modelsLoading, setModelsLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState(false);
	const [testResult, setTestResult] = useState<PermissionReviewerTestResponse | null>(null);

	const loadAudits = useCallback(async () => {
		const response = await credentialApi.permissionReviewerAudits(AUDIT_FETCH_LIMIT);
		setAudits(response.audits);
		setAuditPage(1);
	}, []);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		setLoadError(false);
		Promise.all([
			credentialApi.permissionReviewer(),
			credentialApi.permissionReviewerAudits(AUDIT_FETCH_LIMIT),
		])
			.then(([configResponse, auditResponse]) => {
				if (cancelled) return;
				setConfig(reviewConfig(configResponse.config));
				setAudits(auditResponse.audits);
			})
			.catch(() => {
				if (!cancelled) setLoadError(true);
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [loadVersion]);

	useEffect(() => {
		if (!config.credential_id) {
			setPrimaryModels([]);
			return;
		}
		let cancelled = false;
		setModelsLoading(true);
		credentialApi
			.models(config.credential_id)
			.then((catalog) => {
				if (!cancelled) {
					setPrimaryModels(catalog.models.filter((model) => model.enabled));
				}
			})
			.catch(() => {
				if (!cancelled) setPrimaryModels([]);
			})
			.finally(() => {
				if (!cancelled) setModelsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [config.credential_id]);

	const canSubmit = Boolean(config.credential_id && config.model);
	const auditPageCount = Math.max(1, Math.ceil(audits.length / AUDIT_PAGE_SIZE));
	const visibleAudits = useMemo(() => {
		const start = (auditPage - 1) * AUDIT_PAGE_SIZE;
		return audits.slice(start, start + AUDIT_PAGE_SIZE);
	}, [auditPage, audits]);

	useEffect(() => {
		setAuditPage((current) => Math.min(current, auditPageCount));
	}, [auditPageCount]);

	const update = <K extends keyof PermissionReviewerConfig>(
		key: K,
		value: PermissionReviewerConfig[K],
	) => {
		setConfig((previous) => ({ ...previous, [key]: value }));
		setTestResult(null);
	};

	const handleSave = async () => {
		setSaving(true);
		try {
			const response = await credentialApi.updatePermissionReviewer(reviewConfig(config));
			setConfig(reviewConfig(response.config));
			toast.success(t('credential.permissionReviewer.saved'));
		} finally {
			setSaving(false);
		}
	};

	const handleTest = async () => {
		if (!config.credential_id || !config.model) return;
		setTesting(true);
		setTestResult(null);
		try {
			const result = await credentialApi.testPermissionReviewer(reviewConfig(config));
			setTestResult(result);
			await loadAudits();
		} finally {
			setTesting(false);
		}
	};

	if (loading) {
		return (
			<div className="flex h-full min-h-0 flex-col">
				<div className="flex min-h-16 shrink-0 items-center border-b px-5 py-3">
					<Skeleton className="h-10 w-72 rounded-lg" />
				</div>
				<div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5">
					<Skeleton className="h-40 w-full shrink-0 rounded-xl" />
					<Skeleton className="min-h-[28rem] w-full flex-1 rounded-xl" />
				</div>
			</div>
		);
	}

	if (loadError) {
		return (
			<div role="alert" className="space-y-3 p-6 text-sm">
				<p>{t('credential.permissionReviewer.loadFailed')}</p>
				<Button variant="outline" onClick={() => setLoadVersion((value) => value + 1)}>
					<RefreshCw />
					{t('credential.permissionReviewer.retryLoad')}
				</Button>
			</div>
		);
	}

	return (
		<div className="flex h-full min-h-0 min-w-0 flex-col bg-background">
			<header className="flex min-h-16 shrink-0 items-center border-b px-6 py-3">
				<div className="flex min-w-0 items-center gap-3">
					<div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						<ShieldCheck className="size-5" />
					</div>
					<div className="min-w-0">
						<h1 className="text-lg font-semibold">
							{t('credential.permissionReviewer.title')}
						</h1>
					</div>
				</div>
			</header>

			<div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain p-4 sm:p-5 [scrollbar-gutter:stable]">
				<Card className="@container shrink-0 gap-0 py-0 shadow-none">
					<fieldset disabled={saving || testing} className="min-w-0" aria-busy={saving || testing}>
						<CardContent className="grid grid-cols-1 items-end gap-x-4 gap-y-3 p-4 @md:grid-cols-2 @2xl:grid-cols-3">
							<div className="grid min-w-0 gap-2">
								<Label htmlFor="permission-credential">{t('credential.permissionReviewer.credential')}</Label>
								<Select
									value={config.credential_id ?? undefined}
									onValueChange={(value) => {
										update('credential_id', value);
										update('model', null);
										update('parameters', {});
									}}
								>
									<SelectTrigger id="permission-credential" className="w-full min-w-0">
										<SelectValue
											placeholder={t(
												'credential.permissionReviewer.selectCredential',
											)}
										/>
									</SelectTrigger>
									<SelectContent>
										{credentials.map((credential) => (
											<SelectItem key={credential.id} value={credential.id}>
												{credentialName(credential)}
											</SelectItem>
										))}
									</SelectContent>
								</Select>
							</div>

							<div className="grid min-w-0 gap-2">
								<Label htmlFor="permission-model">{t('credential.permissionReviewer.model')}</Label>
								<Select
									value={config.model ?? undefined}
									onValueChange={(value) => {
										update('model', value);
										update('parameters', {});
									}}
									disabled={!config.credential_id || modelsLoading}
								>
									<SelectTrigger id="permission-model" className="w-full min-w-0">
										<SelectValue
											placeholder={
												modelsLoading
													? t('common.loading')
													: t('credential.permissionReviewer.selectModel')
											}
										/>
									</SelectTrigger>
									<SelectContent>
										{primaryModels.map((model) => (
											<SelectItem key={model.name} value={model.name}>
												{modelName(model)}
											</SelectItem>
										))}
									</SelectContent>
								</Select>
							</div>

							<div className="grid min-w-0 gap-2">
								<Label htmlFor="permission-confidence">
									{t('credential.permissionReviewer.confidence')}
								</Label>
								<div className="relative">
									<Input
										id="permission-confidence"
										type="number"
										min={50}
										max={100}
										step={1}
										value={Math.round(config.confidence_threshold * 100)}
										onChange={(event) =>
											update(
												'confidence_threshold',
												Math.min(
													1,
													Math.max(0.5, Number(event.target.value) / 100),
												),
											)
										}
										className="pr-8 tabular-nums"
									/>
									<span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
										%
									</span>
								</div>
							</div>

							<div className="grid min-w-0 gap-2">
								<Label htmlFor="permission-risk">{t('credential.permissionReviewer.maxRisk')}</Label>
								<Select
									value={config.max_auto_risk}
									onValueChange={(value) =>
										update('max_auto_risk', value as 'low' | 'medium')
									}
								>
									<SelectTrigger id="permission-risk" className="w-full min-w-0">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="low">
											{t('credential.permissionReviewer.risks.low')}
										</SelectItem>
										<SelectItem value="medium">
											{t('credential.permissionReviewer.risks.medium')}
										</SelectItem>
									</SelectContent>
								</Select>
							</div>

							<div className="grid min-w-0 gap-2">
								<Label htmlFor="permission-timeout">
									{t('credential.permissionReviewer.timeout')}
								</Label>
								<div className="relative">
									<Input
										id="permission-timeout"
										type="number"
										min={5}
										max={120}
										value={config.timeout_seconds}
										onChange={(event) =>
											update(
												'timeout_seconds',
												Math.min(120, Math.max(5, Number(event.target.value))),
											)
										}
										className="pr-12 tabular-nums"
									/>
									<span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
										{t('credential.permissionReviewer.seconds')}
									</span>
								</div>
							</div>
							<div className="flex min-w-0 flex-wrap justify-end gap-2 @2xl:col-start-3 @2xl:row-start-2">
								<Button
									variant="outline"
									onClick={handleTest}
									disabled={
										testing ||
										saving ||
										!canSubmit ||
										!config.credential_id ||
										!config.model
									}
								>
									{testing ? <Loader2 className="animate-spin" /> : <FlaskConical />}
									{testing
										? t('credential.permissionReviewer.testing')
										: t('credential.permissionReviewer.test')}
								</Button>
								<Button onClick={handleSave} disabled={!canSubmit || saving || testing}>
									{saving ? <Loader2 className="animate-spin" /> : <Save />}
									{saving
										? t('common.saving')
										: t('credential.permissionReviewer.save')}
								</Button>
							</div>
						</CardContent>

					</fieldset>
					{testResult && (
						<CardContent className="px-4 pt-0 pb-4">
							<PermissionTestResult result={testResult} />
						</CardContent>
					)}
				</Card>

				<Card className="min-h-[28rem] flex-1 gap-0 py-0 shadow-none">
					<CardHeader className="shrink-0 items-center border-b px-4 py-3">
						<CardTitle>{t('credential.permissionReviewer.auditTitle')}</CardTitle>
						<CardAction>
							<Button size="icon-sm" variant="ghost" onClick={loadAudits} aria-label={t('credential.permissionReviewer.retryLoad')}>
								<RefreshCw />
							</Button>
						</CardAction>
					</CardHeader>
					<CardContent className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 [scrollbar-gutter:stable]">
						{audits.length === 0 ? (
							<div className="flex h-full flex-col items-center justify-center gap-3 px-4 py-8 text-center text-sm text-muted-foreground">
								<Clock3 className="size-6 opacity-50" />
								<p>{t('credential.permissionReviewer.noAudits')}</p>
							</div>
						) : (
							<div className="divide-y rounded-lg border">
								{visibleAudits.map((audit) => (
									<div
										key={audit.id}
										className="grid gap-2 p-3 md:grid-cols-[minmax(0,1fr)_auto]"
									>
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<span className="min-w-0 break-all font-medium">
													{audit.tool_name}
												</span>
												<Badge variant={actionVariant(audit.action)}>
													{t(
														`credential.permissionReviewer.actions.${audit.action}`,
													)}
												</Badge>
												<Badge variant="outline">
													{t(
														`credential.permissionReviewer.risks.${audit.risk}`,
													)}
												</Badge>
												<span className="text-xs text-muted-foreground">
													{Math.round(audit.confidence * 100)}%
												</span>
											</div>
											<p className="mt-1 break-words text-sm text-muted-foreground">
												{audit.reason}
											</p>
										</div>
										<div className="flex items-center gap-1 self-start whitespace-nowrap text-xs text-muted-foreground">
											<Clock3 className="size-3" />
											{new Date(audit.created_at).toLocaleString()}
										</div>
									</div>
								))}
							</div>
						)}
					</CardContent>
					{audits.length > 0 && (
						<footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3">
							<span className="text-xs tabular-nums text-muted-foreground">
								{t('credential.permissionReviewer.auditTotal', {
									count: audits.length,
								})}
							</span>
							<div className="ml-auto flex items-center gap-2">
								<Button
									size="icon-sm"
									variant="outline"
									onClick={() =>
										setAuditPage((current) => Math.max(1, current - 1))
									}
									disabled={auditPage <= 1}
									tooltip={t('credential.permissionReviewer.previousPage')}
								>
									<ChevronLeft />
								</Button>
								<span className="min-w-24 text-center text-xs tabular-nums text-muted-foreground">
									{t('credential.permissionReviewer.auditPage', {
										current: auditPage,
										total: auditPageCount,
									})}
								</span>
								<Button
									size="icon-sm"
									variant="outline"
									onClick={() =>
										setAuditPage((current) =>
											Math.min(auditPageCount, current + 1),
										)
									}
									disabled={auditPage >= auditPageCount}
									tooltip={t('credential.permissionReviewer.nextPage')}
								>
									<ChevronRight />
								</Button>
							</div>
						</footer>
					)}
				</Card>
			</div>
		</div>
	);
}
