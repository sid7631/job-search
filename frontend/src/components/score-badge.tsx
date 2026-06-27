import { cn } from '@/lib/utils'
import { scoreTier, tierColor } from '@/lib/format'

const SIZES = {
  sm: 'h-10 w-10 text-base',
  md: 'h-14 w-14 text-xl',
  lg: 'h-20 w-20 text-3xl',
} as const

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
      aria-label={`Match score ${score}`}
    >
      {score}
    </div>
  )
}
