const cleanupCallbacks = new Set<() => void>()
const projectCallbacks = new Set<(projectId: string) => void>()
let selectedProjectId = ''

export function registerRealtimeSessionCleanup(callback: () => void) {
  cleanupCallbacks.add(callback)
  return () => cleanupCallbacks.delete(callback)
}

export function registerRealtimeSessionProject(
  callback: (projectId: string) => void,
) {
  projectCallbacks.add(callback)
  callback(selectedProjectId)
  return () => projectCallbacks.delete(callback)
}

export function setRealtimeSessionProject(projectId: string) {
  selectedProjectId = projectId
  projectCallbacks.forEach(callback => callback(projectId))
}

export function resetRealtimeSession() {
  selectedProjectId = ''
  cleanupCallbacks.forEach(callback => callback())
}
