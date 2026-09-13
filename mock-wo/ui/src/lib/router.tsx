import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from 'react'

// A deliberately small history router: the dashboard has a handful of
// screens and no nested layouts, so a dependency would add nothing.

const listeners = new Set<() => void>()

export function navigate(path: string, { replace = false } = {}) {
  if (replace) window.history.replaceState(null, '', path)
  else window.history.pushState(null, '', path)
  listeners.forEach((listener) => listener())
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    listeners.add(update)
    window.addEventListener('popstate', update)
    return () => {
      listeners.delete(update)
      window.removeEventListener('popstate', update)
    }
  }, [])
  return path
}

export type Route =
  | { name: 'packs' }
  | { name: 'fleet' }
  | { name: 'incident'; id: string }
  | { name: 'audit' }
  | { name: 'work-orders' }
  | { name: 'work-order'; id: string }
  | { name: 'notes' }
  | { name: 'notifications' }
  | { name: 'not-found' }

export function matchRoute(path: string): Route {
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  if (parts.length === 0) return { name: 'fleet' }
  const [head, id, ...rest] = parts
  if (rest.length) return { name: 'not-found' }
  switch (head) {
    case 'packs':
      return id ? { name: 'not-found' } : { name: 'packs' }
    case 'fleet':
      return id ? { name: 'not-found' } : { name: 'fleet' }
    case 'incidents':
      return id ? { name: 'incident', id } : { name: 'not-found' }
    case 'audit':
      return id ? { name: 'not-found' } : { name: 'audit' }
    case 'work-orders':
      return id ? { name: 'work-order', id } : { name: 'work-orders' }
    case 'notes':
      return id ? { name: 'not-found' } : { name: 'notes' }
    case 'notifications':
      return id ? { name: 'not-found' } : { name: 'notifications' }
    default:
      return { name: 'not-found' }
  }
}

export function Link({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
    event.preventDefault()
    navigate(href)
  }
  return <a href={href} onClick={handle} {...rest} />
}
