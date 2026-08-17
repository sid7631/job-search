import { Check, ExternalLink, Minus, Plus } from 'lucide-react'

import { MatchScore } from '@/components/score-badge'
import { SourceTag } from '@/components/source-tag'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { useMatchDetail } from '@/lib/queries'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-2 text-[0.7rem] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </h4>
      {children}
    </section>
  )
}

export function MatchDetailDialog({
  jobId,
  open,
  onOpenChange,
  tracked,
  onTrack,
}: {
  jobId: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
  tracked: boolean
  onTrack: () => void
}) {
  const { data, isLoading } = useMatchDetail(open ? jobId : null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        {isLoading || !data ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : (
          <>
            <DialogHeader className="space-y-0 border-b border-border p-6 pb-5 text-left">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <DialogTitle className="font-display text-xl leading-tight">
                    {data.title}
                  </DialogTitle>
                  <DialogDescription className="mt-1 text-sm">
                    {data.company}
                    {data.location ? ` · ${data.location}` : ''}
                  </DialogDescription>
                  <div className="mt-2">
                    <SourceTag source={data.source} />
                  </div>
                  {data.skills.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {data.skills.slice(0, 12).map((s) => (
                        <span
                          key={s}
                          className="rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[0.7rem] text-muted-foreground"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <MatchScore score={data.score ?? 0} />
              </div>
            </DialogHeader>

            <ScrollArea className="max-h-[44vh]">
              <div className="space-y-6 p-6">
                {data.reason && (
                  <Section title="Why this score">
                    <p className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm leading-relaxed text-foreground/90">
                      {data.reason}
                    </p>
                  </Section>
                )}

                <div className="grid gap-6 sm:grid-cols-2">
                  {data.pros.length > 0 && (
                    <Section title="Pros">
                      <ul className="space-y-1.5">
                        {data.pros.map((p, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                            <span className="text-foreground/90">{p}</span>
                          </li>
                        ))}
                      </ul>
                    </Section>
                  )}
                  {data.cons.length > 0 && (
                    <Section title="Cons">
                      <ul className="space-y-1.5">
                        {data.cons.map((c, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground/40" />
                            <span className="text-foreground/90">{c}</span>
                          </li>
                        ))}
                      </ul>
                    </Section>
                  )}
                </div>

                {data.description && (
                  <Section
                    title={
                      data.description_enriched ? 'Full description' : 'Description (from card)'
                    }
                  >
                    {!data.description_enriched && (
                      <p className="mb-2 text-xs text-muted-foreground/70">
                        The full posting hasn&rsquo;t been fetched for this job, so the AI scored it
                        on the search-result summary alone.
                      </p>
                    )}
                    <p className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                      {data.description}
                    </p>
                  </Section>
                )}
              </div>
            </ScrollArea>

            <div className="flex items-center gap-2 border-t border-border p-4">
              <Button
                variant="secondary"
                className="flex-1"
                disabled={!data.url}
                onClick={() => data.url && window.open(data.url, '_blank', 'noopener')}
              >
                <ExternalLink className="mr-1.5 h-4 w-4" /> Apply
              </Button>
              <Button
                className="flex-1"
                variant={tracked ? 'outline' : 'default'}
                onClick={onTrack}
              >
                {tracked ? (
                  <>
                    <Check className="mr-1.5 h-4 w-4" /> Tracked
                  </>
                ) : (
                  <>
                    <Plus className="mr-1.5 h-4 w-4" /> Track
                  </>
                )}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
