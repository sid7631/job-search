import { Check, ExternalLink, MapPin, Minus, Plus } from 'lucide-react'

import { MatchScore } from '@/components/score-badge'
import { SourceTag } from '@/components/source-tag'
import { Button } from '@/components/ui/button'
import type { Match } from '@/lib/api'
import { cn } from '@/lib/utils'

function NewTag() {
  return (
    <span className="shrink-0 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary">
      New
    </span>
  )
}

function ProConList({ items, kind }: { items: string[]; kind: 'pro' | 'con' }) {
  if (items.length === 0) return null
  const Icon = kind === 'pro' ? Check : Minus
  return (
    <ul className="space-y-1">
      {items.slice(0, 2).map((item, i) => (
        <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Icon
            className={cn(
              'mt-0.5 h-3 w-3 shrink-0',
              kind === 'pro' ? 'text-primary' : 'text-foreground/40',
            )}
          />
          <span className="line-clamp-1">{item}</span>
        </li>
      ))}
    </ul>
  )
}

function ApplyButton({ match, className }: { match: Match; className?: string }) {
  return (
    <Button
      variant="secondary"
      size="sm"
      className={className}
      disabled={!match.url}
      title={match.url ? 'Open the posting in a new tab' : 'No link available for this posting'}
      onClick={() => match.url && window.open(match.url, '_blank', 'noopener')}
    >
      <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Apply
    </Button>
  )
}

function TrackButton({
  tracked,
  onTrack,
  className,
}: {
  tracked: boolean
  onTrack: () => void
  className?: string
}) {
  return (
    <Button
      size="sm"
      variant={tracked ? 'outline' : 'default'}
      className={className}
      onClick={onTrack}
    >
      {tracked ? (
        <>
          <Check className="mr-1.5 h-3.5 w-3.5" /> Tracked
        </>
      ) : (
        <>
          <Plus className="mr-1.5 h-3.5 w-3.5" /> Track
        </>
      )}
    </Button>
  )
}

export function MatchCard({
  match,
  tracked,
  onOpen,
  onTrack,
}: {
  match: Match
  tracked: boolean
  onOpen: () => void
  onTrack: () => void
}) {
  return (
    <article
      onClick={onOpen}
      className="group flex cursor-pointer flex-col rounded-xl border border-border bg-card/70 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h3 className="truncate font-display text-base leading-snug text-foreground group-hover:text-primary">
              {match.title}
            </h3>
            {match.is_new && <NewTag />}
          </div>
          <p className="mt-0.5 truncate text-sm text-muted-foreground">{match.company}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <SourceTag source={match.source} />
            {match.location && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground/80">
                <MapPin className="h-3 w-3" /> {match.location}
              </span>
            )}
          </div>
        </div>
        {/* Score sits on the right, labelled: a bare number beside a job title
            reads as salary or applicant count just as easily as a match. */}
        <MatchScore score={match.score} />
      </div>

      <div className="mt-4 grid flex-1 gap-2">
        <ProConList items={match.pros} kind="pro" />
        <ProConList items={match.cons} kind="con" />
      </div>

      <div className="mt-4 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <ApplyButton match={match} className="flex-1" />
        <TrackButton tracked={tracked} onTrack={onTrack} className="flex-1" />
      </div>
    </article>
  )
}

/** One dense row for the list view — same data, far more of it on screen. */
export function MatchRow({
  match,
  tracked,
  onOpen,
  onTrack,
}: {
  match: Match
  tracked: boolean
  onOpen: () => void
  onTrack: () => void
}) {
  return (
    <article
      onClick={onOpen}
      className="group flex cursor-pointer items-center gap-4 border-b border-border/60 px-4 py-3 transition-colors last:border-b-0 hover:bg-card"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="truncate font-display text-sm leading-snug text-foreground group-hover:text-primary">
            {match.title}
          </h3>
          {match.is_new && <NewTag />}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="truncate font-medium text-foreground/80">{match.company}</span>
          <SourceTag source={match.source} />
          {match.location && (
            <span className="flex items-center gap-1">
              <MapPin className="h-3 w-3" /> {match.location}
            </span>
          )}
        </div>
      </div>

      <MatchScore score={match.score} compact />

      <div className="flex shrink-0 items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <ApplyButton match={match} />
        <TrackButton tracked={tracked} onTrack={onTrack} />
      </div>
    </article>
  )
}
