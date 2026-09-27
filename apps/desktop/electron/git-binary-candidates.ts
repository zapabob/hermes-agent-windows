import path from 'node:path'

export interface GitCandidateFs {
  existsSync: (candidate: string) => boolean
  readdirSync: (dir: string) => string[]
}

export interface WindowsGitEnv {
  localAppData: string
  programFiles: string
  programFilesX86: string
}

/** Keep the existing PortableGit and system locations around UGit's versioned copy. */
export function windowsGitCandidates(env: WindowsGitEnv, fs: GitCandidateFs): string[] {
  const candidates: string[] = []

  if (env.localAppData) {
    candidates.push(path.join(env.localAppData, 'hermes', 'git', 'cmd', 'git.exe'))
    candidates.push(path.join(env.localAppData, 'hermes', 'git', 'bin', 'git.exe'))

    try {
      const ugitRoot = path.join(env.localAppData, 'UGit')

      const versions = fs.readdirSync(ugitRoot)
        .filter(entry => entry.startsWith('app-'))
        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))

      for (const version of versions) {
        const bundled = path.join(ugitRoot, version, 'resources', 'app', 'git', 'cmd', 'git.exe')

        if (fs.existsSync(bundled)) {
          candidates.push(bundled)
        }
      }
    } catch {
      // An absent or unreadable UGit install does not hide the other candidates.
    }
  }

  candidates.push(path.join(env.programFiles, 'Git', 'cmd', 'git.exe'))
  candidates.push(path.join(env.programFilesX86, 'Git', 'cmd', 'git.exe'))

  if (env.localAppData) {
    candidates.push(path.join(env.localAppData, 'Programs', 'Git', 'cmd', 'git.exe'))
  }

  return candidates
}
