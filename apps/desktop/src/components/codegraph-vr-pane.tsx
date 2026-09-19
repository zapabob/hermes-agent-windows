import { useEffect, useState } from 'react'

interface CodeGraphVRPaneProps {
  enabled?: boolean
  maxEdges?: number
  maxNodes?: number
  port?: number
}

export function CodeGraphVRPane({
  enabled = true,
  maxEdges = 8000,
  maxNodes = 3000,
  port = 8734
}: CodeGraphVRPaneProps) {
  const [healthy, setHealthy] = useState(false)
  const [checking, setChecking] = useState(enabled)

  useEffect(() => {
    if (!enabled) {
      setChecking(false)
      setHealthy(false)

      return
    }

    let cancelled = false

    const checkHealth = async () => {
      const controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), 3000)

      try {
        const response = await fetch(`http://127.0.0.1:${port}/healthz`, { signal: controller.signal })

        if (!cancelled) {setHealthy(response.ok)}
      } catch {
        if (!cancelled) {setHealthy(false)}
      } finally {
        window.clearTimeout(timeout)

        if (!cancelled) {setChecking(false)}
      }
    }

    void checkHealth()
    const interval = window.setInterval(() => void checkHealth(), 30000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [enabled, port])

  if (!enabled) {return null}

  if (checking || !healthy) {
    return (
      <div className="flex h-full min-h-48 items-center justify-center bg-card text-center text-xs text-muted-foreground">
        <div>
          <p className="font-medium text-foreground">CodeGraph VR</p>
          <p className="mt-1">{checking ? 'サーバーを確認中…' : `127.0.0.1:${port} に接続できません`}</p>
          {!checking && <code className="mt-2 block text-[10px]">codegraph vr . --quest --port {port}</code>}
        </div>
      </div>
    )
  }

  const query = new URLSearchParams({ 'max-nodes': String(maxNodes), 'max-edges': String(maxEdges) })

  return (
    <iframe
      className="h-full min-h-0 w-full border-0 bg-background"
      sandbox="allow-scripts allow-same-origin allow-forms"
      src={`http://127.0.0.1:${port}/?${query.toString()}`}
      title="CodeGraph VR visualization"
    />
  )
}

export default CodeGraphVRPane
