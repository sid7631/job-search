// Typed client wrapping the M8 JSON API. Uses same-origin /api (Vite proxies it
// to the FastAPI backend in dev); override the base with VITE_API_URL in prod.

const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export const APPLICATION_STATUSES = [
  'SAVED',
  'APPLIED',
  'INTERVIEWING',
  'REJECTED',
  'OFFER',
  'DROPPED',
] as const

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export interface Match {
  job_id: number
  title: string
  company: string
  location: string | null
  url: string | null
  /** Which job board this came from ("naukri", "linkedin"). */
  source: string
  score: number
  pros: string[]
  cons: string[]
  reason: string | null
  llm_model: string | null
  run_id: number
  created_at: string
  /** First seen in this run — badge it as new rather than a repeat from earlier days. */
  is_new: boolean
}

export interface MatchDetail extends Match {
  description: string | null
  /** True when `description` is the real posting, not the search-card summary. */
  description_enriched: boolean
  skills: string[]
}

export interface JobSummary {
  title: string
  company: string
  location: string | null
  url: string | null
}

export interface Application {
  id: number
  job_id: number
  status: ApplicationStatus
  applied_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
  job: JobSummary | null
}

export interface Run {
  id: number
  started_at: string
  finished_at: string | null
  status: string
  source_counts: Record<string, unknown>
  error_text: string | null
  /** {source: message} for sources that were skipped; the run can still be a SUCCESS. */
  source_errors: Record<string, string>
}

export interface Profile {
  id: number
  name: string | null
  years_experience: number | null
  domain: string | null
  skills: string[]
  preferred_locations: string[]
  desired_roles: string[]
  updated_at: string
}

// The provider list is served by the backend (`app/llm_client.py` is the single
// source of truth) so the dropdown can never drift from what the client supports.
export interface LLMProviderInfo {
  key: string
  label: string
  default_base_url: string
  default_model: string
  requires_key: boolean
  docs_url: string
}

export type LLMTestInput = Partial<{
  llm_provider: string
  llm_base_url: string
  llm_model: string
  llm_api_key: string
}>

export interface LLMTestResult {
  ok: boolean
  provider: string
  model: string
  detail: string | null
}

export interface AppSettings {
  naukri_email: string
  naukri_password_set: boolean
  naukri_keywords: string
  naukri_location: string
  naukri_experience: string
  linkedin_email: string
  linkedin_password_set: boolean
  linkedin_keywords: string
  linkedin_location: string
  telegram_min_score: number
  telegram_top_n: number
  llm_provider: string
  llm_base_url: string
  llm_model: string
  llm_api_key_set: boolean
  llm_effective_base_url: string
  llm_effective_model: string
  llm_requires_key: boolean
  /** Search terms implied by the parsed resume, keyed by setting name. */
  derived_from_resume: Record<string, string>
  /** Fields currently coming from the resume rather than an explicit value. */
  auto_fields: string[]
}

export type AppSettingsUpdate = Partial<{
  naukri_email: string
  naukri_password: string
  naukri_keywords: string
  naukri_location: string
  naukri_experience: string
  linkedin_email: string
  linkedin_password: string
  linkedin_keywords: string
  linkedin_location: string
  telegram_min_score: number
  telegram_top_n: number
  llm_provider: string
  llm_base_url: string
  llm_model: string
  llm_api_key: string
}>

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(0, 'Could not reach the API. Is the backend running?')
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = (await response.json())?.detail ?? detail
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  listMatches(params: { date?: string; minScore?: number } = {}): Promise<Match[]> {
    const q = new URLSearchParams()
    if (params.date) q.set('date', params.date)
    if (params.minScore != null) q.set('min_score', String(params.minScore))
    const qs = q.toString()
    return request<Match[]>(`/api/matches${qs ? `?${qs}` : ''}`)
  },

  matchDetail(jobId: number): Promise<MatchDetail> {
    return request<MatchDetail>(`/api/matches/${jobId}`)
  },

  listApplications(status?: ApplicationStatus): Promise<Application[]> {
    const qs = status ? `?status=${status}` : ''
    return request<Application[]>(`/api/applications${qs}`)
  },

  createApplication(body: {
    job_id: number
    status?: ApplicationStatus
    notes?: string
  }): Promise<Application> {
    return request<Application>('/api/applications', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  updateApplication(
    id: number,
    body: { status?: ApplicationStatus; notes?: string },
  ): Promise<Application> {
    return request<Application>(`/api/applications/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },

  listRuns(limit = 50): Promise<Run[]> {
    return request<Run[]>(`/api/runs?limit=${limit}`)
  },

  runNow(): Promise<{ run_id: number; status: string }> {
    return request<{ run_id: number; status: string }>('/api/run-now', { method: 'POST' })
  },

  getProfile(): Promise<Profile | null> {
    return request<Profile | null>('/api/profile')
  },

  getSettings(): Promise<AppSettings> {
    return request<AppSettings>('/api/settings')
  },

  updateSettings(body: AppSettingsUpdate): Promise<AppSettings> {
    return request<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) })
  },

  listLLMProviders(): Promise<LLMProviderInfo[]> {
    return request<LLMProviderInfo[]>('/api/settings/llm/providers')
  },

  // Sends the on-screen values so a key that is typed but not yet saved is what
  // gets tested. Blank fields fall back to the saved settings; nothing is written.
  testLLM(body: LLMTestInput = {}): Promise<LLMTestResult> {
    return request<LLMTestResult>('/api/settings/llm/test', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  async uploadResume(file: File): Promise<Profile> {
    const form = new FormData()
    form.append('file', file)
    let response: Response
    try {
      // No Content-Type header: the browser sets the multipart boundary.
      response = await fetch(`${API_BASE}/api/profile/resume`, { method: 'POST', body: form })
    } catch {
      throw new ApiError(0, 'Could not reach the API. Is the backend running?')
    }
    if (!response.ok) {
      let detail = response.statusText
      try {
        detail = (await response.json())?.detail ?? detail
      } catch {
        /* ignore non-JSON error bodies */
      }
      throw new ApiError(response.status, detail)
    }
    return (await response.json()) as Profile
  },
}
