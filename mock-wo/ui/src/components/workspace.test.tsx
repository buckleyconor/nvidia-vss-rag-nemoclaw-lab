import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EvidenceFocusProvider } from '../lib/evidenceFocus'
import { event, mockFetch, proposal, ragEvidence, vssEvidence } from '../test/helpers'
import { ActivityStream, QUIET_MS } from './ActivityStream'
import { DecisionPanel } from './DecisionPanel'
import { DocumentViewer, toBlocks } from './DocumentViewer'
import { StageRail } from './StageRail'
import { VideoPlayer } from './VideoPlayer'

const MANUAL = {
  id: 'manual-01',
  content_type: 'manual',
  text: '# Manual\n\n## 4.2 Bearing temperature limits\n\n- Normal operating range: 40–60 °C.\n- Bearing temperature above 75°C: replace per preventive schedule.\n\n## 4.3 Replacement procedure\n\n1. Lock out the drive.\n',
  sections: [
    { anchor: 'manual', title: 'Manual', level: 1, line: 0 },
    { anchor: '4.2', title: '4.2 Bearing temperature limits', level: 2, line: 2 },
    { anchor: '4.3', title: '4.3 Replacement procedure', level: 2, line: 7 },
  ],
}

describe('evidence linking (§8.3)', () => {
  it('seeks and pauses the video and scrolls the document to the highlighted passage together', async () => {
    mockFetch({ '/api/v1/packs/pack/documents/manual-01': MANUAL })
    const evidence = [vssEvidence, ragEvidence]
    render(
      <EvidenceFocusProvider>
        <VideoPlayer src="/media/clips/pack/clip.mp4" evidence={evidence} />
        <DocumentViewer packId="pack" evidence={evidence} />
        <ActivityStream
          events={[event(1, 'evidence.added', { evidence: vssEvidence }), event(2, 'evidence.added', { evidence: ragEvidence })]}
          evidence={evidence}
          stage="gather"
          lastEventAt={null}
        />
      </EvidenceFocusProvider>,
    )
    await screen.findByText('4.2 Bearing temperature limits')
    const video = screen.getByTestId('clip') as HTMLVideoElement
    const pause = vi.spyOn(video, 'pause')

    await userEvent.click(screen.getByRole('button', { name: 'Heat signature on bearing housing' }))
    expect(video.currentTime).toBe(42)
    expect(pause).toHaveBeenCalled()
    expect(screen.getByTestId('video-pane')).toHaveClass('linked')

    await userEvent.click(screen.getByRole('button', { name: 'Housing temperature exceeds the replacement threshold' }))
    await waitFor(() => expect(HTMLElement.prototype.scrollTo).toHaveBeenCalled())
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled() // never moves the page
    expect(screen.getByTestId('doc-highlight')).toHaveTextContent('Bearing temperature above 75°C: replace per preventive schedule.')
    expect(screen.getByTestId('doc-pane')).toHaveClass('linked')
  })

  it('places markers for timestamped video evidence and links from them', async () => {
    render(
      <EvidenceFocusProvider>
        <VideoPlayer src="/clip.mp4" evidence={[vssEvidence, ragEvidence]} />
      </EvidenceFocusProvider>,
    )
    const marker = screen.getByRole('button', { name: /Evidence at 00:42/ })
    expect(marker).toHaveStyle({ left: `${(42 / 90) * 100}%` })
    await userEvent.click(marker)
    expect((screen.getByTestId('clip') as HTMLVideoElement).currentTime).toBe(42)
  })

  it('explains an unplayable provisional clip instead of failing silently', () => {
    render(
      <EvidenceFocusProvider>
        <VideoPlayer src="/clip.mp4" evidence={[]} />
      </EvidenceFocusProvider>,
    )
    fireEvent.error(screen.getByTestId('clip'))
    expect(screen.getByRole('status')).toHaveTextContent('provisional')
  })

  it('stays empty until the first rag citation', () => {
    render(
      <EvidenceFocusProvider>
        <DocumentViewer packId="pack" evidence={[vssEvidence]} />
      </EvidenceFocusProvider>,
    )
    expect(screen.getByTestId('doc-pane')).toHaveTextContent('Documents appear here')
  })
})

it('renders documents as escaped text blocks', () => {
  const blocks = toBlocks({ ...MANUAL, text: MANUAL.text + '\n| a | b |\n| - | - |\n<script>alert(1)</script>\n' })
  expect(blocks.filter((b) => b.kind === 'heading').map((b) => b.anchor)).toEqual(['manual', '4.2', '4.3'])
  expect(blocks.find((b) => b.kind === 'pre')?.text).toBe('| a | b |\n| - | - |')
  expect(blocks.some((b) => b.text.includes('<script>'))).toBe(true) // text, rendered escaped by React
})

describe('StageRail', () => {
  it('announces the current step and the not-required decide', () => {
    const { rerender } = render(<StageRail model={{ stage: 'gather', previousStage: 'detect', decideNotRequired: false }} />)
    expect(screen.getByText('Gather context').closest('li')).toHaveAttribute('aria-current', 'step')
    rerender(<StageRail model={{ stage: 'act', previousStage: 'propose', decideNotRequired: true }} />)
    expect(screen.getByText('not required')).toBeInTheDocument()
  })
})

