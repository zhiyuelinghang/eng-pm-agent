import {
	Bot,
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
	CardDescription,
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
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { useTranslation } from '@/i18n/useI18n';

const EMPTY_CONFIG: PermissionReviewerConfig = {
	enabled: false,
	credential_id: null,
	model: null,
	parameters: {},
	fallback_credential_id: null,
	fallback_model: null,
	fallback_parameters: {},
	confidence_threshold: 0.85,
	max_auto_risk: 'low',
	timeout_seconds: 30,
};

const NO_FALLBACK = '__none__';

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

export function PermissionReviewerPanel({ credentials }: { credentials: CredentialView[] }) {
	const { t } = useTranslation();
	const [config, setConfig] = useState<PermissionReviewerConfig>(EMPTY_CONFIG);
	const [primaryModels, setPrimaryModels] = useState<CredentialModelEntry[]>([]);
	const [fallbackModels, setFallbackModels] = useState<CredentialModelEntry[]>([]);
	const [audits, setAudits] = useState<PermissionReviewAudit[]>([]);
	const [loading, setLoading] = useState(true);
	const [modelsLoading, setModelsLoading] = useState(false);
	const [fallbackModelsLoading, setFallbackModelsLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [testing, setTesting] = useState(false);
	const [testResult, setTestResult] = useState<PermissionReviewerTestResponse | null>(null);

	const loadAudits = useCallback(async () => {
		const response = await credentialApi.permissionReviewerAudits(20);
		setAudits(response.audits);
	}, []);

	useEffect(() => {
		let cancelled = false;
		Promise.all([
			credentialApi.permissionReviewer(),
			credentialApi.permissionReviewerAudits(20),
		])
			.then(([configResponse, auditResponse]) => {
				if (cancelled) return;
				setConfig(configResponse.config);
				setAudits(auditResponse.audits);
			})
			.catch(() => {
				// The shared API client already reports the failure.
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);

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

	useEffect(() => {
		if (!config.fallback_credential_id) {
			setFallbackModels([]);
			return;
		}
		let cancelled = false;
		setFallbackModelsLoading(true);
		credentialApi
			.models(config.fallback_credential_id)
			.then((catalog) => {
				if (!cancelled) {
					setFallbackModels(catalog.models.filter((model) => model.enabled));
				}
			})
			.catch(() => {
				if (!cancelled) setFallbackModels([]);
			})
			.finally(() => {
				if (!cancelled) setFallbackModelsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [config.fallback_credential_id]);

	const canSubmit = useMemo(
		() =>
			(!config.enabled || Boolean(config.credential_id && config.model)) &&
			(!config.fallback_credential_id || Boolean(config.fallback_model)),
		[
			config.credential_id,
			config.enabled,
			config.fallback_credential_id,
			config.fallback_model,
			config.model,
		],
	);

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
			const response = await credentialApi.updatePermissionReviewer(config);
			setConfig(response.config);
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
			const result = await credentialApi.testPermissionReviewer(config);
			setTestResult(result);
			await loadAudits();
		} finally {
			setTesting(false);
		}
	};

	if (loading) {
		return (
			<div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
				<Skeleton className="h-24 w-full rounded-xl" />
				<Skeleton className="h-96 w-full rounded-xl" />
			</div>
		);
	}

	return (
		<div className="flex h-full flex-col gap-6 overflow-y-auto p-6">
			<div className="flex items-start justify-between gap-4">
				<div>
					<div className="flex items-center gap-2">
						<div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
							<ShieldCheck className="size-5" />
						</div>
						<div>
							<h2 className="text-lg font-semibold">
								{t('credential.permissionReviewer.title')}
							</h2>
							<p className="text-sm text-muted-foreground">
								{t('credential.permissionReviewer.subtitle')}
							</p>
						</div>
					</div>
				</div>
				<Badge variant="secondary">
					<Bot />
					{t('credential.permissionReviewer.systemBadge')}
				</Badge>
			</div>

			<Alert>
				<ShieldCheck />
				<AlertTitle>{t('credential.permissionReviewer.securityTitle')}</AlertTitle>
				<AlertDescription>
					{t('credential.permissionReviewer.securityDescription')}
				</AlertDescription>
			</Alert>

			<Card>
				<CardHeader>
					<CardTitle>{t('credential.permissionReviewer.bindingTitle')}</CardTitle>
					<CardDescription>
						{t('credential.permissionReviewer.bindingDescription')}
					</CardDescription>
					<CardAction>
						<div className="flex items-center gap-2">
							<Label htmlFor="permission-reviewer-enabled">
								{config.enabled ? t('common.enabled') : t('common.disabled')}
							</Label>
							<Switch
								id="permission-reviewer-enabled"
								checked={config.enabled}
								onCheckedChange={(checked) => update('enabled', checked)}
							/>
						</div>
					</CardAction>
				</CardHeader>
				<CardContent className="grid gap-5 lg:grid-cols-2">
					<div className="grid gap-2">
						<Label>{t('credential.permissionReviewer.credential')}</Label>
						<Select
							value={config.credential_id ?? undefined}
							onValueChange={(value) => {
								update('credential_id', value);
								update('model', null);
								update('parameters', {});
							}}
						>
							<SelectTrigger className="w-full">
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

					<div className="grid gap-2">
						<Label>{t('credential.permissionReviewer.model')}</Label>
						<Select
							value={config.model ?? undefined}
							onValueChange={(value) => {
								update('model', value);
								update('parameters', {});
							}}
							disabled={!config.credential_id || modelsLoading}
						>
							<SelectTrigger className="w-full">
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

					<div className="grid gap-2">
						<Label>{t('credential.permissionReviewer.fallbackCredential')}</Label>
						<Select
							value={config.fallback_credential_id ?? NO_FALLBACK}
							onValueChange={(value) => {
								update(
									'fallback_credential_id',
									value === NO_FALLBACK ? null : value,
								);
								update('fallback_model', null);
								update('fallback_parameters', {});
							}}
						>
							<SelectTrigger className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value={NO_FALLBACK}>
									{t('credential.permissionReviewer.noFallback')}
								</SelectItem>
								{credentials.map((credential) => (
									<SelectItem key={credential.id} value={credential.id}>
										{credentialName(credential)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>

					<div className="grid gap-2">
						<Label>{t('credential.permissionReviewer.fallbackModel')}</Label>
						<Select
							value={config.fallback_model ?? undefined}
							onValueChange={(value) => {
								update('fallback_model', value);
								update('fallback_parameters', {});
							}}
							disabled={!config.fallback_credential_id || fallbackModelsLoading}
						>
							<SelectTrigger className="w-full">
								<SelectValue
									placeholder={
										fallbackModelsLoading
											? t('common.loading')
											: t('credential.permissionReviewer.selectModel')
									}
								/>
							</SelectTrigger>
							<SelectContent>
								{fallbackModels.map((model) => (
									<SelectItem key={model.name} value={model.name}>
										{modelName(model)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>
				</CardContent>

				<Separator />

				<CardContent className="grid gap-5 md:grid-cols-3">
					<div className="grid gap-2">
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
								className="pr-8"
							/>
							<span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
								%
							</span>
						</div>
					</div>

					<div className="grid gap-2">
						<Label>{t('credential.permissionReviewer.maxRisk')}</Label>
						<Select
							value={config.max_auto_risk}
							onValueChange={(value) =>
								update('max_auto_risk', value as 'low' | 'medium')
							}
						>
							<SelectTrigger className="w-full">
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

					<div className="grid gap-2">
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
								className="pr-12"
							/>
							<span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
								{t('credential.permissionReviewer.seconds')}
							</span>
						</div>
					</div>
				</CardContent>

				<CardContent className="flex flex-col gap-3">
					<div className="flex flex-wrap justify-end gap-2">
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
							{saving ? t('common.saving') : t('credential.permissionReviewer.save')}
						</Button>
					</div>
					{testResult && <PermissionTestResult result={testResult} />}
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>{t('credential.permissionReviewer.auditTitle')}</CardTitle>
					<CardDescription>
						{t('credential.permissionReviewer.auditDescription')}
					</CardDescription>
					<CardAction>
						<Button size="icon-sm" variant="ghost" onClick={loadAudits}>
							<RefreshCw />
						</Button>
					</CardAction>
				</CardHeader>
				<CardContent>
					{audits.length === 0 ? (
						<div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
							{t('credential.permissionReviewer.noAudits')}
						</div>
					) : (
						<div className="divide-y rounded-lg border">
							{audits.map((audit) => (
								<div
									key={audit.id}
									className="grid gap-2 p-3 md:grid-cols-[minmax(0,1fr)_auto]"
								>
									<div className="min-w-0">
										<div className="flex flex-wrap items-center gap-2">
											<span className="font-medium">{audit.tool_name}</span>
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
										<p className="mt-1 text-sm text-muted-foreground">
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
			</Card>
		</div>
	);
}
