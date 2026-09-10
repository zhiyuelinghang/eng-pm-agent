import { Info, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { PermissionMode, PlatformAgentConfig, PlatformAgentRole } from '@/api';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';

interface Props {
	values: Partial<PlatformAgentConfig>;
	fixedDuty?: boolean;
	mainDuty?: boolean;
	onChange: (key: keyof PlatformAgentConfig, value: unknown) => void;
}

const ROLES: PlatformAgentRole[] = ['business', 'system_internal'];
const PERMISSION_MODES: PermissionMode[] = [
	'auto',
	'default',
	'accept_edits',
	'explore',
	'dont_ask',
	'bypass',
];

export function AgentPlatformConfigFields({
	values,
	fixedDuty = false,
	mainDuty = false,
	onChange,
}: Props) {
	const { t } = useTranslation();
	const role = values.role ?? 'business';
	const isMain = mainDuty;
	const isFixed = fixedDuty || isMain;
	return (
		<FieldGroup>
			{!isFixed && (
				<>
					<Field>
						<FieldLabel htmlFor="agent-platform-role">
							{t('agent-form.platform-config.role.label')}
						</FieldLabel>
						<Select
							value={role}
							onValueChange={(value) => {
								onChange('role', value as PlatformAgentRole);
								if (value === 'system_internal') onChange('published', false);
							}}
						>
							<SelectTrigger id="agent-platform-role" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								{ROLES.map((value) => (
									<SelectItem key={value} value={value}>
										{t(`agent-form.platform-config.role.options.${value}`)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
						<FieldDescription>
							{t(`agent-form.platform-config.role.descriptions.${role}`)}
						</FieldDescription>
					</Field>
				</>
			)}

			{!isFixed && (
				<>
					<div className="space-y-5">
						<Field orientation="horizontal">
							<Checkbox
								id="agent-platform-enabled"
								checked={values.enabled ?? true}
								onCheckedChange={(checked) => onChange('enabled', checked === true)}
							/>
							<FieldLabel htmlFor="agent-platform-enabled" className="font-normal">
								{t('agent-form.platform-config.enabled')}
							</FieldLabel>
						</Field>
						<FieldDescription className="-mt-3 pl-6">
							{t('agent-form.platform-config.enabledDescription')}
						</FieldDescription>
						<Field orientation="horizontal">
							<Checkbox
								id="agent-platform-published"
								checked={role !== 'system_internal' && (values.published ?? true)}
								disabled={role === 'system_internal'}
								onCheckedChange={(checked) =>
									onChange('published', checked === true)
								}
							/>
							<FieldLabel htmlFor="agent-platform-published" className="font-normal">
								{t('agent-form.platform-config.published')}
							</FieldLabel>
						</Field>
						<FieldDescription className="-mt-3 pl-6">
							{t('agent-form.platform-config.publishedDescription')}
						</FieldDescription>
					</div>
				</>
			)}

			{!isFixed && (
				<div className="grid grid-cols-[minmax(0,1fr)_120px] gap-3">
					<Field>
						<FieldLabel htmlFor="agent-platform-category">
							{t('agent-form.platform-config.category')}
						</FieldLabel>
						<Input
							id="agent-platform-category"
							value={values.category ?? '通用'}
							onChange={(event) => onChange('category', event.target.value)}
						/>
					</Field>
					<Field>
						<FieldLabel htmlFor="agent-platform-sort-order">
							{t('agent-form.platform-config.sortOrder')}
						</FieldLabel>
						<Input
							id="agent-platform-sort-order"
							type="number"
							min={0}
							max={9999}
							value={values.sort_order ?? 100}
							onChange={(event) =>
								onChange('sort_order', Number(event.target.value || 0))
							}
						/>
					</Field>
				</div>
			)}

			<Field>
				<FieldLabel htmlFor="agent-platform-permission-mode">
					{t('agent-form.platform-config.permissionMode')}
				</FieldLabel>
				<Select
					value={values.permission_mode ?? 'auto'}
					onValueChange={(value) => onChange('permission_mode', value as PermissionMode)}
				>
					<SelectTrigger id="agent-platform-permission-mode" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						{PERMISSION_MODES.map((value) => (
							<SelectItem key={value} value={value}>
								{t(`agent-form.platform-config.permissionOptions.${value}`)}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<FieldDescription>
					{t('agent-form.platform-config.permissionModeDescription')}
				</FieldDescription>
			</Field>

			{!isFixed && (
				<Alert>
					{role === 'business' ? <Wrench /> : <Info />}
					<AlertDescription>
						{t('agent-form.platform-config.visibilityNotice')}
					</AlertDescription>
				</Alert>
			)}
		</FieldGroup>
	);
}
