import { CheckCircle2, Loader2, Plug, Save, SlidersHorizontal, Wand2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import type { AppSettings, AppSettingsUpdate, LLMProviderInfo } from '@/lib/api'
import { useLLMProviders, useSettings, useTestLLM, useUpdateSettings } from '@/lib/queries'

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
  llm_provider: string
  llm_base_url: string
  llm_model: string
  llm_api_key: string
}

function initialForm(s: AppSettings): FormState {
  // A field the resume is filling starts EMPTY, with the derived value shown as a
  // placeholder. If it were pre-filled with the derived value, pressing Save once
  // would freeze today's resume into a manual override and the field would never
  // track the resume again — silently defeating the whole auto-fill.
  const auto = (field: string, value: string) => (s.auto_fields.includes(field) ? '' : value)
  return {
    naukri_email: s.naukri_email,
    naukri_password: '',
    naukri_keywords: auto('naukri_keywords', s.naukri_keywords),
    naukri_location: auto('naukri_location', s.naukri_location),
    naukri_experience: auto('naukri_experience', s.naukri_experience),
    linkedin_email: s.linkedin_email,
    linkedin_password: '',
    linkedin_keywords: auto('linkedin_keywords', s.linkedin_keywords),
    linkedin_location: auto('linkedin_location', s.linkedin_location),
    telegram_min_score: String(s.telegram_min_score),
    telegram_top_n: String(s.telegram_top_n),
    llm_provider: s.llm_provider,
    llm_base_url: s.llm_base_url,
    llm_model: s.llm_model,
    llm_api_key: '',
  }
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  auto,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  /** Set when this field is currently being filled from the parsed resume. */
  auto?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Label className="text-xs text-muted-foreground">{label}</Label>
        {auto && (
          <span className="flex items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            <Wand2 className="h-2.5 w-2.5" /> from resume
          </span>
        )}
      </div>
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

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-card/70 p-5">
      <h2 className="font-display text-base">{title}</h2>
      {hint && <p className="mb-4 mt-1 text-xs text-muted-foreground">{hint}</p>}
      <div className={`grid gap-4 sm:grid-cols-2 ${hint ? '' : 'mt-4'}`}>{children}</div>
    </section>
  )
}

