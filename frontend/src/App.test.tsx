import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { ContextUsage, ConversationWithMessages, DocumentInfo, Preset, StatsResponse, Health, ModelsResponse, StoredMessage } from './api/types'

const encoder = new TextEncoder()

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  litellm: {
    base_url: 'http://x/v1',
    reachable: true,
    latency_ms: 120,
    error: null,
    checked_age_s: 0,
  },
  chat_model: { id: 'qwen3.8', available: true },
}
const MODELS: ModelsResponse = {
  default: 'qwen3.8',
  models: [{ id: 'qwen3.8', available: true }],
}

const frame = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
const DONE = frame('done', {
  finish_reason: 'stop',
  usage: { prompt_tokens: 5, completion_tokens: 42 },
  latency_ms: 9000,
  ttft_ms: 300,
})
const META = frame('meta', {
  model: 'qwen3.8',
  thinking: true,
  trimmed_messages: 0,
})

/** A chat response the test can feed piece by piece, like the real server does. */
function liveStream(signal?: AbortSignal | null) {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
      signal?.addEventListener('abort', () => c.error(new DOMException('Aborted', 'AbortError')))
    },
  })
  return {
    response: new Response(body, {
      headers: { 'content-type': 'text/event-stream' },
    }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  }
}

function fullResponse(...frames: string[]): Response {
  return new Response(frames.join(''), {
    headers: { 'content-type': 'text/event-stream' },
  })
}

const stamp = (daysAgo = 0) => new Date(Date.now() - daysAgo * 86_400_000).toISOString()

function conversation(id: string, title: string, extra: Partial<ConversationWithMessages> = {}): ConversationWithMessages {
  return {
    id,
    title,
    model: 'qwen3.8',
    thinking: true,
    system_prompt: '',
    created_at: stamp(),
    updated_at: stamp(),
    messages: [],
    ...extra,
  }
}

function stored(role: 'user' | 'assistant', content: string, extra: Partial<StoredMessage> = {}): StoredMessage {
  return {
    id: `s-${content}`,
    role,
    content,
    reasoning: '',
    status: 'complete',
    error: null,
    finish_reason: null,
    usage: null,
    latency_ms: null,
    ttft_ms: null,
    thinking_ms: null,
    trimmed: false,
    sources: null,
    created_at: stamp(),
    ...extra,
  }
}

interface Turn {
  kind: 'message' | 'regenerate' | 'edit'
  conversationId: string
  messageId?: string
  content?: string
  init: RequestInit
}
type TurnHandler = (turn: Turn) => Response | Promise<Response>

const path0 = (url: string) => url.split('?')[0]

const SUMMARY = { count: 4, avg: 5000, p50: 4000, p95: 9000, max: 9500 }
const STATS: StatsResponse = {
  range: '7d',
  since: null,
  answers: { complete: 42, stopped: 3, failed: 1 },
  tokens: { prompt: 123456, completion: 7890 },
  latency_ms: SUMMARY,
  ttft_ms: { count: 4, avg: 800, p50: 700, p95: 1500, max: 1600 },
  thinking_ms: { count: 40, avg: 6200, p50: 6000, p95: 9000, max: 9500 },
  tokens_per_second: 51.3,
  conversations: 12,
  per_day: [
    { date: '2026-10-20', answers: 5, completion_tokens: 900 },
    { date: '2026-10-21', answers: 0, completion_tokens: 0 },
    { date: '2026-10-22', answers: 10, completion_tokens: 2000 },
  ],
  slowest: [
    { message_id: 'm1', conversation_id: 'c9', title: 'Long analysis', latency_ms: 31000, completion_tokens: 1800, created_at: '2026-10-22T10:00:00.000+00:00' },
  ],
}

function documentInfo(id: string, filename: string, extra: Partial<DocumentInfo> = {}): DocumentInfo {
  return {
    id,
    filename,
    mime: 'application/pdf',
    size_bytes: 2048,
    status: 'ready',
    error: null,
    page_count: 3,
    chunk_count: 7,
    embedded_count: 7,
    created_at: stamp(),
    ...extra,
  }
}

