import type {
  Account,
  CreateAccountPayload,
  DashboardData,
  EventDetail,
  EventVotePayload,
  EventFilters,
  EventListItem,
  EventMutationResult,
  ManualEventTestResult,
  UpdateAccountPayload,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        message = payload.detail
      }
    } catch {
      const text = await response.text()
      if (text) message = text
    }
    throw new ApiError(message, response.status)
  }

  return (await response.json()) as T
}

export async function fetchDashboard(): Promise<DashboardData> {
  return fetchJson<DashboardData>('/api/v1/dashboard')
}

export async function fetchEvents(filters: EventFilters): Promise<EventListItem[]> {
  const params = new URLSearchParams()
  params.set('limit', String(filters.limit ?? 50))
  if (filters.source) params.set('source', filters.source)
  if (filters.alert_status) params.set('alert_status', filters.alert_status)
  if (filters.decision) params.set('decision', filters.decision)
  if (filters.q) params.set('q', filters.q)
  return fetchJson<EventListItem[]>(`/api/v1/events?${params.toString()}`)
}

export async function fetchEventDetail(normalizedPostId: number): Promise<EventDetail> {
  return fetchJson<EventDetail>(`/api/v1/events/${normalizedPostId}`)
}

export async function triggerEventTest(payload: { handle: string; message: string }): Promise<ManualEventTestResult> {
  return fetchJson<ManualEventTestResult>('/api/v1/events/test-trigger', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function voteEvent(normalizedPostId: number, payload: EventVotePayload): Promise<EventDetail> {
  return fetchJson<EventDetail>(`/api/v1/events/${normalizedPostId}/vote`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function refreshEvent(normalizedPostId: number): Promise<EventDetail> {
  return fetchJson<EventDetail>(`/api/v1/events/${normalizedPostId}/refresh`, {
    method: 'POST',
  })
}

export async function deleteEvent(normalizedPostId: number): Promise<EventMutationResult> {
  return fetchJson<EventMutationResult>(`/api/v1/events/${normalizedPostId}`, {
    method: 'DELETE',
  })
}

export async function clearActivity(): Promise<EventMutationResult> {
  return fetchJson<EventMutationResult>('/api/v1/activity', {
    method: 'DELETE',
  })
}

export async function clearAttention(): Promise<EventMutationResult> {
  return fetchJson<EventMutationResult>('/api/v1/activity/attention', {
    method: 'DELETE',
  })
}

export async function resetLatency(): Promise<EventMutationResult> {
  return fetchJson<EventMutationResult>('/api/v1/metrics/latency', {
    method: 'DELETE',
  })
}

export async function createAccount(payload: CreateAccountPayload): Promise<Account> {
  return fetchJson<Account>('/api/v1/accounts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateAccount(accountId: string, payload: UpdateAccountPayload): Promise<Account> {
  return fetchJson<Account>(`/api/v1/accounts/${accountId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteAccount(accountId: string): Promise<Account> {
  return fetchJson<Account>(`/api/v1/accounts/${accountId}`, {
    method: 'DELETE',
  })
}
