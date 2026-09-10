export type AgentImageAttachment = {
  name: string
  media_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'
  data: string
}

type ImageFile = Pick<File, 'name' | 'type' | 'size' | 'arrayBuffer'>

const IMAGE_TYPES: Record<string, AgentImageAttachment['media_type']> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
}
const MAX_IMAGE_BYTES = 30 * 1024 * 1024

export function agentImageType(file: Pick<File, 'name' | 'type'>): AgentImageAttachment['media_type'] | null {
  const declared = file.type.trim().toLowerCase()
  if (Object.values(IMAGE_TYPES).includes(declared as AgentImageAttachment['media_type'])) {
    return declared as AgentImageAttachment['media_type']
  }
  if (declared && declared !== 'application/octet-stream') return null
  return IMAGE_TYPES[file.name.split('.').pop()?.toLowerCase() || ''] ?? null
}

export async function encodeAgentImageAttachments(files: ImageFile[], signal?: AbortSignal): Promise<AgentImageAttachment[]> {
  const selected = files.flatMap(file => {
    const mediaType = agentImageType(file)
    return mediaType ? [{ file, mediaType }] : []
  })
  if (selected.length > 8) throw new Error('每次最多发送 8 张图片。')
  if (selected.some(({ file }) => !file.size || !file.name || file.name.length > 300)) {
    throw new Error('请选择非空图片，文件名不能超过 300 个字符。')
  }
  if (selected.reduce((total, { file }) => total + file.size, 0) > MAX_IMAGE_BYTES) {
    throw new Error('本次发送的图片总大小不能超过 30 MB。')
  }
  const attachments: AgentImageAttachment[] = []
  for (const { file, mediaType } of selected) {
    signal?.throwIfAborted()
    const bytes = new Uint8Array(await file.arrayBuffer())
    signal?.throwIfAborted()
    let binary = ''
    for (let offset = 0; offset < bytes.length; offset += 32768) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768))
    }
    attachments.push({ name: file.name, media_type: mediaType, data: btoa(binary) })
  }
  return attachments
}
