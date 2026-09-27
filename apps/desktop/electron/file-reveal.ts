export interface FileRevealDeps {
  now: () => number
  reveal: (path: string) => void
  log: (message: string) => void
}

const FILE_REVEAL_DEDUPE_MS = 1_500

export function createFileReveal(deps: FileRevealDeps): (path: string) => void {
  const recent = new Map<string, number>()

  return path => {
    const now = deps.now()
    const last = recent.get(path)

    if (last !== undefined && now >= last && now - last < FILE_REVEAL_DEDUPE_MS) {
      return
    }

    for (const [oldPath, timestamp] of recent) {
      if (now < timestamp || now - timestamp >= FILE_REVEAL_DEDUPE_MS) {
        recent.delete(oldPath)
      }
    }

    recent.set(path, now)

    try {
      deps.reveal(path)
    } catch (error) {
      recent.delete(path)
      deps.log(`[file] reveal in folder failed: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
}
