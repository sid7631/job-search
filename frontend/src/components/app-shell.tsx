import {
  LayoutGrid,
  Loader2,
  Play,
  Radar,
  KanbanSquare,
  SlidersHorizontal,
  UserRound,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useRunNow } from '@/lib/queries'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Matches', icon: LayoutGrid, end: true },
  { to: '/pipeline', label: 'Pipeline', icon: KanbanSquare, end: false },
  { to: '/runs', label: 'Runs', icon: Radar, end: false },
  { to: '/profile', label: 'Profile', icon: UserRound, end: false },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontal, end: false },
]

function RunButton() {
  const runNow = useRunNow()
  return (
    <Button
      size="sm"
      onClick={() =>
        runNow.mutate(undefined, {
          onSuccess: (res) =>
            toast.success(`Run #${res.run_id} started`, {
              description: 'Scraping headed — a browser window will open.',
            }),
          onError: (e) => toast.error('Could not start run', { description: (e as Error).message }),
        })
      }
      disabled={runNow.isPending}
    >
      {runNow.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Play className="h-4 w-4" />
      )}
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