/** A small stand-in for the backend: conversations live in memory for the length of a test. */
function mockServer(
  turn: TurnHandler = () => fullResponse(DONE),
  options: {
    health?: Health
    conversations?: ConversationWithMessages[]
    documents?: DocumentInfo[]
    presets?: Preset[]
    stats?: (range: string) => Response | StatsResponse
    context?: (conversationId: string) => ContextUsage
  } = {},
) {
  const db = new Map((options.conversations ?? []).map((c) => [c.id, c]))
  const docs = new Map((options.documents ?? []).map((d) => [d.id, d]))
  const presetList = [...(options.presets ?? [])]
  const attached = new Map<string, string[]>()
  let created = 0
  const calls: { method: string; url: string; body?: unknown }[] = []
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    const body = typeof init.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined
    calls.push({ method, url, body })
    if (url === '/api/health') return Response.json(options.health ?? HEALTH)
    if (path0(url) === '/api/presets') {
      if (method === 'POST') {
        const made = { id: `p${presetList.length + 1}`, name: String(body?.name), content: String(body?.content), created_at: stamp(), updated_at: stamp() }
        presetList.push(made)
        return Response.json(made, { status: 201 })
      }
      return Response.json({ presets: presetList })
    }
    const presetMatch = /^\/api\/presets\/([^/]+)$/.exec(url)
    if (presetMatch) {
      const at = presetList.findIndex((p) => p.id === presetMatch[1])
      if (at < 0) return Response.json({ error: { code: 'preset_not_found', message: 'gone' } }, { status: 404 })
      if (method === 'DELETE') {
        presetList.splice(at, 1)
        return new Response(null, { status: 204 })
      }
      Object.assign(presetList[at]!, body)
      return Response.json(presetList[at])
    }
    if (path0(url) === '/api/stats') {
      const result = options.stats?.(new URLSearchParams(url.split('?')[1]).get('range') ?? '')
      return result instanceof Response ? result : Response.json(result ?? STATS)
    }
    if (url === '/api/models') return Response.json(MODELS)
    const [path, queryString] = url.split('?')
    if (path === '/api/conversations') {
      if (method === 'POST') {
        created += 1
        const made = conversation(`new${created}`, '', {
          thinking: body?.thinking !== false,
          system_prompt: typeof body?.system_prompt === 'string' ? body.system_prompt : '',
        })
        db.set(made.id, made)
        return Response.json(made, { status: 201 })
      }
      const q = new URLSearchParams(queryString).get('q')?.toLowerCase()
      const hits = [...db.values()].flatMap((c) => {
        if (!q) return [{ ...c, messages: undefined }]
        const message = c.messages.find((m) => m.content.toLowerCase().includes(q))
        if (!c.title.toLowerCase().includes(q) && !message) return []
        return [{ ...c, messages: undefined, snippet: message?.content ?? null }]
      })
      return Response.json({
        conversations: hits,
      })
    }
    if (url === '/api/documents') {
      if (method === 'POST') {
        const file = init.body as File
        if (file.name === 'bad.xlsx') {
          return Response.json(
            {
              error: {
                code: 'unsupported_file',
                message: "'bad.xlsx' is not a supported file type.",
              },
            },
            { status: 415 },
          )
        }
        const made = documentInfo(
          `d${docs.size + 1}`,
          decodeURIComponent((init.headers as Record<string, string>)['x-filename']!),
        )
        docs.set(made.id, made)
        return Response.json(made, { status: 201 })
      }
      return Response.json({ documents: [...docs.values()] })
    }
    const docMatch = /^\/api\/documents\/([^/]+)$/.exec(url)
    if (docMatch && method === 'DELETE') {
      docs.delete(docMatch[1]!)
      return new Response(null, { status: 204 })
    }
    const attachMatch = /^\/api\/conversations\/([^/]+)\/documents(?:\/([^/]+))?$/.exec(url)
    if (attachMatch) {
      const id = attachMatch[1]!
      const list = attached.get(id) ?? []
      if (attachMatch[2] && method === 'POST') list.push(attachMatch[2])
      if (attachMatch[2] && method === 'DELETE') list.splice(list.indexOf(attachMatch[2]), 1)
      attached.set(id, list)
      return Response.json({
        documents: list.map((d) => docs.get(d)).filter(Boolean),
      })
    }
    const contextMatch = /^\/api\/conversations\/([^/]+)\/context$/.exec(url)
    if (contextMatch && options.context) return Response.json(options.context(decodeURIComponent(contextMatch[1]!)))
    const editMatch = /^\/api\/conversations\/([^/]+)\/messages\/([^/]+)\/edit$/.exec(url)
    if (editMatch) {
      return turn({
        kind: 'edit',
        conversationId: decodeURIComponent(editMatch[1]!),
        messageId: decodeURIComponent(editMatch[2]!),
        content: body?.content as string | undefined,
        init,
      })
    }
    const match = /^\/api\/conversations\/([^/]+)(\/messages|\/regenerate)?$/.exec(url)
    if (match) {
      const id = decodeURIComponent(match[1]!)
      const found = db.get(id)
      if (!found) {
        return Response.json({ error: { code: 'conversation_not_found', message: 'gone' } }, { status: 404 })
      }
      if (match[2]) {
        const kind = match[2] === '/messages' ? 'message' : 'regenerate'
        const content = body?.content as string | undefined
        if (kind === 'message' && !found.title) found.title = content ?? ''
        return turn({ kind, conversationId: id, content, init })
      }
      if (method === 'DELETE') {
        db.delete(id)
        return new Response(null, { status: 204 })
      }
      if (method === 'PATCH') {
        Object.assign(found, body)
        return Response.json(found)
      }
      return Response.json(found)
    }
    throw new Error(`unexpected request to ${method} ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return { mock, calls, db, docs, attached, presets: presetList }
}

const turnCalls = (server: ReturnType<typeof mockServer>) =>
  server.calls.filter((c) => c.method === 'POST' && /\/(messages|regenerate|edit)$/.test(c.url))

const box = () => screen.getByRole('textbox', { name: 'Message' })

beforeEach(() => {
  localStorage.clear()
  window.location.hash = ''
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows that the model is ready', async () => {
    mockServer(() => fullResponse(DONE))
    render(<App />)
    expect(await screen.findByRole('status')).toHaveTextContent('Ready · 120 ms')
  })

  it('shows what is wrong when LiteLLM is not reachable', async () => {
    const degraded: Health = {
      ...HEALTH,
      status: 'degraded',
      litellm: {
        ...HEALTH.litellm,
        reachable: false,
        latency_ms: null,
        error: 'Cannot reach LiteLLM.',
      },
    }
    mockServer(() => fullResponse(DONE), { health: degraded })
    render(<App />)
    expect(await screen.findByText('Cannot reach LiteLLM.')).toBeInTheDocument()
  })

  it('shows the thinking live, folds it away when the answer starts, then shows the answer', async () => {
    const live = liveStream()
    mockServer(() => live.response)
    const user = userEvent.setup()
    render(<App />)

    await user.type(box(), 'What is 17*23?{Enter}')
    expect(screen.getByText('What is 17*23?')).toBeInTheDocument()

    live.push(META + frame('reasoning', { delta: '17*20 = 340, ' }) + frame('reasoning', { delta: '17*3 = 51' }))
    expect(await screen.findByText(/17\*20 = 340, 17\*3 = 51/)).toBeInTheDocument()
    const thinking = screen.getByText('Thinking…').closest('details')!
    expect(thinking).toHaveAttribute('open')
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()

    live.push(frame('content', { delta: 'The answer is **391**.' }) + DONE)
    live.close()
    expect(await screen.findByText('391')).toBeInTheDocument()
    expect(screen.getByText(/Thought for/)).toBeInTheDocument()
    expect(screen.getByText(/Thought for/).closest('details')).not.toHaveAttribute('open')
    expect(await screen.findByText('42 tokens · 9.0 s · first token 0.3 s')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled() // empty box
  })

  it('saves the chat on the first question and keeps asking in the same chat', async () => {
    const server = mockServer(({ content }) =>
      fullResponse(frame('reasoning', { delta: 'secret thoughts' }), frame('content', { delta: `reply to: ${content}` }), DONE),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'first{Enter}')
    await screen.findByText('reply to: first')
    await user.type(box(), 'second{Enter}')
    await screen.findByText('reply to: second')

    expect(server.calls.filter((c) => c.method === 'POST' && c.url === '/api/conversations')).toHaveLength(1)
    expect(turnCalls(server).map((c) => [c.url, c.body])).toEqual([
      ['/api/conversations/new1/messages', { content: 'first' }],
      ['/api/conversations/new1/messages', { content: 'second' }],
    ])
    expect(window.location.hash).toBe('#/c/new1') // the address shows the chat
    // the sidebar lists it, titled by the first question
    expect(await within(screen.getByRole('navigation', { name: 'Conversations' })).findByText('first')).toBeInTheDocument()
  })

  it('Shift+Enter makes a new line instead of sending', async () => {
    const server = mockServer(() => fullResponse(DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'line one{Shift>}{Enter}{/Shift}line two')
    expect(box()).toHaveValue('line one\nline two')
    expect(turnCalls(server)).toHaveLength(0)
  })

  it('the Thinking switch is sent with the question and remembered', async () => {
    const server = mockServer(() => fullResponse(frame('content', { delta: 'hi' }), DONE))
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await user.click(screen.getByRole('switch', { name: 'Thinking' }))
    await user.type(box(), 'hello{Enter}')
    await screen.findByText('hi')
    const created = server.calls.find((c) => c.method === 'POST' && c.url === '/api/conversations')
    expect(created?.body).toMatchObject({ thinking: false })

    unmount()
    render(<App />)
    expect(screen.getByRole('switch', { name: 'Thinking' })).not.toBeChecked()
  })

  it('renders the answer as markdown with a copyable code block, and ignores raw HTML', async () => {
    const answer = 'Use **bold** text.\n\n```python\nprint("hi")\n```\n\n<script>window.pwned = 1</script>'
    mockServer(() => fullResponse(frame('content', { delta: answer }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'code please{Enter}')

    const bold = await screen.findByText('bold')
    expect(bold.tagName).toBe('STRONG')
    const block = screen.getByText('python').closest('.code-block') as HTMLElement
    expect(block).toHaveTextContent('print("hi")')
    await user.click(within(block).getByRole('button', { name: 'Copy' }))
    expect(await navigator.clipboard.readText()).toBe('print("hi")\n')
    expect(within(block).getByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined()
  })

  it('never turns the answer into live scripts, javascript: links or tracking images', async () => {
    const answer = [
      '[click me](javascript:alert(1))',
      '<img src=x onerror="window.pwned = 2">',
      '![pixel](https://tracker.example/pixel.png)',
      '[fine](https://example.com/page)',
    ].join('\n\n')
    mockServer(() => fullResponse(frame('content', { delta: answer }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'links{Enter}')

    const fine = await screen.findByRole('link', { name: 'fine' })
    expect(fine).toHaveAttribute('href', 'https://example.com/page')
    expect(fine).toHaveAttribute('target', '_blank')
    expect(fine).toHaveAttribute('rel', 'noopener noreferrer')
    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
    }
    expect(document.querySelector('img')).toBeNull() // nothing is fetched from another server
    expect(screen.getByText('[image: pixel]')).toBeInTheDocument()
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined()
  })

  it('explains that the model is busy and lets you try again', async () => {
    let calls = 0
    mockServer(() => {
      calls += 1
      if (calls === 1) {
        return Response.json(
          {
            error: { code: 'upstream_busy', message: 'busy', retry_after_s: 5 },
          },
          { status: 503 },
        )
      }
      return fullResponse(frame('content', { delta: 'Now it works.' }), DONE)
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hello{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('The model is busy right now')

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Now it works.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(within(screen.getByRole('log')).getAllByText('hello')).toHaveLength(1) // the question is not duplicated
  })

  it('an error in the middle of an answer keeps what arrived', async () => {
    mockServer(() =>
      fullResponse(
        frame('content', { delta: 'Half an ans' }),
        frame('error', {
          code: 'upstream_interrupted',
          message: 'The connection to LiteLLM was lost.',
        }),
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hi{Enter}')
    expect(await screen.findByText('Half an ans')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('The connection to LiteLLM was lost.')
  })

  it('an answer that ends without a done event is reported as an error', async () => {
    mockServer(() => fullResponse(frame('content', { delta: 'cut' })))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hi{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('ended unexpectedly')
  })

  it('Stop ends the answer, keeps the text so far and closes the connection', async () => {
    let signal: AbortSignal | null | undefined
    mockServer(({ init }) => {
      signal = init.signal
      const live = liveStream(init.signal)
      live.push(frame('content', { delta: 'Partial answer' }))
      return live.response
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'long one{Enter}')
    expect(await screen.findByText('Partial answer')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument())
    expect(signal?.aborted).toBe(true)
    expect(screen.getByText('Partial answer')).toBeInTheDocument()
    expect(screen.getByText('Stopped')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('New chat clears the conversation', async () => {
    mockServer(() => fullResponse(frame('content', { delta: 'an answer' }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'question{Enter}')
    await screen.findByText('an answer')
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    expect(screen.queryByText('an answer')).toBeNull()
    expect(screen.getByText('What would you like to know?')).toBeInTheDocument()
  })
})

describe('saved conversations', () => {
  const sidebar = () => screen.getByRole('navigation', { name: 'Conversations' })

  it('lists saved chats grouped by day and opens one with its thinking and statistics', async () => {
    const old = conversation('c1', 'Old question', { updated_at: stamp(30) })
    const recent = conversation('c2', 'Fresh question', {
      thinking: false,
      messages: [
        stored('user', 'Fresh question'),
        stored('assistant', 'Fresh **answer**', {
          reasoning: 'some thinking',
          thinking_ms: 2000,
          usage: { prompt_tokens: 3, completion_tokens: 7 },
          latency_ms: 4000,
          ttft_ms: 500,
        }),
      ],
    })
    mockServer(() => fullResponse(DONE), { conversations: [old, recent] })
    const user = userEvent.setup()
    render(<App />)

    expect(await within(sidebar()).findByText('Today')).toBeInTheDocument()
    expect(within(sidebar()).getByText('Older')).toBeInTheDocument()
    await user.click(within(sidebar()).getByRole('button', { name: 'Fresh question' }))

    expect(await screen.findByText('answer')).toBeInTheDocument()
    expect(screen.getByText(/Thought for/)).toBeInTheDocument()
    expect(screen.getByText('7 tokens · 4.0 s · first token 0.5 s')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Thinking' })).not.toBeChecked() // this chat has it off
    expect(window.location.hash).toBe('#/c/c2')
  })

  it('opens the chat named in the address after a reload, and goes home when it is gone', async () => {
    mockServer(() => fullResponse(DONE), {
      conversations: [
        conversation('c1', 'Kept', {
          messages: [stored('user', 'hello again')],
        }),
      ],
    })
    window.location.hash = '#/c/c1'
    const { unmount } = render(<App />)
    expect(await screen.findByText('hello again')).toBeInTheDocument()
    unmount()

    window.location.hash = '#/c/deleted-elsewhere'
    render(<App />)
    expect(await screen.findByText('What would you like to know?')).toBeInTheDocument()
    expect(window.location.hash).toBe('#/')
  })

  it('renames a chat', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Before')],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await within(sidebar()).findByRole('button', { name: 'Rename Before' }))
    const input = screen.getByRole('textbox', { name: 'Chat title' })
    await user.clear(input)
    await user.type(input, 'After{Enter}')
    expect(await within(sidebar()).findByText('After')).toBeInTheDocument()
    expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      title: 'After',
    })
  })

  it('deletes a chat only after confirmation, and leaves the open chat when it is deleted', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Doomed', { messages: [stored('user', 'bye')] })],
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('bye')

    await user.click(within(sidebar()).getByRole('button', { name: 'Delete Doomed' }))
    await user.click(within(sidebar()).getByRole('button', { name: 'Cancel' }))
    expect(server.calls.some((c) => c.method === 'DELETE')).toBe(false)

    await user.click(within(sidebar()).getByRole('button', { name: 'Delete Doomed' }))
    await user.click(within(sidebar()).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(server.calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(await screen.findByText('What would you like to know?')).toBeInTheDocument()
    expect(within(sidebar()).queryByText('Doomed')).toBeNull()
  })

  it('a changed Thinking switch is saved with the open chat', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Chat')],
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Thinking' })).toBeChecked())
    await user.click(screen.getByRole('switch', { name: 'Thinking' }))
    await waitFor(() =>
      expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        thinking: false,
      }),
    )
  })

  it('Try again asks the server for a new answer when the old one was stored', async () => {
    let calls = 0
    const server = mockServer(() => {
      calls += 1
      return calls === 1
        ? fullResponse(
            META,
            frame('content', { delta: 'Half' }),
            frame('error', { code: 'upstream_interrupted', message: 'lost' }),
          )
        : fullResponse(META, frame('content', { delta: 'Whole answer' }), DONE)
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'question{Enter}')
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Whole answer')).toBeInTheDocument()
    expect(turnCalls(server).map((c) => c.url.split('/').pop())).toEqual(['messages', 'regenerate'])
    expect(within(screen.getByRole('log')).getAllByText('question')).toHaveLength(1)
  })

  it('cannot switch chats or start a new one while an answer is being written', async () => {
    const live = liveStream()
    mockServer(() => live.response, {
      conversations: [conversation('c1', 'Other')],
    })
    const user = userEvent.setup()
    render(<App />)
    await within(sidebar()).findByText('Other')
    await user.type(box(), 'working{Enter}')
    live.push(META + frame('content', { delta: 'part' }))
    await screen.findByText('part')
    expect(within(sidebar()).getByRole('button', { name: 'New chat' })).toBeDisabled()
    expect(within(sidebar()).getByRole('button', { name: 'Other' })).toBeDisabled()
    live.push(DONE)
    live.close()
    await waitFor(() => expect(within(sidebar()).getByRole('button', { name: 'New chat' })).toBeEnabled())
  })
})

describe('documents', () => {
  const openPanel = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: /^Documents/ }))
    return screen.getByRole('dialog', { name: 'Documents' })
  }

  it('lists uploaded documents with their state and shows reading progress', async () => {
    mockServer(() => fullResponse(DONE), {
      documents: [
        documentInfo('d1', 'report.pdf'),
        documentInfo('d2', 'big.pdf', {
          status: 'processing',
          chunk_count: 10,
          embedded_count: 4,
        }),
        documentInfo('d3', 'broken.pdf', {
          status: 'error',
          error: 'LiteLLM refused the request.',
        }),
      ],
    })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    expect(await within(panel).findByText('report.pdf')).toBeInTheDocument()
    expect(within(panel).getByText('3 pages · 7 parts · 2 KB')).toBeInTheDocument()
    expect(within(panel).getByText('Reading 4/10')).toBeInTheDocument()
    expect(within(panel).getByRole('alert')).toHaveTextContent('LiteLLM refused the request.')
  })

  it('uploads a file as the request body and uses it in this chat at once', async () => {
    const server = mockServer()
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    const file = new File(['hello'], 'my notes.txt', { type: 'text/plain' })
    await user.upload(within(panel).getByLabelText('Choose files'), file)

    expect(await within(panel).findByText('my notes.txt')).toBeInTheDocument()
    const post = server.mock.mock.calls.find(([u, i]) => String(u) === '/api/documents' && i?.method === 'POST')!
    const init = post[1] as RequestInit
    expect(init.headers).toMatchObject({
      'content-type': 'application/octet-stream',
      'x-filename': 'my%20notes.txt',
    })
    expect(init.body).toBe(file)
    expect(
      within(panel).getByRole('checkbox', {
        name: 'Use my notes.txt in this chat',
      }),
    ).toBeChecked()
    expect(screen.getByRole('button', { name: 'Documents (1)' })).toBeInTheDocument()
  })

  it('says why a file was refused', async () => {
    mockServer()
    const user = userEvent.setup({ applyAccept: false }) // the app's file picker would hide it; drag and drop does not
    render(<App />)
    const panel = await openPanel(user)
    await user.upload(
      within(panel).getByLabelText('Choose files'),
      new File(['x'], 'bad.xlsx', { type: 'application/vnd.ms-excel' }),
    )
    expect(await within(panel).findByRole('alert')).toHaveTextContent("bad.xlsx: 'bad.xlsx' is not a supported file type.")
  })

  it('documents chosen in a new chat are attached when the chat is saved, before the question', async () => {
    const server = mockServer(() => fullResponse(frame('content', { delta: 'ok' }), DONE), {
      documents: [documentInfo('d1', 'report.pdf')],
    })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    await user.click(
      await within(panel).findByRole('checkbox', {
        name: 'Use report.pdf in this chat',
      }),
    )
    await user.type(box(), 'what is in it?{Enter}')
    await screen.findByText('ok')

    const order = server.calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.url}`)
    expect(order).toEqual([
      'POST /api/conversations',
      'POST /api/conversations/new1/documents/d1',
      'POST /api/conversations/new1/messages',
    ])
    expect(screen.getByRole('checkbox', { name: 'Use report.pdf in this chat' })).toBeChecked()
  })

  it('ticking in a saved chat attaches and detaches on the server', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Chat')],
      documents: [documentInfo('d1', 'report.pdf')],
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    const box1 = await within(panel).findByRole('checkbox', {
      name: 'Use report.pdf in this chat',
    })
    await user.click(box1)
    await waitFor(() => expect(server.attached.get('c1')).toEqual(['d1']))
    expect(box1).toBeChecked()
    await user.click(box1)
    await waitFor(() => expect(server.attached.get('c1')).toEqual([]))
    expect(box1).not.toBeChecked()
  })

  it('shows the attached documents of a saved chat when it is opened', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Chat')],
      documents: [documentInfo('d1', 'report.pdf'), documentInfo('d2', 'other.pdf')],
    })
    server.attached.set('c1', ['d2'])
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Documents (1)' })).toBeInTheDocument()
    const panel = await openPanel(user)
    expect(
      within(panel).getByRole('checkbox', {
        name: 'Use other.pdf in this chat',
      }),
    ).toBeChecked()
    expect(
      within(panel).getByRole('checkbox', {
        name: 'Use report.pdf in this chat',
      }),
    ).not.toBeChecked()
  })

  it('deleting a document asks first, then removes it', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      documents: [documentInfo('d1', 'report.pdf')],
    })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    await user.click(await within(panel).findByRole('button', { name: 'Delete report.pdf' }))
    await user.click(within(panel).getByRole('button', { name: 'Cancel' }))
    expect(server.docs.size).toBe(1)
    await user.click(within(panel).getByRole('button', { name: 'Delete report.pdf' }))
    await user.click(within(panel).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(server.docs.size).toBe(0))
    expect(await within(panel).findByText('No documents yet.')).toBeInTheDocument()
  })

  it('shows the sources under an answer, and again after the chat is reopened', async () => {
    const sources = {
      mode: 'search' as const,
      sources: [
        { n: 1, document_id: 'd1', filename: 'report.pdf', page: 3 },
        { n: 2, document_id: 'd1', filename: 'report.pdf', page: 8 },
      ],
      skipped: [{ document_id: 'd2', filename: 'new.pdf', status: 'processing' }],
    }
    mockServer(() => fullResponse(META, frame('sources', sources), frame('content', { delta: 'See [1].' }), DONE))
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await user.type(box(), 'q{Enter}')
    const summary = await screen.findByText('Sources (2) · best matches')
    await user.click(summary)
    expect(screen.getByText('report.pdf, page 3')).toBeInTheDocument()
    expect(screen.getByText('report.pdf, page 8')).toBeInTheDocument()
    expect(screen.getByText(/new\.pdf \(processing\)/)).toBeInTheDocument()
    unmount()

    vi.unstubAllGlobals()
    mockServer(() => fullResponse(DONE), {
      conversations: [
        conversation('c9', 'Saved', {
          messages: [stored('user', 'q'), stored('assistant', 'See [1].', { sources })],
        }),
      ],
    })
    window.location.hash = '#/c/c9'
    render(<App />)
    expect(await screen.findByText('Sources (2) · best matches')).toBeInTheDocument()
  })
})

