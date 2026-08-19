import { apiBaseUrl } from './client'

function authorizedHeaders(): HeadersInit {
  const token = sessionStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function fetchBlob(path: string): Promise<Blob> {
  const response = await fetch(path, { headers: authorizedHeaders() })
  if (!response.ok) {
    let detail = response.statusText
    const raw = await response.text()
    try {
      const payload = JSON.parse(raw)
      detail = String(payload?.detail || payload?.message || detail)
    } catch {
      detail = raw || detail
    }
    throw new Error(detail || '资料读取失败。')
  }
  return response.blob()
}

function projectAssetPath(projectId: string, suffix: string): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `${base}/projects/${encodeURIComponent(projectId)}/engineering-documents/${suffix}`
}

export async function fetchWeKnoraResourceBlob(
  projectId: string,
  handle: string,
): Promise<Blob> {
  return fetchBlob(projectAssetPath(projectId, `resources/${encodeURIComponent(handle)}`))
}

export async function previewWeKnoraKnowledge(
  projectId: string,
  knowledgeId: string,
): Promise<void> {
  const opened = window.open('', '_blank')
  if (opened) opened.opener = null
  try {
    const blob = await fetchBlob(projectAssetPath(
      projectId,
      `knowledge/${encodeURIComponent(knowledgeId)}/preview`,
    ))
    const url = URL.createObjectURL(blob)
    if (opened) opened.location.href = url
    else {
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.target = '_blank'
      anchor.rel = 'noopener noreferrer'
      anchor.click()
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    opened?.close()
    throw error
  }
}

export async function downloadWeKnoraKnowledge(
  projectId: string,
  knowledgeId: string,
  fileName: string,
): Promise<void> {
  const blob = await fetchBlob(projectAssetPath(
    projectId,
    `knowledge/${encodeURIComponent(knowledgeId)}/download`,
  ))
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName || '工程资料'
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
