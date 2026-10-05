import { Play, Radar } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Run } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { useRunNow, useRuns } from '@/lib/queries'

const RUN_STATUS_COLOR: Record<string, string> = {
  SUCCESS: 'oklch(0.86 0.19 142)',
  FAILED: 'oklch(0.66 0.17 25)',
  RUNNING: 'oklch(0.82 0.15 75)',
}

function StatusPill({ status }: { status: string }) {
  const color = RUN_STATUS_COLOR[status] ?? 'oklch(0.7 0.02 260)'
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{
        color,
        background: `color-mix(in oklch, ${color} 14%, transparent)`,
        border: `1px solid color-mix(in oklch, ${color} 35%, transparent)`,
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {status}
    </span>
  )
}

const COUNT_KEYS: [string, string][] = [
  ['raw_jobs', 'raw'],
  ['jobs_inserted', 'new'],
  ['matches_written', 'ranked'],
  ['llm_calls', 'llm'],
]

function Counts({ counts }: { counts: Record<string, unknown> }) {
  const chips = COUNT_KEYS.filter(([k]) => typeof counts[k] === 'number').map(([k, label]) => (
    <span
      key={k}
      className="tabnum rounded-md bg-muted px-1.5 py-0.5 text-[0.7rem] text-muted-foreground"
    >
      {String(counts[k])} {label}
    </span>
  ))
  const gate = counts.semantic_filter as
    | {
        dropped: number
        errors: number
        dropped_jobs: { title: string; company: string; fit: number }[]
      }
    | undefined
  if (gate) {
    const detail = gate.dropped_jobs.length
      ? gate.dropped_jobs.map((d) => `${d.title} @ ${d.company} (fit ${d.fit})`).join('\n')
      : 'Nothing dropped'
    chips.push(
      <span
        key="semantic_filter"
        title={gate.errors ? `${detail}\n${gate.errors} call(s) failed — kept` : detail}
        className="tabnum cursor-help rounded-md bg-muted px-1.5 py-0.5 text-[0.7rem] text-muted-foreground"
      >
        {gate.dropped} gated{gate.errors ? ` · ${gate.errors} err` : ''}
      </span>,
    )
  }
  if (chips.length === 0) return <span className="text-xs text-muted-foreground/60">—</span>
  return <div className="flex flex-wrap gap-1">{chips}</div>
}

export function RunsPage() {
  const runs = useRuns()
  const runNow = useRunNow()

  function trigger() {
    runNow.mutate(undefined, {
      onSuccess: (res) =>
        toast.success(`Run #${res.run_id} started`, {
          description: 'Collecting, ranking, and notifying in the background.',
        }),
      onError: (e) => toast.error('Could not start run', { description: (e as Error).message }),
    })
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
            <Radar className="h-3.5 w-3.5" /> Pipeline health
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">Runs</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Recent pipeline runs — collect, dedup, rank, notify.
          </p>
        </div>
        <Button onClick={trigger} disabled={runNow.isPending}>
          <Play className="mr-1.5 h-4 w-4" />
          {runNow.isPending ? 'Starting…' : 'Run now'}
        </Button>
      </header>

      {runs.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : runs.isError ? (
        <ErrorState message={(runs.error as Error).message} onRetry={() => runs.refetch()} />
      ) : (runs.data ?? []).length === 0 ? (
        <EmptyState
          title="No runs yet"
          description="Hit “Run now” to kick off the first pipeline run."
          icon={<Radar className="h-5 w-5" />}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card/40">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-16">Run</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Counts</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs.data as Run[]).map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="tabnum text-muted-foreground">#{run.id}</TableCell>
                  <TableCell className="whitespace-nowrap text-sm">
                    {formatDateTime(run.started_at)}
                  </TableCell>
                  <TableCell>
                    <StatusPill status={run.status} />
                  </TableCell>
                  <TableCell>
                    <Counts counts={run.source_counts} />
                  </TableCell>
                  <TableCell className="max-w-xs">
                    {run.error_text ? (
                      <span className="line-clamp-2 text-xs text-destructive">
                        {run.error_text}
                      </span>
                    ) : Object.keys(run.source_errors ?? {}).length > 0 ? (
                      // One source was skipped; the run itself still succeeded, so
                      // this is a warning about that source — not a failed run.
                      <div className="space-y-1">
                        {Object.entries(run.source_errors).map(([source, message]) => (
                          <p key={source} className="line-clamp-2 text-xs text-amber-500">
                            <span className="font-medium capitalize">{source} skipped:</span>{' '}
                            {message}
                          </p>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground/60">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
