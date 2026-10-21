import { parseSse, type SseMessage } from './sse'

const encoder = new TextEncoder()

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk)
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<SseMessage[]> {
  const out: SseMessage[] = []
  for await (const message of parseSse(stream)) out.push(message)
  return out
}

describe('parseSse', () => {
  it('parses events and their data', async () => {
    const messages = await collect(streamOf(['event: a\ndata: {"x":1}\n\nevent: b\ndata: {"y":2}\n\n']))
    expect(messages).toEqual([
      { event: 'a', data: '{"x":1}' },
      { event: 'b', data: '{"y":2}' },
    ])
  })

  it('handles an event split across chunks at every position', async () => {
    const text = 'event: content\ndata: {"delta":"Hi there"}\n\nevent: done\ndata: {}\n\n'
    for (let cut = 1; cut < text.length; cut++) {
      const messages = await collect(streamOf([text.slice(0, cut), text.slice(cut)]))
      expect(messages.map((m) => m.event)).toEqual(['content', 'done'])
      expect(JSON.parse(messages[0]!.data)).toEqual({ delta: 'Hi there' })
    }
  })

  it('does not break a multi-byte character that is split between chunks', async () => {
    const bytes = encoder.encode('event: content\ndata: {"delta":"हि"}\n\n')
    const messages = await collect(streamOf([bytes.slice(0, 30), bytes.slice(30)]))
    expect(JSON.parse(messages[0]!.data)).toEqual({ delta: 'हि' })
  })

  it('accepts CRLF line endings, comments and a missing final blank line', async () => {
    const messages = await collect(streamOf([': keep-alive\r\n\r\nevent: x\r\ndata: 1\r\n\r\nevent: y\r\ndata: 2']))
    expect(messages).toEqual([
      { event: 'x', data: '1' },
      { event: 'y', data: '2' },
    ])
  })

  it('joins several data lines and defaults the event name', async () => {
    expect(await collect(streamOf(['data: a\ndata: b\n\n']))).toEqual([{ event: 'message', data: 'a\nb' }])
  })

  it('stops reading and cancels the connection when the caller stops early', async () => {
    let cancelled = false
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: a\ndata: 1\n\n'))
      },
      cancel() {
        cancelled = true
      },
    })
    for await (const message of parseSse(stream)) {
      expect(message.event).toBe('a')
      break
    }
    await Promise.resolve()
    expect(cancelled).toBe(true)
  })
})
