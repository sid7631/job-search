import { scoreTier, tierColor } from '@/lib/format'
import { cn } from '@/lib/utils'

const SIZES = {
  sm: 'h-10 w-10 text-base',
  md: 'h-14 w-14 text-xl',
  lg: 'h-20 w-20 text-3xl',
} as const

/**
 * The raw score as a tile. Kept for the detail dialog, where the surrounding
 * copy already says what the number means.
 */
export function ScoreBadge({
  score,
  size = 'md',
  className,
}: {
  score: number
  size?: keyof typeof SIZES
  className?: string
}) {
  const tier = scoreTier(score)
  const color = tierColor[tier]
  return (
    <div
      className={cn(
        'tabnum relative grid shrink-0 place-items-center rounded-xl border font-semibold',
        SIZES[size],
        className,
      )}
      style={{
        color,
        borderColor: `color-mix(in oklch, ${color} 45%, transparent)`,
        background: `color-mix(in oklch, ${color} 12%, transparent)`,
        boxShadow: tier === 'high' ? `0 0 24px -8px ${color}` : undefined,
      }}
      aria-label={`Match score ${score} out of 100`}
    >
      {score}
    </div>
  )
}

/**
 * The score as a labelled percentage — "90% match".
 *
 * A bare "90" next to a job title reads as anything: salary, applicants, days
 * left. The unit has to travel with the number, so the label is part of the
 * component rather than something each caller remembers to add.
 */
export function MatchScore({
  score,
  compact = false,
  className,
}: {
  score: number
  /** Single-line form for dense list rows. */
  compact?: boolean
  className?: string
}) {
  const tier = scoreTier(score)
  const color = tierColor[tier]

  if (compact) {
    return (
      <div
        className={cn(
          'tabnum flex shrink-0 items-baseline gap-1 rounded-lg border px-2.5 py-1',
          className,
        )}
        style={{
          color,
          borderColor: `color-mix(in oklch, ${color} 40%, transparent)`,
          background: `color-mix(in oklch, ${color} 10%, transparent)`,
        }}
        aria-label={`${score} percent match`}
      >
        <span className="text-base font-semibold leading-none">{score}%</span>
        <span className="text-[10px] font-medium uppercase tracking-wide opacity-70">match</span>
      </div>
    )
  }

  return (
    <div
      className={cn('flex shrink-0 flex-col items-end', className)}
      aria-label={`${score} percent match`}
    >
      <div
        className="tabnum rounded-xl border px-3 py-1.5 text-2xl font-semibold leading-none"
        style={{
          color,
          borderColor: `color-mix(in oklch, ${color} 45%, transparent)`,
          background: `color-mix(in oklch, ${color} 12%, transparent)`,
          boxShadow: tier === 'high' ? `0 0 24px -8px ${color}` : undefined,
        }}
      >
        {score}%
      </div>
      <span className="mt-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        match
      </span>
    </div>
  )
}
