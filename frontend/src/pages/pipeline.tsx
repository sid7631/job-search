import { KanbanSquare } from 'lucide-react'
import { useMemo } from 'react'

import { ApplicationCard } from '@/components/application-card'
import { EmptyState, ErrorState } from '@/components/states'
import { Skeleton } from '@/components/ui/skeleton'
import type { Application, ApplicationStatus } from '@/lib/api'
import { STATUS_ORDER, statusMeta } from '@/lib/format'
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

  const total = apps.data?.length ?? 0

  return (
    <div className="space-y-6">
      <header>
        <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
          <KanbanSquare className="h-3.5 w-3.5" /> Application tracker
        </p>
        <h1 className="mt-1 font-display text-3xl tracking-tight">Pipeline</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total} tracked {total === 1 ? 'application' : 'applications'} across the funnel.
        </p>
      </header>

      {apps.isLoading ? (
        <div className="flex gap-4 overflow-x-auto pb-2">
          {STATUS_ORDER.map((s) => (
            <div key={s} className="w-72 shrink-0 space-y-3">
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
          description="Track a match from the Matches tab to start building your pipeline."
          icon={<KanbanSquare className="h-5 w-5" />}
        />
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {STATUS_ORDER.map((status) => {
            const items = byStatus[status]
            return (
              <section key={status} className="flex w-72 shrink-0 flex-col">
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
                    items.map((a) => <ApplicationCard key={a.id} app={a} />)
                  )}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
