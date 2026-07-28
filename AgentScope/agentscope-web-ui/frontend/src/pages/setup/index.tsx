import { useState } from 'react';

import { ApiError, loginManagement } from '@/api/client.ts';
import { Button } from '@/components/ui/button.tsx';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card.tsx';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field.tsx';
import { Input } from '@/components/ui/input.tsx';
import { useTranslation } from '@/i18n/useI18n.ts';
import { cn } from '@/lib/utils.ts';

interface Props {
	onComplete: () => void;
	className?: string;
}

export const SetupPage = ({ onComplete, className }: Props) => {
	const { t } = useTranslation();
	const [username, setUsername] = useState(() => localStorage.getItem('auth_username') || '');
	const [password, setPassword] = useState('');
	const [submitting, setSubmitting] = useState(false);
	const [error, setError] = useState('');

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError('');
		setSubmitting(true);
		try {
			await loginManagement(username, password);
			setPassword('');
			onComplete();
		} catch (reason) {
			setError(reason instanceof ApiError ? reason.detail : t('setup.connectionFailed'));
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<div className="flex items-center justify-center h-full">
			<div className={cn('flex flex-col gap-6 w-full max-w-sm', className)}>
				<Card>
					<CardHeader>
						<CardTitle>{t('setup.title')}</CardTitle>
						<CardDescription>{t('setup.description')}</CardDescription>
					</CardHeader>
					<CardContent>
						<form onSubmit={handleSubmit}>
							<FieldGroup>
								<Field>
									<FieldLabel htmlFor="username-input">
										{t('setup.username')}
									</FieldLabel>
									<Input
										id="username-input"
										type="text"
										placeholder={t('setup.usernamePlaceholder')}
										value={username}
										onChange={(e) => setUsername(e.target.value)}
										required
									/>
								</Field>
								<Field>
									<FieldLabel htmlFor="password-input">
										{t('setup.password')}
									</FieldLabel>
									<Input
										id="password-input"
										type="password"
										autoComplete="current-password"
										placeholder={t('setup.passwordPlaceholder')}
										value={password}
										onChange={(e) => setPassword(e.target.value)}
										required
									/>
								</Field>
								{error && (
									<FieldDescription className="text-destructive">
										{error}
									</FieldDescription>
								)}
								<Field>
									<Button type="submit" className="w-full" disabled={submitting}>
										{submitting ? t('setup.submitting') : t('setup.submit')}
									</Button>
								</Field>
							</FieldGroup>
						</form>
					</CardContent>
				</Card>
				<FieldDescription className="px-6 text-center">{t('setup.hint')}</FieldDescription>
			</div>
		</div>
	);
};
