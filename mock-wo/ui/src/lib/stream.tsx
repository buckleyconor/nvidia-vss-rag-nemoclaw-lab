import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { EVENT_TYPES, type StreamEvent } from './types'

// One multiplexed SSE connection for the whole app (§6.3). Consumers
// subscribe to events; on every (re)connect they are told to backfill, so a
// dropped connection or navigation never leaves a stream silently incomplete.

type Listener = (event: StreamEvent) => void
type ReconnectListener = () => void

interface StreamApi {
  subscribe: (listener: Listener) => () => void
  onReconnect: (listener: ReconnectListener) => () => void
  connected: boolean
}

const StreamContext = createContext<StreamApi | null>(null)

export function StreamProvider({ children, url = '/api/v1/stream' }: { children: ReactNode; url?: string }) {
  const listeners = useRef(new Set<Listener>())
  const reconnects = useRef(new Set<ReconnectListener>())
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const source = new EventSource(url)
    const handle = (message: MessageEvent) => {
      try {
        const event = JSON.parse(message.data) as StreamEvent
        listeners.current.forEach((listener) => listener(event))
      } catch {
        // A malformed frame is dropped; seq gaps trigger a backfill.
      }
    }
    EVENT_TYPES.forEach((type) => source.addEventListener(type, handle as EventListener))
    source.onopen = () => {
      setConnected(true)
      reconnects.current.forEach((listener) => listener())
    }
    source.onerror = () => setConnected(false)
    return () => {
      EVENT_TYPES.forEach((type) => source.removeEventListener(type, handle as EventListener))
      source.close()
    }
  }, [url])

  const value: StreamApi = {
    connected,
    subscribe: (listener) => {
      listeners.current.add(listener)
      return () => listeners.current.delete(listener)
    },
    onReconnect: (listener) => {
      reconnects.current.add(listener)
      return () => reconnects.current.delete(listener)
    },
  }
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>
}

export function useStream(): StreamApi {
  const api = useContext(StreamContext)
  if (!api) throw new Error('useStream outside StreamProvider')
  return api
}

export function useStreamEvents(listener: Listener, deps: unknown[] = []) {
  const { subscribe } = useStream()
  const latest = useRef(listener)
  latest.current = listener
  useEffect(() => subscribe((event) => latest.current(event)), [subscribe, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
}
