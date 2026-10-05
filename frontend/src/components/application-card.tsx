import { BellRing, Clock, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { APPLICATION_STATUSES, type Application, type ApplicationStatus } from '@/lib/api'
import { formatDate, statusMeta } from '@/lib/format'
import { useUpdateApplication } from '@/lib/queries'

// Mirrors DISMISS_REASONS on the backend; the queue endpoint serves the live list.
const DISMISS_LABELS: Record<string, string> = {
  wrong_stack: 'wrong tech stack',
  too_junior: 'too junior',
  too_senior: 'too senior',
  location: 'wrong location',
  company: 'not interested in the company',
  other: 'not a fit',
  duplicate: 'duplicate posting',
}

function StatusDot({ status }: { status: ApplicationStatus }) {
  return (
    <span
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ background: statusMeta[status].color }}
    />
  )
}

export function ApplicationCard({
  app,
  needsFollowUp = false,
}: {
  app: Application
  needsFollowUp?: boolean
}) {
  const update = useUpdateApplication()
  const [notes, setNotes] = useState(app.notes ?? '')
  const dirty = notes !== (app.notes ?? '')

  function changeStatus(status: ApplicationStatus) {
    update.mutate(
      { id: app.id, status },
      {
        onSuccess: () => toast.success(`Moved to ${statusMeta[status].label}`),
        onError: (e) => toast.error('Update failed', { description: (e as Error).message }),
      },
    )
  }

  function saveNotes() {
    update.mutate(
      { id: app.id, notes },
      {
        onSuccess: () => toast.success('Note saved'),
        onError: (e) => toast.error('Save failed', { description: (e as Error).message }),
      },
    )
  }

  const job = app.job

  return (
    <div className="rounded-xl border border-border bg-card/80 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium leading-snug">{job?.title ?? 'Job'}</h3>
          <p className="truncate text-xs text-muted-foreground">{job?.company ?? '—'}</p>
        </div>
        {job?.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-muted-foreground transition-colors hover:text-primary"
            aria-label="Open job posting"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>

      <div className="mt-3">
        <Select value={app.status} onValueChange={(v) => changeStatus(v as ApplicationStatus)}>
          <SelectTrigger className="h-8 w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {APPLICATION_STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                <span className="flex items-center gap-2">
                  <StatusDot status={s} />
                  {statusMeta[s].label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Add a note…"
        className="mt-2 min-h-[2.25rem] resize-none bg-background/40 text-xs"
        rows={2}
      />
      {dirty && (
        <div className="mt-2 flex justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setNotes(app.notes ?? '')}
          >
            Cancel
          </Button>
          <Button size="sm" className="h-7 text-xs" onClick={saveNotes} disabled={update.isPending}>
            Save note
          </Button>
        </div>
      )}

      {app.applied_at && (
        <p className="mt-3 flex items-center gap-1 text-[0.7rem] text-muted-foreground">
          <Clock className="h-3 w-3" /> Applied {formatDate(app.applied_at)}
        </p>
      )}
      {needsFollowUp && (
        <p className="mt-2 flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-1 text-[0.7rem] text-amber-300">
          <BellRing className="h-3 w-3" /> No reply in a week — worth a follow-up
        </p>
      )}
      {app.status === 'DROPPED' && app.dismiss_reason && (
        <p className="mt-2 text-[0.7rem] text-muted-foreground">
          Passed: {DISMISS_LABELS[app.dismiss_reason] ?? app.dismiss_reason}
        </p>
      )}
    </div>
  )
}
