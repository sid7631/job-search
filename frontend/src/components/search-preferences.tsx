import { Ban, Loader2, Save, Search } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Field } from '@/components/form-field'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { AppSettings } from '@/lib/api'
import { useSettings, useUpdateSettings } from '@/lib/queries'

const SEARCH_FIELDS = [
  'naukri_keywords',
  'naukri_location',
  'naukri_experience',
  'linkedin_keywords',
  'linkedin_location',
] as const

type SearchField = (typeof SEARCH_FIELDS)[number]
type FormState = Record<SearchField | 'exclude_keywords', string>

function initialForm(s: AppSettings): FormState {
  // A field the résumé is filling starts empty with the derived value as a
  // placeholder; pre-filling it would freeze today's résumé into an override.
  const form = { exclude_keywords: s.exclude_keywords } as FormState
  for (const f of SEARCH_FIELDS) form[f] = s.auto_fields.includes(f) ? '' : s[f]
  return form
}

function Form({ current }: { current: AppSettings }) {
  const save = useUpdateSettings()
  const [form, setForm] = useState<FormState>(() => initialForm(current))
  const set = (key: keyof FormState) => (v: string) => setForm((f) => ({ ...f, [key]: v }))
  const field = (key: SearchField, label: string) => (
    <Field
      label={label}
      value={form[key]}
      onChange={set(key)}
      placeholder={current.derived_from_resume[key] ?? ''}
      auto={current.auto_fields.includes(key)}
    />
  )

  function onSave() {
    save.mutate(form, {
      onSuccess: () => toast.success('Search saved', { description: 'Used on the next run.' }),
      onError: (e) => toast.error('Could not save', { description: (e as Error).message }),
    })
  }

  return (
    <section className="rounded-xl border border-border bg-card/70 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-display text-base">
            <Search className="h-4 w-4 text-primary" /> What to search for
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Blank fields follow your résumé. Each source runs one search per run, so use a single
            focused phrase (“python full stack developer”).
          </p>
        </div>
        <Button size="sm" onClick={onSave} disabled={save.isPending}>
          {save.isPending ? (
            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="mr-2 h-3.5 w-3.5" />
          )}
          Save search
        </Button>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-3">
        {field('naukri_keywords', 'Naukri keywords')}
        {field('naukri_location', 'Naukri location')}
        {field('naukri_experience', 'Years of experience')}
        {field('linkedin_keywords', 'LinkedIn keywords')}
        {field('linkedin_location', 'LinkedIn location')}
      </div>

      <div className="mt-5 rounded-lg border border-border/70 bg-background/30 p-4">
        <Field
          label="Never show jobs with these words in the title"
          value={form.exclude_keywords}
          onChange={set('exclude_keywords')}
          placeholder="e.g. java, sap, intern"
        />
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Ban className="h-3 w-3" /> Whole words, comma-separated: “java” hides Java roles but
          keeps JavaScript. Applies instantly to Today and to every future run.
        </p>
      </div>
    </section>
  )
}

export function SearchPreferences() {
  const settings = useSettings()
  if (!settings.data) return <Skeleton className="h-64 w-full" />
  return <Form key={settings.dataUpdatedAt} current={settings.data} />
}
