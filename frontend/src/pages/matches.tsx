import { Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { MatchCard } from '@/components/match-card'
import { MatchDetailDialog } from '@/components/match-detail-dialog'
import { CardSkeletonGrid, EmptyState, ErrorState } from '@/components/states'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useApplications, useMatches, useTrackApplication } from '@/lib/queries'

const SCORE_FILTERS = [
  { value: '0', label: 'All scores' },
  { value: '70', label: '70+' },
  { value: '80', label: '80+' },
  { value: '90', label: '90+' },
]

export function MatchesPage() {
  const [minScore, setMinScore] = useState(0)
  const [openJobId, setOpenJobId] = useState<number | null>(null)

  const matches = useMatches(minScore || undefined)
  const applications = useApplications()
  const track = useTrackApplication()

  const trackedIds = useMemo(
    () => new Set((applications.data ?? []).map((a) => a.job_id)),
    [applications.data],
  )

  function handleTrack(jobId: number, title: string) {
    track.mutate(
      { job_id: jobId, status: 'SAVED' },
      {
        onSuccess: () => toast.success('Tracked', { description: `${title} → Pipeline (Saved)` }),
        onError: (e) => toast.error('Could not track', { description: (e as Error).message }),
      },
    )
  }

  const data = matches.data ?? []

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
            <Sparkles className="h-3.5 w-3.5" /> Today&rsquo;s ranking
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">Matches</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {matches.isSuccess
              ? `${data.length} ${data.length === 1 ? 'role' : 'roles'} from the latest run, scored against your resume.`
              : 'Ranked roles from the latest pipeline run.'}
          </p>
        </div>
        <Select value={String(minScore)} onValueChange={(v) => setMinScore(Number(v))}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SCORE_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </header>

      {matches.isLoading ? (
        <CardSkeletonGrid />
      ) : matches.isError ? (
        <ErrorState message={(matches.error as Error).message} onRetry={() => matches.refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          title="No matches yet"
          description="Run the pipeline from the Runs tab to collect and rank today's jobs."
          icon={<Sparkles className="h-5 w-5" />}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((m, i) => (
            <div key={m.job_id} className="reveal" style={{ animationDelay: `${i * 40}ms` }}>
              <MatchCard
                match={m}
                tracked={trackedIds.has(m.job_id)}
                onOpen={() => setOpenJobId(m.job_id)}
                onTrack={() => handleTrack(m.job_id, m.title)}
              />
            </div>
          ))}
        </div>
      )}

      <MatchDetailDialog
        jobId={openJobId}
        open={openJobId != null}
        onOpenChange={(o) => !o && setOpenJobId(null)}
        tracked={openJobId != null && trackedIds.has(openJobId)}
        onTrack={() => {
          const m = data.find((x) => x.job_id === openJobId)
          if (m) handleTrack(m.job_id, m.title)
        }}
      />
    </div>
  )
}
