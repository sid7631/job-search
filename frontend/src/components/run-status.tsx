import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  History,
  Loader2,
  Play,
  XCircle,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import type { Run } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import { useCurrentRun } from '@/lib/queries'
import { useStartRun } from '@/lib/use-start-run'
import { cn } from '@/lib/utils'

// Mirrors the pipeline's `progress(stage, ...)` calls, in order.
const STAGES: { key: string; label: string }[] = [
  { key: 'collect', label: 'Collect' },
  { key: 'dedupe', label: 'Dedupe' },
  { key: 'shortlist', label: 'Shortlist' },
  { key: 'enrich', label: 'Read postings' },
  { key: 'gate', label: 'Fit check' },
  { key: 'rank', label: 'Score' },
]

function Stepper({ stage }: { stage?: string }) {
  const current = STAGES.findIndex((s) => s.key === stage)
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs">
      {STAGES.map((s, i) => {
        const done = current > i
        const active = current === i
        return (
          <li key={s.key} className="flex items-center gap-1">
            <span
              className={cn(
                'flex items-center gap-1.5 rounded-full px-2 py-0.5',
                active && 'bg-primary/15 text-primary',
                done && 'text-foreground/70',
                !active && !done && 'text-muted-foreground/50',
              )}
            >
              {active ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : done ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
              )}
              {s.label}
            </span>
            {i < STAGES.length - 1 && <span className="text-muted-foreground/30">›</span>}
          </li>
        )
      })}
    </ol>
  )
}

function lastRunSummary(run: Run): string {
  const c = run.source_counts as Record<string, unknown>
  const parts: string[] = []
  if (typeof c.matches_written === 'number') parts.push(`${c.matches_written} scored`)
  if (typeof c.jobs_inserted === 'number') parts.push(`${c.jobs_inserted} new`)
  return parts.join(' · ')
}

/** Live progress while a run is going; otherwise the last run and a Run button. */
export function RunStatusPanel() {
  const current = useCurrentRun()
  const { start, pending } = useStartRun()
  const active = current.data?.active
  const last = current.data?.last

  if (active) {
    const attention = active.progress.attention
    return (
      <section className="space-y-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="font-medium">Run #{active.id} in progress</span>
            <span className="text-muted-foreground">· {active.progress.detail ?? 'Starting…'}</span>
          </p>
          <span className="text-xs text-muted-foreground">
            started {formatRelative(active.started_at)}
          </span>
        </div>
        <Stepper stage={active.progress.stage} />
        {attention && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
          >
            <BellRing className="mt-0.5 h-4 w-4 shrink-0 animate-pulse" />
            <span>
              <span className="font-medium">Needs you:</span> {attention}
            </span>
          </div>
        )}
      </section>
    )
  }

  const warnings = last ? Object.entries(last.source_errors ?? {}) : []
  const failed = last?.status === 'FAILED'

  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card/60 px-4 py-3">
      <div className="min-w-0 space-y-1 text-sm">
        {last ? (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {failed ? (
              <XCircle className="h-4 w-4 text-destructive" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-primary" />
            )}
            <span>
              Last run {formatRelative(last.finished_at ?? last.started_at)}
              {failed ? ' failed' : ''}
            </span>
            {!failed && <span className="text-muted-foreground">{lastRunSummary(last)}</span>}
          </p>
        ) : (
          <p className="text-muted-foreground">No runs yet.</p>
        )}
        {failed && last?.error_text && (
          <p className="line-clamp-2 text-xs text-destructive">{last.error_text}</p>
        )}
        {warnings.map(([source, msg]) => (
          <p key={source} className="flex items-start gap-1.5 text-xs text-amber-300/90">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            <span className="line-clamp-1">
              <span className="capitalize">{source}</span> skipped: {msg}
            </span>
          </p>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/runs">
            <History className="mr-1.5 h-3.5 w-3.5" /> History
          </Link>
        </Button>
        <Button size="sm" onClick={start} disabled={pending}>
          {pending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="mr-1.5 h-3.5 w-3.5" />
          )}
          Find new jobs
        </Button>
      </div>
    </section>
  )
}
