// Command selection shared by backend construction and the backend-off Git
// policy probe. It does not build backend environments, import-probe or bootstrap.
import path from 'node:path'

export interface PythonBackendCommandDeps {
  findPythonForRoot: (root: string) => string | null
  venvRootForPython: (python: string, root: string) => string | null
  getVenvPython: (venvRoot: string) => string
  fileExists: (file: string) => boolean
  isWindows: boolean
}

export function pythonBackendCommand(root: string, deps: PythonBackendCommandDeps) {
  const python = deps.findPythonForRoot(root)

  if (!python) {
    return null
  }
  const venvRoot = deps.venvRootForPython(python, root) ?? path.join(root, 'venv')
  const venvPython = deps.getVenvPython(venvRoot)
  const command = deps.isWindows && deps.fileExists(venvPython) ? venvPython : python

  return { command, venvRoot }
}
