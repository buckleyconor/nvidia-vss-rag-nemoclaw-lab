// The forwarder is deliberately dumb: it ships raw hook events to mock-wo and
// never interprets them. Mapping to skill.invoked / skill.completed /
// agent.token lives server-side (mock-wo/app/telemetry.py), where it is tested
// and where secrets are redacted before anything is stored or rebroadcast.
//
// Two rules keep telemetry from ever affecting the agent (ADR-V09):
// - send() returns immediately; hooks never await the network.
// - failures are swallowed and counted; a bounded queue drops the oldest
//   events rather than growing without limit when mock-wo is unreachable.

export type HookName = 'before_tool_call' | 'after_tool_call' | 'llm_output' | 'agent_end'

export interface AgentEvent {
  hook: HookName
  run_id?: string
  tool_call_id?: string
  tool_name?: string
  params?: Record<string, unknown>
  error?: string
  duration_ms?: number
  text?: string
}

export interface ForwarderOptions {
  url: string
  fetchImpl?: typeof fetch
  timeoutMs?: number
  maxQueue?: number
}

export interface Forwarder {
  send: (event: AgentEvent) => void
  flush: () => Promise<void>
  stats: () => { sent: number; failed: number; dropped: number; queued: number }
}

export const DEFAULT_URL = 'http://host.openshell.internal:8090/api/v1/agent-events'
const MAX_TEXT = 32000

export function createForwarder({ url, fetchImpl = fetch, timeoutMs = 2000, maxQueue = 500 }: ForwarderOptions): Forwarder {
  const queue: AgentEvent[] = []
  let draining: Promise<void> | null = null
  let sent = 0
  let failed = 0
  let dropped = 0

  const post = async (event: AgentEvent) => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetchImpl(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(event),
        signal: controller.signal,
      })
      if (response.ok) sent += 1
      else failed += 1
    } catch {
      failed += 1
    } finally {
      clearTimeout(timer)
    }
  }

  // Events are posted one at a time, in order: mock-wo pairs skill starts and
  // completions by arrival order within a run.
  const drain = async () => {
    while (queue.length) {
      await post(queue.shift()!)
    }
    draining = null
  }

  return {
    send(event) {
      if (queue.length >= maxQueue) {
        queue.shift()
        dropped += 1
      }
      queue.push(event.text && event.text.length > MAX_TEXT ? { ...event, text: event.text.slice(0, MAX_TEXT) } : event)
      if (!draining) draining = drain()
    },
    async flush() {
      while (draining) await draining
    },
    stats: () => ({ sent, failed, dropped, queued: queue.length }),
  }
}
