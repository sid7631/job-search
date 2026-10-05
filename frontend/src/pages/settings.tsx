import {
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  History,
  Loader2,
  Plug,
  Save,
  SlidersHorizontal,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Field } from '@/components/form-field'
import { ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
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
import {
  useLLMProviders,
  useSchedule,
  useSetSchedule,
  useSettings,
  useTestLLM,
  useUpdateSettings,
} from '@/lib/queries'

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

function ScheduleCard() {
  const schedule = useSchedule()
  const setSchedule = useSetSchedule()
  const data = schedule.data

  function toggle() {
    if (!data) return
    setSchedule.mutate(!data.enabled, {
      onSuccess: (s) =>
        toast.success(s.enabled ? 'Daily run turned on' : 'Daily run turned off', {
          description: s.enabled
            ? `Runs every day at ${String(s.run_hour).padStart(2, '0')}:00, and catches up after sleep.`
            : 'Run it yourself from Today whenever you like.',
        }),
      onError: (e) =>
        toast.error('Could not change schedule', { description: (e as Error).message }),
    })
  }

  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card/70 p-5">
      <div>
        <h2 className="flex items-center gap-2 font-display text-base">
          <CalendarClock className="h-4 w-4 text-primary" /> Daily run
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {data
            ? data.supported
              ? `Find and score new jobs every day at ${String(data.run_hour).padStart(2, '0')}:00 (${data.timezone}). Starts at login; a missed run catches up when your Mac wakes.`
              : 'Scheduling from here needs macOS. Use `start-scheduler` on other systems.'
            : 'Loading…'}
        </p>
      </div>
      <Button
        variant={data?.enabled ? 'outline' : 'default'}
        size="sm"
        onClick={toggle}
        disabled={!data?.supported || setSchedule.isPending}
      >
        {setSchedule.isPending && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
        {data?.enabled ? 'On — turn off' : 'Turn on'}
      </Button>
    </section>
  )
}

function SettingsForm({ current }: { current: AppSettings }) {
  const save = useUpdateSettings()
  const [form, setForm] = useState<FormState>(() => initialForm(current))
  const [advanced, setAdvanced] = useState(false)

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function onSave() {
    // Search terms live on the Profile page; this form only owns its own fields.
    const body: AppSettingsUpdate = {
      naukri_email: form.naukri_email,
      linkedin_email: form.linkedin_email,
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
            Schedule, AI and accounts. What to search for lives on your{' '}
            <Link to="/profile" className="text-primary underline underline-offset-2">
              Profile
            </Link>
            .
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
        <ScheduleCard />

        <LLMSection current={current} form={form} set={set} />

        <Section
          title="Job site accounts"
          hint="Naukri works without signing in. LinkedIn needs an account; the first sign-in may ask you to approve it on your phone."
        >
          <Field
            label="LinkedIn email"
            value={form.linkedin_email}
            onChange={(v) => set('linkedin_email', v)}
          />
          <Field
            label="LinkedIn password"
            type="password"
            value={form.linkedin_password}
            onChange={(v) => set('linkedin_password', v)}
            placeholder={
              current.linkedin_password_set ? '•••••••• (set — leave blank to keep)' : 'not set'
            }
          />
          <Field
            label="Naukri email (optional)"
            value={form.naukri_email}
            onChange={(v) => set('naukri_email', v)}
          />
          <Field
            label="Naukri password (optional)"
            type="password"
            value={form.naukri_password}
            onChange={(v) => set('naukri_password', v)}
            placeholder={
              current.naukri_password_set ? '•••••••• (set — leave blank to keep)' : 'not set'
            }
          />
        </Section>

        <section className="rounded-xl border border-border bg-card/40">
          <button
            type="button"
            onClick={() => setAdvanced((a) => !a)}
            className="flex w-full items-center justify-between px-5 py-4 text-left"
          >
            <span className="font-display text-base">Advanced</span>
            <ChevronDown
              className={`h-4 w-4 text-muted-foreground transition-transform ${advanced ? 'rotate-180' : ''}`}
            />
          </button>
          {advanced && (
            <div className="space-y-5 border-t border-border/60 p-5">
              <div>
                <h3 className="text-sm font-medium">Telegram digest</h3>
                <p className="mb-3 mt-1 text-xs text-muted-foreground">
                  Optional daily push. The bot token and chat id are set in{' '}
                  <code>backend/.env</code>.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field
                    label="Jobs per digest"
                    type="number"
                    value={form.telegram_top_n}
                    onChange={(v) => set('telegram_top_n', v)}
                  />
                  <Field
                    label="Only include scores at or above"
                    type="number"
                    value={form.telegram_min_score}
                    onChange={(v) => set('telegram_min_score', v)}
                  />
                </div>
              </div>
              <Link
                to="/runs"
                className="flex items-center gap-2 text-sm text-primary underline-offset-2 hover:underline"
              >
                <History className="h-4 w-4" /> Run history and diagnostics
              </Link>
            </div>
          )}
        </section>

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
