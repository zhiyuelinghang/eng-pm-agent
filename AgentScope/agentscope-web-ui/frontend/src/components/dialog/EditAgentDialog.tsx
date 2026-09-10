import { CircleAlert, Loader2, Save } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useUnsavedChanges } from './UnsavedChangesDialog';
import { agentApi } from '@/api';
import type { AgentView, InviteConfig, PlatformAgentConfig } from '@/api';
import {
	AgentFormFields,
	defaultAgentFormValues,
	type AgentFormValues,
	type AgentSection,
	type EditorSection,
} from '@/components/form/AgentFormFields';
import { AgentFormSkeleton } from '@/components/form/AgentFormSkeleton';
import { Alert, AlertDescription } from '@/components/ui/alert.tsx';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogDescription,
} from '@/components/ui/dialog';
import { useAgents } from '@/hooks/useAgents';
import { useAgentSchema } from '@/hooks/useAgentSchema';
import {
	AgentModelPolicyFormError,
	agentModelPolicyUpdateFromForm,
	agentModelPolicyToForm,
	type AgentModelPolicyFormValues,
} from '@/lib/agent-model-policy';
import { agentDuty, type Duty } from '@/lib/agent-workbench';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: AgentView;
	onUpdated?: () => void;
	initialSection?: EditorSection;
}

export function EditAgentDialog({ open, onOpenChange, agent, onUpdated, initialSection }: Props) {
	const { update } = useAgents();
	const { t } = useTranslation();
	const { schema, error: schemaError, retry } = useAgentSchema();
	const [submitting, setSubmitting] = useState(false);
	const [values, setValues] = useState<AgentFormValues | null>(null);
	const [errorMsg, setErrorMsg] = useState('');
	const [dirty, setDirty] = useState(false);
	const { leave, prompt } = useUnsavedChanges(dirty, submitting);
	const initialized = useRef<string | null>(null);
	const [dutyContext, setDutyContext] = useState<{ agentId: string; duty?: Duty } | null>(null);
	const [dutyError, setDutyError] = useState('');
	const [dutyRevision, setDutyRevision] = useState(0);
	const dutyReady = dutyContext?.agentId === agent.id;

	useEffect(() => {
		if (!open) {
			setDutyContext(null);
			setDutyError('');
			return;
		}
		let cancelled = false;
		setDutyContext(null);
		setDutyError('');
		void agentApi.getPlatformSettings().then(
			(settings) => {
				if (!cancelled)
					setDutyContext({ agentId: agent.id, duty: agentDuty(agent.id, settings) });
			},
			(error) => {
				if (!cancelled) setDutyError(formatApiErrorForAlert(error));
			},
		);
		return () => {
			cancelled = true;
		};
	}, [open, agent.id, dutyRevision]);

	useEffect(() => {
		if (!open || !schema) {
			if (!open) {
				initialized.current = null;
				setValues(null);
				setDirty(false);
				setErrorMsg('');
			}
			return;
		}
		if (initialized.current === agent.id) return;
		initialized.current = agent.id;
		// Start from schema defaults, then overlay the existing agent's data so
		// any unset fields fall back to defaults rather than empty.
		const base = defaultAgentFormValues(schema);
		const d = agent.data;
		setValues({
			identity: {
				...base.identity,
				name: d.name,
				system_prompt: d.system_prompt,
			},
			context_config: { ...base.context_config, ...(d.context_config ?? {}) },
			react_config: { ...base.react_config, ...(d.react_config ?? {}) },
			model_policy: agentModelPolicyToForm(d.model_policy),
			platform_config: {
				...base.platform_config,
				...(d.platform_config ?? {}),
			},
			invite_config: { ...base.invite_config, ...(d.invite_config ?? {}) },
			call_config: { ...base.call_config, ...(d.call_config ?? {}) },
		});
		setErrorMsg('');
	}, [open, schema, agent]);

	const handleChange = (section: AgentSection, key: string, value: unknown) => {
		setDirty(true);
		setErrorMsg('');
		setValues((prev) =>
			prev ? { ...prev, [section]: { ...prev[section], [key]: value } } : prev,
		);
	};

	const handleSubmit = async () => {
		if (!values || !dutyReady) return;
		const name = (values.identity.name as string | undefined)?.trim();
		if (!name) return;
		setErrorMsg('');
		setSubmitting(true);
		try {
			const modelPolicy = agentModelPolicyUpdateFromForm(
				values.model_policy as AgentModelPolicyFormValues,
				agent.data.model_policy,
			);
			await update(
				agent.id,
				{
					name,
					system_prompt: values.identity.system_prompt as string | undefined,
					model_policy: modelPolicy,
					platform_config: values.platform_config as unknown as PlatformAgentConfig,
					invite_config: values.invite_config as unknown as InviteConfig,
				},
				{ silent: true },
			);
			onOpenChange(false);
			onUpdated?.();
		} catch (e) {
			setErrorMsg(
				e instanceof AgentModelPolicyFormError
					? t(`agent-form.model-policy.errors.${e.code}`)
					: formatApiErrorForAlert(e),
			);
		} finally {
			setSubmitting(false);
		}
	};

	const nameValid = !!(values?.identity.name as string | undefined)?.trim();

	return (
		<>
			<Dialog
				open={open}
				onOpenChange={(next) => {
					if (next) onOpenChange(true);
					else leave(() => onOpenChange(false));
				}}
			>
				<DialogContent className="grid h-[min(820px,calc(100vh-2rem))] max-h-[calc(100vh-2rem)] !w-[min(1040px,calc(100vw-2rem))] !max-w-[1040px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
					<DialogHeader className="border-b px-6 py-6 pr-14">
						<DialogTitle className="text-2xl leading-tight">
							{t('dialog-agent-edit.title')}
						</DialogTitle>
						<DialogDescription>{t('dialog-agent-edit.description')}</DialogDescription>
					</DialogHeader>
					<div className="min-h-0">
						{schema && values && dutyReady ? (
							<AgentFormFields
								schema={schema}
								primaryDuty={dutyContext.duty}
								initialSection={initialSection}
								values={values}
								onChange={handleChange}
							/>
						) : schemaError || dutyError ? (
							<div className="p-6 space-y-3">
								<p role="alert">{schemaError?.message || dutyError}</p>
								<Button
									variant="outline"
									onClick={() => {
										if (schemaError) retry();
										if (dutyError) setDutyRevision((revision) => revision + 1);
									}}
								>
									{t('common.retry')}
								</Button>
							</div>
						) : (
							<AgentFormSkeleton />
						)}
					</div>
					<div className="shrink-0">
						{errorMsg && (
							<Alert variant="destructive" className="mx-6 mt-3 w-auto">
								<CircleAlert />
								<AlertDescription className="whitespace-pre-wrap">
									{errorMsg}
								</AlertDescription>
							</Alert>
						)}
						<DialogFooter className="m-0 rounded-none bg-background px-6 py-4">
							<Button
								variant="ghost"
								onClick={() => leave(() => onOpenChange(false))}
								disabled={submitting}
							>
								{t('common.cancel')}
							</Button>
							<Button
								onClick={handleSubmit}
								disabled={
									!nameValid || submitting || !schema || !values || !dutyReady
								}
							>
								{submitting ? (
									<Loader2 className="size-3.5 animate-spin" />
								) : (
									<Save className="size-3.5" />
								)}
								{submitting ? t('common.saving') : t('common.save')}
							</Button>
						</DialogFooter>
					</div>
				</DialogContent>
			</Dialog>
			{prompt}
		</>
	);
}
