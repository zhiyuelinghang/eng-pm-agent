import {
	Bot,
	CheckCircle2,
	Crown,
	FileSearch,
	Loader2,
	ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { agentApi } from '@/api';
import type { AgentView, PlatformSettings } from '@/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgents } from '@/hooks/useAgents';
import { useTranslation } from '@/i18n/useI18n';

function isMainCandidate(agent: AgentView) {
	return (
		agent.editable &&
		agent.data.platform_config.enabled &&
		agent.data.model_policy.mode === 'fixed' &&
		agent.data.model_policy.chat_model_config !== null
	);
}

export function PlatformSettingsPage() {
	const { t } = useTranslation();
	const { agents, loading: agentsLoading, refetch } = useAgents();
	const [settings, setSettings] = useState<PlatformSettings | null>(null);
	const [mainSelectedId, setMainSelectedId] = useState<string>('');
	const [initializerSelectedId, setInitializerSelectedId] =
		useState<string>('');
	const [loading, setLoading] = useState(true);
	const [savingMain, setSavingMain] = useState(false);
	const [savingInitializer, setSavingInitializer] = useState(false);

	useEffect(() => {
		let active = true;
		agentApi
			.getPlatformSettings()
			.then(async (value) => {
				if (!active) return;
				setSettings(value);
				setMainSelectedId(value.global_main_agent_id ?? '');
				setInitializerSelectedId(value.project_initializer_agent_id ?? '');
				await refetch();
			})
			.catch(() => undefined)
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [refetch]);

	const candidates = useMemo(
		() =>
			agents
				.filter(isMainCandidate)
				.sort(
					(a, b) =>
						a.data.platform_config.sort_order -
							b.data.platform_config.sort_order ||
						a.data.name.localeCompare(b.data.name),
				),
		[agents],
	);
	const mainCandidates = candidates.filter(
		(agent) => agent.id !== initializerSelectedId,
	);
	const initializerCandidates = candidates.filter(
		(agent) => agent.id !== mainSelectedId,
	);
	const selectedAgent =
		agents.find((agent) => agent.id === mainSelectedId) ?? null;
	const selectedInitializer =
		agents.find((agent) => agent.id === initializerSelectedId) ?? null;
	const currentAgent =
		agents.find((agent) => agent.id === settings?.global_main_agent_id) ?? null;
	const currentInitializer =
		agents.find(
			(agent) => agent.id === settings?.project_initializer_agent_id,
		) ?? null;
	const selectedIsValid =
		selectedAgent !== null && isMainCandidate(selectedAgent);
	const initializerIsValid =
		selectedInitializer !== null && isMainCandidate(selectedInitializer);
	const mainUnchanged =
		mainSelectedId === (settings?.global_main_agent_id ?? '');
	const initializerUnchanged =
		initializerSelectedId ===
		(settings?.project_initializer_agent_id ?? '');

	const saveMain = async () => {
		if (!mainSelectedId || !selectedIsValid) return;
		setSavingMain(true);
		try {
			const updated = await agentApi.updatePlatformSettings({
				global_main_agent_id: mainSelectedId,
			});
			setSettings(updated);
			await refetch();
			toast.success(t('platform-settings.saved'));
		} finally {
			setSavingMain(false);
		}
	};

	const saveInitializer = async () => {
		if (!initializerSelectedId || !initializerIsValid) return;
		setSavingInitializer(true);
		try {
			const updated = await agentApi.updatePlatformSettings({
				project_initializer_agent_id: initializerSelectedId,
			});
			setSettings(updated);
			await refetch();
			toast.success(t('platform-settings.initializer.saved'));
		} finally {
			setSavingInitializer(false);
		}
	};

	const busy = loading || agentsLoading;

	return (
		<div className="h-full overflow-y-auto bg-muted/20">
			<div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-8 lg:px-10">
				<div className="space-y-2">
					<div className="flex items-center gap-3">
						<div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
							<Crown className="size-5" />
						</div>
						<div>
							<h1 className="text-2xl font-semibold tracking-tight">
								{t('platform-settings.title')}
							</h1>
							<p className="text-sm text-muted-foreground">
								{t('platform-settings.description')}
							</p>
						</div>
					</div>
				</div>

				<Card>
					<CardHeader>
						<CardTitle className="flex items-center gap-2">
							<Bot className="size-5" />
							{t('platform-settings.main.title')}
						</CardTitle>
						<CardDescription>
							{t('platform-settings.main.description')}
						</CardDescription>
					</CardHeader>
					<CardContent className="space-y-5">
						{busy ? (
							<div className="space-y-3">
								<Skeleton className="h-10 w-full" />
								<Skeleton className="h-24 w-full" />
							</div>
						) : (
							<>
								<div className="space-y-2">
									<label className="text-sm font-medium" htmlFor="global-main-agent">
										{t('platform-settings.main.selector')}
									</label>
									<Select
										value={mainSelectedId}
										onValueChange={setMainSelectedId}
									>
										<SelectTrigger id="global-main-agent" className="w-full">
											<SelectValue
												placeholder={t('platform-settings.main.placeholder')}
											/>
										</SelectTrigger>
										<SelectContent>
											{mainCandidates.map((agent) => (
												<SelectItem key={agent.id} value={agent.id}>
													{agent.data.name}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
									<p className="text-xs text-muted-foreground">
										{t('platform-settings.main.requirement')}
									</p>
								</div>

								{selectedAgent ? (
									<div className="rounded-xl border bg-card p-4">
										<div className="flex flex-wrap items-start justify-between gap-3">
											<div className="space-y-1">
												<div className="flex items-center gap-2">
													<span className="font-medium">{selectedAgent.data.name}</span>
													<Badge variant="secondary">
														{selectedAgent.data.platform_config.category}
													</Badge>
												</div>
												<p className="text-sm text-muted-foreground">
													{selectedAgent.data.platform_config.description ||
														selectedAgent.data.invite_config.invite_description ||
														t('platform-settings.main.noDescription')}
												</p>
											</div>
											{selectedIsValid && (
												<Badge className="gap-1">
													<CheckCircle2 className="size-3" />
													{t('platform-settings.main.ready')}
												</Badge>
											)}
										</div>
										<div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
											<div className="rounded-lg bg-muted/60 px-3 py-2">
												<div className="text-xs text-muted-foreground">
													{t('platform-settings.main.model')}
												</div>
												<div className="mt-1 font-medium">
													{selectedAgent.data.model_policy.chat_model_config?.model ??
														t('platform-settings.main.notConfigured')}
												</div>
											</div>
											<div className="rounded-lg bg-muted/60 px-3 py-2">
												<div className="text-xs text-muted-foreground">
													{t('platform-settings.main.permission')}
												</div>
												<div className="mt-1 font-medium">
													{selectedAgent.data.platform_config.permission_mode}
												</div>
											</div>
										</div>
									</div>
								) : (
									<Alert>
										<ShieldCheck />
										<AlertTitle>
											{t('platform-settings.main.unconfiguredTitle')}
										</AlertTitle>
										<AlertDescription>
											{mainCandidates.length === 0
												? t('platform-settings.main.noCandidates')
												: t('platform-settings.main.unconfigured')}
										</AlertDescription>
									</Alert>
								)}

								{currentAgent && !isMainCandidate(currentAgent) && (
									<Alert variant="destructive">
										<AlertTitle>
											{t('platform-settings.main.invalidCurrentTitle')}
										</AlertTitle>
										<AlertDescription>
											{t('platform-settings.main.invalidCurrent')}
										</AlertDescription>
									</Alert>
								)}
							</>
						)}
					</CardContent>
					<CardFooter className="flex-col items-stretch justify-between gap-3 border-t bg-muted/20 sm:flex-row sm:items-center">
						<p className="max-w-xl text-xs text-muted-foreground">
							{t('platform-settings.main.effect')}
						</p>
						<Button
							onClick={saveMain}
							disabled={
								busy ||
								savingMain ||
								mainUnchanged ||
								!selectedIsValid
							}
						>
							{savingMain && <Loader2 className="animate-spin" />}
							{savingMain
								? t('common.saving')
								: t('platform-settings.main.save')}
						</Button>
					</CardFooter>
				</Card>

				<Card>
					<CardHeader>
						<CardTitle className="flex items-center gap-2">
							<FileSearch className="size-5" />
							{t('platform-settings.initializer.title')}
						</CardTitle>
						<CardDescription>
							{t('platform-settings.initializer.description')}
						</CardDescription>
					</CardHeader>
					<CardContent className="space-y-5">
						{busy ? (
							<div className="space-y-3">
								<Skeleton className="h-10 w-full" />
								<Skeleton className="h-24 w-full" />
							</div>
						) : (
							<>
								<div className="space-y-2">
									<label
										className="text-sm font-medium"
										htmlFor="project-initializer-agent"
									>
										{t('platform-settings.initializer.selector')}
									</label>
									<Select
										value={initializerSelectedId}
										onValueChange={setInitializerSelectedId}
									>
										<SelectTrigger
											id="project-initializer-agent"
											className="w-full"
										>
											<SelectValue
												placeholder={t(
													'platform-settings.initializer.placeholder',
												)}
											/>
										</SelectTrigger>
										<SelectContent>
											{initializerCandidates.map((agent) => (
												<SelectItem key={agent.id} value={agent.id}>
													{agent.data.name}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
									<p className="text-xs text-muted-foreground">
										{t('platform-settings.initializer.requirement')}
									</p>
								</div>

								{selectedInitializer ? (
									<div className="rounded-xl border bg-card p-4">
										<div className="flex flex-wrap items-start justify-between gap-3">
											<div className="space-y-1">
												<div className="flex items-center gap-2">
													<span className="font-medium">
														{selectedInitializer.data.name}
													</span>
													<Badge variant="secondary">
														{t('platform-settings.initializer.internal')}
													</Badge>
												</div>
												<p className="text-sm text-muted-foreground">
													{selectedInitializer.data.platform_config.description ||
														selectedInitializer.data.invite_config
															.invite_description ||
														t('platform-settings.main.noDescription')}
												</p>
											</div>
											{initializerIsValid && (
												<Badge className="gap-1">
													<CheckCircle2 className="size-3" />
													{t('platform-settings.main.ready')}
												</Badge>
											)}
										</div>
										<div className="mt-4 rounded-lg bg-muted/60 px-3 py-2 text-sm">
											<div className="text-xs text-muted-foreground">
												{t('platform-settings.main.model')}
											</div>
											<div className="mt-1 font-medium">
												{selectedInitializer.data.model_policy.chat_model_config
													?.model ??
													t('platform-settings.main.notConfigured')}
											</div>
										</div>
									</div>
								) : (
									<Alert>
										<FileSearch />
										<AlertTitle>
											{t('platform-settings.initializer.unconfiguredTitle')}
										</AlertTitle>
										<AlertDescription>
											{initializerCandidates.length === 0
												? t('platform-settings.initializer.noCandidates')
												: t('platform-settings.initializer.unconfigured')}
										</AlertDescription>
									</Alert>
								)}

								{currentInitializer &&
									!isMainCandidate(currentInitializer) && (
										<Alert variant="destructive">
											<AlertTitle>
												{t('platform-settings.initializer.invalidCurrentTitle')}
											</AlertTitle>
											<AlertDescription>
												{t('platform-settings.initializer.invalidCurrent')}
											</AlertDescription>
										</Alert>
									)}
							</>
						)}
					</CardContent>
					<CardFooter className="flex-col items-stretch justify-between gap-3 border-t bg-muted/20 sm:flex-row sm:items-center">
						<p className="max-w-xl text-xs text-muted-foreground">
							{t('platform-settings.initializer.effect')}
						</p>
						<Button
							onClick={saveInitializer}
							disabled={
								busy ||
								savingInitializer ||
								initializerUnchanged ||
								!initializerIsValid
							}
						>
							{savingInitializer && (
								<Loader2 className="animate-spin" />
							)}
							{savingInitializer
								? t('common.saving')
								: t('platform-settings.initializer.save')}
						</Button>
					</CardFooter>
				</Card>
			</div>
		</div>
	);
}
