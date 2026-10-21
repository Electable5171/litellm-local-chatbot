import { useRef, useState, type DragEvent } from 'react'
import type { DocumentInfo } from '../api/types'

interface Props {
  docs: DocumentInfo[]
  attachedIds: string[]
  problems: string[]
  attachError: string | null
  uploading: string | null
  locked: boolean
  onClose: () => void
  onUpload: (files: File[]) => void
  onToggle: (id: string) => void
  onDelete: (id: string) => void
}

const ACCEPT = '.pdf,.docx,.md,.txt'

function size(bytes: number): string {
  return bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function Status({ doc }: { doc: DocumentInfo }) {
  if (doc.status === 'ready') {
    const pages = doc.page_count ? `${doc.page_count} pages · ` : ''
    return <span className="doc-status">{`${pages}${doc.chunk_count} ${doc.chunk_count === 1 ? 'part' : 'parts'} · ${size(doc.size_bytes)}`}</span>
  }
  if (doc.status === 'processing') {
    return (
      <span className="doc-status">
        <progress max={Math.max(doc.chunk_count, 1)} value={doc.embedded_count} aria-label={`Reading ${doc.filename}`} /> Reading{' '}
        {doc.embedded_count}/{doc.chunk_count}
      </span>
    )
  }
  return (
    <span className="doc-status error" role="alert">
      Failed: {doc.error ?? 'unknown error'} (upload the file again to retry)
    </span>
  )
}

export function DocumentsPanel({
  docs,
  attachedIds,
  problems,
  attachError,
  uploading,
  locked,
  onClose,
  onUpload,
  onToggle,
  onDelete,
}: Props) {
  const picker = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    const files = [...event.dataTransfer.files]
    if (files.length > 0) onUpload(files)
  }

  return (
    <aside
      className={`docs-panel${over ? ' over' : ''}`}
      role="dialog"
      aria-label="Documents"
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <header>
        <h2>Documents</h2>
        <button type="button" className="ghost" onClick={onClose}>
          Close
        </button>
      </header>
      <p className="docs-help">
        Tick the documents this chat should use. PDF, DOCX, Markdown or text. Drop files here or pick them.
      </p>
      <input
        ref={picker}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        aria-label="Choose files"
        onChange={(event) => {
          const files = [...(event.target.files ?? [])]
          event.target.value = ''
          if (files.length > 0) onUpload(files)
        }}
      />
      <button type="button" className="new-chat" onClick={() => picker.current?.click()} disabled={uploading !== null}>
        {uploading ? `Uploading ${uploading}…` : 'Upload documents'}
      </button>
      {[...problems, ...(attachError ? [attachError] : [])].map((text) => (
        <p key={text} className="notice error" role="alert">
          {text}
        </p>
      ))}
      {docs.length === 0 && <p className="docs-help">No documents yet.</p>}
      <ul>
        {docs.map((doc) => (
          <li key={doc.id} className="doc">
            <label>
              <input
                type="checkbox"
                checked={attachedIds.includes(doc.id)}
                disabled={locked}
                onChange={() => onToggle(doc.id)}
                aria-label={`Use ${doc.filename} in this chat`}
              />
              <span className="doc-name" title={doc.filename}>
                {doc.filename}
              </span>
            </label>
            <Status doc={doc} />
            {confirming === doc.id ? (
              <span className="doc-confirm">
                Delete from this computer?{' '}
                <button
                  type="button"
                  className="ghost small danger"
                  onClick={() => {
                    setConfirming(null)
                    onDelete(doc.id)
                  }}
                >
                  Delete
                </button>{' '}
                <button type="button" className="ghost small" onClick={() => setConfirming(null)}>
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="ghost small"
                aria-label={`Delete ${doc.filename}`}
                onClick={() => setConfirming(doc.id)}
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
    </aside>
  )
}