function LLMSection({
  current,
  form,
  set,
}: {
  current: AppSettings
  form: FormState
  set: <K extends keyof FormState>(key: K, value: string) => void
}) {
  const providers = useLLMProviders()
  const test = useTestLLM()
  const spec: LLMProviderInfo | undefined = providers.data?.find((p) => p.key === form.llm_provider)
  // Local runtimes (Ollama, LM Studio) and self-hosted gateways need no key.
  const needsKey = spec ? spec.requires_key : current.llm_requires_key

  function onProviderChange(next: string) {
    set('llm_provider', next)
    // Endpoint and model are provider-specific: clear them so the new provider's
    // defaults apply instead of, say, an OpenAI URL pointed at Ollama.
    set('llm_base_url', '')
    set('llm_model', '')
  }

  function onTest() {
    // Test what's on screen, not what was last saved — otherwise a key typed here
    // but not yet saved gets silently ignored and the old one is tested instead.
    test.mutate({
      llm_provider: form.llm_provider,
      llm_base_url: form.llm_base_url,
      llm_model: form.llm_model,
      llm_api_key: form.llm_api_key,
    })
  }

  return (
    <section className="rounded-xl border border-border bg-card/70 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-base">AI Provider</h2>
        <Button variant="outline" size="sm" onClick={onTest} disabled={test.isPending}>
          {test.isPending ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> Testing…
            </>
          ) : (
            <>
              <Plug className="mr-2 h-3.5 w-3.5" /> Test connection
            </>
          )}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Provider</Label>
          <Select value={form.llm_provider} onValueChange={onProviderChange}>
            <SelectTrigger className="bg-background/40">
              <SelectValue placeholder="Select provider" />
            </SelectTrigger>
            <SelectContent>
              {(providers.data ?? []).map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Field
          label={spec && !spec.default_base_url ? 'Base URL (required)' : 'Base URL (optional)'}
          value={form.llm_base_url}
          onChange={(v) => set('llm_base_url', v)}
          placeholder={spec?.default_base_url || 'https://your-endpoint/v1'}
        />
        <Field
          label="Model"
          value={form.llm_model}
          onChange={(v) => set('llm_model', v)}
          placeholder={spec?.default_model || 'model name'}
        />
        <Field
          label={needsKey ? 'API key' : 'API key (not required)'}
          type="password"
          value={form.llm_api_key}
          onChange={(v) => set('llm_api_key', v)}
          placeholder={
            current.llm_api_key_set
              ? '•••••••• (set — leave blank to keep)'
              : needsKey
                ? 'required for this provider'
                : 'leave blank for local models'
          }
        />
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        Blank Base URL / Model use the provider default
        {spec?.default_base_url ? ` (${spec.default_base_url}` : ''}
        {spec?.default_base_url && spec?.default_model ? `, ${spec.default_model})` : ''}
        {spec?.default_base_url && !spec?.default_model ? ')' : ''}. Test connection uses what is on
        screen — it saves nothing, so you can try a key before committing it.
        {spec?.docs_url ? (
          <>
            {' '}
            <a
              href={spec.docs_url}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline underline-offset-2"
            >
              {needsKey ? 'Get an API key' : 'Setup guide'}
            </a>
          </>
        ) : null}
      </p>

      {test.data ? (
        <p
          className={`mt-2 flex items-start gap-2 text-xs ${
            test.data.ok ? 'text-emerald-500' : 'text-destructive'
          }`}
        >
          {test.data.ok ? (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          ) : (
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          )}
          <span className="break-all">
            {test.data.ok
              ? `${test.data.provider} responded using ${test.data.model}.`
              : test.data.detail}
          </span>
        </p>
      ) : null}
      {test.isError ? (
        <p className="mt-2 text-xs text-destructive">{(test.error as Error).message}</p>
      ) : null}
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
      llm_provider: form.llm_provider,
      llm_base_url: form.llm_base_url,
      llm_model: form.llm_model,
    }
    if (form.naukri_password) body.naukri_password = form.naukri_password
    if (form.linkedin_password) body.linkedin_password = form.linkedin_password
    if (form.llm_api_key) body.llm_api_key = form.llm_api_key

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
        <Section
          title="Naukri"
          hint="Leave a field blank to use the value from your resume; type anything here to override it."
        >
          <Field
            label="Keywords"
            value={form.naukri_keywords}
            onChange={(v) => set('naukri_keywords', v)}
            placeholder={current.derived_from_resume['naukri_keywords'] ?? ''}
            auto={current.auto_fields.includes('naukri_keywords')}
          />
          <Field
            label="Location"
            value={form.naukri_location}
            onChange={(v) => set('naukri_location', v)}
            placeholder={current.derived_from_resume['naukri_location'] ?? ''}
            auto={current.auto_fields.includes('naukri_location')}
          />
          <Field
            label="Experience (years)"
            value={form.naukri_experience}
            onChange={(v) => set('naukri_experience', v)}
            placeholder={current.derived_from_resume['naukri_experience'] ?? ''}
            auto={current.auto_fields.includes('naukri_experience')}
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

        <Section
          title="LinkedIn"
          hint="Leave a field blank to use the value from your resume; type anything here to override it."
        >
          <Field
            label="Keywords"
            value={form.linkedin_keywords}
            onChange={(v) => set('linkedin_keywords', v)}
            placeholder={current.derived_from_resume['linkedin_keywords'] ?? ''}
            auto={current.auto_fields.includes('linkedin_keywords')}
          />
          <Field
            label="Location"
            value={form.linkedin_location}
            onChange={(v) => set('linkedin_location', v)}
            placeholder={current.derived_from_resume['linkedin_location'] ?? ''}
            auto={current.auto_fields.includes('linkedin_location')}
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

        <LLMSection current={current} form={form} set={set} />

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
