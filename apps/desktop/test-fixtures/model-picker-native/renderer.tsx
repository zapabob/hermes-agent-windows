import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ModelMenuPanel } from '@/app/shell/model-menu-panel'
import { modelOptionsQueryKey } from '@/lib/model-options'
import { $activeSessionId, $currentModel, $currentProvider, $currentReasoningEffort, $currentFastMode } from '@/store/session'
import type { ModelOptionsResponse } from '@/types/hermes'

const original: ModelOptionsResponse = { providers: [{ slug: 'owned-provider', name: 'Owned provider', models: ['listed-model'] }] }
const refreshed: ModelOptionsResponse = { providers: [{ slug: 'other-provider', name: 'Other provider', models: ['first-fallback'] }] }
const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000, refetchOnWindowFocus: false } } })
const calls: {method: string; params?: Record<string, unknown>}[] = []
const selected: unknown[] = []
let resolve: ((value: ModelOptionsResponse) => void) | undefined
let reject: ((error: Error) => void) | undefined
let mode = 'success'
$activeSessionId.set('owned-session')
$currentModel.set('selected-new-model')
$currentProvider.set('owned-provider')
$currentReasoningEffort.set('high')
$currentFastMode.set(true)
const key = modelOptionsQueryKey('work', 'owned-session', 'owned-connection')
const other = modelOptionsQueryKey('work', 'owned-session', 'other-connection')
client.setQueryData(other, refreshed)
async function request<T>(method: string, params?: Record<string, unknown>): Promise<T> {
  calls.push({ method, params })
  if (method !== 'model.options') throw new Error('unexpected write or runtime request')
  if (!params?.refresh) return original as T
  if (mode === 'success') return refreshed as T
  return new Promise<ModelOptionsResponse>((ok, fail) => { resolve = ok; reject = fail }) as Promise<T>
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><DropdownMenu><DropdownMenuTrigger>Models</DropdownMenuTrigger><DropdownMenuContent>
  <ModelMenuPanel profile="work" ownerConnectionId="owned-connection" requestGateway={request} onSelectModel={value => { selected.push(value) }} />
</DropdownMenuContent></DropdownMenu></QueryClientProvider>)
Object.assign(window, { pickerProbe: {
  mode: (value: string) => { mode = value },
  newer: () => { $currentModel.set('newer-choice'); $currentProvider.set('newer-provider'); $currentReasoningEffort.set('medium') },
  complete: () => resolve?.(refreshed), fail: () => reject?.(new Error('owned failure')),
  snapshot: () => ({ selected, calls, current: [$currentModel.get(), $currentProvider.get(), $currentReasoningEffort.get(), $currentFastMode.get()], data: client.getQueryData(key), otherInvalidated: client.getQueryState(other)?.isInvalidated })
} })
