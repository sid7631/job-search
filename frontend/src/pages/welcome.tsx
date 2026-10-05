import {
  ArrowRight,
  Bot,
  CheckCircle2,
  FileText,
  Loader2,
  Play,
  Rocket,
  Search,
  Upload,
  XCircle,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Field } from '@/components/form-field'
import { SearchPreferences } from '@/components/search-preferences'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  useLLMProviders,
  useProfile,
  useSchedule,
  useSetSchedule,
  useSettings,
  useTestLLM,
  useUpdateSettings,
  useUploadResume,
} from '@/lib/queries'
import { useStartRun } from '@/lib/use-start-run'
import { cn } from '@/lib/utils'

// The AI model comes first: reading the résumé is itself an AI call.
const STEPS = [
  { title: 'AI model', icon: Bot },
  { title: 'Your résumé', icon: FileText },
  { title: 'What to search', icon: Search },
  { title: 'Go', icon: Rocket },
]

function ResumeStep({ onNext }: { onNext: () => void }) {
  const profile = useProfile()
  const upload = useUploadResume()
  const input = useRef<HTMLInputElement>(null)
  const p = profile.data

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Every job is scored against your résumé, and your search terms are suggested from it. PDF or
        DOCX; it stays on this machine.
      </p>
      <input
        ref={input}
        type="file"
        accept=".pdf,.docx"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file)
            upload.mutate(file, {
              onError: (err) =>
                toast.error('Could not read that résumé', { description: (err as Error).message }),
            })
        }}
      />
      {p ? (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="h-4 w-4 text-primary" /> {p.name ?? 'Profile'} ·{' '}
            {p.years_experience ?? '?'} years · {p.domain ?? 'unknown domain'}
          </p>
          <p className="mt-2 text-muted-foreground">
            {p.skills.slice(0, 12).join(', ')}
            {p.skills.length > 12 ? '…' : ''}
          </p>
        </div>
      ) : null}
      <div className="flex gap-2">
        <Button
          variant={p ? 'outline' : 'default'}
          onClick={() => input.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Upload className="mr-2 h-4 w-4" />
          )}
          {upload.isPending ? 'Reading…' : p ? 'Upload a different one' : 'Upload résumé'}
        </Button>
        {p && (
          <Button onClick={onNext}>
            Continue <ArrowRight className="ml-1.5 h-4 w-4" />
          </Button>
        )}
      </div>
      {upload.isPending && (
        <p className="text-xs text-muted-foreground">
          The AI model reads it — this can take a minute on a local model.
        </p>
      )}
    </div>
  )
}

