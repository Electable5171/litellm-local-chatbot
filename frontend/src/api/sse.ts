export interface SseMessage {
  event: string
  data: string
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue // comment / keep-alive
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  return data.length > 0 ? { event, data: data.join('\n') } : null
}

/**
 * Read server-sent events from a fetch() body. Network chunks can split an event anywhere,
 * so text is buffered until a blank line completes an event.
 */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let end = buffer.indexOf('\n\n')
      while (end >= 0) {
        const message = parseBlock(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
        if (message) yield message
        end = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) {
      const message = parseBlock(buffer)
      if (message) yield message
    }
  } finally {
    // Also runs when the caller stops early: tell the browser to drop the connection.
    reader.cancel().catch(() => undefined)
  }
}
