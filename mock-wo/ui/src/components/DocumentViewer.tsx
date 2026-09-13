import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { documentRef, useEvidenceFocus } from '../lib/evidenceFocus'
import type { DocumentBody, Evidence } from '../lib/types'

interface Block {
  kind: 'heading' | 'para' | 'item' | 'pre'
  text: string
  level?: number
  anchor?: string
}

// A deliberately small Markdown reader for the corpus: headings (anchors),
// list items, tables/code as preformatted text, paragraphs. React escapes all
// text — no HTML from documents is ever injected.
export function toBlocks(doc: DocumentBody): Block[] {
  const anchors = new Map(doc.sections.map((section) => [section.line, section]))
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'para', text: para.join(' ') })
    para = []
  }
  doc.text.split('\n').forEach((line, index) => {
    const section = anchors.get(index)
    if (section) {
      flush()
      blocks.push({ kind: 'heading', text: section.title, level: section.level, anchor: section.anchor })
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      flush()
      blocks.push({ kind: 'item', text: line.replace(/^\s*([-*]|\d+\.)\s+/, '') })
    } else if (/^\s*\|/.test(line) || /^\s{4,}\S/.test(line)) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last && last.kind === 'pre') last.text += `\n${line}`
      else blocks.push({ kind: 'pre', text: line })
    } else if (line.trim() === '') {
      flush()
    } else {
      para.push(line.trim())
    }
  })
  flush()
  return blocks
}

function normalise(text: string) {
  return text.replace(/\s+/g, ' ').trim().toLowerCase()
}

function Highlighted({ text, quote }: { text: string; quote: string | null }) {
  if (!quote) return <>{text}</>
  const needle = normalise(quote)
  const hay = normalise(text)
  const at = needle ? hay.indexOf(needle) : -1
  if (at < 0) return <>{text}</>
  // Map the normalised offset back onto the original string.
  const collapsed = text.replace(/\s+/g, ' ')
  const lead = collapsed.length - collapsed.trimStart().length
  const start = at + lead
  return (
    <>
      {collapsed.slice(0, start)}
      <mark data-testid="doc-highlight">{collapsed.slice(start, start + needle.length)}</mark>
      {collapsed.slice(start + needle.length)}
    </>
  )
}

// §8.2 — empty until the first `rag` evidence, then the cited document scrolled
// to its anchor with the passage highlighted; steps through all citations.
export function DocumentViewer({ packId, evidence }: { packId: string; evidence: Evidence[] }) {
  const citations = useMemo(() => evidence.filter((row) => row.source_type === 'rag'), [evidence])
  const { target } = useEvidenceFocus()
  const [current, setCurrent] = useState<Evidence | null>(null)
  const [doc, setDoc] = useState<DocumentBody | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [linked, setLinked] = useState(false)
  const body = useRef<HTMLDivElement>(null)

  // First citation to arrive opens the viewer.
  useEffect(() => {
    if (!current && citations.length) setCurrent(citations[0])
  }, [citations, current])

  useEffect(() => {
    if (!target.document || target.nonce === 0) return
    setCurrent(target.document)
    setLinked(true)
    const timer = window.setTimeout(() => setLinked(false), 900)
    return () => window.clearTimeout(timer)
  }, [target])

  const ref = current ? documentRef(current) : null
  useEffect(() => {
    if (!ref) return
    let cancelled = false
    setError(null)
    api
      .document(packId, ref.docId)
      .then((loaded) => !cancelled && setDoc(loaded))
      .catch(() => !cancelled && setError(`Document ${ref.docId} is not in this pack's corpus.`))
    return () => {
      cancelled = true
    }
  }, [packId, ref?.docId]) // eslint-disable-line react-hooks/exhaustive-deps

  const blocks = useMemo(() => (doc ? toBlocks(doc) : []), [doc])
  const activeAnchor = ref?.anchor ?? null

  useEffect(() => {
    if (!doc || !activeAnchor || !body.current) return
    const container = body.current
    const heading = container.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(activeAnchor)}"]`)
    if (!heading) return
    // Scroll the document well only — scrollIntoView would also move the page.
    const top = heading.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
    container.scrollTo?.({ top: Math.max(0, top - 8), behavior: 'smooth' })
  }, [doc, activeAnchor, target.nonce, current])

  if (!citations.length && !current) {
    return (
      <div className="pane doc-pane" data-testid="doc-pane">
        <div className="pane-empty muted">Documents appear here when the agent cites the corpus.</div>
      </div>
    )
  }

  const index = current ? citations.findIndex((row) => row.id === current.id) : -1
  let inSection = false
  return (
    <div className={`pane doc-pane ${linked ? 'linked' : ''}`} data-testid="doc-pane">
      <div className="doc-bar">
        <span className="mono breadcrumb">
          {ref?.docId}
          {activeAnchor ? ` › ${activeAnchor}` : ''}
        </span>
        <span className="doc-steps">
          <button type="button" disabled={index <= 0} onClick={() => setCurrent(citations[index - 1])} aria-label="Previous citation">
            ‹
          </button>
          <span className="muted">
            {index + 1}/{citations.length}
          </span>
          <button
            type="button"
            disabled={index < 0 || index >= citations.length - 1}
            onClick={() => setCurrent(citations[index + 1])}
            aria-label="Next citation"
          >
            ›
          </button>
        </span>
      </div>
      <div className="pane-well doc-body" ref={body}>
        {error && <div className="muted">{error}</div>}
        {blocks.map((block, i) => {
          if (block.kind === 'heading') {
            inSection = block.anchor === activeAnchor
            const Tag = `h${Math.min(6, (block.level ?? 1) + 2)}` as 'h3'
            return (
              <Tag key={i} data-anchor={block.anchor} className={inSection ? 'doc-active' : undefined}>
                {block.text}
              </Tag>
            )
          }
          const quote = inSection || !activeAnchor ? current?.quote ?? null : null
          const content = <Highlighted text={block.text} quote={quote} />
          return (
            <Fragment key={i}>
              {block.kind === 'item' && <p className="doc-item">• {content}</p>}
              {block.kind === 'para' && <p>{content}</p>}
              {block.kind === 'pre' && <pre className="mono">{block.text}</pre>}
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}