function AIStep({ onNext }: { onNext: () => void }) {
  const settings = useSettings()
  const providers = useLLMProviders()
  const test = useTestLLM()
  const save = useUpdateSettings()
  const [provider, setProvider] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')

  const chosen = provider ?? settings.data?.llm_provider ?? 'ollama'
  const spec = providers.data?.find((p) => p.key === chosen)

  function body() {
    return { llm_provider: chosen, llm_model: model, llm_api_key: apiKey }
  }

  function onSaveAndContinue() {
    // Send only what changed: a blank model would replace a saved one with the
    // provider default.
    const update: Record<string, string> = {}
    if (provider)
      Object.assign(update, { llm_provider: provider, llm_base_url: '', llm_model: model })
    else if (model) update.llm_model = model
    if (apiKey) update.llm_api_key = apiKey
    if (Object.keys(update).length === 0) return onNext()
    save.mutate(update, {
      onSuccess: onNext,
      onError: (e) => toast.error('Could not save', { description: (e as Error).message }),
    })
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        The model reads postings and explains each score. <b>Ollama (local)</b> is free and private
        if it’s installed; hosted providers are faster and need an API key.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Provider</Label>
          <Select
            value={chosen}
            onValueChange={(v) => {
              setProvider(v)
              setModel('')
            }}
          >
            <SelectTrigger className="bg-background/40">
              <SelectValue />
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
          label="Model (optional)"
          value={model}
          onChange={setModel}
          placeholder={
            (provider ? undefined : settings.data?.llm_effective_model) ||
            spec?.default_model ||
            'model name'
          }
        />
        {spec?.requires_key && (
          <Field
            label="API key"
            type="password"
            value={apiKey}
            onChange={setApiKey}
            placeholder={
              settings.data?.llm_api_key_set && !provider ? '•••••••• (saved)' : 'paste your key'
            }
          />
        )}
      </div>
      {spec?.docs_url && (
        <a
          href={spec.docs_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-primary underline underline-offset-2"
        >
          {spec.requires_key ? `Get a ${spec.label} API key` : `Set up ${spec.label}`}
        </a>
      )}
      {test.data && (
        <p
          className={cn(
            'flex items-start gap-2 text-xs',
            test.data.ok ? 'text-emerald-500' : 'text-destructive',
          )}
        >
          {test.data.ok ? (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          ) : (
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          )}
          <span className="break-all">
            {test.data.ok ? `Working — ${test.data.model} answered.` : test.data.detail}
          </span>
        </p>
      )}
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => test.mutate(body())} disabled={test.isPending}>
          {test.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Test it
        </Button>
        <Button onClick={onSaveAndContinue} disabled={save.isPending}>
          Save and continue <ArrowRight className="ml-1.5 h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

function GoStep() {
  const navigate = useNavigate()
  const { start, pending } = useStartRun()
  const schedule = useSchedule()
  const setSchedule = useSetSchedule()

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        The first run opens a browser window to read Naukri (and LinkedIn, if you added an account
        in Settings), then scores everything. It takes a few minutes; you can watch progress on
        Today.
      </p>
      {schedule.data?.supported && (
        <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-background/30 p-3 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[var(--primary)]"
            checked={schedule.data.enabled}
            disabled={setSchedule.isPending}
            onChange={(e) => setSchedule.mutate(e.target.checked)}
          />
          <span>
            Also find new jobs automatically every day at{' '}
            {String(schedule.data.run_hour).padStart(2, '0')}:00
          </span>
        </label>
      )}
      <Button
        size="lg"
        disabled={pending}
        onClick={() => {
          start()
          navigate('/')
        }}
      >
        <Play className="mr-2 h-4 w-4" /> Find my first jobs
      </Button>
    </div>
  )
}

export function WelcomePage() {
  const [step, setStep] = useState(0)
  const profile = useProfile()
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1))

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <header>
        <p className="text-xs uppercase tracking-[0.2em] text-primary">Welcome</p>
        <h1 className="mt-1 font-display text-3xl tracking-tight">Let’s set up your job hunt</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Four quick steps. You can change any of this later.
        </p>
      </header>

      <ol className="grid grid-cols-4 gap-2">
        {STEPS.map(({ title, icon: Icon }, i) => {
          const reachable = i <= 1 || Boolean(profile.data)
          return (
            <li key={title}>
              <button
                type="button"
                disabled={!reachable}
                onClick={() => setStep(i)}
                className={cn(
                  'flex w-full flex-col items-start gap-1 rounded-lg border px-3 py-2 text-left text-xs transition-colors',
                  i === step
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : i < step
                      ? 'border-border text-foreground/80'
                      : 'border-border/50 text-muted-foreground',
                  !reachable && 'opacity-50',
                )}
              >
                <Icon className="h-4 w-4" />
                <span>
                  {i + 1}. {title}
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <section className="rounded-xl border border-border bg-card/70 p-6">
        <h2 className="mb-4 font-display text-xl">{STEPS[step].title}</h2>
        {step === 0 && <AIStep onNext={next} />}
        {step === 1 && <ResumeStep onNext={next} />}
        {step === 2 && (
          <div className="space-y-4">
            <SearchPreferences />
            <Button onClick={next}>
              Continue <ArrowRight className="ml-1.5 h-4 w-4" />
            </Button>
          </div>
        )}
        {step === 3 && <GoStep />}
      </section>
    </div>
  )
}
