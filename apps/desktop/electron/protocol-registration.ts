/** Injected Electron boundary: unit tests never register anything with the OS. */
export interface ProtocolRegistrationApp {
  getAppPath(): string
  setAsDefaultProtocolClient(protocol: string, executable?: string, args?: string[]): boolean
}

export interface ProtocolRegistrationOptions {
  app: ProtocolRegistrationApp
  protocol: string
  execPath: string
  defaultApp: boolean
  testWorkerIndex?: string
  log(message: string): void
}

export function registerDeepLinkProtocol({
  app, protocol, execPath, defaultApp, testWorkerIndex, log
}: ProtocolRegistrationOptions): void {
  // Isolating HOME/userData does not isolate Windows HKCU URL handlers.
  // Presence, including worker "0" and an empty value, must prevent host writes.
  if (testWorkerIndex !== undefined) {
    log('[deeplink] test worker skipped host protocol registration')

    return
  }

  try {
    // Electron resolves the app entry independently of debugger/Chromium argv.
    const registered = defaultApp
      ? app.setAsDefaultProtocolClient(protocol, execPath, [app.getAppPath()])
      : app.setAsDefaultProtocolClient(protocol)

    log(registered
      ? `[deeplink] registered ${protocol}:// handler`
      : `[deeplink] could not register ${protocol}:// handler`)
  } catch (error) {
    log(`[deeplink] protocol registration failed: ${error instanceof Error ? error.message : String(error)}`)
  }
}
