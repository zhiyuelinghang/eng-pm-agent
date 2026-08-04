import { CircleAlert, Loader2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type {
	AgentCallConfig,
	AgentView,
	ContextConfig,
	InviteConfig,
	PlatformAgentConfig,
	ReActConfig,
} from '@/api';
import {
	AgentFormFields,
	defaultAgentFormValues,
	type AgentFormValues,
	type AgentSection,
} from '@/components/form/AgentFormFields';
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
	agentModelPolicyFromForm,
	agentModelPolicyToForm,
	type AgentModelPolicyFormValues,
} from '@/lib/agent-model-policy';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: AgentView;
	onUpdated?: () => void;
}

export function EditAgentDialog({ open, onOpenChange, agent, onUpdated }: Props) {
	const { agents, update } = useAgents();
	const { t } = useTranslation();
	const { schema } = useAgentSchema();
	const [submitting, setSubmitting] = useState(false);
	const [values, setValues] = useState<AgentFormValues | null>(null);
	const [errorMsg, setErrorMsg] = useState('');

	useEffect(() => {
		if (!open || !schema) {
			if (!open) {
				setValues(null);
				setErrorMsg('');
			}
			return;
		}
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
		setErrorMsg('');
		setValues((prev) =>
			prev ? { ...prev, [section]: { ...prev[section], [key]: value } } : prev,
		);
	};

	const handleSubmit = async () => {
		if (!values) return;
		const name = (values.identity.name as string | undefined)?.trim();
		if (!name) return;
		setErrorMsg('');
		setSubmitting(true);
		try {
			const modelPolicy = agentModelPolicyFromForm(
				values.model_policy as AgentModelPolicyFormValues,
			);
			await update(
				agent.id,
				{
					name,
					system_prompt: values.identity.system_prompt as string | undefined,
					context_config: values.context_config as unknown as ContextConfig,
					react_config: values.react_config as unknown as ReActConfig,
					model_policy: modelPolicy,
					platform_config:
						values.platform_config as unknown as PlatformAgentConfig,
					invite_config: values.invite_config as unknown as InviteConfig,
					call_config: values.call_config as unknown as AgentCallConfig,
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
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="grid h-[min(880px,calc(100vh-2rem))] max-h-[calc(100vh-2rem)] !w-[min(900px,calc(100vw-2rem))] !max-w-[900px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
				<DialogHeader className="border-b px-6 py-6 pr-14">
					<DialogTitle className="text-2xl leading-tight">
						{t('dialog-agent-edit.title')}
					</DialogTitle>
					<DialogDescription>
						{t('dialog-agent-edit.description')}
					</DialogDescription>
				</DialogHeader>
				<div className="min-h-0">
					{schema && values ? (
						<AgentFormFields
							schema={schema}
							values={values}
							agents={agents}
							currentAgentId={agent.id}
							onChange={handleChange}
						/>
					) : (
						<p className="text-muted-foreground text-sm">{t('common.loading')}</p>
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
							onClick={() => onOpenChange(false)}
							disabled={submitting}
						>
							{t('common.cancel')}
						</Button>
						<Button
							onClick={handleSubmit}
							disabled={!nameValid || submitting || !schema || !values}
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
	);
}
