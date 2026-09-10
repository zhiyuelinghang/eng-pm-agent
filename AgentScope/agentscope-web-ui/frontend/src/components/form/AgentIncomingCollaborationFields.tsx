import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';

export function AgentIncomingCollaborationFields({
	description,
	allowGlobalMainCall,
	invitable,
	mainDuty = false,
	primaryDuty,
	onAllowGlobalMainCallChange,
	onInvitableChange,
	onChange,
}: {
	description: string;
	allowGlobalMainCall: boolean;
	invitable: boolean;
	mainDuty?: boolean;
	primaryDuty?: 'main' | 'initializer' | 'taskAssistant' | 'knowledgeAssistant';
	onAllowGlobalMainCallChange: (allowed: boolean) => void;
	onInvitableChange: (allowed: boolean) => void;
	onChange: (description: string | null) => void;
}) {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const id = useId();
	if (mainDuty || primaryDuty === 'main' || primaryDuty === 'initializer') {
		return (
			<p className="text-sm leading-6 text-muted-foreground">
				{primaryDuty === 'initializer'
					? zh
						? '项目初始化仅在初始化页面使用，不接受其他智能体调用。'
						: 'Project initialization runs only from its dedicated page and cannot be delegated to.'
					: zh
						? '总控承接用户请求并下发工作，不接受其他智能体调用。'
						: 'The orchestrator handles user requests and delegates work; other agents cannot invoke it.'}
			</p>
		);
	}
	const fixedMainAccess = primaryDuty === 'taskAssistant' || primaryDuty === 'knowledgeAssistant';
	return (
		<div className="space-y-6 text-sm">
			<div className="rounded-lg border bg-muted/20 p-4 leading-6">
				<p className="font-medium">{zh ? '接收协作请求' : 'Incoming collaboration'}</p>
				<div className="mt-3 space-y-5">
					{fixedMainAccess && (
						<p className="text-muted-foreground">
							{zh
								? '作为平台固定助手，总控可直接调用此智能体，无需另行授权。'
								: 'As a fixed platform assistant, this agent is available to the orchestrator without an additional toggle.'}
						</p>
					)}
					{!fixedMainAccess && (
						<div className="space-y-2">
							<label className="flex w-fit cursor-pointer items-center gap-2">
								<Checkbox
									checked={allowGlobalMainCall}
									aria-describedby={`${id}-main-call-hint`}
									onCheckedChange={(checked) =>
										onAllowGlobalMainCallChange(checked === true)
									}
								/>
								<Badge variant="secondary" className="h-auto rounded-md text-sm">
									{zh ? '允许总控调用' : 'Allow orchestrator calls'}
								</Badge>
							</label>
							<p id={`${id}-main-call-hint`} className="pl-6 text-muted-foreground">
								{zh
									? '开启后，已启用的此智能体自动加入总控的协作范围。'
									: 'When on, this enabled agent automatically joins the orchestrator’s collaboration catalogue.'}
							</p>
						</div>
					)}
					<div className="space-y-2">
						<label className="flex w-fit cursor-pointer items-center gap-2">
							<Checkbox
								checked={invitable}
								aria-describedby={`${id}-invitation-hint`}
								onCheckedChange={(checked) => onInvitableChange(checked === true)}
							/>
							<Badge variant="secondary" className="h-auto rounded-md text-sm">
								{zh ? '允许其他智能体邀请' : 'Allow invitations from other agents'}
							</Badge>
						</label>
						<p id={`${id}-invitation-hint`} className="pl-6 text-muted-foreground">
							{zh
								? '开启后，已启用的此智能体才会出现在其他智能体的候选列表中；对方可以将它加入协作名单。'
								: 'When on, this enabled agent appears in other agents’ candidate lists; they can add it to their collaboration lists.'}
						</p>
					</div>
				</div>
			</div>
			<div className="space-y-2">
				<label htmlFor={id} className="font-medium">
					{zh ? '协作说明' : 'Collaboration description'}
				</label>
				<Textarea
					id={id}
					rows={5}
					placeholder={
						zh
							? '说明适合交给此智能体的工作、所需信息和交付结果。'
							: 'Describe suitable tasks, required inputs and expected results.'
					}
					value={description}
					onChange={(event) => onChange(event.target.value || null)}
				/>
				<p className="text-xs leading-5 text-muted-foreground">
					{zh
						? '供调用方判断何时使用此智能体。留空时使用职责说明。'
						: 'Helps callers decide when to use this agent. Falls back to its description when empty.'}
				</p>
			</div>
		</div>
	);
}