describe('ActivityStream (§8.4)', () => {
  it('says what it is waiting on after eight quiet seconds — never a spinner', () => {
    vi.useFakeTimers()
    const start = Date.parse('2026-09-13T12:00:01Z')
    let now = start
    const events = [event(1, 'stage.changed', { stage: 'gather', previous: 'detect' })]
    render(
      <EvidenceFocusProvider>
        <ActivityStream events={events} evidence={[]} stage="gather" lastEventAt={events[0].ts} now={() => now} />
      </EvidenceFocusProvider>,
    )
    expect(screen.queryByTestId('waiting')).toBeNull()
    now = start + QUIET_MS + 1000
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.getByTestId('waiting')).toHaveTextContent('Waiting on VSS video analysis and the agent')
    vi.useRealTimers()
  })

  it('collapses long reasoning with an expander and renders each class', async () => {
    const long = 'I will compare the housing temperature with the manual limit. '.repeat(5)
    render(
      <EvidenceFocusProvider>
        <ActivityStream
          events={[
            event(1, 'skill.invoked', { skill_name: 'vss-generate-video-report-rag', rationale: 'Report with RAG context' }),
            event(2, 'agent.token', { text: long }),
            event(3, 'retrieval.query', { query: 'bearing temperature limits' }),
            event(4, 'retrieval.result', { documents: [{ document_name: 'manual-01.md' }], latency_ms: 1690 }),
            event(5, 'skill.completed', { skill_name: 'vss-generate-video-report-rag', duration_ms: 2500, outcome: 'ok' }),
            event(6, 'error', { stage: 'gather', message: 'VSS /generate failed', recoverable: true }),
          ]}
          evidence={[]}
          stage="gather"
          lastEventAt={null}
        />
      </EvidenceFocusProvider>,
    )
    expect(screen.getByText('Report with RAG context')).toBeInTheDocument()
    expect(screen.getByText('bearing temperature limits')).toBeInTheDocument()
    expect(screen.getByText(/manual-01\.md/)).toBeInTheDocument()
    expect(screen.getByText(/done in 2\.5 s/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('VSS /generate failed')
    const expander = screen.getByRole('button', { name: 'Show more' })
    await userEvent.click(expander)
    expect(screen.getByRole('button', { name: 'Show less' })).toBeInTheDocument()
  })

  it('offers retry for a recoverable detect error', async () => {
    const onRetry = vi.fn()
    render(
      <EvidenceFocusProvider>
        <ActivityStream
          events={[event(1, 'error', { stage: 'detect', message: 'wake hook refused', recoverable: true })]}
          evidence={[]}
          stage="detect"
          lastEventAt={null}
          onRetry={onRetry}
        />
      </EvidenceFocusProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('DecisionPanel (§8.6)', () => {
  it('approves with the selected line items', async () => {
    const calls = mockFetch({ '/api/v1/proposals/prop-1/decision': { ...proposal, state: 'approved' } })
    const onDecided = vi.fn()
    render(<DecisionPanel proposal={proposal} onDecided={onDecided} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /De-rate/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(onDecided).toHaveBeenCalled())
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ action: 'approve', line_items_approved: ['li-1'] })
  })

  it('cannot approve with no actions selected', async () => {
    render(<DecisionPanel proposal={proposal} onDecided={vi.fn()} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /Order bearing/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /De-rate/ }))
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('requires a reason to deny', async () => {
    const calls = mockFetch({ '/api/v1/proposals/prop-1/decision': { ...proposal, state: 'denied' } })
    render(<DecisionPanel proposal={proposal} onDecided={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }))
    const confirm = screen.getAllByRole('button', { name: 'Deny' }).at(-1)!
    expect(confirm).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Wrong root cause' }))
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ action: 'deny', reason: 'Wrong root cause' })
  })

  it('requires an edit and a note to modify, and sends only changed fields', async () => {
    const calls = mockFetch({ '/api/v1/proposals/prop-1/decision': { ...proposal, state: 'modified' } })
    render(<DecisionPanel proposal={proposal} onDecided={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Modify' }))
    const submit = screen.getByRole('button', { name: 'Approve with changes' })
    expect(submit).toBeDisabled()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Priority' }), 'medium')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox', { name: /What changed/ }), 'Planned window')
    await userEvent.click(submit)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      action: 'modify',
      reason: 'Planned window',
      modifications: { priority: 'medium' },
      line_items_approved: ['li-1', 'li-2'],
    })
  })

  it('reports a replayed decision and refreshes', async () => {
    mockFetch({
      '/api/v1/proposals/prop-1/decision': () =>
        new Response(JSON.stringify({ detail: 'proposal_already_decided' }), { status: 409 }),
    })
    const onDecided = vi.fn()
    render(<DecisionPanel proposal={proposal} onDecided={onDecided} />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already been decided')
    expect(onDecided).toHaveBeenCalled()
  })

  it('shows the recorded outcome with the outcome word', () => {
    render(
      <DecisionPanel
        proposal={{
          ...proposal,
          state: 'approved',
          decision: {
            id: 'd',
            action: 'approve',
            reason: null,
            modifications: null,
            line_items_approved: ['li-1'],
            work_order_id: 'abcdef1234',
            decided_at: 'x',
          },
        }}
        onDecided={vi.fn()}
      />,
    )
    expect(screen.getByTestId('decided')).toHaveTextContent('Approved')
    expect(screen.getByRole('link', { name: 'WO-abcdef12' })).toHaveAttribute('href', '/work-orders/abcdef1234')
  })

  it('states that monitoring notes are not gated', () => {
    render(<DecisionPanel proposal={{ ...proposal, kind: 'monitoring_note', state: 'auto_filed', line_items: [] }} onDecided={vi.fn()} />)
    expect(screen.getByText(/No approval required/)).toBeInTheDocument()
  })
})