describe('search and export', () => {
  const sidebar = () => screen.getByRole('navigation', { name: 'Conversations' })

  it('searches chats by text and shows where it matched', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [
        conversation('c1', 'Cooking', { messages: [stored('assistant', 'Add the saffron last.')] }),
        conversation('c2', 'Travel', { messages: [stored('user', 'Where is Lisbon?')] }),
      ],
    })
    const user = userEvent.setup()
    render(<App />)
    await within(sidebar()).findByText('Cooking')

    await user.type(within(sidebar()).getByRole('searchbox', { name: 'Search chats' }), 'saffron')
    expect(await within(sidebar()).findByText('Results (1)')).toBeInTheDocument()
    expect(within(sidebar()).getByText('Add the saffron last.')).toBeInTheDocument()
    expect(within(sidebar()).queryByText('Travel')).toBeNull()
    expect(server.calls.some((c) => c.url === '/api/conversations?q=saffron')).toBe(true)

    await user.clear(within(sidebar()).getByRole('searchbox', { name: 'Search chats' }))
    expect(await within(sidebar()).findByText('Travel')).toBeInTheDocument()
    expect(within(sidebar()).queryByText(/Results/)).toBeNull()

    await user.type(within(sidebar()).getByRole('searchbox', { name: 'Search chats' }), 'zzz')
    expect(await within(sidebar()).findByText('No chat contains that text.')).toBeInTheDocument()
  })

  it('sends one search request after typing stops, not one per key', async () => {
    const server = mockServer(() => fullResponse(DONE), { conversations: [conversation('c1', 'Cooking')] })
    const user = userEvent.setup()
    render(<App />)
    await within(sidebar()).findByText('Cooking')
    await user.type(within(sidebar()).getByRole('searchbox', { name: 'Search chats' }), 'cook')
    await within(sidebar()).findByText('Results (1)')
    expect(server.calls.filter((c) => c.url.startsWith('/api/conversations?q=')).map((c) => c.url)).toEqual([
      '/api/conversations?q=cook',
    ])
  })

  it('offers a Markdown download for a saved chat only', async () => {
    mockServer(() => fullResponse(DONE), { conversations: [conversation('c1', 'Saved')] })
    render(<App />)
    expect(screen.queryByRole('link', { name: 'Export' })).toBeNull() // a new chat is not saved yet

    window.location.hash = '#/c/c1'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    const link = await screen.findByRole('link', { name: 'Export' })
    expect(link).toHaveAttribute('href', '/api/conversations/c1/export')
    expect(link).toHaveAttribute('download')
  })
})

