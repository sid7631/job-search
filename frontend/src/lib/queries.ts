// TanStack Query hooks over the API client. Mutations invalidate the relevant
// caches so the UI stays in sync after tracking / status changes / manual runs.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { api, type Application, type ApplicationStatus, type TriageAction } from '@/lib/api'

export const keys = {
  matches: (minScore?: number) => ['matches', { minScore }] as const,
  matchDetail: (jobId: number) => ['matches', jobId] as const,
  applications: (status?: ApplicationStatus) => ['applications', { status }] as const,
  runs: () => ['runs'] as const,
}

export function useMatches(minScore?: number) {
  return useQuery({
    queryKey: keys.matches(minScore),
    queryFn: () => api.listMatches({ minScore }),
  })
}

export function useMatchDetail(jobId: number | null) {
  return useQuery({
    queryKey: jobId == null ? ['matches', 'none'] : keys.matchDetail(jobId),
    queryFn: () => api.matchDetail(jobId as number),
    enabled: jobId != null,
  })
}

export function useApplications(status?: ApplicationStatus) {
  return useQuery({
    queryKey: keys.applications(status),
    queryFn: () => api.listApplications(status),
  })
}

export function useRuns() {
  return useQuery({ queryKey: keys.runs(), queryFn: () => api.listRuns() })
}

export function useTrackApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { job_id: number; status?: ApplicationStatus; notes?: string }) =>
      api.createApplication(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      status?: ApplicationStatus
      notes?: string
      dismiss_reason?: string
    }): Promise<Application> => api.updateApplication(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useRunNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.runNow(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      qc.invalidateQueries({ queryKey: ['run-current'] })
    },
  })
}

export function useQueue() {
  return useQuery({ queryKey: ['queue'], queryFn: () => api.getQueue() })
}

export function useTriage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      job_id: number
      action: TriageAction
      reason?: string
      similar_ids?: number[]
    }) => api.triage(body),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

export function useUndoTriage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobIds: number[]) => api.undoTriage(jobIds),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

/**
 * The active run (polled every 2s while one is going) and the last finished one.
 * When a run finishes, everything it produced is refetched.
 */
export function useCurrentRun() {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['run-current'],
    queryFn: () => api.currentRun(),
    refetchInterval: (q) => (q.state.data?.active ? 2000 : 30_000),
    staleTime: 0,
  })
  const wasActive = useRef(false)
  const active = Boolean(query.data?.active)
  useEffect(() => {
    if (wasActive.current && !active) {
      for (const key of ['queue', 'matches', 'runs', 'applications']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
    }
    wasActive.current = active
  }, [active, qc])
  return query
}

export function useSchedule() {
  return useQuery({ queryKey: ['schedule'], queryFn: () => api.getSchedule() })
}

export function useSetSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) => api.setSchedule(enabled),
    onSuccess: (data) => qc.setQueryData(['schedule'], data),
  })
}

export function useProfile() {
  return useQuery({ queryKey: ['profile'], queryFn: () => api.getProfile() })
}

export function useUploadResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadResume(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['profile'] }),
  })
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: () => api.getSettings() })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: import('@/lib/api').AppSettingsUpdate) => api.updateSettings(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      // The exclude list filters the queue immediately.
      qc.invalidateQueries({ queryKey: ['queue'] })
    },
  })
}

export function useLLMProviders() {
  return useQuery({
    queryKey: ['llm-providers'],
    queryFn: () => api.listLLMProviders(),
    // The registry only changes when the backend is redeployed.
    staleTime: Infinity,
  })
}

export function useTestLLM() {
  return useMutation({
    mutationFn: (body: import('@/lib/api').LLMTestInput) => api.testLLM(body),
  })
}
