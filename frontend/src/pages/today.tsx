import {
  ArrowRight,
  Bookmark,
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Inbox,
  MapPin,
  Minus,
  PartyPopper,
  Sun,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { toast } from 'sonner'

import { MatchDetailDialog } from '@/components/match-detail-dialog'
import { RunStatusPanel } from '@/components/run-status'
import { MatchScore } from '@/components/score-badge'
import { SourceTag } from '@/components/source-tag'
import { CardSkeletonGrid, EmptyState, ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import type { Application, QueueEntry, TriageAction } from '@/lib/api'
import {
  useApplications,
  useCurrentRun,
  useProfile,
  useQueue,
  useTriage,
  useUndoTriage,
} from '@/lib/queries'
import { FOLLOW_UP_DAYS, staleApplications } from '@/lib/format'
import { cn } from '@/lib/utils'

type Mode = 'idle' | 'dismissing' | 'confirming-apply'

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="ml-1.5 hidden rounded border border-current/30 px-1 font-mono text-[10px] leading-4 opacity-70 sm:inline">
      {children}
    </kbd>
  )
}

function FollowUps({ apps }: { apps: Application[] }) {
  if (apps.length === 0) return null
  return (
    <Link
      to="/applications"
      className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card/60 px-4 py-2.5 text-sm transition-colors hover:border-primary/40"
    >
      <span>
        <span className="font-medium">
          {apps.length} {apps.length === 1 ? 'application has' : 'applications have'}
        </span>{' '}
        <span className="text-muted-foreground">
          had no update for {FOLLOW_UP_DAYS}+ days —{' '}
          {apps
            .slice(0, 2)
            .map((a) => a.job?.company)
            .filter(Boolean)
            .join(', ')}
          {apps.length > 2 ? '…' : ''}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 text-primary">
        Follow up <ArrowRight className="h-3.5 w-3.5" />
      </span>
    </Link>
  )
}

