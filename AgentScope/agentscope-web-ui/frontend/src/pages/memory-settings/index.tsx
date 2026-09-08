import { BrainCircuit, Loader2, Save, RotateCcw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { agentApi } from '@/api/agent';
import type { MemorySettings, MemorySettingsResponse } from '@/api/types';
import { LlmSelect } from '@/components/select/LlmSelect';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

export function MemorySettingsPage() {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const text = (cn: string, en: string) => zh ? cn : en;
	const navigate = useNavigate();
	const [response, setResponse] = useState<MemorySettingsResponse | null>(null);
	const [settings, setSettings] = useState<MemorySettings | null>(null);
	const [error, setError] = useState('');
	const [busy, setBusy] = useState(false);
	useEffect(() => { let active = true; agentApi.getMemorySettings().then((value) => {
		if (active) { setResponse(value); setSettings(value.settings); }
	}).catch((err) => { if (active) setError(formatApiErrorForAlert(err)); }); return () => { active = false; }; }, []);
	const update = <K extends keyof MemorySettings>(key: K, value: MemorySettings[K]) => setSettings((old) => old ? { ...old, [key]: value } : old);
	const save = async (reset = false) => {
		if (!settings || !response) return;
		if (reset && !window.confirm(text('恢复设置默认值？已有记忆不会删除。', 'Reset settings? Existing memories will be preserved.'))) return;
		setBusy(true);
		try { const value = reset ? await agentApi.resetMemorySettings(response.revision) : await agentApi.updateMemorySettings({ settings, expected_revision: response.revision });
			setResponse(value); setSettings(value.settings); toast.success(text('设置已保存', 'Settings saved'));
		} catch (err) { toast.error(formatApiErrorForAlert(err)); } finally { setBusy(false); }
	};
	if (error) return <div role="alert" className="p-6 text-sm text-destructive">{error}</div>;
	if (!settings || !response) return <div className="flex items-center gap-2 p-6 text-sm"><Loader2 className="size-4 animate-spin" />{text('正在读取设置', 'Loading settings')}</div>;
	const number = (key: keyof MemorySettings, title: string, help: string, min: number, max: number, step = 1) => <label key={key} className="block space-y-2 rounded-lg border p-4">
		<span className="text-sm font-medium">{title}</span><Input type="number" min={min} max={max} step={step} value={String(settings[key])} onChange={(e) => update(key, Number(e.target.value))} />
		<span className="block text-xs leading-5 text-muted-foreground">{help}</span></label>;
	const toggle = (key: 'memory_profile_enabled' | 'memory_semantic_search_enabled' | 'memory_index_enabled' | 'learning_enabled' | 'group_learning_enabled' | 'learning_auto_consolidate' | 'learning_capture_corrections' | 'learning_capture_failures' | 'learning_capture_verified_tasks' | 'learning_capture_patterns', title: string, help: string) => <div key={key} className="flex items-start justify-between gap-4 rounded-lg border p-4">
		<div><label htmlFor={key} className="text-sm font-medium">{title}</label><p className="mt-1 text-xs leading-5 text-muted-foreground">{help}</p></div>
		<Switch id={key} checked={settings[key]} onCheckedChange={(value) => update(key, value)} /></div>;
	return <div className="flex h-full min-h-0 flex-col bg-muted/20 text-sm">
		<header className="flex flex-wrap items-center justify-between gap-4 border-b bg-background px-6 py-4"><div><h1 className="flex items-center gap-2 text-lg font-semibold"><BrainCircuit className="size-5" />{text('记忆设置', 'Memory settings')}</h1>
			<p className="mt-1 text-xs text-muted-foreground">{text('主模型决定保存内容，正文直接落库，后台建立索引。', 'The main model selects facts; content is saved directly and indexed in the background.')}</p></div>
			<div className="flex gap-2"><Button variant="outline" disabled={busy} onClick={() => void save(true)}><RotateCcw className="size-4" />{text('恢复默认', 'Reset')}</Button><Button disabled={busy || JSON.stringify(settings) === JSON.stringify(response.settings)} onClick={() => void save()}><Save className="size-4" />{text('保存设置', 'Save')}</Button></div></header>
		<main className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4 sm:p-6">
			<section className="space-y-4 rounded-xl border bg-background p-5"><h2 className="font-semibold">{text('三个抽屉的保存规则', 'Three-drawer storage')}</h2>
				<p className="text-sm leading-7">{text('用户级保存跨项目个人资料；用户＋项目级保存项目内私人上下文；项目级保存已授权共享的事实。保存过程不调用分类模型，也不等待向量生成。', 'User memories span projects; user + project memories remain private; project memories contain authorized shared facts. Saving does not call a classification model or wait for embeddings.')}</p>
				<Button variant="outline" onClick={() => navigate('/memory-management')}>{text('打开记忆管理', 'Open memory management')}</Button>
			</section>
			<section className="space-y-4 rounded-xl border bg-background p-5"><h2 className="font-semibold">{text('读取与后台索引', 'Retrieval and indexing')}</h2><div className="grid gap-3 lg:grid-cols-2">
				{toggle('memory_profile_enabled', text('加载常用个人资料', 'Load essential profile'), text('只读取姓名、称呼和回答详略等明确字段；群聊不加载私人资料。', 'Read exact name, address and response preferences. Private profiles are excluded from group conversations.'))}
				{toggle('memory_semantic_search_enabled', text('使用语义检索', 'Use semantic retrieval'), text('向量模型就绪时辅助文字检索；未就绪或超时时使用文本检索。', 'Use embeddings when ready; fall back to text retrieval if unavailable or slow.'))}
				{toggle('memory_index_enabled', text('处理后台索引任务', 'Process index jobs'), text('关闭后暂停建立索引，正文仍可保存、修改及按字段查询；重新开启后继续处理。', 'Pause indexing without stopping content writes or exact lookup. Pending jobs resume when enabled.'))}
				{number('recall_top_k', text('默认返回条数', 'Default result count'), text('工具单次最多返回 10 条，优先保留相关结果。', 'Return up to 10 relevant records per tool call.'), 1, 10)}
			</div><p className="text-xs text-muted-foreground">{response.infrastructure.embedding_provider} · {response.infrastructure.embedding_model} · {response.infrastructure.embedding_dimensions} {text('维', 'dimensions')}</p>
				<p className="text-xs leading-5 text-muted-foreground">{text('索引任务状态、失败原因及重试入口位于记忆管理页面。', 'Index job status, failures and retry controls are available in memory management.')}</p></section>
			<section className="space-y-4 rounded-xl border bg-background p-5"><h2 className="font-semibold">{text('群聊持续学习', 'Continuous group learning')}</h2>
				<p className="text-xs leading-6 text-muted-foreground">{text('所有成员的消息均可提供证据，无须 @ 智能体。后台检查不调用模型，满足条件后一次完成价值判断与提炼；允许没有成果，群内不发送总结通知。全体群可以产生项目记忆，子群仅产生有权成员的用户＋项目记忆，个人偏好仅归发言者本人。', 'All members contribute evidence. Scheduling is silent; one model call evaluates and extracts valuable results with visibility-based routing.')}</p>
				{toggle('group_learning_enabled', text('自动学习群聊消息', 'Learn from group messages'), text('同时受后台学习总开关和全局主智能体的学习权限控制。恢复后继续未处理消息。', 'Also follows the global learning switch and main agent policy.'))}
				<div className="grid gap-3 lg:grid-cols-2">
					{number('group_learning_scan_seconds', text('检查间隔（秒）', 'Scan interval (seconds)'), text('默认每 5 分钟检查新增与变更消息；检查本身不调用模型。', 'Check new and changed messages without a model call.'), 30, 3600)}
					{number('group_learning_message_threshold', text('累计消息触发条数', 'Message threshold'), text('达到条数即可排队；空闲或最长等待也可触发。', 'Queue after this count, idle time, or maximum wait.'), 1, 100)}
					{number('group_learning_idle_seconds', text('群聊空闲触发（秒）', 'Idle time (seconds)'), text('有待处理消息且安静这么久后，整理尚未完成的讨论。', 'Process pending messages after the group becomes quiet.'), 60, 86400)}
					{number('group_learning_max_wait_seconds', text('最长等待（秒）', 'Maximum wait (seconds)'), text('避免持续零星发言导致永远无法触发。', 'Prevent low-volume active groups from starving.'), 300, 86400)}
					{number('group_learning_batch_size', text('每批最多变更条数', 'Changes per batch'), text('多余消息留给下一批；失败保留本批区间，重试不会覆盖已完成批次。', 'Leave excess changes for subsequent batches.'), 1, 100)}
					{number('group_learning_daily_limit', text('每日群聊批次上限', 'Daily group batch limit'), text('独立于对话学习预算；超出时保留未处理消息。', 'Independent of interactive learning; retain pending messages beyond the limit.'), 1, 2000)}
				</div><p className="text-xs leading-6 text-muted-foreground">{text('使用下方学习模型；未配置时使用全局主智能体的固定模型。群聊后台任务没有当前会话模型可回退。进度、证据、跳过原因、暂停和重试位于记忆管理。', 'Uses the learning model or the global main agent’s fixed model. Progress, evidence, pause and retry are available in memory management.')}</p>
			</section>
			<section className="space-y-4 rounded-xl border bg-background p-5"><h2 className="font-semibold">{text('后台学习', 'Background learning')}</h2>
				<p className="text-xs leading-6 text-muted-foreground">{text('从实际纠正和任务证据生成反思、经验或操作技能，系统自动判断价值并校验，满足条件直接生效。私人对话按下列事件触发，群聊按上方持续学习策略处理。明确事实直接保存。每个智能体可分别关闭记录、提炼或使用。', 'Automatically evaluate and publish useful lessons from evidence. Private conversations use event triggers; groups use the continuous policy above.')}</p>
				{toggle('learning_enabled', text('启用后台学习', 'Enable background learning'), text('暂停新素材记录和后台提炼时，保留现有成果与待处理任务。', 'Pausing preserves existing results and jobs.'))}
				<div className="space-y-2"><p className="text-sm font-medium">{text('学习模型', 'Learning model')}</p><LlmSelect value={settings.learning_model_config} onChange={(value) => update('learning_model_config', value)} onAddCredential={() => navigate('/credential')} allowClear placeholder={text('使用来源智能体／会话模型', 'Use source agent/session model')} clearLabel={text('使用来源智能体／会话模型', 'Use source agent/session model')} /><p className="text-xs leading-5 text-muted-foreground">{text('与对话压缩模型独立。未配置时使用来源智能体固定模型或来源会话模型；不可用时保留任务供重试。', 'Independent of compression. Unavailable models leave retryable jobs.')}</p></div>
				<div className="grid gap-3 lg:grid-cols-2">
					{toggle('learning_capture_corrections', text('用户纠正触发', 'User corrections'), text('结合上一条回答记录纠正，不把普通记住指令当成错误。', 'Capture corrections with the previous answer.'))}
					{toggle('learning_capture_failures', text('失败与修复触发', 'Failures and recovery'), text('单独失败只记录素材；观察到同一工具修复成功后再提炼。', 'Record isolated failures; generate lessons after recovery.'))}
					{toggle('learning_capture_verified_tasks', text('任务完成触发', 'Task completion'), text('需要新完成的任务和实际工具结果，助手自称完成不够。', 'Require a completed task and actual tool results.'))}
					{toggle('learning_capture_patterns', text('重复操作触发', 'Repeated patterns'), text('同一归属下重复工具操作达到阈值后提炼。', 'Generate after repeated patterns in the same owner scope.'))}
					{toggle('learning_auto_consolidate', text('周期合并已验证经验', 'Periodic consolidation'), text('每小时检查；同一归属至少 3 条经验时生成合并候选，同一批版本不重复处理。', 'Check hourly and consolidate at least three lessons in one owner scope. Source versions are processed only once.'))}
					{number('learning_daily_job_limit', text('每智能体每日自动任务上限', 'Daily jobs per agent'), text('超出后保留素材，可在管理端手动排队。', 'Keep evidence beyond the limit.'), 1, 200)}
					{number('learning_cooldown_seconds', text('提炼等待／冷却秒数', 'Delay / cooldown seconds'), text('收集任务结果，减少相同事件重复调用模型。', 'Collect results and suppress duplicate calls.'), 0, 3600)}
					{number('learning_pattern_threshold', text('重复模式触发次数', 'Pattern threshold'), text('重复触发候选提炼，不自动证明方法正确。', 'Repetition does not imply correctness.'), 2, 20)}
					{number('learning_timeout_seconds', text('单次提炼超时秒数', 'Generation timeout'), text('失败最多自动尝试 3 次，可取消或手动重试。', 'Up to three attempts, with cancel and retry.'), 10, 180)}
					{number('learning_input_char_limit', text('单次学习材料字符预算', 'Input character budget'), text('限制送入模型的材料长度；完整证据仍保留供审计。', 'Bound model input while retaining full audit evidence.'), 4000, 60000, 1000)}
					{number('learning_review_days', text('学习成果复核周期（天）', 'Review interval (days)'), text('到期或收到失败反馈时标记复核，不自动删除明确事实。', 'Flag aging lessons and failures without deleting facts.'), 7, 365)}
					{number('learning_skill_limit', text('单轮最多加载操作技能', 'Skills per turn'), text('仅匹配已启用技能；0 表示不自动加载。', 'Only relevant active skills; zero disables loading.'), 0, 10)}
				</div>
			</section>
			<section className="space-y-4 rounded-xl border bg-background p-5"><h2 className="font-semibold">{text('长对话压缩', 'Long conversation compression')}</h2><p className="text-xs leading-5 text-muted-foreground">{text('此模型只处理长对话摘要和压缩，不审核或阻塞记忆保存。留空时沿用当前对话模型。', 'This model summarizes long conversations. It does not approve or block memory writes. Leave empty to use the conversation model.')}</p>
				<LlmSelect value={settings.memory_model_config} onChange={(value) => update('memory_model_config', value)} onAddCredential={() => navigate('/credential')} allowClear placeholder={text('使用当前对话模型', 'Use conversation model')} clearLabel={text('使用当前对话模型', 'Use conversation model')} />
				<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
					{number('compression_trigger_ratio', text('压缩触发比例', 'Compression trigger'), text('相对于当前对话模型的上下文窗口。', 'Relative to the conversation model context window.'), 0.1, 0.9, 0.01)}
					{number('compression_keep_messages', text('保留近期消息', 'Keep recent messages'), text('优先完整保留最近的对话。', 'Preserve recent conversation messages.'), 2, 200)}
					{number('emergency_compression_ratio', text('紧急压缩比例', 'Emergency compression'), text('必须高于普通触发比例。', 'Must exceed the regular trigger ratio.'), 0.9, 1, 0.01)}
					{number('compression_max_consecutive', text('连续压缩上限', 'Consecutive compression limit'), text('防止连续压缩反复消耗模型调用。', 'Bound repeated compression calls.'), 1, 20)}
					{number('compression_min_rounds_between', text('压缩最小间隔轮数', 'Minimum turn interval'), text('两次普通压缩之间的最少对话轮数。', 'Minimum turns between regular compressions.'), 0, 100)}
					{number('compression_quality_threshold', text('摘要质量阈值', 'Summary quality threshold'), text('用于检查压缩结果。', 'Check the quality of compressed summaries.'), 0, 1, 0.01)}
				</div><label className="block space-y-2"><span>{text('压缩方式', 'Compression mode')}</span><select className="block h-9 rounded-md border bg-background px-3 text-sm" value={settings.compression_mode} onChange={(e) => update('compression_mode', e.target.value as MemorySettings['compression_mode'])}><option value="incremental">{text('增量摘要', 'Incremental')}</option><option value="full">{text('完整摘要', 'Full')}</option></select></label>
			</section>
			<details className="space-y-4 rounded-xl border bg-background p-5"><summary className="cursor-pointer font-semibold">{text('高级：对话压缩提示词', 'Advanced: compression prompts')}</summary>
				{(['compression_system_prompt', 'compression_user_prompt', 'compression_incremental_prompt'] as const).map((key) => <label key={key} className="block space-y-2"><span className="text-xs">{key}</span><Textarea rows={10} className="text-xs leading-6" value={settings[key]} onChange={(e) => update(key, e.target.value)} /></label>)}
			</details>
		</main>
	</div>;
}
