import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Evidence } from './types'

// Evidence linking (§8.3) — the most demonstrable behaviour in the app.
// Clicking any claim focuses a set of evidence rows. The video pane seeks to
// the first row with a timestamp; the document pane scrolls to the first row
// with a document. Both panes briefly outline so it is visible they moved
// together. `nonce` makes a second click on the same claim move them again.

export interface FocusTarget {
  video: Evidence | null
  document: Evidence | null
  nonce: number
}

interface FocusApi {
  target: FocusTarget
  focusEvidence: (rows: Evidence[]) => void
}

const FocusContext = createContext<FocusApi | null>(null)

export function EvidenceFocusProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<FocusTarget>({ video: null, document: null, nonce: 0 })
  const focusEvidence = useCallback((rows: Evidence[]) => {
    const video = rows.find((row) => row.source_type === 'vss' && row.t_start !== null) ?? null
    const document = rows.find((row) => row.source_type === 'rag') ?? null
    if (!video && !document) return
    setTarget((previous) => ({ video, document, nonce: previous.nonce + 1 }))
  }, [])
  const value = useMemo(() => ({ target, focusEvidence }), [target, focusEvidence])
  return <FocusContext.Provider value={value}>{children}</FocusContext.Provider>
}

export function useEvidenceFocus(): FocusApi {
  const api = useContext(FocusContext)
  if (!api) throw new Error('useEvidenceFocus outside EvidenceFocusProvider')
  return api
}

// A rag source_id is `<doc-id>#<anchor>`; the anchor field wins when present.
export function documentRef(row: Evidence): { docId: string; anchor: string | null } {
  const [docId, hashAnchor] = row.source_id.split('#', 2)
  return { docId, anchor: row.document_anchor ?? hashAnchor ?? null }
}
