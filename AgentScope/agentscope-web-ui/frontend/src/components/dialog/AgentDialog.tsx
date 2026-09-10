import { CircleAlert, Loader2, PlusCircle, Settings2, Save } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useUnsavedChanges } from './UnsavedChangesDialog';
import { agentApi } from '@/api';
import type { AgentCallConfig, InviteConfig, PlatformAgentConfig } from '@/api';
import {
	AgentFormFields,
	defaultAgentFormValues,
	type AgentFormValues,
	type AgentSection,
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
	DialogTrigger,
} from '@/components/ui/dialog';
import { useAgents } from '@/hooks/useAgents';
import { useAgentSchema } from '@/hooks/useAgentSchema';
import {
	AgentModelPolicyFormError,
	agentModelPolicyFromForm,
	type AgentModelPolicyFormValues,
} from '@/lib/agent-model-policy';
import type { Duty } from '@/lib/agent-workbench';
import { formatApiErrorForAlert } from '@/lib/api-error';
import { saveFixedAgentSetup } from '@/lib/fixed-agent-setup';

interface Props {
	onCreated?: (agentId: string) => void;
	triggerLabel?: string;
	triggerId?: string;
	primaryDuty?: Duty;
}

export function AgentDialog({ onCreated, triggerId, triggerLabel, primaryDuty }: Props) {
	const { create } = useAgents();
	const { t } = useTranslation();
	const { schema, error: schemaError, retry } = useAgentSchema();
	const [open, setOpen] = useState(false);
	const [submitting, setSubmitting] = useState(false);
	const [values, setValues] = useState<AgentFormValues | null>(null);
	const [errorMsg, setErrorMsg] = useState('');
	const [dirty, setDirty] = useState(false);
	// Retain the created object if completing its fixed entry needs a retry.
	const pendingPrimaryId = useRef<{ agentId: string | null }>({ agentId: null });
	const { leave, prompt } = useUnsavedChanges(dirty, submitting);

	useEffect(() => {
		if (open && schema && !values) {
			const defaults = defaultAgentFormValues(schema);
			if (primaryDuty) {
				defaults.identity = {
					...defaults.identity,
					name: primaryDuty.name,
					system_prompt: `你是 Dobby 的${primaryDuty.name}。${primaryDuty.description}根据已授权的能力完成工作，缺少信息时向用户说明，不编造执行结果。`,
				};
				defaults.model_policy = { ...defaults.model_policy, mode: 'fixed' };
				defaults.platform_config = {
					...defaults.platform_config,
					enabled: true,
					published: primaryDuty.key === 'knowledgeAssistant',
					description: primaryDuty.description,
				};
			}
			setValues(defaults);
		}
		if (!open && !pendingPrimaryId.current.agentId) {
			setValues(null);
			setDirty(false);
			setErrorMsg('');
		}
	}, [open, schema, values, primaryDuty]);

	const handleChange = (section: AgentSection, key: string, value: unknown) => {
		setDirty(true);
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
			if (primaryDuty && (modelPolicy.mode !== 'fixed' || !modelPolicy.chat_model_config)) {
				throw new Error('请为主智能体配置固定模型。');
			}
			const body = {
				name,
				system_prompt: values.identity.system_prompt as string | undefined,
				model_policy: modelPolicy,
				platform_config: values.platform_config as unknown as PlatformAgentConfig,
				invite_config: values.invite_config as unknown as InviteConfig,
				call_config: values.call_config as unknown as AgentCallConfig,
			};
			let agentId: string;
			if (primaryDuty) {
				agentId = await saveFixedAgentSetup(
					primaryDuty,
					body,
					pendingPrimaryId.current,
					agentApi,
				);
			} else {
				agentId = (await create(body, { silent: true })).agent_id;
			}
			setOpen(false);
			onCreated?.(agentId);
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
					if (next) setOpen(true);
					else leave(() => setOpen(false));
				}}
			>
				<DialogTrigger asChild>
					<Button id={triggerId}>
						{primaryDuty ? <Settings2 /> : <PlusCircle />}
						<span>{triggerLabel ?? t('dialog-agent-create.trigger')}</span>
					</Button>
				</DialogTrigger>
				<DialogContent className="grid h-[min(820px,calc(100vh-2rem))] max-h-[calc(100vh-2rem)] !w-[min(1040px,calc(100vw-2rem))] !max-w-[1040px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
					<DialogHeader className="border-b px-6 py-6 pr-14">
						<DialogTitle className="text-2xl leading-tight">
							{triggerLabel ?? t('dialog-agent-create.title')}
						</DialogTitle>
						<DialogDescription>
							{primaryDuty
								? `配置${primaryDuty.name}的模型、工作指令与平台能力。`
								: t('dialog-agent-create.description')}
						</DialogDescription>
					</DialogHeader>
					<div className="min-h-0">
						{schema && values ? (
							<AgentFormFields
								schema={schema}
								primaryDuty={primaryDuty}
								values={values}
								onChange={handleChange}
							/>
						) : schemaError ? (
							<div className="p-6 space-y-3">
								<p role="alert">{schemaError.message}</p>
								<Button variant="outline" onClick={retry}>
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
								onClick={() => leave(() => setOpen(false))}
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
								) : primaryDuty ? (
									<Save className="size-3.5" />
								) : (
									<PlusCircle className="size-3.5" />
								)}
								{submitting
									? t('common.saving')
									: primaryDuty
										? t('common.save')
										: t('common.create')}
							</Button>
						</DialogFooter>
					</div>
				</DialogContent>
			</Dialog>
			{prompt}
		</>
	);
}
