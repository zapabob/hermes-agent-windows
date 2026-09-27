import path from 'node:path'

interface SourceBackendEnvOptions {
  hermesHome: string
  pythonPathEntries: string[]
  venvRoot: string | null
}

interface SourceBackendDependencies {
  hermesHome: string
  isWindows: boolean
  override?: string
  pathModule?: typeof path
  fileExists: (candidate: string) => boolean
  getVenvSitePackagesEntries: (venvRoot: string | null) => string[]
  buildEnv: (options: SourceBackendEnvOptions) => NodeJS.ProcessEnv
}

// A source checkout owns its Python choice. The active/bootstrap backend has
// a separate policy and may use a system interpreter while creating its venv.
export function createSourcePythonBackend(
  root: string,
  label: string,
  backendArgs: string[],
  dependencies: SourceBackendDependencies,
  options: { bootstrap?: boolean } = {}
) {
  const {
    hermesHome,
    isWindows,
    override,
    pathModule = path,
    fileExists,
    getVenvSitePackagesEntries,
    buildEnv
  } = dependencies

  let python = override && fileExists(override) ? override : null

  if (!python) {
    const relativePaths = isWindows
      ? [pathModule.join('.venv', 'Scripts', 'python.exe'), pathModule.join('venv', 'Scripts', 'python.exe')]
      : [pathModule.join('.venv', 'bin', 'python'), pathModule.join('venv', 'bin', 'python')]

    for (const relativePath of relativePaths) {
      const candidate = pathModule.join(root, relativePath)

      if (fileExists(candidate)) {
        python = candidate

        break
      }
    }
  }

  if (!python) {
    return null
  }

  const parent = pathModule.dirname(python)
  const binName = pathModule.basename(parent).toLowerCase()
  let venvRoot: string | null = null

  if (binName === 'bin' || binName === 'scripts') {
    const candidate = pathModule.dirname(parent)
    const relative = pathModule.relative(root, candidate)

    if (relative && !relative.startsWith('..') && !pathModule.isAbsolute(relative)) {
      venvRoot = candidate
    }
  }

  // Windows needs the selected venv's console python.exe. An external
  // override keeps its own command and never inherits a sibling venv.
  const venvPython = venvRoot
    ? pathModule.join(venvRoot, isWindows ? 'Scripts' : 'bin', isWindows ? 'python.exe' : 'python')
    : null

  const command = isWindows && venvPython && fileExists(venvPython) ? venvPython : python

  return {
    kind: 'python',
    label,
    command,
    args: ['-m', 'hermes_cli.main', ...backendArgs],
    env: buildEnv({
      hermesHome,
      pythonPathEntries: [root, ...getVenvSitePackagesEntries(venvRoot)],
      venvRoot
    }),
    root,
    bootstrap: Boolean(options.bootstrap),
    shell: false
  }
}
