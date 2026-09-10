import axios from 'axios'
import api, { type ApiEnvelope } from './client'
import type { InitializationApplyInput, InitializationApplyResult, InitializationChangePreview, InitializationPreviewInput } from '@/types/initializationChanges'

export async function getConversationInitializationDraft<TDraft>(projectId: string, conversationId: number, signal?: AbortSignal) {
  const response = await api.get<ApiEnvelope<TDraft | null>>(
    `/projects/${encodeURIComponent(projectId)}/initialization-drafts/latest`,
    { params: { conversation_id: conversationId }, signal },
  )
  return response.data.data
}

export async function previewInitializationChanges(projectId: string, draftId: number, input: InitializationPreviewInput, signal?: AbortSignal) {
  const response = await api.post<ApiEnvelope<InitializationChangePreview>>(
    `/projects/${encodeURIComponent(projectId)}/initialization-drafts/${draftId}/change-preview`,
    input, { signal, timeout: 120_000 },
  )
  return response.data.data
}

export async function applyInitializationChanges(projectId: string, draftId: number, input: InitializationApplyInput) {
  const response = await api.post<ApiEnvelope<InitializationApplyResult>>(
    `/projects/${encodeURIComponent(projectId)}/initialization-drafts/${draftId}/apply-changes`,
    input, { timeout: 120_000 },
  )
  return response.data.data
}

export function initializationChangeError(error: unknown): { message: string; stale: boolean; cancelled: boolean } {
  if (axios.isCancel(error)) return { message: '', stale: false, cancelled: true }
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail
    const detailMessage = detail && typeof detail === 'object' && 'message' in detail ? String(detail.message) : ''
    return {
      message: typeof detail === 'string' ? detail : detailMessage || '无法完成本次核对，请重试。',
      stale: error.response?.status === 409,
      cancelled: false,
    }
  }
  return { message: error instanceof Error ? error.message : '无法完成本次核对，请重试。', stale: false, cancelled: false }
}
