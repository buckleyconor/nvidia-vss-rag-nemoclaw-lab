import { describe, expect, it, vi } from 'vitest'
import { createForwarder, DEFAULT_URL } from './forwarder.js'
import { llmEvent, registerHooks, resolveUrl, toolEvent } from './index.js'

const okFetch = () => vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(null, { status: 202 }))

describe('event mapping', () => {
  it('maps tool calls with run id fallback, error and duration', () => {
    expect(
      toolEvent('before_tool_call', { toolName: 'read', params: { path: 'skills/vss-ask-video/SKILL.md' }, toolCallId: 't1' }, { runId: 'r1' }),
    ).toEqual({ hook: 'before_tool_call', run_id: 'r1', tool_call_id: 't1', tool_name: 'read', params: { path: 'skills/vss-ask-video/SKILL.md' } })
    expect(toolEvent('after_tool_call', { toolName: 'exec', params: {}, runId: 'r2', error: 'refused', durationMs: 12 }, {})).toMatchObject({
      run_id: 'r2',
      error: 'refused',
      duration_ms: 12,
    })
  })

  it('joins assistant texts and skips empty output', () => {
    expect(llmEvent({ runId: 'r', assistantTexts: ['First.', 'Second.'] }, {})).toEqual({ hook: 'llm_output', run_id: 'r', text: 'First.\nSecond.' })
    expect(llmEvent({ runId: 'r', assistantTexts: ['  '] }, {})).toBeNull()
    expect(llmEvent({ runId: 'r' }, {})).toBeNull()
  })
})

describe('forwarder', () => {
  it('posts in order to the agent-events URL without blocking the hook', async () => {
    const fetchImpl = okFetch()
    const forwarder = createForwarder({ url: 'http://mock-wo:8090/api/v1/agent-events', fetchImpl })
    const returned = forwarder.send({ hook: 'llm_output', text: 'a' })
    expect(returned).toBeUndefined()
    forwarder.send({ hook: 'agent_end' })
    await forwarder.flush()
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body)))
    expect(bodies.map((b) => b.hook)).toEqual(['llm_output', 'agent_end'])
    expect(String(fetchImpl.mock.calls[0][0])).toBe('http://mock-wo:8090/api/v1/agent-events')
    expect(forwarder.stats()).toMatchObject({ sent: 2, failed: 0 })
  })

  it('swallows network failures and non-2xx responses', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockResolvedValueOnce(new Response(null, { status: 422 }))
    const forwarder = createForwarder({ url: 'http://x', fetchImpl: fetchImpl as unknown as typeof fetch })
    forwarder.send({ hook: 'agent_end' })
    forwarder.send({ hook: 'agent_end' })
    await forwarder.flush()
    expect(forwarder.stats()).toMatchObject({ sent: 0, failed: 2 })
  })

  it('bounds the queue by dropping the oldest events', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => (release = resolve))
    const fetchImpl = vi.fn(async () => {
      await gate
      return new Response(null, { status: 202 })
    })
    const forwarder = createForwarder({ url: 'http://x', fetchImpl: fetchImpl as unknown as typeof fetch, maxQueue: 3 })
    for (let i = 0; i < 10; i++) forwarder.send({ hook: 'llm_output', text: String(i) })
    expect(forwarder.stats().queued).toBe(3)
    expect(forwarder.stats().dropped).toBe(6)
    release()
    await forwarder.flush()
    expect(forwarder.stats().sent).toBe(4)
  })

  it('aborts a hung request after the timeout', async () => {
    vi.useFakeTimers()
    const fetchImpl = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new Error('aborted')))),
    )
    const forwarder = createForwarder({ url: 'http://x', fetchImpl: fetchImpl as unknown as typeof fetch, timeoutMs: 50 })
    forwarder.send({ hook: 'agent_end' })
    await vi.advanceTimersByTimeAsync(60)
    await forwarder.flush()
    expect(forwarder.stats().failed).toBe(1)
    vi.useRealTimers()
  })

  it('truncates oversized text', async () => {
    const fetchImpl = okFetch()
    const forwarder = createForwarder({ url: 'http://x', fetchImpl })
    forwarder.send({ hook: 'llm_output', text: 'x'.repeat(40000) })
    await forwarder.flush()
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body)).text).toHaveLength(32000)
  })
})

describe('registration', () => {
  it('registers exactly the four display hooks and returns nothing from them', async () => {
    const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>()
    const fetchImpl = okFetch()
    const forwarder = createForwarder({ url: 'http://x', fetchImpl })
    registerHooks({ on: (name, handler) => handlers.set(name, handler as never) }, forwarder)
    expect([...handlers.keys()]).toEqual(['before_tool_call', 'after_tool_call', 'llm_output', 'agent_end'])
    expect(handlers.get('before_tool_call')!({ toolName: 'read', params: {} }, { runId: 'r' })).toBeUndefined()
    handlers.get('llm_output')!({ runId: 'r', assistantTexts: [] }, {})
    handlers.get('agent_end')!({}, { runId: 'r' })
    await forwarder.flush()
    expect(fetchImpl).toHaveBeenCalledTimes(2) // empty llm_output is not sent
  })
})

describe('resolveUrl', () => {
  it('prefers plugin config, then env, then the default agent-port URL', () => {
    expect(resolveUrl({ url: 'http://a:8090/api/v1/agent-events' }, { MOCK_WO_TELEMETRY_URL: 'http://b' })).toBe('http://a:8090/api/v1/agent-events')
    expect(resolveUrl(undefined, { MOCK_WO_TELEMETRY_URL: 'http://b:8090/x' })).toBe('http://b:8090/x')
    expect(resolveUrl({}, {})).toBe(DEFAULT_URL)
  })

  it('refuses the operator port', () => {
    expect(() => resolveUrl({ url: 'http://host:8091/api/v1/agent-events' }, {})).toThrow(/8091/)
  })
})
