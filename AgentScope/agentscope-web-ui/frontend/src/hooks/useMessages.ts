import { EventType } from '@agentscope-ai/agentscope/event';
import type {
	AgentEvent,
	CustomEvent,
	DataBlockStartEvent,
	DataBlockDeltaEvent,
	DataBlockEndEvent,
	ReplyStartEvent,
	UserConfirmResultEvent,
} from '@agentscope-ai/agentscope/event';
import { appendEvent, AssistantMsg, UserMsg } from '@agentscope-ai/agentscope/message';
import type { Msg, ContentBlock } from '@agentscope-ai/agentscope/message';
import type { ToolCallBlock } from '@agentscope-ai/agentscope/message';
import { useState, useCallback, useRef, useEffect } from 'react';

import { sessionApi } from '@/api';
import { chatApi } from '@/api';
import { useAudioManager } from '@/context/AudioContext';

/**
 * One pending subagent HITL request, projected from a team *member*
 * session onto its *leader* session so the leader UI can render and
 * resolve it. Mirrors the Python payload written by
 * ``SubagentHitlProjector`` and pushed/replayed as a ``CustomEvent``
 * (``name="subagent_require_user_confirm"``).
 */
export type SubagentHitlEntry = {
	worker_session_id: string;
	worker_agent_id: string;
	worker_agent_name: string;
	reply_id: string;
	event_type: 'require_user_confirm' | 'require_external_execution';
	/** The original ``RequireUserConfirmEvent`` payload (serialized). */
	event: { tool_calls?: ToolCallBlock[] } & Record<string, unknown>;
	created_at: string;
};

/**
 * Return true if ``msg`` is an assistant reply currently parked on a
 * pending tool_call (awaiting user confirmation or an external
 * execution result). Used both to detect the "in-flight reply on page
 * load" case and as the SDK-gap workaround that hides the confirm
 * card once the paired tool_result lands.
 */
const hasPendingToolCall = (msg: Msg | undefined): boolean => {
	if (!msg || msg.role !== 'assistant') return false;
	for (const block of msg.content) {
		if (block.type !== 'tool_call') continue;
		const state = (block as ToolCallBlock).state;
		if (state === 'asking' || state === 'submitted') return true;
	}
	return false;
};

const hitlKey = (e: { worker_session_id: string; reply_id: string }) =>
	`${e.worker_session_id}:${e.reply_id}`;

/**
 * Lifecycle phase of the reply currently owned by this session.
 *
 * - ``idle`` — no in-flight reply; the send button is enabled.
 * - ``streaming`` — a reply is in progress (either actively producing
 *   events or parked awaiting HITL). The send button is replaced by a
 *   Stop button. The parked-vs-generating distinction is not tracked
 *   here; HITL cards render themselves from message content when a
 *   ``RequireUserConfirmEvent`` block is present.
 * - ``interrupting`` — the user has requested a stop and we are
 *   waiting for the backend's terminating ``ReplyEndEvent``. Stop
 *   button is shown but disabled so users cannot spam it. Falls back
 *   to ``idle`` after a 10s safety timeout in case the terminating
 *   event never arrives (dropped SSE frame, backend bug, etc.).
 * - ``settling`` — the terminal event has arrived, but the complete
 *   backend task is still releasing its run lock and persisting state.
 *   Sending remains disabled until the status endpoint confirms idle.
 */
export type ReplyPhase = 'idle' | 'streaming' | 'interrupting' | 'settling';

/** Safety fallback: force phase back to idle if REPLY_END is not seen. */
const INTERRUPT_TIMEOUT_MS = 10_000;
/** Poll cadence and safety deadline while backend persistence settles. */
const SETTLE_POLL_INTERVAL_MS = 100;
const SETTLE_TIMEOUT_MS = 60_000;

/**
 * Manages messages for a single ``(agentId, sessionId)`` pair.
 *
 * Event delivery has two independent channels:
 *
 * - **History** — ``GET /sessions/{sid}/messages`` fetches persisted
 *   ``Msg`` objects (each a complete reply).
 * - **Live stream** — ``GET /sessions/{sid}/stream`` is a long-lived
 *   SSE connection that pushes ``AgentEvent`` deltas as they are
 *   produced by any chat run on this session (user-triggered,
 *   background retrigger, team member message, …).
 *
 * The hook opens the SSE connection immediately after fetching
 * history. User input and human-in-the-loop confirmations are sent
 * via ``POST /chat/`` (fire-and-forget); the resulting events arrive
 * through the already-open SSE connection.
 *
 * ``phase`` moves to ``streaming`` on ``ReplyStartEvent`` and to
 * ``settling`` on ``ReplyEndEvent``. A status probe moves it to
 * ``idle`` only after the complete backend task has finished. Calling
 * ``interrupt()`` moves it to ``interrupting`` until the terminal
 * event arrives (or a 10s safety timeout fires).
 *
 * @param agentId - The agent whose session to subscribe. ``null`` to
 *   skip.
 * @param sessionId - The session to subscribe. ``null`` to skip.
 * @returns Object with ``msgs``, ``loading``, ``phase``, ``error``,
 *   ``send``, ``onUserConfirm``, and ``abort``.
 */
