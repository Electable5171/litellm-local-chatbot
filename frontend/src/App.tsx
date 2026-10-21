import { useState } from 'react'
import { Composer } from './components/Composer'
import { Header } from './components/Header'
import { MessageList } from './components/MessageList'
import { useChat } from './hooks/useChat'
import { useHealth, useModels } from './hooks/useServer'

const THINKING_KEY = 'thinking'

// The thinking switch is remembered in this browser. Storage can be blocked; the page still works.
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
  const [thinking, setThinking] = useState(loadThinking)
  const [chosenModel, setChosenModel] = useState<string>()
  const model = chosenModel ?? models?.default
  const chat = useChat({ model, thinking })

  return (
    <div className="app">
      <Header
        server={server}
        models={models}
        model={model}
        onModel={setChosenModel}
        thinking={thinking}
        onThinking={(on) => {
          setThinking(on)
          saveThinking(on)
        }}
        onNewChat={chat.newChat}
        busy={chat.busy}
      />
      <MessageList messages={chat.messages} onRetry={chat.retry} />
      <Composer busy={chat.busy} onSend={chat.send} onStop={chat.stop} />
    </div>
  )
}