describe('chat titles', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('picks up the title the model writes a few seconds after the first answer', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const server = mockServer(() => fullResponse(frame('content', { delta: 'Paris.' }), DONE))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<App />)
    await user.type(box(), 'What is the capital of France?{Enter}')
    const nav = screen.getByRole('navigation', { name: 'Conversations' })
    expect(await within(nav).findByText('What is the capital of France?')).toBeInTheDocument() // draft

    server.db.get('new1')!.title = 'Capital of France' // the backend wrote it meanwhile
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })
    expect(await within(nav).findByText('Capital of France')).toBeInTheDocument()
  })
})

describe('editing a message', () => {
  const twoTurns = () =>
    conversation('c1', 'Chat', {
      messages: [
        stored('user', 'first question'),
        stored('assistant', 'first answer'),
        stored('user', 'second question'),
        stored('assistant', 'second answer'),
      ],
    })

  it('replaces the message and everything after it with a new answer', async () => {
    const server = mockServer(({ kind, content }) =>
      kind === 'edit'
        ? fullResponse(
            frame('meta', { model: 'qwen3.8', thinking: true, trimmed_messages: 0, user_message_id: 'srv-new' }),
            frame('content', { delta: `answer to: ${content}` }),
            DONE,
          )
        : fullResponse(DONE),
      { conversations: [twoTurns()] },
    )
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('second answer')

    const log = screen.getByRole('log')
    await user.click(within(log).getAllByRole('button', { name: 'Edit' })[1]!) // the second question
    expect(screen.getByText('Saving removes the 1 message after this one and writes a new answer.')).toBeInTheDocument()
    const box1 = screen.getByRole('textbox', { name: 'Edit message' })
    await user.clear(box1)
    await user.type(box1, 'a better second question')
    await user.click(screen.getByRole('button', { name: 'Save and answer' }))

    expect(await within(log).findByText('answer to: a better second question')).toBeInTheDocument()
    expect(within(log).queryByText('second answer')).toBeNull()
    expect(within(log).queryByText('second question')).toBeNull()
    expect(within(log).getByText('first answer')).toBeInTheDocument()
    const call = turnCalls(server).at(-1)!
    expect(call.url).toBe(`/api/conversations/c1/messages/s-second%20question/edit`)
    expect(call.body).toEqual({ content: 'a better second question' })
  })

  it('warns how many messages go, and Cancel changes nothing', async () => {
    const server = mockServer(() => fullResponse(DONE), { conversations: [twoTurns()] })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('second answer')
    await user.click(within(screen.getByRole('log')).getAllByRole('button', { name: 'Edit' })[0]!)
    expect(screen.getByText('Saving removes the 3 messages after this one and writes a new answer.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save and answer' })).toBeDisabled() // not changed yet
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByText('second answer')).toBeInTheDocument()
    expect(turnCalls(server)).toHaveLength(0)
  })

  it('shows what the server still has when it refuses the edit', async () => {
    mockServer(
      ({ kind }) =>
        kind === 'edit'
          ? Response.json({ error: { code: 'conversation_busy', message: 'An answer is still being written.' } }, { status: 409 })
          : fullResponse(DONE),
      { conversations: [twoTurns()] },
    )
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('second answer')
    await user.click(within(screen.getByRole('log')).getAllByRole('button', { name: 'Edit' })[0]!)
    const box1 = screen.getByRole('textbox', { name: 'Edit message' })
    await user.clear(box1)
    await user.type(box1, 'changed')
    await user.click(screen.getByRole('button', { name: 'Save and answer' }))

    expect(await screen.findByText('An answer is still being written.')).toBeInTheDocument()
    expect(await screen.findByText('second answer')).toBeInTheDocument() // nothing was lost on screen
    expect(screen.getByText('first question')).toBeInTheDocument()
  })

  it('offers Edit only for saved messages and not while an answer is being written', async () => {
    const live = liveStream()
    mockServer(() => live.response, { conversations: [twoTurns()] })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('second answer')
    expect(within(screen.getByRole('log')).getAllByRole('button', { name: 'Edit' })).toHaveLength(2)

    await user.type(box(), 'third{Enter}')
    live.push(META + frame('content', { delta: 'part' }))
    await screen.findByText('part')
    expect(within(screen.getByRole('log')).queryByRole('button', { name: 'Edit' })).toBeNull()
  })

  it('a message just sent can be edited once the server has stored it', async () => {
    mockServer(() =>
      fullResponse(
        frame('meta', { model: 'qwen3.8', thinking: true, trimmed_messages: 0, user_message_id: 'srv-1' }),
        frame('content', { delta: 'hi' }),
        DONE,
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hello{Enter}')
    await screen.findByText('hi')
    expect(await within(screen.getByRole('log')).findByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })
})

describe('usage page', () => {
  it('shows the figures, the chart and the slowest answers, and opens a chat from the list', async () => {
    const server = mockServer(() => fullResponse(DONE), { conversations: [conversation('c9', 'Long analysis')] })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Usage' }))

    expect(window.location.hash).toBe('#/stats')
    expect(await screen.findByRole('heading', { name: 'Usage' })).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('12 chats · 3 stopped · 1 failed')).toBeInTheDocument()
    expect(screen.getByText('7,890')).toBeInTheDocument()
    expect(screen.getByText('123,456')).toBeInTheDocument()
    expect(screen.getAllByText('5.0 s').length).toBeGreaterThan(0) // average response time
    expect(screen.getByText('51.3 tokens/s')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Answers per day: 15 in 3 days/ })).toBeInTheDocument()
    const request = server.calls.find((c) => c.url.startsWith('/api/stats'))!
    expect(request.url).toMatch(/^\/api\/stats\?range=7d&tz=-?\d+$/)

    const slowest = screen.getByRole('heading', { name: 'Slowest answers' }).closest('section')!
    await user.click(within(slowest).getByRole('button', { name: 'Long analysis' }))
    expect(window.location.hash).toBe('#/c/c9')
    expect(await screen.findByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('asks again for another time range', async () => {
    const asked: string[] = []
    mockServer(() => fullResponse(DONE), {
      stats: (range) => {
        asked.push(range)
        return { ...STATS, range: range as StatsResponse['range'], answers: { complete: range === 'today' ? 7 : 42, stopped: 0, failed: 0 } }
      },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Usage' }))
    await screen.findByText('42')
    await user.click(screen.getByRole('button', { name: 'Today' }))
    expect(await screen.findByText('7')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true')
    expect(asked).toEqual(['7d', 'today'])
  })

  it('says so when there are no answers yet', async () => {
    mockServer(() => fullResponse(DONE), {
      stats: () => ({
        ...STATS,
        answers: { complete: 0, stopped: 0, failed: 0 },
        latency_ms: { count: 0, avg: null, p50: null, p95: null, max: null },
        slowest: [],
      }),
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Usage' }))
    expect(await screen.findByText('No answers in this range yet.')).toBeInTheDocument()
  })

  it('shows a failure to load the figures', async () => {
    mockServer(() => fullResponse(DONE), {
      stats: () => Response.json({ error: { code: 'x', message: 'The database is locked.' } }, { status: 500 }),
    })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Usage' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The database is locked.')
  })

  it('opens from the address and goes back to the chat', async () => {
    mockServer(() => fullResponse(DONE))
    window.location.hash = '#/stats'
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Usage' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Back to chat/ }))
    expect(window.location.hash).toBe('#/')
    expect(await screen.findByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('cannot be opened while an answer is being written', async () => {
    const live = liveStream()
    mockServer(() => live.response)
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'working{Enter}')
    live.push(META + frame('content', { delta: 'part' }))
    await screen.findByText('part')
    expect(screen.getByRole('button', { name: 'Usage' })).toBeDisabled()
  })
})

describe('instructions and presets', () => {
  const preset = (id: string, name: string, content: string) => ({
    id,
    name,
    content,
    created_at: stamp(),
    updated_at: stamp(),
  })
  const PRESETS = [preset('p1', 'Concise', 'Answer briefly.'), preset('p2', 'Plain language', 'Use plain words.')]
  const openPanel = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: /^Instructions/ }))
    return screen.getByRole('dialog', { name: 'Instructions' })
  }

  it('a preset fills the box, and using it in a new chat saves the chat with it', async () => {
    const server = mockServer(() => fullResponse(frame('content', { delta: 'ok' }), DONE), { presets: PRESETS })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    expect(within(panel).getByText('None')).toBeInTheDocument()
    await user.click(await within(panel).findByRole('button', { name: 'Concise' }))
    expect(within(panel).getByRole('textbox', { name: 'Instructions for this chat' })).toHaveValue('Answer briefly.')
    await user.click(within(panel).getByRole('button', { name: 'Use in this chat' }))
    expect(screen.getByRole('button', { name: 'Instructions •' })).toBeInTheDocument()

    await user.type(box(), 'hello{Enter}')
    await screen.findByText('ok')
    const created = server.calls.find((c) => c.method === 'POST' && c.url === '/api/conversations')
    expect(created?.body).toMatchObject({ system_prompt: 'Answer briefly.' })
    expect(server.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('in a saved chat the instructions are saved with the chat', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Chat', { system_prompt: 'Answer briefly.' })],
      presets: PRESETS,
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Instructions •' })).toBeInTheDocument()
    const panel = await openPanel(user)
    expect(within(panel).getByText(/In use now:/)).toHaveTextContent('In use now: Concise') // recognised as a preset
    await user.click(within(panel).getByRole('button', { name: 'Plain language' }))
    await user.click(within(panel).getByRole('button', { name: 'Use in this chat' }))
    await waitFor(() =>
      expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ system_prompt: 'Use plain words.' }),
    )
  })

  it('your own text is saved as a new preset', async () => {
    const server = mockServer(() => fullResponse(DONE), { presets: PRESETS })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    await user.type(within(panel).getByRole('textbox', { name: 'Instructions for this chat' }), 'Reply in French.')
    await user.type(within(panel).getByRole('textbox', { name: 'Preset name' }), 'French')
    await user.click(within(panel).getByRole('button', { name: 'Save as preset' }))
    expect(await within(panel).findByRole('button', { name: 'French' })).toBeInTheDocument()
    expect(server.presets.at(-1)).toMatchObject({ name: 'French', content: 'Reply in French.' })
  })

  it('updates and deletes a preset (delete asks first)', async () => {
    const server = mockServer(() => fullResponse(DONE), { presets: PRESETS })
    const user = userEvent.setup()
    render(<App />)
    const panel = await openPanel(user)
    await user.click(await within(panel).findByRole('button', { name: 'Concise' }))
    const text = within(panel).getByRole('textbox', { name: 'Instructions for this chat' })
    await user.clear(text)
    await user.type(text, 'Answer in one line.')
    await user.click(within(panel).getByRole('button', { name: /Update preset/ }))
    await waitFor(() => expect(server.presets[0]!.content).toBe('Answer in one line.'))

    await user.click(within(panel).getByRole('button', { name: 'Delete preset Concise' }))
    await user.click(within(panel).getByRole('button', { name: 'Cancel' }))
    expect(server.presets).toHaveLength(2)
    await user.click(within(panel).getByRole('button', { name: 'Delete preset Concise' }))
    await user.click(within(panel).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(server.presets.map((p) => p.name)).toEqual(['Plain language']))
    expect(within(panel).queryByRole('button', { name: 'Concise' })).toBeNull()
  })

  it('cannot be changed while an answer is being written, and shows a failed save', async () => {
    const live = liveStream()
    mockServer(() => live.response, { presets: PRESETS })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'working{Enter}')
    live.push(META + frame('content', { delta: 'part' }))
    await screen.findByText('part')
    const panel = await openPanel(user)
    await user.type(within(panel).getByRole('textbox', { name: 'Instructions for this chat' }), 'x')
    expect(within(panel).getByRole('button', { name: 'Use in this chat' })).toBeDisabled()
    expect(within(panel).getByText(/An answer is being written/)).toBeInTheDocument()
  })

  it('a new chat starts without the previous chat\'s instructions', async () => {
    mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Chat', { system_prompt: 'Answer briefly.' })],
      presets: PRESETS,
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Instructions •' })
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    expect(await screen.findByRole('button', { name: 'Instructions' })).toBeInTheDocument()
  })
})

describe('context meter', () => {
  const usage = (extra: Partial<ContextUsage> = {}): ContextUsage => ({
    used: 10_200,
    budget: 24_320,
    percent: 42,
    parts: { instructions: 100, documents: 3_000, messages: 7_100 },
    messages: 6,
    would_trim: 0,
    limit: 32_768,
    reserved_for_answer: 8_448,
    ...extra,
  })
  const withChat = () => ({ conversations: [conversation('c1', 'Chat', { messages: [stored('user', 'hi')] })] })

  it('shows how full a saved chat is, with the breakdown on hover', async () => {
    mockServer(() => fullResponse(DONE), { ...withChat(), context: () => usage() })
    window.location.hash = '#/c/c1'
    render(<App />)
    expect(await screen.findByText('Context 42% · 10.2k of 24.3k tokens')).toBeInTheDocument()
    const meter = screen.getByRole('meter', { name: 'Context used' })
    expect(meter).toHaveAttribute('aria-valuenow', '42')
    const box1 = meter.closest('.context-meter')!
    expect(box1).toHaveClass('ok')
    expect(box1.getAttribute('title')).toBe(
      'Instructions 100 · Documents 3.0k · Messages 7.1k · Kept free for the answer 8.4k · Working limit 32.8k tokens',
    )
  })

  it('warns when old messages would be left out, and says how many', async () => {
    mockServer(() => fullResponse(DONE), {
      ...withChat(),
      context: () => usage({ used: 26_000, percent: 107, would_trim: 3 }),
    })
    window.location.hash = '#/c/c1'
    render(<App />)
    expect(await screen.findByText(/3 older messages will be left out of the next request/)).toBeInTheDocument()
    expect(screen.getByText(/Context full · 26.0k of 24.3k tokens/)).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Context used' })).toHaveAttribute('aria-valuenow', '100') // the bar stops at full
    expect(screen.getByRole('meter').closest('.context-meter')).toHaveClass('full')
  })

  it('uses the singular for one message', async () => {
    mockServer(() => fullResponse(DONE), { ...withChat(), context: () => usage({ percent: 80, used: 19_500, would_trim: 1 }) })
    window.location.hash = '#/c/c1'
    render(<App />)
    await screen.findByText('Context 80% · 19.5k of 24.3k tokens')
    expect(screen.getByText(/1 older message will be left out/)).toBeInTheDocument()
  })

  it('turns amber from 75 per cent', async () => {
    mockServer(() => fullResponse(DONE), { ...withChat(), context: () => usage({ percent: 80, used: 19_500 }) })
    window.location.hash = '#/c/c1'
    render(<App />)
    await screen.findByText('Context 80% · 19.5k of 24.3k tokens')
    expect(screen.getByRole('meter').closest('.context-meter')).toHaveClass('warn')
  })

  it('is not shown for a new chat or an empty one', async () => {
    mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Empty')],
      context: () => usage({ used: 0, percent: 0 }),
    })
    const { unmount } = render(<App />)
    await screen.findByRole('textbox', { name: 'Message' })
    expect(screen.queryByRole('meter')).toBeNull()
    unmount()
    window.location.hash = '#/c/c1'
    render(<App />)
    await screen.findByRole('textbox', { name: 'Message' })
    await waitFor(() => expect(screen.queryByRole('meter')).toBeNull())
  })

  it('is read again when an answer has finished', async () => {
    let percent = 10
    mockServer(() => fullResponse(frame('content', { delta: 'ok' }), DONE), {
      ...withChat(),
      context: () => usage({ percent, used: percent * 100 }),
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Context 10% · 1.0k of 24.3k tokens')
    percent = 30
    await user.type(box(), 'next{Enter}')
    expect(await screen.findByText('Context 30% · 3.0k of 24.3k tokens')).toBeInTheDocument()
  })

  it('is read again when a document is attached', async () => {
    let docs = 0
    const server = mockServer(() => fullResponse(DONE), {
      ...withChat(),
      documents: [documentInfo('d1', 'report.pdf')],
      context: () => usage({ parts: { instructions: 0, documents: docs, messages: 7_100 }, percent: docs ? 60 : 40 }),
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Context 40%/)
    docs = 4_000
    await user.click(screen.getByRole('button', { name: /^Documents/ }))
    await user.click(await screen.findByRole('checkbox', { name: 'Use report.pdf in this chat' }))
    expect(await screen.findByText(/Context 60%/)).toBeInTheDocument()
    expect(server.attached.get('c1')).toEqual(['d1'])
  })
})
