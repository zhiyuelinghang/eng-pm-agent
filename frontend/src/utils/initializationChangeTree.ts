import type { InitializationChange } from '@/types/initializationChanges'

export type InitializationChangeTreeRow = {
  change: InitializationChange
  depth: number
  ancestorKeys: string[]
  hasChildren: boolean
  contextOnly: boolean
  /** Vertical branches for ancestors that still have a following sibling. */
  ancestorBranches?: boolean[]
  lastSibling?: boolean
  childCount?: number
}

/** Keep filtered ancestors as context, but never add them to the selection. */
export function buildInitializationChangeTree(changes: InitializationChange[], matching: InitializationChange[]) {
  const matches = new Set(matching.map(change => change.key))
  const wbs = changes.filter(change => change.section === 'wbs')
  const byCode = new Map<string, InitializationChange[]>()
  const code = (change: InitializationChange) => String(change.after.wbs_code ?? '')
  for (const change of wbs) {
    const value = code(change)
    if (value) byCode.set(value, [...(byCode.get(value) || []), change])
  }
  const parents = new Map<string, InitializationChange>()
  for (const change of wbs) {
    const candidates = byCode.get(String(change.after.parent_wbs_code ?? '')) || []
    // Duplicate codes need matching; don't arbitrarily attach children to one.
    if (candidates.length === 1 && candidates[0].key !== change.key) parents.set(change.key, candidates[0])
  }
  const included = new Set<string>()
  for (const change of wbs.filter(item => matches.has(item.key))) {
    let node: InitializationChange | undefined = change
    const visited = new Set<string>()
    while (node && !visited.has(node.key)) {
      visited.add(node.key)
      included.add(node.key)
      node = parents.get(node.key)
    }
  }
  const children = new Map<string, InitializationChange[]>()
  const roots: InitializationChange[] = []
  for (const change of wbs.filter(item => included.has(item.key))) {
    const parent = parents.get(change.key)
    if (parent && included.has(parent.key)) children.set(parent.key, [...(children.get(parent.key) || []), change])
    else roots.push(change)
  }
  const compare = (a: InitializationChange, b: InitializationChange) => code(a).localeCompare(code(b), 'zh-CN', { numeric: true })
  roots.sort(compare)
  for (const siblings of children.values()) siblings.sort(compare)
  const treeRows: InitializationChangeTreeRow[] = []
  const seen = new Set<string>()
  function append(change: InitializationChange, ancestorKeys: string[], ancestorBranches: boolean[] = [], lastSibling = true) {
    if (seen.has(change.key)) return
    seen.add(change.key)
    const descendants = (children.get(change.key) || []).filter(child => !seen.has(child.key))
    treeRows.push({ change, depth: ancestorKeys.length, ancestorKeys, ancestorBranches, lastSibling, childCount: descendants.length, hasChildren: descendants.length > 0, contextOnly: !matches.has(change.key) })
    for (const [index, child] of descendants.entries()) append(child, [...ancestorKeys, change.key], [...ancestorBranches, !lastSibling], index === descendants.length - 1)
  }
  for (const [index, root] of roots.entries()) append(root, [], [], index === roots.length - 1)
  // Broken imported cycles must remain visible and addressable for correction.
  for (const change of wbs.filter(item => included.has(item.key)).sort(compare)) append(change, [])
  const rows: InitializationChangeTreeRow[] = []
  let insertedWbs = false
  for (const change of matching) {
    if (change.section === 'wbs') {
      if (!insertedWbs) rows.push(...treeRows)
      insertedWbs = true
    } else rows.push({ change, depth: 0, ancestorKeys: [], hasChildren: false, contextOnly: false })
  }
  return { rows, groupKeys: treeRows.filter(row => row.hasChildren).map(row => row.change.key) }
}

export function visibleInitializationChangeTreeRows(rows: InitializationChangeTreeRow[], collapsed: ReadonlySet<string>) {
  return rows.filter(row => !row.ancestorKeys.some(key => collapsed.has(key)))
}
