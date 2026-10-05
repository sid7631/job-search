import { ChevronDown, KanbanSquare } from 'lucide-react'
import { useMemo, useState } from 'react'

import { ApplicationCard } from '@/components/application-card'
import { EmptyState, ErrorState } from '@/components/states'
import { Skeleton } from '@/components/ui/skeleton'
import type { Application, ApplicationStatus } from '@/lib/api'
import { FOLLOW_UP_DAYS, STATUS_ORDER, staleApplications, statusMeta } from '@/lib/format'

// In-flight stages get board columns; finished ones fold into a list below, so a
// growing pile of dismissed jobs never pushes the live ones off screen.
const ACTIVE = STATUS_ORDER.filter((s) => s !== 'REJECTED' && s !== 'DROPPED')
import { useApplications } from '@/lib/queries'

export function PipelinePage() {
  const apps = useApplications()

  const byStatus = useMemo(() => {
    const groups: Record<ApplicationStatus, Application[]> = {
      SAVED: [],
      APPLIED: [],
      INTERVIEWING: [],
      OFFER: [],
      REJECTED: [],
      DROPPED: [],
    }
    for (const a of apps.data ?? []) groups[a.status]?.push(a)
    return groups
  }, [apps.data])

  const [showClosed, setShowClosed] = useState(false)
  const total = apps.data?.length ?? 0
  const closed = [...byStatus.REJECTED, ...byStatus.DROPPED]
  const stale = useMemo(() => new Set(staleApplications(apps.data).map((a) => a.id)), [apps.data])

  return (
    <div className="space-y-6">
      <header>
        <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
          <KanbanSquare className="h-3.5 w-3.5" /> Application tracker
        </p>
        <h1 className="mt-1 font-display text-3xl tracking-tight">Applications</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total - closed.length} in progress
          {stale.size > 0 && (
            <>
              {' · '}
              <span className="text-amber-300">
                {stale.size} waiting {FOLLOW_UP_DAYS}+ days for a reply
              </span>
            </>
          )}
        </p>
      </header>

      {apps.isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ACTIVE.map((s) => (
            <div key={s} className="space-y-3">
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ))}
        </div>
      ) : apps.isError ? (
        <ErrorState message={(apps.error as Error).message} onRetry={() => apps.refetch()} />
      ) : total === 0 ? (
        <EmptyState
          title="Nothing tracked yet"
          description="Apply to or save a role from Today and it shows up here."
          icon={<KanbanSquare className="h-5 w-5" />}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {ACTIVE.map((status) => {
              const items = byStatus[status]
              return (
                <section key={status} className="flex min-w-0 flex-col">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: statusMeta[status].color }}
                      />
                      <h2 className="text-sm font-medium">{statusMeta[status].label}</h2>
                    </div>
                    <span className="tabnum rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {items.length}
                    </span>
                  </div>
                  <div className="flex-1 space-y-3 rounded-xl border border-dashed border-border/60 bg-card/20 p-2">
                    {items.length === 0 ? (
                      <p className="py-6 text-center text-xs text-muted-foreground/60">Empty</p>
                    ) : (
                      items.map((a) => (
                        <ApplicationCard key={a.id} app={a} needsFollowUp={stale.has(a.id)} />
                      ))
                    )}
                  </div>
                </section>
              )
            })}
          </div>

          {closed.length > 0 && (
            <section className="rounded-xl border border-border bg-card/40">
              <button
                type="button"
                onClick={() => setShowClosed((v) => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm"
              >
                <span>
                  Closed{' '}
                  <span className="text-muted-foreground">
                    · {closed.length} rejected or passed on
                  </span>
                </span>
                <ChevronDown
                  className={`h-4 w-4 text-muted-foreground transition-transform ${showClosed ? 'rotate-180' : ''}`}
                />
              </button>
              {showClosed && (
                <div className="grid gap-3 border-t border-border/60 p-3 sm:grid-cols-2 lg:grid-cols-3">
                  {closed.map((a) => (
                    <ApplicationCard key={a.id} app={a} />
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
