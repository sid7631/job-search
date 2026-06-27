import { Check, ExternalLink, Minus, Plus, MapPin } from 'lucide-react'

import { ScoreBadge } from '@/components/score-badge'
import { Button } from '@/components/ui/button'
import type { Match } from '@/lib/api'
import { cn } from '@/lib/utils'

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
      <div className="flex items-start gap-4">
        <ScoreBadge score={match.score} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-base leading-snug text-foreground group-hover:text-primary">
            {match.title}
          </h3>
          <p className="mt-0.5 truncate text-sm text-muted-foreground">{match.company}</p>
          {match.location && (
            <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground/80">
              <MapPin className="h-3 w-3" /> {match.location}
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 grid flex-1 gap-2">
        <ProConList items={match.pros} kind="pro" />
        <ProConList items={match.cons} kind="con" />
      </div>

      <div className="mt-4 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <Button
          variant="secondary"
          size="sm"
          className="flex-1"
          disabled={!match.url}
          onClick={() => match.url && window.open(match.url, '_blank', 'noopener')}
        >
          <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Apply
        </Button>
        <Button
          size="sm"
          variant={tracked ? 'outline' : 'default'}
          className="flex-1"
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
      </div>
    </article>
  )
}
