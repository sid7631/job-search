import { cn } from '@/lib/utils'

/**
 * Which job board a role came from.
 *
 * Colours are the boards' own, so the tag is recognisable at a glance in a long
 * list. An unknown source still renders — a new collector should show up as a
 * readable label rather than disappearing.
 */
const SOURCE_META: Record<string, { label: string; color: string }> = {
  naukri: { label: 'Naukri', color: 'oklch(0.72 0.16 45)' },
  linkedin: { label: 'LinkedIn', color: 'oklch(0.68 0.13 245)' },
}

export function SourceTag({ source, className }: { source: string; className?: string }) {
  const meta = SOURCE_META[source?.toLowerCase()] ?? {
    label: source || 'Unknown',
    color: 'oklch(0.66 0.02 260)',
  }
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        className,
      )}
      style={{
        color: meta.color,
        borderColor: `color-mix(in oklch, ${meta.color} 35%, transparent)`,
        background: `color-mix(in oklch, ${meta.color} 10%, transparent)`,
      }}
    >
      {meta.label}
    </span>
  )
}
