import { Search, SearchX, Wrench } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { AgentView, WorkspaceTool } from '@/api';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n';

interface ToolPanelProps {
	agent: AgentView | null;
	tools: WorkspaceTool[];
	loading?: boolean;
}

interface ToolParameter {
	name: string;
	type: string;
	description: string | null;
	required: boolean;
}

const WORKSPACE_TOOL_KEYS: Record<string, string> = {
	Edit: 'edit',
	Glob: 'glob',
	Grep: 'grep',
	Read: 'read',
	Write: 'write',
};

function readToolParameters(inputSchema: Record<string, unknown>): ToolParameter[] {
	const rawProperties = inputSchema.properties;
	if (!rawProperties || typeof rawProperties !== 'object' || Array.isArray(rawProperties)) {
		return [];
	}
	const required = new Set(
		Array.isArray(inputSchema.required)
			? inputSchema.required.filter((value): value is string => typeof value === 'string')
			: [],
	);
	return Object.entries(rawProperties).map(([name, rawDefinition]) => {
		const definition =
			rawDefinition && typeof rawDefinition === 'object' && !Array.isArray(rawDefinition)
				? (rawDefinition as Record<string, unknown>)
				: {};
		const rawType = definition.type;
		const type = Array.isArray(rawType)
			? rawType.filter((value) => typeof value === 'string').join(' / ')
			: typeof rawType === 'string'
				? rawType
				: 'any';
		return {
			name,
			type,
			description: typeof definition.description === 'string' ? definition.description : null,
			required: required.has(name),
		};
	});
}

export function ToolPanel({ agent, tools, loading = false }: ToolPanelProps) {
	const { t, i18n } = useTranslation();
	const [search, setSearch] = useState('');
	const [selectedName, setSelectedName] = useState<string | null>(null);
	const isChinese = i18n.language.startsWith('zh');
	const visibleTools = useMemo(
		() => tools.filter((tool) => tool.category !== 'database'),
		[tools],
	);

	const getPresentation = (tool: WorkspaceTool) => {
		const workspaceKey = WORKSPACE_TOOL_KEYS[tool.name];
		const rawDescription = tool.description?.trim() ?? '';
		return {
			name:
				tool.display_name?.trim() ||
				(workspaceKey ? t(`panel.tool.workspaceTools.${workspaceKey}.name`) : tool.name),
			description: workspaceKey
				? t(`panel.tool.workspaceTools.${workspaceKey}.description`)
				: isChinese && rawDescription && !/[\u3400-\u9fff]/u.test(rawDescription)
					? t('panel.tool.untranslatedDescription')
					: rawDescription,
		};
	};

	const query = search.trim().toLowerCase();
	const filtered = query
		? visibleTools.filter((tool) => {
				const presentation = getPresentation(tool);
				return (
					tool.name.toLowerCase().includes(query) ||
					presentation.name.toLowerCase().includes(query) ||
					presentation.description.toLowerCase().includes(query)
				);
			})
		: visibleTools;
	const selectedTool = visibleTools.find((tool) => tool.name === selectedName) ?? null;
	const selectedPresentation = selectedTool ? getPresentation(selectedTool) : null;
	const selectedParameters = selectedTool ? readToolParameters(selectedTool.input_schema) : [];

	if (loading && !agent) {
		return (
			<div className="flex flex-1 items-center justify-center">
				<p className="text-sm text-muted-foreground">{t('panel.loading')}</p>
			</div>
		);
	}

	if (!agent) {
		return (
			<PanelEmpty
				icon={Wrench}
				title={t('panel.tool.noAgentTitle')}
				description={t('panel.tool.noAgentDescription')}
			/>
		);
	}

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<Dialog
				open={selectedTool !== null}
				onOpenChange={(open) => {
					if (!open) setSelectedName(null);
				}}
			>
				{selectedTool && selectedPresentation ? (
					<DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-2xl">
						<DialogHeader>
							<DialogTitle>{selectedPresentation.name}</DialogTitle>
							<DialogDescription>
								<code className="break-all text-xs">{selectedTool.name}</code>
							</DialogDescription>
						</DialogHeader>

						<div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-1">
							<section className="space-y-2">
								<h3 className="text-sm font-medium">{t('panel.tool.details')}</h3>
								<p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
									{selectedPresentation.description || t('panel.tool.noDescription')}
								</p>
							</section>

							<section className="space-y-2">
								<h3 className="text-sm font-medium">{t('panel.tool.parameters')}</h3>
								{selectedParameters.length ? (
									<div className="divide-y rounded-md border">
										{selectedParameters.map((parameter) => {
											const translatedName = t(
												`panel.tool.parameterNames.${parameter.name}`,
												{ defaultValue: parameter.name },
											);
											const visibleDescription =
												!isChinese ||
												(parameter.description &&
													/[\u3400-\u9fff]/u.test(parameter.description))
													? parameter.description
													: null;
											return (
												<div key={parameter.name} className="px-3 py-2.5">
													<div className="flex items-center justify-between gap-2">
														<div className="min-w-0">
															<span className="text-sm font-medium">
																{translatedName}
															</span>
															{translatedName !== parameter.name ? (
																<code className="ml-2 text-xs text-muted-foreground">
																	{parameter.name}
																</code>
															) : null}
														</div>
														<span className="shrink-0 text-xs text-muted-foreground">
															{parameter.required
																? t('panel.tool.required')
																: t('panel.tool.optional')}
															{' · '}
															{parameter.type}
														</span>
													</div>
													{visibleDescription ? (
														<p className="mt-1 text-sm text-muted-foreground">
															{visibleDescription}
														</p>
													) : null}
												</div>
											);
										})}
									</div>
								) : (
									<p className="text-sm text-muted-foreground">
										{t('panel.tool.noParameters')}
									</p>
								)}
							</section>
						</div>

						<DialogFooter>
							<Button variant="outline" onClick={() => setSelectedName(null)}>
								{t('common.close')}
							</Button>
						</DialogFooter>
					</DialogContent>
				) : null}
			</Dialog>

			<div className="flex-none space-y-3 pb-3">
				<div className="flex items-baseline justify-between gap-3">
					<span className="text-sm font-medium">{t('panel.tool.catalogTitle')}</span>
					<span className="text-xs tabular-nums text-muted-foreground">
						{t('panel.tool.countSummary', { count: visibleTools.length })}
					</span>
				</div>
				<InputGroup>
					<InputGroupInput
						placeholder={t('panel.tool.searchPlaceholder')}
						value={search}
						onChange={(event) => setSearch(event.target.value)}
					/>
					<InputGroupAddon align="inline-end">
						<Search />
					</InputGroupAddon>
				</InputGroup>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border">
				{loading ? (
					<div className="flex h-full items-center justify-center">
						<p className="text-sm text-muted-foreground">{t('panel.loading')}</p>
					</div>
				) : filtered.length === 0 ? (
					<PanelEmpty
						icon={search ? SearchX : Wrench}
						title={search ? t('panel.search.emptyTitle') : t('panel.tool.emptyTitle')}
						description={
							search
								? t('panel.search.emptyDescription', { query: search })
								: t('panel.tool.emptyDescription')
						}
					/>
				) : (
					<div className="divide-y">
						{filtered.map((tool) => {
							const presentation = getPresentation(tool);
							return (
								<PanelCatalogRow
									key={tool.name}
									title={presentation.name}
									description={presentation.description}
									onOpen={() => setSelectedName(tool.name)}
									openLabel={t('panel.tool.viewDetails', {
										name: presentation.name,
									})}
								/>
							);
						})}
					</div>
				)}
			</div>
		</div>
	);
}
