import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { CodeGraphVRPane } from '@/components/codegraph-vr-pane'
import { PageLoader } from '@/components/page-loader'
import { useI18n } from '@/i18n'
import { $starmapError, $starmapGraph, $starmapLoading, loadStarmapGraph } from '@/store/starmap'
import type { StarmapGraph } from '@/types/hermes'

import { Panel, PanelEmpty } from '../overlays/panel'

import { StarMap } from './star-map'

// Star map overlay: a top-down map of what Hermes has learned for a profile,
// over a radial time axis. Data is fetched on demand into the $starmap* atoms;
// the map itself lives in ./star-map. The chrome is owned by the map itself
// (timeline scrubber + legend float over the canvas), so there's no panel
// header here.
export function StarmapView({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const graph = useStore($starmapGraph)
  const loading = useStore($starmapLoading)
  const error = useStore($starmapError)

  const [imported, setImported] = useState<StarmapGraph | null>(null)
  const [view, setView] = useState<'memory' | 'codegraph'>('memory')

  useEffect(() => {
    void loadStarmapGraph()
  }, [])

  useEffect(() => {
    setImported(null)
  }, [graph])

  const shown = imported ?? graph

  return (
    <Panel closeLabel={t.starmap.close} onClose={onClose}>
      <div aria-label="Visualization" className="mb-3 flex shrink-0 items-center gap-1" role="tablist">
        <button
          aria-selected={view === 'memory'}
          className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground aria-selected:bg-accent aria-selected:text-foreground"
          onClick={() => setView('memory')}
          role="tab"
          type="button"
        >
          Memory map
        </button>
        <button
          aria-selected={view === 'codegraph'}
          className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground aria-selected:bg-accent aria-selected:text-foreground"
          onClick={() => setView('codegraph')}
          role="tab"
          type="button"
        >
          CodeGraph VR
        </button>
      </div>
      {view === 'codegraph' ? (
        <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border/60">
          <CodeGraphVRPane />
        </div>
      ) : error ? (
        <PanelEmpty description={error} icon="warning" title={t.starmap.loadFailed} />
      ) : !shown && loading ? (
        <PageLoader aria-label={t.starmap.loading} className="min-h-0 flex-1" />
      ) : shown && shown.nodes.length === 0 && !imported ? (
        <PanelEmpty description={t.starmap.emptyDesc} icon="lightbulb" title={t.starmap.emptyTitle} />
      ) : shown ? (
        <StarMap
          graph={shown}
          imported={imported !== null}
          onImport={setImported}
          onResetMap={() => setImported(null)}
        />
      ) : null}
    </Panel>
  )
}

export default StarmapView
