/**
 * mock-wo-telemetry — OpenClaw plugin (operator-dashboard-spec ADR-V09, O24).
 *
 * Forwards four hook events to mock-wo's agent port so the operator dashboard
 * can show the skill trace and the agent's reasoning:
 *
 *   before_tool_call, after_tool_call — tool name, params, result error, duration
 *   llm_output                         — the assistant text of each model call
 *   agent_end                          — completes the running skill
 *
 * Checked against the OpenClaw 2026.5.27 plugin SDK. There is no skill hook
 * and no token hook: mock-wo derives skills from reads of `SKILL.md`, and
 * reasoning arrives per model call. `llm_output` is a conversation hook and
 * needs conversation access granted to this plugin in the sandbox config —
 * verify on the VM (O24).
 *
 * The plugin registers no tools and never changes a tool call: every handler
 * returns nothing, and forwarding never blocks the agent.
 */

import { definePluginEntry } from 'openclaw/plugin-sdk/plugin-entry'
import { createForwarder, DEFAULT_URL, type AgentEvent, type Forwarder } from './forwarder.js'

interface ToolEvent {
  toolName: string
  params: Record<string, unknown>
  runId?: string
  toolCallId?: string
  error?: string
  durationMs?: number
}

interface LlmOutputEvent {
  runId: string
  assistantTexts?: string[]
}

interface HookContext {
  runId?: string
}

interface HookApi {
  on: (hookName: string, handler: (event: never, ctx: never) => unknown) => void
  pluginConfig?: Record<string, unknown>
}

export function toolEvent(hook: 'before_tool_call' | 'after_tool_call', event: ToolEvent, ctx: HookContext): AgentEvent {
  return {
    hook,
    run_id: event.runId ?? ctx.runId,
    tool_call_id: event.toolCallId,
    tool_name: event.toolName,
    params: event.params,
    ...(hook === 'after_tool_call' && event.error ? { error: String(event.error) } : {}),
    ...(hook === 'after_tool_call' && typeof event.durationMs === 'number' ? { duration_ms: event.durationMs } : {}),
  }
}

export function llmEvent(event: LlmOutputEvent, ctx: HookContext): AgentEvent | null {
  const text = (event.assistantTexts ?? []).join('\n').trim()
  return text ? { hook: 'llm_output', run_id: event.runId ?? ctx.runId, text } : null
}

export function registerHooks(api: HookApi, forwarder: Forwarder): void {
  api.on('before_tool_call', ((event: ToolEvent, ctx: HookContext) => {
    forwarder.send(toolEvent('before_tool_call', event, ctx))
  }) as never)
  api.on('after_tool_call', ((event: ToolEvent, ctx: HookContext) => {
    forwarder.send(toolEvent('after_tool_call', event, ctx))
  }) as never)
  api.on('llm_output', ((event: LlmOutputEvent, ctx: HookContext) => {
    const mapped = llmEvent(event, ctx)
    if (mapped) forwarder.send(mapped)
  }) as never)
  api.on('agent_end', ((_event: unknown, ctx: HookContext) => {
    forwarder.send({ hook: 'agent_end', run_id: ctx.runId })
  }) as never)
}

export function resolveUrl(config: Record<string, unknown> | undefined, env: Record<string, string | undefined>): string {
  const configured = typeof config?.url === 'string' ? config.url : env.MOCK_WO_TELEMETRY_URL
  const url = configured || DEFAULT_URL
  // ADR-V08: telemetry goes to the agent port. Refuse the operator port so a
  // misconfiguration cannot quietly widen what the sandbox talks to.
  if (/:8091(\/|$)/.test(url)) throw new Error('mock-wo-telemetry: the operator port 8091 is never an agent destination')
  return url
}

export default definePluginEntry({
  id: 'mock-wo-telemetry',
  name: 'mock-wo telemetry',
  description: 'Forwards tool-call and model-output hook events to mock-wo (display-only).',
  register(api) {
    const forwarder = createForwarder({ url: resolveUrl(api.pluginConfig as Record<string, unknown> | undefined, process.env) })
    registerHooks(api as unknown as HookApi, forwarder)
  },
})
