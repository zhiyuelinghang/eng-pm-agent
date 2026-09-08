import type { AgentRuntimeTrace } from '@/types/agentRuntime'

/** References are evidence from successful authorized tool results, never inputs. */
export function knowledgeAgentReferences(trace?: AgentRuntimeTrace | null): Array<Record<string, unknown>> {
  const references: Array<Record<string, unknown>> = []
  const seen = new Set<string>()
  for (const message of trace?.messages || []) {
    for (const block of message.content) {
      if (block.type !== 'tool_result' || block.state !== 'success'
        || block.metadata?.operation !== 'weknora_query_project_knowledge') continue
      const texts = typeof block.output === 'string' ? [block.output]
        : block.output.filter(item => item.type === 'text').map(item => item.text)
      for (const text of texts) {
        try {
          const payload = JSON.parse(text)
          for (const reference of Array.isArray(payload.references) ? payload.references : []) {
            if (!reference || typeof reference !== 'object' || !reference.knowledge_id) continue
            const key = `${reference.knowledge_id}:${reference.chunk_id || reference.id || reference.chunk_index || ''}`
            if (seen.has(key)) continue
            seen.add(key)
            references.push(reference)
          }
        } catch { /* A non-JSON tool result is not a citation source. */ }
      }
    }
  }
  return references
}

export function knowledgeAgentText(trace?: AgentRuntimeTrace | null): string {
  return (trace?.messages || []).filter(message => message.role === 'assistant')
    .flatMap(message => message.content.filter(block => block.type === 'text').map(block => block.text)).join('\n\n')
}
