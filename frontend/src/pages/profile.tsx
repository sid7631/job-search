import { FileText, Loader2, Upload, UserRound } from 'lucide-react'
import { useRef } from 'react'
import { toast } from 'sonner'

import { EmptyState, ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useProfile, useUploadResume } from '@/lib/queries'

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm text-foreground">{value || '—'}</p>
    </div>
  )
}

function Chips({ items }: { items: string[] }) {
  if (!items.length) return <span className="text-sm text-muted-foreground">—</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <span
          key={s}
          className="rounded-full border border-border bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground"
        >
          {s}
        </span>
      ))}
    </div>
  )
}

export function ProfilePage() {
  const profile = useProfile()
  const upload = useUploadResume()
  const inputRef = useRef<HTMLInputElement>(null)

  function onPick(file: File | undefined) {
    if (!file) return
    upload.mutate(file, {
      onSuccess: (p) =>
        toast.success('Résumé parsed', { description: `Profile updated for ${p.name ?? 'you'}.` }),
      onError: (e) => toast.error('Could not parse résumé', { description: (e as Error).message }),
    })
  }

  const p = profile.data

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
            <UserRound className="h-3.5 w-3.5" /> Candidate
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">Profile</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every job is scored against this. Upload a new résumé to refresh it.
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          onChange={(e) => onPick(e.target.files?.[0])}
        />
        <Button onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Parsing…
            </>
          ) : (
            <>
              <Upload className="mr-2 h-4 w-4" /> Upload résumé
            </>
          )}
        </Button>
      </header>

      {profile.isLoading ? (
        <div className="space-y-3 rounded-xl border border-border bg-card/60 p-6">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : profile.isError ? (
        <ErrorState message={(profile.error as Error).message} onRetry={() => profile.refetch()} />
      ) : !p ? (
        <EmptyState
          title="No résumé yet"
          description="Upload your résumé (PDF or DOCX) to create your profile — then run the pipeline to score jobs against it."
          icon={<FileText className="h-5 w-5" />}
        />
      ) : (
        <div className="rounded-xl border border-border bg-card/70 p-6">
          <div className="grid gap-6 sm:grid-cols-2">
            <Field label="Name" value={p.name} />
            <Field
              label="Experience"
              value={p.years_experience != null ? `${p.years_experience} years` : '—'}
            />
            <Field label="Domain" value={p.domain} />
            <Field label="Desired roles" value={<Chips items={p.desired_roles} />} />
            <div className="sm:col-span-2">
              <p className="mb-1 text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground">
                Skills
              </p>
              <Chips items={p.skills} />
            </div>
            <div className="sm:col-span-2">
              <p className="mb-1 text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground">
                Preferred locations
              </p>
              <Chips items={p.preferred_locations} />
            </div>
          </div>
          <p className="mt-6 text-xs text-muted-foreground">
            Updated {new Date(p.updated_at).toLocaleString()}
          </p>
        </div>
      )}
    </div>
  )
}
