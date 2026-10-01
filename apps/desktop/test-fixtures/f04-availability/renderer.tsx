import type { Unstable_TriggerItem } from '@assistant-ui/core'
import { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { useComposerTrigger } from '@/app/chat/composer/hooks/use-composer-trigger'
import { useSlashCompletions } from '@/app/chat/composer/hooks/use-slash-completions'
import { composerPlainText, placeCaretAtOffset, renderComposerContents, RICH_INPUT_SLOT } from '@/app/chat/composer/rich-editor'
import type { HermesGateway } from '@/hermes'
import { type CommandsCatalogLike, desktopSlashCommandArgumentMode, desktopSlashUnavailableMessage, isDesktopSlashCommand, resolveDesktopCommand } from '@/lib/desktop-slash-commands'
import { invalidateSlashCompletions } from '@/lib/slash-completion-cache'

declare global {
  interface Window {
    catalogProbe: {
      configure: (catalog: CommandsCatalogLike, completion: object) => void
      load: (text: string) => void
      pick: (command: string) => void
      pickAccepted: (command: string) => void
      requests: () => string[]
      snapshot: () => { text: string; chips: number; freeText: boolean }
      mode: (command: string) => string | null
      invalidate: () => void
      rows: () => string[]
      surface: (command: string) => unknown
      executable: (command: string) => boolean
      unavailable: (command: string) => string | null
    }
  }
}

function Probe() {
  const editorRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef('')
  const [, setText] = useState('')
  const wire = useRef<{ catalog?: CommandsCatalogLike; completion?: object; requests: string[] }>({ requests: [] })

  const [gateway] = useState(() => ({ request: async <T,>(method: string): Promise<T> => {
    wire.current.requests.push(method)
    const value = method === 'commands.catalog' ? wire.current.catalog : wire.current.completion

    if (!value) {throw new Error('test wire not configured')}

    return value as T
  } }) as unknown as HermesGateway)

  const slash = useSlashCompletions({ gateway })

  const trigger = useComposerTrigger({
    editorRef, draftRef, at: { adapter: null, loading: false },
    slash, requestMainFocus: () => editorRef.current?.focus(), setComposerText: setText
  })

  window.catalogProbe = {
    configure: (catalog, completion) => { wire.current = { catalog, completion, requests: [] } },
    requests: () => [...wire.current.requests],
    load: text => {
      const editor = editorRef.current!
      renderComposerContents(editor, text)
      draftRef.current = text
      editor.focus()
      placeCaretAtOffset(editor, text.length)
      trigger.refreshTrigger()
    },
    pick: command => {
      const item: Unstable_TriggerItem = {
        id: command, type: 'slash', label: command.slice(1),
        metadata: { command, display: command, meta: '', group: 'Commands', rawText: command }
      }

      trigger.replaceTriggerWithChip(item)
    },
    pickAccepted: command => {
      const item = trigger.triggerItems.find(row => (row.metadata as { command?: string })?.command === command)

      if (!item) {throw new Error(`missing accepted row: ${command}`)}
      trigger.replaceTriggerWithChip(item)
    },
    snapshot: () => ({
      text: composerPlainText(editorRef.current!),
      chips: editorRef.current!.querySelectorAll('[data-slash-kind]').length,
      freeText: trigger.slashFreeTextArgStage
    }),
    mode: desktopSlashCommandArgumentMode,
    invalidate: invalidateSlashCompletions,
    rows: () => trigger.triggerItems.map(row => (row.metadata as { command: string }).command),
    surface: command => resolveDesktopCommand(command)?.surface ?? null,
    executable: isDesktopSlashCommand,
    unavailable: desktopSlashUnavailableMessage
  }

  return <div contentEditable data-slot={RICH_INPUT_SLOT} data-testid="editor" onInput={() => trigger.refreshTrigger()} onKeyDown={event => {
      if (!event.nativeEvent.isComposing && (event.key === ' ' || event.key === 'Tab') && trigger.commitTypedSlashDirective()) {
        event.preventDefault()
      }
    }}
    ref={editorRef}
    suppressContentEditableWarning />
}

createRoot(document.getElementById('root')!).render(<Probe />)
