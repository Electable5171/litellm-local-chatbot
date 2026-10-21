import { isValidElement, memo, useEffect, useRef, useState, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

/** Copies text and shows "Copied" for a moment. Clipboard access can be blocked; that is not an error. */
export function useCopy(): { copied: boolean; copy: (text: string) => void } {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const copy = (text: string) => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => {
        setCopied(true)
        clearTimeout(timer.current)
        timer.current = setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => undefined)
  }
  return { copied, copy }
}

function CodeBlock({ children, ...rest }: ComponentPropsWithoutRef<'pre'>) {
  const preRef = useRef<HTMLPreElement>(null)
  const { copied, copy } = useCopy()
  const child = Array.isArray(children) ? children[0] : children
  const className = isValidElement(child) ? (child.props as { className?: string }).className : ''
  const language = /language-([\w-]+)/.exec(className ?? '')?.[1]
  return (
    <div className="code-block">
      <div className="code-head">
        <span>{language ?? 'code'}</span>
        <button type="button" className="ghost small" onClick={() => copy(preRef.current?.textContent ?? '')}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre ref={preRef} {...rest}>
        {children}
      </pre>
    </div>
  )
}

function SafeLink(props: ComponentPropsWithoutRef<'a'>) {
  return <a {...props} target="_blank" rel="noopener noreferrer" />
}

/**
 * Images are never loaded: an address chosen by the model could carry your data to another
 * server just by being fetched. The description is shown instead.
 */
function BlockedImage({ alt }: ComponentPropsWithoutRef<'img'>) {
  return <span className="image-blocked">[image: {alt || 'not shown'}]</span>
}

/**
 * Renders the model's answer. The model's output is untrusted: it is sanitised (no raw HTML,
 * no scripts, no javascript: links, no images) before syntax highlighting adds its own spans.
 */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize, rehypeHighlight]}
        components={{ pre: CodeBlock, a: SafeLink, img: BlockedImage }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
})
