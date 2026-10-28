import { useCallback, useState } from 'react'
import { updateConversation } from './api/conversations'
import { describeError } from './api/errors'
import { Composer } from './components/Composer'
import { ContextMeter } from './components/ContextMeter'
import { DocumentsPanel } from './components/DocumentsPanel'
import { Header } from './components/Header'
import { InstructionsPanel } from './components/InstructionsPanel'
import { MessageList } from './components/MessageList'
import { Sidebar } from './components/Sidebar'
import { StatsPage } from './components/StatsPage'
import { useAttached } from './hooks/useAttached'
import { useChat } from './hooks/useChat'
import { useContextUsage } from './hooks/useContextUsage'
import { useConversations } from './hooks/useConversations'
import { useDocuments } from './hooks/useDocuments'
import { usePresets } from './hooks/usePresets'
import { useRoute } from './hooks/useRoute'
import { useHealth, useModels } from './hooks/useServer'

const THINKING_KEY = 'thinking'

// The thinking switch is remembered in this browser for new chats. Storage can be blocked.
function loadThinking(): boolean {
  try {
    return localStorage.getItem(THINKING_KEY) !== 'off'
  } catch {
    return true
  }
}

function saveThinking(on: boolean): void {
  try {
    localStorage.setItem(THINKING_KEY, on ? 'on' : 'off')
  } catch {
    // ignore
  }
}

export default function App() {
  const server = useHealth()
  const models = useModels()
  const conversations = useConversations()
  const { id: routeId, view, open, openStats } = useRoute()
  const [thinking, setThinking] = useState(loadThinking)
  const [chosenModel, setChosenModel] = useState<string>()
  const [drawer, setDrawer] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [instructionsOpen, setInstructionsOpen] = useState(false)
  const [instructions, setInstructions] = useState('')
  const [instructionsError, setInstructionsError] = useState<string | null>(null)
  const presets = usePresets()
  const [answers, setAnswers] = useState(0) // counts finished answers, to read the context use again
  const documents = useDocuments()
  const attached = useAttached(routeId)
  const model = chosenModel ?? models?.default

  const go = useCallback(
    (id: string | null) => {
      if (id === null) {
        setThinking(loadThinking())
        setChosenModel(undefined)
        setInstructions('')
      }
      setDrawer(false)
      open(id)
    },
    [open],
  )

  const chat = useChat({
    conversationId: routeId,
    model,
    thinking,
    attachedIds: attached.ids,
    instructions,
    onCreated: attached.adopt,
    onOpen: go,
    onLoaded: (conversation) => {
      setThinking(conversation.thinking)
      setChosenModel(conversation.model)
      setInstructions(conversation.system_prompt)
    },
    onChanged: () => {
      conversations.refreshSoon()
      setAnswers((n) => n + 1)
    },
  })

  const contextUsage = useContextUsage(routeId, `${answers}|${attached.ids.join(',')}|${instructions}`)

  // Instructions apply to the chat from the next question on; a saved chat keeps them with it.
  const applyInstructions = async (text: string) => {
    setInstructionsError(null)
    if (routeId !== null) {
      try {
        await updateConversation(routeId, { system_prompt: text })
      } catch (error) {
        setInstructionsError(describeError(error).message)
        return
      }
    }
    setInstructions(text)
  }

  // Settings of a saved chat are saved with it, so they are still there when it is opened again.
  const remember = (change: { model?: string; thinking?: boolean }) => {
    if (routeId !== null) void updateConversation(routeId, change).catch(() => undefined)
  }

  return (
    <div className="shell">
      <Sidebar
        items={conversations.items}
        error={conversations.error}
        query={conversations.query}
        shown={conversations.shown}
        onQuery={conversations.setQuery}
        activeId={routeId}
        busy={chat.busy}
        open={drawer}
        onClose={() => setDrawer(false)}
        onNew={() => go(null)}
        onUsage={() => {
          setDrawer(false)
          openStats()
        }}
        usageActive={view === 'stats'}
        onSelect={go}
        onRename={(id, title) => void conversations.rename(id, title)}
        onDelete={(id) => {
          void conversations.remove(id)
          if (id === routeId) go(null)
        }}
      />
      {view === 'stats' ? (
        <StatsPage onBack={() => go(null)} onOpenChat={go} />
      ) : (
        <div className="app">
          <Header
            server={server}
            models={models}
            model={model}
            onModel={(next) => {
              setChosenModel(next)
              remember({ model: next })
            }}
            thinking={thinking}
            onThinking={(on) => {
              setThinking(on)
              saveThinking(on)
              remember({ thinking: on })
            }}
            onMenu={() => setDrawer(true)}
          instructionsOn={instructions.trim() !== ''}
          onInstructions={() => setInstructionsOpen((open) => !open)}
            exportHref={routeId ? `/api/conversations/${encodeURIComponent(routeId)}/export` : undefined}
            busy={chat.busy}
          />
          {chat.loading ? (
            <div className="messages">
              <p className="notice">Loading…</p>
            </div>
          ) : (
            <>
              {chat.actionError && (
                <p className="notice error" role="alert">
                  {chat.actionError}
                </p>
              )}
              {chat.loadError && (
                <p className="notice error" role="alert">
                  Could not open this chat: {chat.loadError}
                </p>
              )}
              <MessageList messages={chat.messages} busy={chat.busy} onRetry={chat.retry} onEdit={chat.edit} />
            </>
          )}
          {contextUsage && !chat.loading && <ContextMeter usage={contextUsage} />}
          <Composer
            busy={chat.busy}
            onSend={chat.send}
            onStop={chat.stop}
            documentCount={attached.ids.length}
            onDocuments={() => setDocsOpen((open) => !open)}
          />
        </div>
      )}
      {instructionsOpen && view === 'chat' && (
        <InstructionsPanel
          key={`${routeId ?? 'new'}:${instructions}`}
          current={instructions}
          presets={presets.items}
          error={presets.error ?? instructionsError}
          locked={chat.busy}
          onClose={() => setInstructionsOpen(false)}
          onUse={(text) => void applyInstructions(text)}
          onCreate={presets.create}
          onUpdate={(id, text) => void presets.update(id, text)}
          onDelete={(id) => void presets.remove(id)}
        />
      )}
      {docsOpen && view === 'chat' && (
        <DocumentsPanel
          docs={documents.items}
          attachedIds={attached.ids}
          problems={documents.problems}
          attachError={attached.error}
          uploading={documents.uploading}
          locked={chat.busy}
          onClose={() => setDocsOpen(false)}
          onUpload={(files) => {
            void documents.upload(files).then((stored) => {
              // New uploads are used in this chat right away.
              for (const id of stored) if (!attached.ids.includes(id)) void attached.toggle(id)
            })
          }}
          onToggle={(id) => void attached.toggle(id)}
          onDelete={(id) => {
            attached.forget(id)
            void documents.remove(id)
          }}
        />
      )}
    </div>
  )
}
