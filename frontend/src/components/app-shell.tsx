import {
  BellRing,
  KanbanSquare,
  Loader2,
  Play,
  SlidersHorizontal,
  Sun,
  UserRound,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useCurrentRun } from '@/lib/queries'
import { useStartRun } from '@/lib/use-start-run'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Today', icon: Sun, end: true },
  { to: '/applications', label: 'Applications', icon: KanbanSquare, end: false },
  { to: '/profile', label: 'Profile', icon: UserRound, end: false },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontal, end: false },
]

/** Starts a run, or — while one is going — shows it is running and links to Today. */
function RunButton() {
  const { start, pending } = useStartRun()
  const current = useCurrentRun()
  const active = current.data?.active

  if (active) {
    const attention = Boolean(active.progress.attention)
    return (
      <Button size="sm" variant="outline" asChild>
        <Link to="/" className={cn(attention && 'border-amber-500/60 text-amber-300')}>
          {attention ? (
            <BellRing className="h-4 w-4 animate-pulse" />
          ) : (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          <span className="ml-1.5 hidden sm:inline">{attention ? 'Needs you' : 'Running'}</span>
        </Link>
      </Button>
    )
  }
  return (
    <Button size="sm" onClick={start} disabled={pending}>
      {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
      <span className="ml-1.5 hidden sm:inline">Run</span>
    </Button>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5">
          <div className="flex items-baseline gap-2.5">
            <span
              className="grid h-7 w-7 place-items-center rounded-md text-sm font-bold text-primary-foreground"
              style={{ background: 'var(--primary)' }}
            >
              ▲
            </span>
            <span className="font-display text-lg leading-none tracking-tight">
              Job<span className="text-primary">Hunter</span>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <nav className="flex items-center gap-1 rounded-full border border-border bg-card/60 p-1">
              {NAV.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline">{label}</span>
                </NavLink>
              ))}
            </nav>
            <RunButton />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
    </div>
  )
}
