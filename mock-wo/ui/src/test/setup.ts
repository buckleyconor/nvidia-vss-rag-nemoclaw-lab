import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom has no media playback or layout; the tests assert what the app asks of them.
Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: vi.fn() })
Element.prototype.scrollIntoView = vi.fn()
HTMLElement.prototype.scrollTo = vi.fn() as unknown as typeof HTMLElement.prototype.scrollTo
if (!globalThis.CSS) (globalThis as { CSS?: unknown }).CSS = {}
if (!CSS.escape) CSS.escape = (value: string) => value.replace(/["\\]/g, '\\$&')
