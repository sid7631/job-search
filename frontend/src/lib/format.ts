import type { Application, ApplicationStatus } from '@/lib/api'

export type Tier = 'high' | 'mid' | 'low'

export function scoreTier(score: number): Tier {
  if (score >= 85) return 'high'
  if (score >= 70) return 'mid'
  return 'low'
}

export const tierColor: Record<Tier, string> = {
  high: 'var(--score-high)',
  mid: 'var(--score-mid)',
  low: 'var(--score-low)',
}

export interface StatusMeta {
  label: string
  color: string
}

// Ordered as a job moves through the funnel — drives the pipeline columns.
export const STATUS_ORDER: ApplicationStatus[] = [
  'SAVED',
  'APPLIED',
  'INTERVIEWING',
  'OFFER',
  'REJECTED',
  'DROPPED',
]

export const statusMeta: Record<ApplicationStatus, StatusMeta> = {
  SAVED: { label: 'Saved', color: 'oklch(0.74 0.04 250)' },
  APPLIED: { label: 'Applied', color: 'oklch(0.72 0.13 240)' },
  INTERVIEWING: { label: 'Interviewing', color: 'oklch(0.82 0.15 75)' },
  OFFER: { label: 'Offer', color: 'oklch(0.86 0.19 142)' },
  REJECTED: { label: 'Rejected', color: 'oklch(0.66 0.17 25)' },
  DROPPED: { label: 'Dropped', color: 'oklch(0.62 0.02 260)' },
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Date.now() - then
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return `${days}d ago`
}

export const FOLLOW_UP_DAYS = 7

/** Applications sent a while ago that have not moved since — time to chase. */
export function staleApplications(apps: Application[] | undefined): Application[] {
  const cutoff = Date.now() - FOLLOW_UP_DAYS * 86_400_000
  return (apps ?? []).filter(
    (a) =>
      a.status === 'APPLIED' &&
      new Date(a.applied_at ?? a.updated_at).getTime() < cutoff &&
      new Date(a.updated_at).getTime() < cutoff,
  )
}
