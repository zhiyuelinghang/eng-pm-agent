import { Pencil, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type { Skill } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';
import { cleanSkillHeading, getSkillDisplayName } from '@/lib/skill-display';

interface SkillDetailDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	skill: Skill | null;
	onEdit: (skill: Skill) => void;
	onDelete: (skill: Skill) => void;
}

interface SkillContentSection {
	id: string;
	label: string;
	markdown: string;
}

function readSkillSections(markdown: string, fallbackLabel: string): SkillContentSection[] {
	const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
	const sections: Array<{ label: string; lines: string[] }> = [];
	let current: { label: string; lines: string[] } = {
		label: fallbackLabel,
		lines: [],
	};

	for (const line of lines) {
		const heading = /^(#{1,2})\s+(.+?)\s*#*\s*$/.exec(line);
		if (!heading) {
			current.lines.push(line);
			continue;
		}
		if (current.lines.some((item) => item.trim())) sections.push(current);
		current = {
			label: cleanSkillHeading(heading[2]) || fallbackLabel,
			lines: [],
		};
	}
	if (current.lines.some((item) => item.trim()) || sections.length === 0) sections.push(current);

	return sections.map((section, index) => ({
		id: `content:${index}`,
		label: section.label,
		markdown: section.lines.join('\n').trim(),
	}));
}

export function SkillDetailDialog({
	open,
	onOpenChange,
	skill,
	onEdit,
	onDelete,
}: SkillDetailDialogProps) {
	const { t } = useTranslation();
	const detailScrollRef = useRef<HTMLDivElement>(null);
	const detailSectionRefs = useRef<Record<string, HTMLElement | null>>({});
	const [activeSection, setActiveSection] = useState('overview');
	const contentSections = useMemo(
		() => readSkillSections(skill?.markdown ?? '', t('panel.skill.instructions')),
		[skill?.markdown, t],
	);
	const directorySections = skill
		? [
				{ id: 'overview', label: t('panel.skill.details') },
				...contentSections.map(({ id, label }) => ({ id, label })),
			]
		: [];

	useEffect(() => {
		if (!open) return;
		setActiveSection('overview');
		detailScrollRef.current?.scrollTo({ top: 0 });
	}, [open, skill?.name]);

	const scrollToSection = (sectionId: string) => {
		const container = detailScrollRef.current;
		const section = detailSectionRefs.current[sectionId];
		if (!container || !section) return;
		container.scrollTo({
			top: Math.max(0, section.offsetTop - 24),
			behavior: 'smooth',
		});
		setActiveSection(sectionId);
	};

	const handleScroll = () => {
		const container = detailScrollRef.current;
		if (!container) return;
		const position = container.scrollTop + 48;
		let current = 'overview';
		for (const section of directorySections) {
			const element = detailSectionRefs.current[section.id];
			if (!element || element.offsetTop > position) break;
			current = section.id;
		}
		setActiveSection(current);
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			{skill ? (
				<DialogContent className="grid h-[min(820px,calc(100dvh-2rem))] max-h-[calc(100dvh-2rem)] !w-[min(900px,calc(100vw-2rem))] !max-w-[900px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
					<DialogHeader className="border-b px-6 py-5 pr-14">
						<DialogTitle className="text-xl leading-tight">
							{getSkillDisplayName(skill)}
						</DialogTitle>
						<DialogDescription>{skill.name}</DialogDescription>
					</DialogHeader>

					<div className="grid min-h-0 grid-cols-1 md:grid-cols-[12rem_minmax(0,1fr)]">
						<nav
							aria-label={t('panel.skill.directory')}
							className="flex gap-1 overflow-x-auto border-b bg-muted/20 p-3 md:flex-col md:overflow-x-hidden md:border-r md:border-b-0 md:px-3 md:py-5"
						>
							{directorySections.map((section, index) => {
								const active = activeSection === section.id;
								return (
									<button
										key={section.id}
										type="button"
										aria-current={active ? 'location' : undefined}
										onClick={() => scrollToSection(section.id)}
										className={`group flex min-w-max items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring md:min-w-0 ${
											active
												? 'bg-background text-[#c95622] shadow-sm ring-1 ring-border/70'
												: 'text-muted-foreground hover:bg-background/80 hover:text-foreground'
										}`}
										title={section.label}
									>
										<span
											aria-hidden="true"
											className={`flex size-5 shrink-0 items-center justify-center rounded-md text-xs tabular-nums ${
												active
													? 'bg-[#c95622]/10 text-[#c95622]'
													: 'bg-muted text-muted-foreground'
											}`}
										>
											{index === 0 ? 'i' : index}
										</span>
										<span className="truncate">{section.label}</span>
									</button>
								);
							})}
						</nav>

						<div
							ref={detailScrollRef}
							onScroll={handleScroll}
							className="no-scrollbar relative min-h-0 overflow-y-auto scroll-smooth px-6 py-6"
						>
							<article className="mx-auto max-w-2xl">
								<section
									ref={(element) => {
										detailSectionRefs.current.overview = element;
									}}
									className="scroll-mt-6 pb-7"
								>
									<h2 className="text-lg font-semibold">{t('panel.skill.details')}</h2>
									<p className="mt-3 max-w-[65ch] whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
										{skill.description}
									</p>
								</section>

								{contentSections.map((section) => (
									<section
										key={section.id}
										ref={(element) => {
											detailSectionRefs.current[section.id] = element;
										}}
										className="scroll-mt-6 border-t py-7"
									>
										<h2 className="text-lg font-semibold">{section.label}</h2>
										{section.markdown ? (
											<div className="prose mt-4 min-w-full max-w-none text-sm">
												<ReactMarkdown remarkPlugins={[remarkGfm]}>
													{section.markdown}
												</ReactMarkdown>
											</div>
										) : (
											<p className="mt-3 text-sm text-muted-foreground">
												{t('panel.skill.noInstructions')}
											</p>
										)}
									</section>
								))}
							</article>
						</div>
					</div>

					<DialogFooter className="m-0 rounded-none border-t bg-background px-6 py-4 sm:justify-between">
						<Button variant="ghost" onClick={() => onDelete(skill)}>
							<Trash2 />
							{t('common.delete')}
						</Button>
						<div className="flex justify-end gap-2">
							<Button variant="outline" onClick={() => onOpenChange(false)}>
								{t('common.close')}
							</Button>
							<Button onClick={() => onEdit(skill)}>
								<Pencil />
								{t('common.edit')}
							</Button>
						</div>
					</DialogFooter>
				</DialogContent>
			) : null}
		</Dialog>
	);
}
