import { matchRoute, usePath, Link } from './lib/router'
import { StreamProvider, useStream } from './lib/stream'
import { FleetView } from './views/FleetView'
import { IncidentWorkspace } from './views/IncidentWorkspace'
import { AuditView, NotesView, NotificationsView, PackSelector, WorkOrderDetail, WorkOrdersView } from './views/Records'

const NAV = [
  { href: '/fleet', label: 'Fleet', match: ['fleet', 'incident'] },
  { href: '/audit', label: 'Audit trail', match: ['audit'] },
  { href: '/work-orders', label: 'Work orders', match: ['work-orders', 'work-order'] },
  { href: '/notes', label: 'Notes', match: ['notes'] },
  { href: '/notifications', label: 'Notifications', match: ['notifications'] },
  { href: '/packs', label: 'Verticals', match: ['packs'] },
]

function Header({ route }: { route: string }) {
  const { connected } = useStream()
  return (
    <header className="app-header">
      <div className="lockup" aria-label="Dell Technologies and NVIDIA">
        <span className="brand-dell">DELL</span>
        <span className="brand-sep" aria-hidden>
          ×
        </span>
        <span className="brand-nvidia">NVIDIA</span>
        <span className="app-name">Operator Dashboard</span>
      </div>
      <nav>
        {NAV.map((item) => (
          <Link key={item.href} href={item.href} className={item.match.includes(route) ? 'active' : undefined}>
            {item.label}
          </Link>
        ))}
      </nav>
      <span className={`live ${connected ? 'live-on' : ''}`}>{connected ? 'Live' : 'Reconnecting'}</span>
    </header>
  )
}

function Screen() {
  const route = matchRoute(usePath())
  let body
  switch (route.name) {
    case 'packs':
      body = <PackSelector />
      break
    case 'fleet':
      body = <FleetView />
      break
    case 'incident':
      body = <IncidentWorkspace key={route.id} incidentId={route.id} />
      break
    case 'audit':
      body = <AuditView />
      break
    case 'work-orders':
      body = <WorkOrdersView />
      break
    case 'work-order':
      body = <WorkOrderDetail id={route.id} />
      break
    case 'notes':
      body = <NotesView />
      break
    case 'notifications':
      body = <NotificationsView />
      break
    default:
      body = (
        <div className="page">
          <p>This page does not exist.</p>
          <Link href="/fleet">Go to the fleet</Link>
        </div>
      )
  }
  return (
    <>
      <Header route={route.name} />
      <main>{body}</main>
      <footer className="app-footer">Technical demonstration, not a product. Mock CMMS — no real work orders are created.</footer>
    </>
  )
}

export function App() {
  return (
    <StreamProvider>
      <Screen />
    </StreamProvider>
  )
}
