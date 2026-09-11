/** Show review only after this round has finished extracting and validating. */
export function showInitializationDraftDock(draft: { status: string; pending_change_count?: number; validation?: { status: string } | null } | null, running: boolean) {
  return Boolean(draft && !running && draft.status !== 'applied' && draft.pending_change_count !== 0 && (
    ['ready', 'invalid', 'partially_applied'].includes(draft.status)
    || draft.validation?.status === 'failed'))
}
