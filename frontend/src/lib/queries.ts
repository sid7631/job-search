// TanStack Query hooks over the API client. Mutations invalidate the relevant
// caches so the UI stays in sync after tracking / status changes / manual runs.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Application, type ApplicationStatus } from '@/lib/api'

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
    }): Promise<Application> => api.updateApplication(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useRunNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.runNow(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}
