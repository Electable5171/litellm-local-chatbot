import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { ChatRequestBody, Health, ModelsResponse } from './api/types'

const encoder = new TextEncoder()

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  litellm: { base_url: 'http://x/v1', reachable: true, latency_ms: 120, error: null, checked_age_s: 0 },
  chat_model: { id: 'qwen3.8', available: true },
}
const MODELS: ModelsResponse = { default: 'qwen3.8', models: [{ id: 'qwen3.8', available: true }] }

const frame = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
const DONE = frame('done', {
  finish_reason: 'stop',
  usage: { prompt_tokens: 5, completion_tokens: 42 },
  latency_ms: 9000,
  ttft_ms: 300,
})
const META = frame('meta', { model: 'qwen3.8', thinking: true, trimmed_messages: 0 })

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
    response: new Response(body, { headers: { 'content-type': 'text/event-stream' } }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  }
}

function fullResponse(...frames: string[]): Response {
  return new Response(frames.join(''), { headers: { 'content-type': 'text/event-stream' } })
}

type ChatHandler = (body: ChatRequestBody, init: RequestInit) => Response | Promise<Response>

function mockServer(chat: ChatHandler, health: Health = HEALTH) {
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    if (url === '/api/health') return Response.json(health)
    if (url === '/api/models') return Response.json(MODELS)
    if (url === '/api/chat') return chat(JSON.parse(String(init.body)) as ChatRequestBody, init)
    throw new Error(`unexpected request to ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

const chatCalls = (mock: ReturnType<typeof mockServer>) =>
  mock.mock.calls.filter(([url]) => String(url) === '/api/chat')

const box = () => screen.getByRole('textbox', { name: 'Message' })

beforeEach(() => {
  localStorage.clear()
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
      litellm: { ...HEALTH.litellm, reachable: false, latency_ms: null, error: 'Cannot reach LiteLLM.' },
    }
    mockServer(() => fullResponse(DONE), degraded)
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

  it('sends the earlier conversation but never the reasoning', async () => {
    const mock = mockServer((body) =>
      fullResponse(
        frame('reasoning', { delta: 'secret thoughts' }),
        frame('content', { delta: `reply to: ${body.messages.at(-1)?.content}` }),
        DONE,
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'first{Enter}')
    await screen.findByText('reply to: first')
    await user.type(box(), 'second{Enter}')
    await screen.findByText('reply to: second')

    const second = JSON.parse(String(chatCalls(mock)[1]![1]!.body)) as ChatRequestBody
    expect(second.messages).toEqual([
      { role: 'user', content: 'first' },
      { role: 'assistant', content: 'reply to: first' },
      { role: 'user', content: 'second' },
    ])
    expect(JSON.stringify(second)).not.toContain('secret thoughts')
  })

  it('Shift+Enter makes a new line instead of sending', async () => {
    const mock = mockServer(() => fullResponse(DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'line one{Shift>}{Enter}{/Shift}line two')
    expect(box()).toHaveValue('line one\nline two')
    expect(chatCalls(mock)).toHaveLength(0)
  })

  it('the Thinking switch is sent with the question and remembered', async () => {
    const mock = mockServer(() => fullResponse(frame('content', { delta: 'hi' }), DONE))
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await user.click(screen.getByRole('switch', { name: 'Thinking' }))
    await user.type(box(), 'hello{Enter}')
    await screen.findByText('hi')
    expect((JSON.parse(String(chatCalls(mock)[0]![1]!.body)) as ChatRequestBody).thinking).toBe(false)

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
          { error: { code: 'upstream_busy', message: 'busy', retry_after_s: 5 } },
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
    expect(screen.getAllByText('hello')).toHaveLength(1) // the question is not duplicated
  })

  it('an error in the middle of an answer keeps what arrived', async () => {
    mockServer(() =>
      fullResponse(
        frame('content', { delta: 'Half an ans' }),
        frame('error', { code: 'upstream_interrupted', message: 'The connection to LiteLLM was lost.' }),
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
    mockServer((_body, init) => {
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
