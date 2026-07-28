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
		<main className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#f4f7f5] px-5 py-10 dark:bg-background">
			<div
				aria-hidden="true"
				className="pointer-events-none absolute -top-40 -right-28 size-[30rem] rounded-full bg-[#c95622]/8 blur-3xl"
			/>
			<div
				aria-hidden="true"
				className="pointer-events-none absolute -bottom-56 -left-32 size-[34rem] rounded-full bg-[#173f3e]/8 blur-3xl"
			/>
			<div className={cn('relative flex w-full max-w-md flex-col gap-5', className)}>
				<Card className="gap-5 bg-card/95 py-6 shadow-[0_24px_70px_rgba(16,37,40,0.12)] backdrop-blur-sm">
					<CardHeader className="gap-4 px-6">
						<div className="flex items-center gap-3.5">
							<img
								src="/dobby.svg"
								alt="Dobby"
								className="size-12 rounded-xl shadow-[0_8px_20px_rgba(201,86,34,0.24)]"
							/>
							<div className="min-w-0">
								<p className="text-[11px] font-semibold tracking-[0.18em] text-[#c95622] uppercase">
									Dobby
								</p>
								<CardTitle className="mt-0.5 text-xl font-semibold tracking-[-0.02em] text-[#173f3e] dark:text-foreground">
									{t('setup.title')}
								</CardTitle>
							</div>
						</div>
						<CardDescription className="max-w-[36ch] leading-6">
							{t('setup.description')}
						</CardDescription>
					</CardHeader>
					<CardContent className="px-6">
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
									<Button
										type="submit"
										className="w-full bg-[#173f3e] text-white transition-transform duration-200 hover:-translate-y-0.5 hover:bg-[#102f30] active:translate-y-0"
										disabled={submitting}
									>
										{submitting ? t('setup.submitting') : t('setup.submit')}
									</Button>
								</Field>
							</FieldGroup>
						</form>
					</CardContent>
				</Card>
				<FieldDescription className="px-8 text-center leading-5">
					{t('setup.hint')}
				</FieldDescription>
			</div>
		</main>
	);
};