function FocusCard({
  entry,
  mode,
  reasons,
  onAction,
  onDismissReason,
  onConfirmApply,
  onCancel,
  onOpen,
}: {
  entry: QueueEntry
  mode: Mode
  reasons: [string, string][]
  onAction: (a: TriageAction) => void
  onDismissReason: (reason: string) => void
  onConfirmApply: (applied: boolean) => void
  onCancel: () => void
  onOpen: () => void
}) {
  const m = entry.match
  const [showSimilar, setShowSimilar] = useState(false)

  return (
    <article className="reveal rounded-2xl border border-primary/30 bg-card p-6 shadow-[0_0_40px_-20px_var(--primary)]">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {m.is_new && (
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary">
                New
              </span>
            )}
            <SourceTag source={m.source} />
          </div>
          <h2
            className="mt-2 cursor-pointer font-display text-2xl leading-tight tracking-tight hover:text-primary"
            onClick={onOpen}
          >
            {m.title}
          </h2>
          <p className="mt-1 text-muted-foreground">
            {m.company}
            {m.location && (
              <span className="ml-3 inline-flex items-center gap-1 text-sm text-muted-foreground/80">
                <MapPin className="h-3.5 w-3.5" /> {m.location}
              </span>
            )}
          </p>
        </div>
        <MatchScore score={m.score} />
      </div>

      {m.reason && <p className="mt-4 text-sm leading-relaxed text-foreground/85">{m.reason}</p>}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <ul className="space-y-1.5">
          {m.pros.map((p, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" /> {p}
            </li>
          ))}
        </ul>
        <ul className="space-y-1.5">
          {m.cons.map((c, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
              <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground/40" /> {c}
            </li>
          ))}
        </ul>
      </div>

      {entry.similar.length > 0 && (
        <div className="mt-4 rounded-lg border border-border/70 bg-background/40">
          <button
            type="button"
            onClick={() => setShowSimilar((s) => !s)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground hover:text-foreground"
          >
            <Copy className="h-3.5 w-3.5" />
            {entry.similar.length} similar {entry.similar.length === 1 ? 'posting' : 'postings'} at{' '}
            {m.company} — your decision applies to all
            <ChevronDown
              className={cn(
                'ml-auto h-3.5 w-3.5 transition-transform',
                showSimilar && 'rotate-180',
              )}
            />
          </button>
          {showSimilar && (
            <ul className="space-y-1 border-t border-border/60 px-3 py-2">
              {entry.similar.map((s) => (
                <li
                  key={s.job_id}
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                >
                  <span className="tabnum w-8 text-right">{s.score}%</span>
                  <span className="truncate">{s.title}</span>
                  {s.location && <span className="truncate opacity-70">· {s.location}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-6 border-t border-border/60 pt-4">
        {mode === 'dismissing' ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Why not? This teaches the ranker. <Kbd>Esc</Kbd> to cancel.
            </p>
            <div className="flex flex-wrap gap-2">
              {reasons.map(([key, label], i) => (
                <Button key={key} variant="outline" size="sm" onClick={() => onDismissReason(key)}>
                  {label.charAt(0).toUpperCase() + label.slice(1)}
                  <Kbd>{i + 1}</Kbd>
                </Button>
              ))}
            </div>
          </div>
        ) : mode === 'confirming-apply' ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="mr-2 text-sm">Did you apply?</p>
            <Button size="sm" onClick={() => onConfirmApply(true)}>
              <Check className="mr-1.5 h-3.5 w-3.5" /> Yes, applied <Kbd>Y</Kbd>
            </Button>
            <Button variant="secondary" size="sm" onClick={() => onConfirmApply(false)}>
              <Bookmark className="mr-1.5 h-3.5 w-3.5" /> Not yet, save it <Kbd>N</Kbd>
            </Button>
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Cancel <Kbd>Esc</Kbd>
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => onAction('apply')}>
              <ExternalLink className="mr-1.5 h-4 w-4" /> Apply <Kbd>A</Kbd>
            </Button>
            <Button variant="secondary" onClick={() => onAction('save')}>
              <Bookmark className="mr-1.5 h-4 w-4" /> Save <Kbd>S</Kbd>
            </Button>
            <Button variant="outline" onClick={() => onAction('dismiss')}>
              <X className="mr-1.5 h-4 w-4" /> Not for me <Kbd>X</Kbd>
            </Button>
            <Button variant="ghost" onClick={onOpen} className="ml-auto">
              Full posting <Kbd>↵</Kbd>
            </Button>
          </div>
        )}
      </div>
    </article>
  )
}

function UpNext({ entries, onPick }: { entries: QueueEntry[]; onPick: (jobId: number) => void }) {
  if (entries.length === 0) return null
  return (
    <section>
      <h3 className="mb-2 text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground">
        Up next <span className="normal-case tracking-normal">· J / K to move</span>
      </h3>
      <div className="overflow-hidden rounded-xl border border-border bg-card/50">
        {entries.map((e) => (
          <button
            key={e.match.job_id}
            type="button"
            onClick={() => onPick(e.match.job_id)}
            className="flex w-full items-center gap-3 border-b border-border/50 px-4 py-2.5 text-left last:border-b-0 hover:bg-card"
          >
            <span className="tabnum w-10 shrink-0 text-sm text-muted-foreground">
              {e.match.score}%
            </span>
            <span className="min-w-0 flex-1 truncate text-sm">{e.match.title}</span>
            <span className="hidden max-w-[40%] truncate text-xs text-muted-foreground sm:inline">
              {e.match.company}
              {e.similar.length > 0 && ` · +${e.similar.length}`}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

export function TodayPage() {
  const profile = useProfile()
  const queue = useQueue()
  const applications = useApplications()
  const current = useCurrentRun()
  const triage = useTriage()
  const undo = useUndoTriage()

  // Optimistically hidden while the server catches up (and restored on undo/error).
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const [focusId, setFocusId] = useState<number | null>(null)
  // Keyed to a job, so a half-finished action never carries over to the next one.
  const [modeFor, setModeFor] = useState<{ jobId: number; mode: Mode } | null>(null)
  const [openJobId, setOpenJobId] = useState<number | null>(null)
  const [lastIds, setLastIds] = useState<number[] | null>(null)

  const items = useMemo(
    () => (queue.data?.items ?? []).filter((e) => !hidden.has(e.match.job_id)),
    [queue.data, hidden],
  )
  const focusIndex = Math.max(
    0,
    items.findIndex((e) => e.match.job_id === focusId),
  )
  const focused = items[focusIndex] as QueueEntry | undefined
  const focusedId = focused?.match.job_id ?? null
  const mode: Mode = modeFor && modeFor.jobId === focused?.match.job_id ? modeFor.mode : 'idle'
  const setMode = useCallback(
    (next: Mode) => setModeFor(focusedId != null ? { jobId: focusedId, mode: next } : null),
    [focusedId],
  )
  const reasons = useMemo(() => Object.entries(queue.data?.dismiss_reasons ?? {}), [queue.data])

  const restore = useCallback((ids: number[]) => {
    setHidden((h) => {
      const next = new Set(h)
      ids.forEach((id) => next.delete(id))
      return next
    })
  }, [])

  const undoLast = useCallback(
    (ids: number[] | null = lastIds) => {
      if (!ids) return
      undo.mutate(ids, {
        onSuccess: () => {
          restore(ids)
          setFocusId(ids[0])
          toast('Undone', { description: 'Back in your queue.' })
        },
      })
      setLastIds(null)
    },
    [lastIds, undo, restore],
  )

  const decide = useCallback(
    (entry: QueueEntry, action: TriageAction, reason?: string) => {
      const ids = [entry.match.job_id, ...entry.similar.map((s) => s.job_id)]
      const next = items[focusIndex + 1] ?? items[focusIndex - 1]
      setHidden((h) => new Set([...h, ...ids]))
      setFocusId(next ? next.match.job_id : null)
      setMode('idle')
      setLastIds(ids)
      triage.mutate(
        {
          job_id: entry.match.job_id,
          action,
          reason,
          similar_ids: entry.similar.map((s) => s.job_id),
        },
        {
          onError: (e) => {
            restore(ids)
            toast.error('Could not save that', { description: (e as Error).message })
          },
        },
      )
      const verb = action === 'apply' ? 'Applied' : action === 'save' ? 'Saved' : 'Dismissed'
      toast(`${verb}: ${entry.match.title}`, {
        description: entry.match.company,
        action: { label: 'Undo (Z)', onClick: () => undoLast(ids) },
      })
    },
    [items, focusIndex, triage, restore, undoLast, setMode],
  )

  const onAction = useCallback(
    (action: TriageAction) => {
      if (!focused) return
      if (action === 'dismiss') return setMode('dismissing')
      if (action === 'apply' && focused.match.url) {
        window.open(focused.match.url, '_blank', 'noopener')
        return setMode('confirming-apply')
      }
      decide(focused, action)
    },
    [focused, decide, setMode],
  )

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (openJobId != null || isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (key === 'z') return undoLast()
      if (!focused) return

      if (mode === 'dismissing') {
        const n = Number(key)
        if (n >= 1 && n <= reasons.length) decide(focused, 'dismiss', reasons[n - 1][0])
        else if (key === 'escape') setMode('idle')
        return
      }
      if (mode === 'confirming-apply') {
        if (key === 'y') decide(focused, 'apply')
        else if (key === 'n') decide(focused, 'save')
        else if (key === 'escape') setMode('idle')
        return
      }
      const move = (delta: number) => {
        const target = items[focusIndex + delta]
        if (target) setFocusId(target.match.job_id)
      }
      if (key === 'a') onAction('apply')
      else if (key === 's') onAction('save')
      else if (key === 'x') onAction('dismiss')
      else if (key === 'j' || key === 'arrowdown') move(1)
      else if (key === 'k' || key === 'arrowup') move(-1)
      else if (key === 'enter') setOpenJobId(focused.match.job_id)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [focused, mode, reasons, items, focusIndex, openJobId, decide, onAction, undoLast, setMode])

  if (profile.isSuccess && !profile.data) return <Navigate to="/welcome" replace />

  const stale = staleApplications(applications.data)
  const q = queue.data
  const upNext = items.filter((_, i) => i !== focusIndex).slice(0, 12)

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
            <Sun className="h-3.5 w-3.5" /> Today
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">
            {items.length > 0
              ? `${items.length} ${items.length === 1 ? 'role' : 'roles'} to review`
              : 'Your queue'}
          </h1>
          {q && q.total_matches > 0 && (
            <p className="mt-1 text-sm text-muted-foreground">
              {q.triaged > 0 && `${q.triaged} already handled · `}
              {q.excluded > 0 && `${q.excluded} hidden by your exclude list · `}
              best fit first, near-duplicates grouped
            </p>
          )}
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/matches">
            All matches <ArrowRight className="ml-1 h-3.5 w-3.5" />
          </Link>
        </Button>
      </header>

      <RunStatusPanel />
      <FollowUps apps={stale} />

      {queue.isLoading ? (
        <CardSkeletonGrid count={2} />
      ) : queue.isError ? (
        <ErrorState message={(queue.error as Error).message} onRetry={() => queue.refetch()} />
      ) : !q || q.total_matches === 0 ? (
        <EmptyState
          title={current.data?.active ? 'Finding jobs…' : 'No jobs scored yet'}
          description={
            current.data?.active
              ? 'Your queue fills in when the run finishes.'
              : 'Press “Find new jobs” to scrape and score today’s postings against your résumé.'
          }
          icon={<Inbox className="h-5 w-5" />}
        />
      ) : !focused ? (
        <EmptyState
          title="All caught up"
          description={`You’ve been through every role from the latest run. New ones arrive with the next run.`}
          icon={<PartyPopper className="h-5 w-5" />}
        />
      ) : (
        <>
          <FocusCard
            entry={focused}
            mode={mode}
            reasons={reasons}
            onAction={onAction}
            onDismissReason={(r) => decide(focused, 'dismiss', r)}
            onConfirmApply={(applied) => decide(focused, applied ? 'apply' : 'save')}
            onCancel={() => setMode('idle')}
            onOpen={() => setOpenJobId(focused.match.job_id)}
          />
          <UpNext entries={upNext} onPick={setFocusId} />
          {lastIds && (
            <p className="text-center text-xs text-muted-foreground">
              Press <kbd className="font-mono">Z</kbd> to undo the last decision
            </p>
          )}
        </>
      )}

      <MatchDetailDialog
        jobId={openJobId}
        open={openJobId != null}
        onOpenChange={(o) => !o && setOpenJobId(null)}
        tracked={false}
        onTrack={() => {
          if (focused && openJobId === focused.match.job_id) {
            setOpenJobId(null)
            decide(focused, 'save')
          }
        }}
      />
    </div>
  )
}
