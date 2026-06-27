import { Loader2, Save, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import type { AppSettings, AppSettingsUpdate } from '@/lib/api'
import { useSettings, useUpdateSettings } from '@/lib/queries'

type FormState = {
  naukri_email: string
  naukri_password: string
  naukri_keywords: string
  naukri_location: string
  naukri_experience: string
  linkedin_email: string
  linkedin_password: string
  linkedin_keywords: string
  linkedin_location: string
  telegram_min_score: string
  telegram_top_n: string
}

function initialForm(s: AppSettings): FormState {
  return {
    naukri_email: s.naukri_email,
    naukri_password: '',
    naukri_keywords: s.naukri_keywords,
    naukri_location: s.naukri_location,
    naukri_experience: s.naukri_experience,
    linkedin_email: s.linkedin_email,
    linkedin_password: '',
    linkedin_keywords: s.linkedin_keywords,
    linkedin_location: s.linkedin_location,
    telegram_min_score: String(s.telegram_min_score),
    telegram_top_n: String(s.telegram_top_n),
  }
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="bg-background/40"
      />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card/70 p-5">
      <h2 className="mb-4 font-display text-base">{title}</h2>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  )
}

function SettingsForm({ current }: { current: AppSettings }) {
  const save = useUpdateSettings()
  const [form, setForm] = useState<FormState>(() => initialForm(current))

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function onSave() {
    const body: AppSettingsUpdate = {
      naukri_email: form.naukri_email,
      naukri_keywords: form.naukri_keywords,
      naukri_location: form.naukri_location,
      naukri_experience: form.naukri_experience,
      linkedin_email: form.linkedin_email,
      linkedin_keywords: form.linkedin_keywords,
      linkedin_location: form.linkedin_location,
      telegram_min_score: Number(form.telegram_min_score) || 0,
      telegram_top_n: Number(form.telegram_top_n) || 0,
    }
    if (form.naukri_password) body.naukri_password = form.naukri_password
    if (form.linkedin_password) body.linkedin_password = form.linkedin_password

    save.mutate(body, {
      onSuccess: () => toast.success('Settings saved', { description: 'Used on the next run.' }),
      onError: (e) => toast.error('Could not save', { description: (e as Error).message }),
    })
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-primary">
            <SlidersHorizontal className="h-3.5 w-3.5" /> Configuration
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Search terms and accounts. Changes apply to the next run — no restart needed.
          </p>
        </div>
        <Button onClick={onSave} disabled={save.isPending}>
          {save.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving…
            </>
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" /> Save
            </>
          )}
        </Button>
      </header>

      <div className="space-y-5">
        <Section title="Naukri">
          <Field
            label="Keywords"
            value={form.naukri_keywords}
            onChange={(v) => set('naukri_keywords', v)}
          />
          <Field
            label="Location"
            value={form.naukri_location}
            onChange={(v) => set('naukri_location', v)}
          />
          <Field
            label="Experience (years)"
            value={form.naukri_experience}
            onChange={(v) => set('naukri_experience', v)}
          />
          <Field label="Email" value={form.naukri_email} onChange={(v) => set('naukri_email', v)} />
          <Field
            label="Password"
            type="password"
            value={form.naukri_password}
            onChange={(v) => set('naukri_password', v)}
            placeholder={
              current.naukri_password_set ? '•••••••• (set — leave blank to keep)' : 'not set'
            }
          />
        </Section>

        <Section title="LinkedIn">
          <Field
            label="Keywords"
            value={form.linkedin_keywords}
            onChange={(v) => set('linkedin_keywords', v)}
          />
          <Field
            label="Location"
            value={form.linkedin_location}
            onChange={(v) => set('linkedin_location', v)}
          />
          <Field
            label="Email"
            value={form.linkedin_email}
            onChange={(v) => set('linkedin_email', v)}
          />
          <Field
            label="Password"
            type="password"
            value={form.linkedin_password}
            onChange={(v) => set('linkedin_password', v)}
            placeholder={
              current.linkedin_password_set ? '•••••••• (set — leave blank to keep)' : 'not set'
            }
          />
        </Section>

        <Section title="Telegram digest">
          <Field
            label="Top picks to push"
            type="number"
            value={form.telegram_top_n}
            onChange={(v) => set('telegram_top_n', v)}
          />
          <Field
            label="Min score counted as high-quality"
            type="number"
            value={form.telegram_min_score}
            onChange={(v) => set('telegram_min_score', v)}
          />
        </Section>

        <p className="text-xs text-muted-foreground">
          Stored locally in your database (overrides <code>.env</code>). The API has no auth — keep
          it on localhost.
        </p>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const settings = useSettings()

  if (settings.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (settings.isError || !settings.data) {
    return (
      <ErrorState
        message={settings.error ? (settings.error as Error).message : 'Could not load settings.'}
        onRetry={() => settings.refetch()}
      />
    )
  }
  // Remount the form when the saved data changes, so it re-initializes cleanly.
  return <SettingsForm key={settings.dataUpdatedAt} current={settings.data} />
}