export function useMessages(
	agentId: string | null,
	sessionId: string | null,
	options?: {
		/**
		 * Called when a ``CUSTOM`` event with ``name="team_updated"``
		 * arrives — the team membership has changed (TeamCreate /
		 * AgentCreate / TeamDelete ran). The typical response is to
		 * refetch the session list so the team sidebar updates.
		 */
		onTeamUpdated?: () => void;
		/**
		 * Called when a ``CUSTOM`` event with ``name="state_updated"``
		 * arrives — agent state (tasks / permission) changed during a
		 * tool call. The ``value`` payload contains the latest
		 * ``tasks_context`` and ``permission_context``.
		 */
		onStateUpdated?: (value: Record<string, unknown>) => void;
	},
) {
	const [msgs, setMsgs] = useState<Msg[]>([]);
	const [loading, setLoading] = useState(false);
	const [phase, setPhase] = useState<ReplyPhase>('idle');
	const [error, setError] = useState<Error | null>(null);
	// Pending subagent HITL cards projected onto this (leader) session.
	const [subagentHitl, setSubagentHitl] = useState<SubagentHitlEntry[]>([]);

	const msgsRef = useRef<Msg[]>([]);
	const currentReplyRef = useRef<Msg | null>(null);
	const phaseRef = useRef<ReplyPhase>('idle');
	const abortRef = useRef<AbortController | null>(null);
	const rafRef = useRef<number | null>(null);
	// Incrementing either generation invalidates stale async work after a
	// session switch or a newer reply lifecycle transition.
	const bindingGenerationRef = useRef(0);
	const settleGenerationRef = useRef(0);
	const replyStartGenerationRef = useRef(0);
	// Timer that reverts ``interrupting`` back to ``idle`` if the
	// terminating REPLY_END never arrives (dropped SSE frame, etc.).
	const interruptTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const clearInterruptTimer = useCallback(() => {
		if (interruptTimerRef.current !== null) {
			clearTimeout(interruptTimerRef.current);
			interruptTimerRef.current = null;
		}
	}, []);

	const setReplyPhase = useCallback((next: ReplyPhase) => {
		phaseRef.current = next;
		setPhase(next);
	}, []);

	const audioManager = useAudioManager();

	const optionsRef = useRef(options);
	useEffect(() => {
		optionsRef.current = options;
	}, [options]);
	const scheduleUpdate = useCallback(() => {
		if (rafRef.current !== null) return;
		rafRef.current = requestAnimationFrame(() => {
			rafRef.current = null;
			setMsgs([...msgsRef.current]);
		});
	}, []);

	/**
	 * Keep the composer locked after REPLY_END until the complete backend
	 * task (including memory/state persistence) has left the run registry.
	 */
	const beginSettling = useCallback(() => {
		if (!agentId || !sessionId) {
			setReplyPhase('idle');
			return;
		}

		const generation = ++settleGenerationRef.current;
		setReplyPhase('settling');

		void (async () => {
			const deadline = Date.now() + SETTLE_TIMEOUT_MS;
			let lastError: Error | null = null;

			while (settleGenerationRef.current === generation) {
				try {
					const { status } = await sessionApi.status(sessionId, agentId);
					if (settleGenerationRef.current !== generation) return;

					lastError = null;
					if (status !== 'running') {
						// Parked HITL/external-tool sessions remain non-sendable and
						// retain the Stop control; only true idle enables Send.
						setReplyPhase(status === 'idle' ? 'idle' : 'streaming');
						return;
					}
				} catch (e) {
					lastError = e as Error;
				}

				if (Date.now() >= deadline) break;
				await new Promise<void>((resolve) =>
					setTimeout(resolve, SETTLE_POLL_INTERVAL_MS),
				);
			}

			if (settleGenerationRef.current !== generation) return;
			setError(
				lastError ??
					new Error('Timed out waiting for the session to finish persisting.'),
			);
			// Fail open after the safety deadline. A rejected retry is still
			// rolled back below, so no optimistic ghost message can remain.
			setReplyPhase('idle');
		})();
	}, [agentId, sessionId, setReplyPhase]);

	/** Apply a single AgentEvent to the in-progress reply. */
	const processEvent = useCallback(
		(event: AgentEvent) => {
			// Custom events are service-layer notifications, not agent
			// reply content — route them to callbacks and skip appendEvent.
			if (event.type === EventType.CUSTOM) {
				const custom = event as CustomEvent;
				if (custom.name === 'team_updated') {
					optionsRef.current?.onTeamUpdated?.();
				} else if (custom.name === 'state_updated' && custom.value) {
					optionsRef.current?.onStateUpdated?.(custom.value as Record<string, unknown>);
				} else if (custom.name === 'subagent_require_user_confirm') {
					// A team member is asking for confirmation; show (or
					// refresh) its card on this leader view. Dedup by
					// (worker_session_id, reply_id).
					const e = custom.value as unknown as SubagentHitlEntry;
					setSubagentHitl((prev) => [
						...prev.filter((x) => hitlKey(x) !== hitlKey(e)),
						e,
					]);
				} else if (custom.name === 'subagent_user_confirm_result') {
					// The member resolved (or its run ended); clear the card.
					const v = custom.value as { worker_session_id: string; reply_id: string };
					setSubagentHitl((prev) => prev.filter((x) => hitlKey(x) !== hitlKey(v)));
				}
				return;
			}
			if (event.type === EventType.REPLY_START) {
				const e = event as ReplyStartEvent;
				replyStartGenerationRef.current += 1;
				// A run resumed after confirmation may emit REPLY_START again
				// with the same reply id. Reuse that message so React keys stay
				// unique and any remaining confirmation cards remain visible.
				const existing = msgsRef.current.find((msg) => msg.id === e.reply_id);
				if (existing) {
					currentReplyRef.current = existing;
				} else {
					audioManager?.stopAllPlayback();
					const msg = AssistantMsg({ id: e.reply_id, name: e.name, content: [] });
					msgsRef.current = [...msgsRef.current, msg];
					currentReplyRef.current = msg;
				}
				clearInterruptTimer();
				settleGenerationRef.current += 1;
				setReplyPhase('streaming');
			} else if (event.type === EventType.REPLY_END) {
				if (currentReplyRef.current) {
					appendEvent(currentReplyRef.current, event);
				}
				clearInterruptTimer();
				currentReplyRef.current = null;
				beginSettling();
			} else if (currentReplyRef.current) {
				appendEvent(currentReplyRef.current, event);
			}

			// Route streaming audio DataBlocks to the audio manager. They still
			// flow through `appendEvent` above (which builds up `source.data`
			// in the Msg), but MessageBubble reads playback state from the
			// manager so it can show progress and autoplay on completion.
			if (audioManager) {
				if (event.type === EventType.DATA_BLOCK_START) {
					const e = event as DataBlockStartEvent;
					if (e.media_type.startsWith('audio/')) {
						audioManager.start(e.block_id, e.media_type);
					}
				} else if (event.type === EventType.DATA_BLOCK_DELTA) {
					const e = event as DataBlockDeltaEvent;
					if (e.media_type.startsWith('audio/')) {
						audioManager.append(e.block_id, e.data);
					}
				} else if (event.type === EventType.DATA_BLOCK_END) {
					const e = event as DataBlockEndEvent;
					// `end` is a no-op when the block isn't being tracked, so
					// we can call it unconditionally.
					audioManager.end(e.block_id);
				}
			}

			scheduleUpdate();
		},
		[
			scheduleUpdate,
			audioManager,
			clearInterruptTimer,
			beginSettling,
			setReplyPhase,
		],
	);

	// ── Lifecycle: fetch history + open SSE stream ──────────────────
	useEffect(() => {
		bindingGenerationRef.current += 1;
		settleGenerationRef.current += 1;
		msgsRef.current = [];
		currentReplyRef.current = null;
		setMsgs([]);
		setError(null);
		clearInterruptTimer();
		setReplyPhase('idle');
		setSubagentHitl([]);
		audioManager?.disposeAll();

		if (!agentId || !sessionId) return;

		const controller = new AbortController();
		abortRef.current = controller;
		let cancelled = false;

		(async () => {
			// 1. Fetch persisted history
			setLoading(true);
			try {
				const { messages, is_running } = await sessionApi.messages(sessionId, agentId);
				if (cancelled) return;
				msgsRef.current = messages;
				// If a reply is in flight (running on a worker) OR the
				// tail msg is parked on a pending tool_call (awaiting
				// user confirmation / external execution), initialise the
				// phase to ``streaming`` so the interrupt button is
				// available immediately — otherwise a fresh page load
				// while parked leaves the UI stuck on ``idle`` with no
				// way to abort.
				const tail = messages[messages.length - 1];
				if (is_running || hasPendingToolCall(tail)) {
					setReplyPhase('streaming');
					if (hasPendingToolCall(tail)) {
						// Prime the ref so continuation events (which
						// arrive without a fresh REPLY_START) apply to
						// the right msg.
						currentReplyRef.current = tail ?? null;
					}
				}
				scheduleUpdate();
			} catch (e) {
				if (!cancelled) setError(e as Error);
				return;
			} finally {
				if (!cancelled) setLoading(false);
			}

			// 2. Open SSE long connection for live events
			try {
				for await (const event of sessionApi.streamEvents(
					sessionId,
					agentId,
					controller.signal,
				)) {
					if (cancelled) break;
					processEvent(event);
				}
			} catch (e) {
				if ((e as Error).name !== 'AbortError' && !cancelled) {
					setError(e as Error);
				}
			}
		})();

		return () => {
			cancelled = true;
			bindingGenerationRef.current += 1;
			settleGenerationRef.current += 1;
			controller.abort();
			abortRef.current = null;
			clearInterruptTimer();
		};
	}, [
		agentId,
		sessionId,
		scheduleUpdate,
		processEvent,
		audioManager,
		clearInterruptTimer,
		setReplyPhase,
	]);

	/**
	 * Send a user message. Appends the message to the local list
	 * optimistically, then fires a ``POST /chat/`` trigger. Events
	 * arrive via the already-open SSE connection.
	 *
	 * @param content - The message content blocks.
	 */
	const send = useCallback(
		async (content: ContentBlock[]): Promise<boolean> => {
			if (!agentId || !sessionId || phaseRef.current !== 'idle') return false;

			const bindingGeneration = bindingGenerationRef.current;
			const replyStartGeneration = replyStartGenerationRef.current;
			settleGenerationRef.current += 1;
			setReplyPhase('streaming');
			setError(null);

			const userMsg = UserMsg({ name: 'user', content });
			msgsRef.current = [...msgsRef.current, userMsg];
			scheduleUpdate();

			try {
				await chatApi.trigger({
					agent_id: agentId,
					session_id: sessionId,
					input: userMsg,
				});
				return true;
			} catch (e) {
				if (bindingGenerationRef.current !== bindingGeneration) return false;

				setError(e as Error);
				if (replyStartGenerationRef.current !== replyStartGeneration) {
					// The backend accepted the run and its SSE stream already
					// started; keep the optimistic message despite an ambiguous HTTP
					// transport failure.
					return true;
				}

				msgsRef.current = msgsRef.current.filter((msg) => msg.id !== userMsg.id);
				scheduleUpdate();
				setReplyPhase('idle');
				return false;
			}
		},
		[agentId, sessionId, scheduleUpdate, setReplyPhase],
	);

	/**
	 * Confirm or deny a tool call (human-in-the-loop). Fires a
	 * ``POST /chat/`` with a ``UserConfirmResultEvent``; events
	 * arrive via SSE.
	 *
	 * @param toolCall - The tool call block to confirm/deny.
	 * @param confirm - Whether the user confirmed.
	 * @param replyId - The reply id the tool call belongs to.
	 * @param rules - Optional permission rules to attach.
	 */
	const onUserConfirm = useCallback(
		async (
			toolCall: ToolCallBlock,
			confirm: boolean,
			replyId: string,
			rules?: ToolCallBlock['suggested_rules'],
		) => {
			if (!agentId || !sessionId) return;

			// Restore the ref so continuation events (no REPLY_START)
			// have a target.
			currentReplyRef.current = msgsRef.current.find((m) => m.id === replyId) ?? null;

			const event: UserConfirmResultEvent = {
				type: EventType.USER_CONFIRM_RESULT,
				id: crypto.randomUUID(),
				created_at: new Date().toISOString(),
				reply_id: replyId,
				confirm_results: [
					{ confirmed: confirm, tool_call: toolCall, rules: rules ?? null },
				],
			};

			try {
				await chatApi.trigger({
					agent_id: agentId,
					session_id: sessionId,
					input: event,
				});
			} catch (e) {
				setError(e as Error);
				throw e;
			}
		},
		[agentId, sessionId],
	);

	/** Abort the current SSE connection. */
	const abort = useCallback(() => {
		abortRef.current?.abort();
	}, []);

	/**
	 * Request interruption of the in-progress reply (running or parked
	 * on HITL). Optimistically moves ``phase`` to ``interrupting`` so
	 * the UI can disable the Stop button; the terminal event advances
	 * through ``settling`` and the backend status probe decides when it
	 * is truly idle (or a 10s interrupt timeout fires if that event is
	 * lost).
	 *
	 * Backend contract:
	 * - 202: interrupt was accepted (cancel signal broadcast for a
	 *   running reply, or wakeup enqueued for a parked one). The
	 *   resulting ``ReplyEndEvent`` arrives through the SSE stream and
	 *   drives the phase transition.
	 * - Idle sessions are a silent no-op at the agent layer, so
	 *   spamming this callback is safe.
	 */
	const interrupt = useCallback(async () => {
		if (!agentId || !sessionId) return;
		// Only escalate to ``interrupting`` if a reply is actually in
		// flight; if we're already idle (SSE completed just before the
		// click) leave the phase alone.
		if (phaseRef.current !== 'streaming') return;
		setReplyPhase('interrupting');
		clearInterruptTimer();
		interruptTimerRef.current = setTimeout(() => {
			interruptTimerRef.current = null;
			if (phaseRef.current === 'interrupting') setReplyPhase('idle');
		}, INTERRUPT_TIMEOUT_MS);
		try {
			await sessionApi.interrupt(sessionId, agentId);
		} catch (e) {
			clearInterruptTimer();
			if ((phaseRef.current as ReplyPhase) === 'interrupting') {
				setReplyPhase('idle');
			}
			setError(e as Error);
		}
	}, [agentId, sessionId, clearInterruptTimer, setReplyPhase]);

	/**
	 * Confirm or deny a tool call that a *team member* is awaiting,
	 * from this leader view (design §3.6 — backend routing).
	 *
	 * The result is POSTed to the **leader** session (the
	 * ``(agentId, sessionId)`` this hook is bound to), NOT the worker.
	 * The backend resolves ``reply_id`` → worker session via the
	 * leader's pending hash and forwards the event to the worker's
	 * continuation. The client never addresses the worker directly —
	 * ``entry.worker_*`` ids are used only for local dedup / clearing.
	 *
	 * @param entry - The pending subagent HITL entry being resolved.
	 * @param toolCall - The tool call block to confirm/deny.
	 * @param confirm - Whether the user confirmed.
	 * @param rules - Optional permission rules to attach.
	 */
	const onSubagentConfirm = useCallback(
		async (
			entry: SubagentHitlEntry,
			toolCall: ToolCallBlock,
			confirm: boolean,
			rules?: ToolCallBlock['suggested_rules'],
		) => {
			if (!agentId || !sessionId) return;

			const event: UserConfirmResultEvent = {
				type: EventType.USER_CONFIRM_RESULT,
				id: crypto.randomUUID(),
				created_at: new Date().toISOString(),
				reply_id: entry.reply_id, // worker's reply_id; backend maps it
				confirm_results: [
					{ confirmed: confirm, tool_call: toolCall, rules: rules ?? null },
				],
			};

			try {
				// Post to the leader front door — backend routes to the
				// worker session (§3.6). Do NOT address the worker here.
				await chatApi.trigger({
					agent_id: agentId,
					session_id: sessionId,
					input: event,
				});
			} catch (e) {
				setError(e as Error);
				// Let the card re-enable itself so the confirmation can be retried.
				throw e;
			}

			// Remove only the call that was answered. One projected entry may
			// contain several pending calls and its siblings must remain visible.
			setSubagentHitl((prev) =>
				prev.flatMap((candidate) => {
					if (hitlKey(candidate) !== hitlKey(entry)) return [candidate];
					const remaining = (candidate.event.tool_calls ?? []).filter(
						(pending) => pending.id !== toolCall.id,
					);
					return remaining.length > 0
						? [
								{
									...candidate,
									event: { ...candidate.event, tool_calls: remaining },
								},
							]
						: [];
				}),
			);
		},
		[agentId, sessionId],
	);

	return {
		msgs,
		loading,
		phase,
		error,
		send,
		onUserConfirm,
		onSubagentConfirm,
		subagentHitl,
		abort,
		interrupt,
	};
}
