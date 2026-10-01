import { createRoot } from 'react-dom/client'

import { type ComposerEffects, ComposerFixture, prepareComposerFixture } from './fixture'

declare global {
  interface Window { f04cEffects: ComposerEffects }
}
window.f04cEffects = { draftText: '', submissions: [], rpc: [], outputs: [] }
prepareComposerFixture()
createRoot(document.getElementById('root')!).render(<ComposerFixture effects={window.f04cEffects} />)
