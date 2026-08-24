import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  startTransition,
  useDeferredValue,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useForm, type UseFormReturn } from 'react-hook-form'
import { z } from 'zod'

import {
  ApiError,
  clearActivity,
  clearAttention,
  createAccount,
  deleteEvent,
  deleteAccount,
  fetchDashboard,
  fetchEventDetail,
  fetchEvents,
  refreshEvent,
  resetLatency,
  triggerEventTest,
  updateAccount,
  voteEvent,
} from './api'
import {
  formatCompactNumber,
  formatCurrency,
  formatDateTime,
  formatLatencyValue,
  formatRelativeTime,
  formatSourceLabel,
  formatStatusLabel,
} from './format'
import type {
  Account,
  ActivityItem,
  DashboardData,
  Distribution,
  EventDetail,
  EventFeedbackVote,
  EventListItem,
  ManualEventTestResult,
  StreamMessage,
  UpdateAccountPayload,
} from './types'

const addAccountSchema = z.object({
  source: z.enum(['x', 'truth_social']),
  display_name: z.string().trim().min(1, 'Enter a display name').max(120),
  handle: z
    .string()
    .trim()
    .min(1, 'Enter a handle')
    .max(80)
    .regex(/^@?[A-Za-z0-9._]+$/, 'Use a valid handle'),
  authority_rank: z.coerce.number().int().min(0).max(100),
  alert_threshold: z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d+$/.test(value) && Number(value) >= 0 && Number(value) <= 100), {
      message: 'Use 0 to 100 or leave blank',
    }),
})

type AddAccountFormValues = z.input<typeof addAccountSchema>

const manualTriggerSchema = z.object({
  handle: z
    .string()
    .trim()
    .min(1, 'Enter a tracked handle')
    .max(80)
    .regex(/^@?[A-Za-z0-9._]+$/, 'Use a valid handle'),
  message: z.string().trim().min(1, 'Enter a test message').max(4000, 'Keep the message under 4000 characters'),
})

type ManualTriggerFormValues = z.input<typeof manualTriggerSchema>

const DEFAULT_LIMIT = 50
const EVENT_VOTES_STORAGE_KEY = 'event-radar:event-votes'
const EMPTY_DISTRIBUTION: Distribution = {
  count: 0,
  p50: null,
  p95: null,
  p99: null,
  min: null,
  max: null,
}
const LATENCY_METRIC_ORDER = [
  'source_to_observed_seconds',
  'observed_to_persisted_seconds',
  'persisted_to_classification_seconds',
  'classification_to_relay_seconds',
  'end_to_end_seconds',
] as const

function readStoredVotes(): Record<number, EventFeedbackVote | null> {
  if (typeof window === 'undefined') {
    return {}
  }
  try {
    const raw = window.localStorage.getItem(EVENT_VOTES_STORAGE_KEY)
    if (!raw) {
      return {}
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const votes: Record<number, EventFeedbackVote | null> = {}
    for (const [key, value] of Object.entries(parsed)) {
      if (value === 'up' || value === 'down' || value === null) {
        votes[Number(key)] = value
      }
    }
    return votes
  } catch {
    return {}
  }
}

function persistStoredVotes(votes: Record<number, EventFeedbackVote | null>): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(EVENT_VOTES_STORAGE_KEY, JSON.stringify(votes))
  } catch {
    return
  }
}

function App() {
  const queryClient = useQueryClient()
  const [sourceFilter, setSourceFilter] = useState<'all' | 'x' | 'truth_social'>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [decisionFilter, setDecisionFilter] = useState<string>('all')
  const [searchInput, setSearchInput] = useState('')
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null)
  const [isInspectorOpen, setIsInspectorOpen] = useState(false)
  const [isAddAccountOpen, setIsAddAccountOpen] = useState(false)
  const [updatingAccountId, setUpdatingAccountId] = useState<string | null>(null)
  const [deletingAccountId, setDeletingAccountId] = useState<string | null>(null)
  const [votingEventId, setVotingEventId] = useState<number | null>(null)
  const [refreshingEventId, setRefreshingEventId] = useState<number | null>(null)
  const [deletingEventId, setDeletingEventId] = useState<number | null>(null)
  const [localVotes, setLocalVotes] = useState<Record<number, EventFeedbackVote | null>>(() => readStoredVotes())
  const [liveMessage, setLiveMessage] = useState('Connecting live updates')
  const deferredSearch = useDeferredValue(searchInput)
  const lastEventTriggerRef = useRef<HTMLButtonElement | null>(null)
  const manualTriggerForm = useForm<ManualTriggerFormValues>({
    resolver: zodResolver(manualTriggerSchema),
    defaultValues: {
      handle: '',
      message: '',
    },
  })

  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 30000,
    staleTime: 15000,
  })

  const eventsQuery = useQuery({
    queryKey: ['events', sourceFilter, statusFilter, decisionFilter, deferredSearch],
    queryFn: () =>
      fetchEvents({
        limit: DEFAULT_LIMIT,
        source: sourceFilter === 'all' ? undefined : sourceFilter,
        alert_status: statusFilter === 'all' ? undefined : statusFilter,
        decision: decisionFilter === 'all' ? undefined : decisionFilter,
        q: deferredSearch.trim() || undefined,
      }),
    refetchInterval: 30000,
    staleTime: 15000,
  })

  const detailQuery = useQuery({
    queryKey: ['event', selectedEventId],
    queryFn: () => fetchEventDetail(selectedEventId as number),
    enabled: selectedEventId !== null && isInspectorOpen,
  })

  useEffect(() => {
    const events = eventsQuery.data ?? []
    if (!events.length) {
      startTransition(() => setSelectedEventId(null))
      startTransition(() => setIsInspectorOpen(false))
      return
    }
    if (selectedEventId === null || !events.some((event) => event.normalized_post_id === selectedEventId)) {
      startTransition(() => setSelectedEventId(events[0].normalized_post_id))
    }
  }, [eventsQuery.data, selectedEventId])

  const addAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: async () => {
      setIsAddAccountOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['events'] }),
      ])
    },
  })

  const updateAccountMutation = useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: UpdateAccountPayload }) =>
      updateAccount(accountId, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const deleteAccountMutation = useMutation({
    mutationFn: deleteAccount,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const manualTestMutation = useMutation({
    mutationFn: triggerEventTest,
  })

  const voteMutation = useMutation({
    mutationFn: ({ eventId, vote }: { eventId: number; vote: EventFeedbackVote | null }) => voteEvent(eventId, { vote }),
    onMutate: async ({ eventId, vote }) => {
      await queryClient.cancelQueries({ queryKey: ['events'] })
      setVotingEventId(eventId)
      setLocalVotes((current) => ({ ...current, [eventId]: vote }))
    },
    onSuccess: (updatedEvent, variables) => {
      queryClient.setQueriesData<EventListItem[]>({ queryKey: ['events'] }, (current) =>
        current?.map((event) =>
          event.normalized_post_id === updatedEvent.normalized_post_id
            ? {
                ...event,
                feedback_vote: updatedEvent.feedback_vote,
                feedback_vote_updated_at: updatedEvent.feedback_vote_updated_at,
              }
            : event,
        ),
      )
      queryClient.setQueryData<EventDetail | undefined>(['event', updatedEvent.normalized_post_id], updatedEvent)
      setLocalVotes((current) => ({
        ...current,
        [updatedEvent.normalized_post_id]: updatedEvent.feedback_vote ?? variables.vote,
      }))
    },
    onSettled: (_data, _error, variables) => {
      setVotingEventId((current) => (current === variables.eventId ? null : current))
    },
  })

  const refreshEventMutation = useMutation({
    mutationFn: refreshEvent,
    onSuccess: async (updatedEvent) => {
      queryClient.setQueryData(['event', updatedEvent.normalized_post_id], updatedEvent)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
    },
  })

  const deleteEventMutation = useMutation({
    mutationFn: deleteEvent,
    onSuccess: async (_result, eventId) => {
      if (selectedEventId === eventId) {
        startTransition(() => setSelectedEventId(null))
        startTransition(() => setIsInspectorOpen(false))
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
    },
  })

  const clearActivityMutation = useMutation({
    mutationFn: clearActivity,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const clearAttentionMutation = useMutation({
    mutationFn: clearAttention,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const resetLatencyMutation = useMutation({
    mutationFn: resetLatency,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const handleStreamMessage = useEffectEvent((payload: StreamMessage) => {
    if (payload.type === 'activity.create') {
      queryClient.setQueryData<DashboardData | undefined>(['dashboard'], (current) => {
        if (!current) return current
        const activity = [payload.activity, ...current.activity].slice(0, 12)
        const attention = [payload.activity, ...current.attention]
          .filter((item) => item.level === 'warning' || item.level === 'error')
          .slice(0, 8)
        return {
          ...current,
          activity,
          attention,
          summary: {
            ...current.summary,
            attention_count: attention.length,
            last_activity_at: payload.activity.created_at,
          },
        }
      })
    }

    if (payload.type === 'connector.update') {
      queryClient.setQueryData<DashboardData | undefined>(['dashboard'], (current) => {
        if (!current) return current
        return {
          ...current,
          connectors: current.connectors.map((connector) =>
            connector.name === payload.connector.name ? payload.connector : connector,
          ),
        }
      })
    }

    if (payload.type === 'event.upsert') {
      if (payload.event?.normalized_post_id === selectedEventId) {
        queryClient.setQueryData(['event', selectedEventId], payload.event)
      }
      void queryClient.invalidateQueries({ queryKey: ['events'] })
    }

    if (payload.type === 'event.delete') {
      if (payload.normalized_post_id === selectedEventId) {
        startTransition(() => setSelectedEventId(null))
        startTransition(() => setIsInspectorOpen(false))
      }
      void queryClient.invalidateQueries({ queryKey: ['events'] })
      queryClient.removeQueries({ queryKey: ['event', payload.normalized_post_id] })
    }

    if (payload.type === 'dashboard.invalidate' || payload.type === 'event.upsert' || payload.type === 'event.delete') {
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    }
  })

  useEffect(() => {
    const source = new EventSource('/api/v1/events/stream')

    source.onopen = () => {
      setLiveMessage('Live updates connected')
    }

    source.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as StreamMessage
        handleStreamMessage(payload)
      } catch {
        setLiveMessage('Live updates lost sync')
      }
    }

    source.onerror = () => {
      setLiveMessage('Reconnecting live updates')
    }

    return () => {
      source.close()
    }
  }, [])

  const closeInspector = () => {
    startTransition(() => setIsInspectorOpen(false))
    const trigger = lastEventTriggerRef.current
    if (trigger) {
      requestAnimationFrame(() => trigger.focus())
    }
  }

  const closeAddAccountModal = () => {
    if (addAccountMutation.isPending) {
      return
    }
    setIsAddAccountOpen(false)
    addAccountMutation.reset()
  }

  const closeAddAccountModalEffect = useEffectEvent(() => {
    closeAddAccountModal()
  })

  const handleCloseInspectorEffect = useEffectEvent(() => {
    closeInspector()
  })

  useEffect(() => {
    if (!isInspectorOpen && !isAddAccountOpen) {
      return undefined
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        if (isAddAccountOpen) {
          closeAddAccountModalEffect()
          return
        }
        handleCloseInspectorEffect()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isAddAccountOpen, isInspectorOpen])

  useEffect(() => {
    if (!isInspectorOpen && !isAddAccountOpen) {
      return undefined
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isAddAccountOpen, isInspectorOpen])

  const dashboard = dashboardQuery.data
  const eventsData = eventsQuery.data
  const events = eventsData ?? []
  const selectedEvent = detailQuery.data

  useEffect(() => {
    if (!eventsData?.length) {
      return
    }
    setLocalVotes((current) => {
      let changed = false
      const next = { ...current }
      for (const event of eventsData) {
        if (!(event.normalized_post_id in next) && event.feedback_vote !== undefined) {
          next[event.normalized_post_id] = event.feedback_vote
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [eventsData])

  useEffect(() => {
    persistStoredVotes(localVotes)
  }, [localVotes])

  const effectiveVotes: Record<number, EventFeedbackVote | null> = {}
  for (const event of events) {
    effectiveVotes[event.normalized_post_id] =
      event.normalized_post_id in localVotes ? localVotes[event.normalized_post_id] : event.feedback_vote
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>

      <div className="sr-only" aria-live="polite">
        {liveMessage}
      </div>

      <main id="content" className="dashboard">
        <div className="workbench-grid">
          <section className="queue-stage">
            <ManualTriggerPanel
              form={manualTriggerForm}
              result={manualTestMutation.data}
              isSubmitting={manualTestMutation.isPending}
              error={manualTestMutation.error}
              onSubmit={async (values) => {
                await manualTestMutation.mutateAsync({
                  handle: values.handle.trim().replace(/^@+/, '').toLowerCase(),
                  message: values.message.trim(),
                })
              }}
            />

            <EventQueue
              events={events}
              isLoading={eventsQuery.isLoading && !events.length}
              isError={eventsQuery.isError}
              error={eventsQuery.error}
              searchInput={searchInput}
              sourceFilter={sourceFilter}
              statusFilter={statusFilter}
              decisionFilter={decisionFilter}
              highlightedEventId={isInspectorOpen ? selectedEventId : null}
              onSearchChange={setSearchInput}
              onSourceChange={setSourceFilter}
              onStatusChange={setStatusFilter}
              onDecisionChange={setDecisionFilter}
              onClearFilters={() => {
                setSearchInput('')
                setSourceFilter('all')
                setStatusFilter('all')
                setDecisionFilter('all')
              }}
              onRetry={() => void eventsQuery.refetch()}
              onSelectEvent={(eventId, trigger) => {
                lastEventTriggerRef.current = trigger
                startTransition(() => setSelectedEventId(eventId))
                setIsInspectorOpen(true)
              }}
              onRefresh={async (eventId) => {
                setRefreshingEventId(eventId)
                try {
                  const updatedEvent = await refreshEventMutation.mutateAsync(eventId)
                  queryClient.setQueryData(['event', eventId], updatedEvent)
                } finally {
                  setRefreshingEventId((current) => (current === eventId ? null : current))
                }
              }}
              onDelete={async (eventId) => {
                setDeletingEventId(eventId)
                try {
                  await deleteEventMutation.mutateAsync(eventId)
                } finally {
                  setDeletingEventId((current) => (current === eventId ? null : current))
                }
              }}
              onVote={async (eventId, vote) => {
                try {
                  await voteMutation.mutateAsync({ eventId, vote })
                } catch {
                  return
                }
              }}
              votingEventId={votingEventId}
              refreshingEventId={refreshingEventId}
              deletingEventId={deletingEventId}
              effectiveVotes={effectiveVotes}
            />
          </section>

          <aside className="sidebar-stage">
            <section className="operations-grid">
              <Panel
                title="Connector health"
                eyebrow="Sources"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard?.connectors.length}
                emptyTitle="No connector status"
                emptyDescription="Connector health will appear here once the service starts."
              >
                <ConnectorHealthTable connectors={dashboard?.connectors ?? []} />
              </Panel>

              <Panel
                title="Tracked accounts"
                eyebrow="Accounts"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard?.accounts.length}
                emptyTitle="No accounts tracked"
                emptyDescription="Add an account to begin monitoring a new source."
                actions={
                  <>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setIsAddAccountOpen(true)}
                    >
                      Add account
                    </button>
                    {updateAccountMutation.isPending || deleteAccountMutation.isPending ? (
                      <span className="helper-text">
                        {deleteAccountMutation.isPending ? 'Removing account...' : 'Saving changes...'}
                      </span>
                    ) : null}
                  </>
                }
              >
                <TrackedAccountsList
                  accounts={dashboard?.accounts ?? []}
                  updatingAccountId={updatingAccountId}
                  deletingAccountId={deletingAccountId}
                  onUpdateAccount={async (accountId, payload) => {
                    setUpdatingAccountId(accountId)
                    try {
                      await updateAccountMutation.mutateAsync({ accountId, payload })
                    } finally {
                      setUpdatingAccountId((current) => (current === accountId ? null : current))
                    }
                  }}
                  onDeleteAccount={async (accountId) => {
                    setDeletingAccountId(accountId)
                    try {
                      await deleteAccountMutation.mutateAsync(accountId)
                    } finally {
                      setDeletingAccountId((current) => (current === accountId ? null : current))
                    }
                  }}
                />
              </Panel>

              <Panel
                title="Latency"
                eyebrow="Timing"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard || !hasLatencySamples(dashboard.latency)}
                emptyTitle="Latency is not available"
                emptyDescription="Latency samples appear once posts move through the full pipeline."
                actions={
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={resetLatencyMutation.isPending}
                    onClick={() => void resetLatencyMutation.mutateAsync()}
                  >
                    {resetLatencyMutation.isPending ? 'Resetting...' : 'Reset latency'}
                  </button>
                }
              >
                <LatencyTable latency={dashboard?.latency ?? {}} />
              </Panel>

              <Panel
                title="Cost"
                eyebrow="Usage"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard}
                emptyTitle="Cost data is not available"
                emptyDescription="OpenAI and X usage metrics will appear after the service records activity."
              >
                {dashboard ? <CostSummary dashboard={dashboard} /> : null}
              </Panel>

              <Panel
                title="Recent activity"
                eyebrow="Operations"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard?.activity.length}
                emptyTitle="No activity yet"
                emptyDescription="Service activity will appear here once the system starts processing work."
                actions={
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={clearActivityMutation.isPending}
                    onClick={() => void clearActivityMutation.mutateAsync()}
                  >
                    {clearActivityMutation.isPending ? 'Clearing...' : 'Clear'}
                  </button>
                }
              >
                <OperationalFeed items={dashboard?.activity ?? []} kind="activity" />
              </Panel>

              <Panel
                title="Attention required"
                eyebrow="Warnings"
                loading={dashboardQuery.isLoading && !dashboard}
                empty={!dashboard?.attention.length}
                emptyTitle="No active warnings"
                emptyDescription="Warnings and errors will be listed here when operator attention is needed."
                actions={
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={clearAttentionMutation.isPending}
                    onClick={() => void clearAttentionMutation.mutateAsync()}
                  >
                    {clearAttentionMutation.isPending ? 'Clearing...' : 'Clear'}
                  </button>
                }
              >
                <OperationalFeed items={dashboard?.attention ?? []} kind="attention" />
              </Panel>
            </section>
          </aside>
        </div>
      </main>

      <EventInspectorDrawer
        isOpen={isInspectorOpen}
        selectedEventId={selectedEventId}
        event={selectedEvent}
        isLoading={detailQuery.isLoading && !selectedEvent}
        isError={detailQuery.isError}
        error={detailQuery.error}
        onRetry={() => void detailQuery.refetch()}
        onClose={closeInspector}
      />

      <AddAccountDrawer
        isOpen={isAddAccountOpen}
        isSubmitting={addAccountMutation.isPending}
        error={addAccountMutation.error}
        onClose={closeAddAccountModal}
        onSubmit={async (values) => {
          const normalizedHandle = values.handle.trim().replace(/^@+/, '').toLowerCase()
          await addAccountMutation.mutateAsync({
            source: values.source,
            entity_key: buildEntityKey(values.display_name, normalizedHandle),
            display_name: values.display_name.trim(),
            handle: normalizedHandle,
            authority_rank: Number(values.authority_rank),
            alert_threshold: values.alert_threshold.trim() === '' ? undefined : Number(values.alert_threshold),
          })
        }}
      />
    </div>
  )
}

function ManualTriggerPanel({
  form,
  result,
  isSubmitting,
  error,
  onSubmit,
}: {
  form: UseFormReturn<ManualTriggerFormValues>
  result?: ManualEventTestResult
  isSubmitting: boolean
  error: unknown
  onSubmit: (values: ManualTriggerFormValues) => Promise<void>
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = form

  return (
    <section className="panel trigger-panel">
      <form className="trigger-panel-form" onSubmit={handleSubmit(onSubmit)}>
        <label className="field trigger-handle-field">
          <span>Handle</span>
          <input type="text" placeholder="@tracked_handle" autoComplete="off" {...register('handle')} />
          {errors.handle ? <small>{errors.handle.message}</small> : null}
        </label>

        <label className="field trigger-message-field">
          <span>Message</span>
          <input type="text" placeholder="Paste the post text you want to test." autoComplete="off" {...register('message')} />
          {errors.message ? <small>{errors.message.message}</small> : null}
        </label>

        <div className="trigger-panel-actions">
          <button type="submit" className="button button-primary" disabled={isSubmitting}>
            {isSubmitting ? 'Testing...' : 'Run test'}
          </button>
        </div>
      </form>

      {error ? (
        <StateNotice tone="danger" title="Manual trigger failed" description={readApiError(error)} />
      ) : result ? (
        <article className="trigger-result-card" aria-live="polite">
          <div className="trigger-result-header">
            <div>
              <div className="event-card-meta">
                <Badge tone="neutral">{formatSourceLabel(result.account.source)}</Badge>
                <Badge tone={statusTone(result.outcome.status)} className={statusBadgeClass(result.outcome.status)}>
                  {formatStatusLabel(result.outcome.status)}
                </Badge>
                <Badge tone={statusTone(result.analysis.decision)}>{formatStatusLabel(result.analysis.decision)}</Badge>
              </div>
              <h3>{result.analysis.summary}</h3>
              <p className="detail-copy">
                {result.account.display_name} (@{result.account.handle}) · threshold {result.analysis.threshold} ·{' '}
                {formatStatusLabel(result.analysis.mode)}
              </p>
            </div>

            <div className="trigger-result-score">
              <strong>{result.analysis.total_score.toFixed(1)}</strong>
              <span>Score</span>
            </div>
          </div>

          <p className="trigger-result-message">{result.outcome.message_text}</p>
          {result.analysis.categories.length ? (
            <p className="detail-meta-line">{formatCategoryLine(result.analysis.categories)}</p>
          ) : null}
          <p className="detail-copy">{result.analysis.reasoning}</p>
        </article>
      ) : null}
    </section>
  )
}

function EventQueue({
  events,
  isLoading,
  isError,
  error,
  searchInput,
  sourceFilter,
  statusFilter,
  decisionFilter,
  highlightedEventId,
  onSearchChange,
  onSourceChange,
  onStatusChange,
  onDecisionChange,
  onClearFilters,
  onRetry,
  onSelectEvent,
  onRefresh,
  onDelete,
  onVote,
  votingEventId,
  refreshingEventId,
  deletingEventId,
  effectiveVotes,
}: {
  events: EventListItem[]
  isLoading: boolean
  isError: boolean
  error: unknown
  searchInput: string
  sourceFilter: 'all' | 'x' | 'truth_social'
  statusFilter: string
  decisionFilter: string
  highlightedEventId: number | null
  onSearchChange: (value: string) => void
  onSourceChange: (value: 'all' | 'x' | 'truth_social') => void
  onStatusChange: (value: string) => void
  onDecisionChange: (value: string) => void
  onClearFilters: () => void
  onRetry: () => void
  onSelectEvent: (eventId: number, trigger: HTMLButtonElement) => void
  onRefresh: (eventId: number) => Promise<void>
  onDelete: (eventId: number) => Promise<void>
  onVote: (eventId: number, vote: EventFeedbackVote | null) => Promise<void>
  votingEventId: number | null
  refreshingEventId: number | null
  deletingEventId: number | null
  effectiveVotes: Record<number, EventFeedbackVote | null>
}) {
  return (
    <section className="panel queue-panel">
      <div className="queue-heading">
        <div>
          <h2 className="section-heading">{formatSectionHeading('Primary queue', 'Recent events')}</h2>
        </div>

        <div className="queue-summary">
          <strong>{formatCompactNumber(events.length)}</strong>
          <span>items</span>
        </div>
      </div>

      <form className="queue-toolbar" onSubmit={(event) => event.preventDefault()}>
        <label className="field field-search">
          <span>Search</span>
          <input
            type="search"
            aria-label="Search"
            placeholder="Search actor, summary, or post text"
            value={searchInput}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>

        <label className="field">
          <span>Source</span>
          <select value={sourceFilter} onChange={(event) => onSourceChange(event.target.value as typeof sourceFilter)}>
            <option value="all">All sources</option>
            <option value="x">X</option>
            <option value="truth_social">Truth Social</option>
          </select>
        </label>

        <label className="field">
          <span>Status</span>
          <select value={statusFilter} onChange={(event) => onStatusChange(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="sent">Sent</option>
            <option value="dry_run">Dry run</option>
            <option value="suppressed">Suppressed</option>
            <option value="failed">Failed</option>
          </select>
        </label>

        <label className="field">
          <span>Decision</span>
          <select value={decisionFilter} onChange={(event) => onDecisionChange(event.target.value)}>
            <option value="all">All decisions</option>
            <option value="alerted">Alerted</option>
            <option value="below_threshold">Below threshold</option>
            <option value="historical_backfill">Backfill only</option>
            <option value="suppressed_recent_duplicate">Duplicate suppressed</option>
            <option value="more_authoritative_than_recent_duplicate">More authoritative duplicate</option>
            <option value="score_materially_higher_than_recent_duplicate">Higher-scoring duplicate</option>
            <option value="alert_failed">Alert failed</option>
          </select>
        </label>

        <button type="button" className="button button-secondary queue-toolbar-action" onClick={onClearFilters}>
          Reset filters
        </button>
      </form>

      {isLoading ? (
        <ul className="event-list" aria-label="Loading events">
          {Array.from({ length: 4 }).map((_, index) => (
            <li key={index} className="event-item skeleton-item" />
          ))}
        </ul>
      ) : isError ? (
        <StateNotice
          tone="danger"
          title="Events could not be loaded"
          description={readApiError(error)}
          actionLabel="Retry"
          onAction={onRetry}
        />
      ) : events.length === 0 ? (
        <StateNotice
          tone="neutral"
          title="No events match these filters"
          description="Try widening the filters or reset the search query."
        />
      ) : (
        <ul className="event-list">
          <li className="queue-columns" aria-hidden="true">
            <span>Actions</span>
            <span>Source</span>
            <span>Actor</span>
            <span>Event</span>
            <span>Status</span>
            <span>Score</span>
            <span>Published</span>
            <span>Vote</span>
          </li>
          {events.map((event) => (
            <li key={event.normalized_post_id}>
              <article className={`event-row ${highlightedEventId === event.normalized_post_id ? 'is-selected' : ''}`}>
                <EventActionControls
                  event={event}
                  isRefreshing={refreshingEventId === event.normalized_post_id}
                  isDeleting={deletingEventId === event.normalized_post_id}
                  onRefresh={onRefresh}
                  onDelete={onDelete}
                />
                <button
                  type="button"
                  className={`event-card ${highlightedEventId === event.normalized_post_id ? 'is-selected' : ''}`}
                  aria-expanded={highlightedEventId === event.normalized_post_id}
                  aria-controls="event-inspector"
                  onClick={(clickEvent) => onSelectEvent(event.normalized_post_id, clickEvent.currentTarget)}
                >
                  <div className="event-cell event-cell-source">
                    <Badge tone="neutral" className="badge-queue-source">
                      {formatSourceLabel(event.source)}
                    </Badge>
                    <span>{formatRelativeTime(event.observed_at)}</span>
                  </div>

                  <div className="event-cell event-cell-actor">
                    <strong>{event.display_name}</strong>
                    <span>@{event.handle}</span>
                  </div>

                  <div className="event-cell event-cell-summary">
                    <h3>{event.summary || event.text}</h3>
                    <span>{formatEventMetaLine(event)}</span>
                  </div>

                  <div className="event-cell event-cell-status">
                    {(() => {
                      const statusValue = event.alert_status ?? event.decision
                      const badgeClass = statusBadgeClass(statusValue)
                      return (
                    <Badge
                      tone={statusTone(statusValue)}
                      className={`badge-queue-status${badgeClass ? ` ${badgeClass}` : ''}`}
                    >
                      {formatStatusLabel(statusValue ?? 'pending')}
                    </Badge>
                      )
                    })()}
                  </div>

                  <div className="event-cell event-cell-score">
                    <strong>{event.total_score ? event.total_score.toFixed(1) : 'Pending'}</strong>
                  </div>

                  <div className="event-cell event-cell-published">
                    <strong>{formatDateTime(event.published_at)}</strong>
                  </div>
                </button>

                <EventVoteControls
                  event={event}
                  selectedVote={effectiveVotes[event.normalized_post_id]}
                  isPending={votingEventId === event.normalized_post_id}
                  onVote={onVote}
                />
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function EventActionControls({
  event,
  isRefreshing,
  isDeleting,
  onRefresh,
  onDelete,
}: {
  event: EventListItem
  isRefreshing: boolean
  isDeleting: boolean
  onRefresh: (eventId: number) => Promise<void>
  onDelete: (eventId: number) => Promise<void>
}) {
  const isBusy = isRefreshing || isDeleting

  return (
    <div className="event-action-stack" aria-label="Event actions">
      <button
        type="button"
        className="action-button action-button-reload"
        aria-label={`Reload ${event.display_name} event`}
        title="Re-run this event live and ignore duplicate suppression."
        disabled={isBusy}
        onClick={() => void onRefresh(event.normalized_post_id)}
      >
        <ActionIcon kind="reload" />
      </button>

      <button
        type="button"
        className="action-button action-button-delete"
        aria-label={`Delete ${event.display_name} event`}
        title="Delete this stored event."
        disabled={isBusy}
        onClick={() => {
          if (!window.confirm(`Delete the stored event for ${event.display_name}?`)) {
            return
          }
          void onDelete(event.normalized_post_id)
        }}
      >
        <ActionIcon kind="delete" />
      </button>
    </div>
  )
}

function EventVoteControls({
  event,
  selectedVote,
  isPending,
  onVote,
}: {
  event: EventListItem
  selectedVote: EventFeedbackVote | null | undefined
  isPending: boolean
  onVote: (eventId: number, vote: EventFeedbackVote | null) => Promise<void>
}) {
  return (
    <div className="event-vote-stack" aria-label="Event feedback controls">
      <button
        type="button"
        className={`vote-button vote-button-up ${selectedVote === 'up' ? 'is-active' : ''}`}
        aria-label={`Upvote ${event.display_name} event`}
        aria-pressed={selectedVote === 'up'}
        disabled={isPending}
        onClick={() => void onVote(event.normalized_post_id, selectedVote === 'up' ? null : 'up')}
      >
        <ThumbIcon direction="up" filled={selectedVote === 'up'} />
      </button>

      <button
        type="button"
        className={`vote-button vote-button-down ${selectedVote === 'down' ? 'is-active' : ''}`}
        aria-label={`Downvote ${event.display_name} event`}
        aria-pressed={selectedVote === 'down'}
        disabled={isPending}
        onClick={() => void onVote(event.normalized_post_id, selectedVote === 'down' ? null : 'down')}
      >
        <ThumbIcon direction="down" filled={selectedVote === 'down'} />
      </button>
    </div>
  )
}

function ActionIcon({ kind }: { kind: 'reload' | 'delete' }) {
  if (kind === 'reload') {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="action-icon action-icon-reload"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M17 8a7 7 0 1 0 1.57 7.24" />
        <path d="M17 4.5V9h-4.5" />
      </svg>
    )
  }

  return (
      <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="action-icon action-icon-delete"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" />
      <path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3" />
    </svg>
  )
}

function EventInspectorDrawer({
  isOpen,
  selectedEventId,
  event,
  isLoading,
  isError,
  error,
  onRetry,
  onClose,
}: {
  isOpen: boolean
  selectedEventId: number | null
  event?: EventDetail
  isLoading: boolean
  isError: boolean
  error: unknown
  onRetry: () => void
  onClose: () => void
}) {
  if (!isOpen) {
    return null
  }

  return (
    <div className="overlay-backdrop overlay-backdrop-inspector" role="presentation" onClick={onClose}>
      <section
        id="event-inspector"
        className="inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-inspector-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-heading">
          <div>
            <h2 id="event-inspector-title" className="section-heading">
              {formatSectionHeading('Selected event', 'Event inspector')}
            </h2>
          </div>

          <div className="drawer-heading-actions">
            {event?.canonical_url ? (
              <a className="button button-secondary" href={event.canonical_url} target="_blank" rel="noreferrer">
                Open source
              </a>
            ) : null}

            <button type="button" className="button button-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {selectedEventId === null ? (
          <StateNotice
            tone="neutral"
            title="Select an event"
            description="Choose an item from the queue to inspect the scoring, relay outcome, and source content."
          />
        ) : isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <StateNotice
            tone="danger"
            title="Event detail could not be loaded"
            description={readApiError(error)}
            actionLabel="Retry"
            onAction={onRetry}
          />
        ) : event ? (
          <DetailContent event={event} />
        ) : null}
      </section>
    </div>
  )
}

function Panel({
  title,
  eyebrow,
  loading,
  empty,
  emptyTitle,
  emptyDescription,
  actions,
  children,
}: {
  title: string
  eyebrow: string
  loading: boolean
  empty: boolean
  emptyTitle: string
  emptyDescription: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2 className="section-heading">{formatSectionHeading(eyebrow, title)}</h2>
        </div>
        {actions ? <div className="panel-heading-actions">{actions}</div> : null}
      </div>

      {loading ? (
        <div className="stack-list">
          <div className="stack-card skeleton-item panel-skeleton" />
          <div className="stack-card skeleton-item panel-skeleton" />
        </div>
      ) : empty ? (
        <StateNotice tone="neutral" title={emptyTitle} description={emptyDescription} />
      ) : (
        children
      )}
    </section>
  )
}

function ConnectorHealthTable({ connectors }: { connectors: DashboardData['connectors'] }) {
  return (
    <div className="panel-table connector-table" role="table" aria-label="Connector health">
      <div className="panel-table-header connector-table-layout" aria-hidden="true">
        <span>Source</span>
        <span>State</span>
        <span>Auth</span>
        <span>Last success</span>
        <span>Detail</span>
      </div>
      <div className="panel-table-body">
        {connectors.map((connector) => (
          <article key={connector.name} className="panel-table-row connector-table-layout">
            <div className="table-cell table-cell-primary">
              <strong>{formatSourceLabel(connector.name)}</strong>
            </div>
            <div className="table-cell table-cell-status">
              <Badge tone={connector.running ? 'success' : connector.auth_configured ? 'warning' : 'danger'}>
                {connector.running ? 'Running' : connector.auth_configured ? 'Waiting' : 'Blocked'}
              </Badge>
            </div>
            <div className="table-cell">{connector.auth_configured ? 'Configured' : 'Missing'}</div>
            <div className="table-cell">{connector.last_success_at ? formatRelativeTime(connector.last_success_at) : 'No data'}</div>
            <div className="table-cell table-cell-detail">{formatConnectorDetail(connector.detail || connector.last_error)}</div>
          </article>
        ))}
      </div>
    </div>
  )
}

function OperationalFeed({
  items,
  kind,
}: {
  items: ActivityItem[]
  kind: 'attention' | 'activity'
}) {
  const heading = kind === 'attention' ? 'Attention required' : 'Recent activity'
  const rows = kind === 'activity' ? mergeOperationalItems(items) : items.map((item) => ({ ...item, duplicate_count: 1 }))
  return (
    <div className="panel-table feed-table" role="table" aria-label={heading}>
      <div className="panel-table-header feed-table-layout" aria-hidden="true">
        <span>{kind === 'attention' ? 'Incident' : 'Activity'}</span>
        <span>Component</span>
        <span>Level</span>
        <span>Time</span>
      </div>
      <div className="panel-table-body">
        {rows.map((item) => (
          <article key={item.id} className="panel-table-row feed-table-layout">
            <div className="table-cell table-cell-primary table-cell-feed">
              <strong>{item.title}</strong>
              <span>{item.message}</span>
            </div>
            <div className="table-cell">{humanizeComponentName(item.component)}</div>
            <div className="table-cell table-cell-status">
              <Badge tone={item.level === 'error' ? 'danger' : item.level === 'warning' ? 'warning' : 'neutral'}>
                {formatStatusLabel(item.level)}
              </Badge>
            </div>
            <div className="table-cell">{formatRelativeTime(item.created_at)}</div>
          </article>
        ))}
      </div>
    </div>
  )
}

function LatencyTable({ latency }: { latency: DashboardData['latency'] }) {
  const entries = LATENCY_METRIC_ORDER.map((key) => ({
    key,
    stats: latency[key] ?? EMPTY_DISTRIBUTION,
    copy: getLatencyMetricCopy(key),
  })).filter(({ stats }) => stats.count > 0)

  return (
    <div className="panel-table latency-table" role="table" aria-label="Latency metrics">
      <div className="panel-table-header latency-table-layout" aria-hidden="true">
        <span>Stage</span>
        <span>What it covers</span>
        <span>Typical (P50)</span>
        <span>Slow case (P95)</span>
        <span>Samples</span>
      </div>
      <div className="panel-table-body">
        {entries.map(({ key, stats, copy }) => (
          <article key={key} className="panel-table-row latency-table-layout">
            <div className="table-cell table-cell-primary">
              <strong>{copy.label}</strong>
            </div>
            <div className="table-cell table-cell-latency-description">{copy.description}</div>
            <div className="table-cell table-cell-latency-value">
              <span className={formatLatencyCellClass(key, stats.p50, stats.count)}>
                {stats.count ? formatLatencyValue(stats.p50) : 'No data'}
              </span>
            </div>
            <div className="table-cell table-cell-latency-value">
              <span className={formatLatencyCellClass(key, stats.p95, stats.count)}>
                {stats.count ? formatLatencyValue(stats.p95) : 'No data'}
              </span>
            </div>
            <div className="table-cell table-cell-latency-samples">{formatCompactNumber(stats.count)}</div>
          </article>
        ))}
      </div>
    </div>
  )
}

function getLatencyMetricCopy(key: (typeof LATENCY_METRIC_ORDER)[number]): { label: string; description: string } {
  const copy: Record<(typeof LATENCY_METRIC_ORDER)[number], { label: string; description: string }> = {
    source_to_observed_seconds: {
      label: 'Collector lag',
      description: 'Time from the original post timestamp to when Event Radar sees it.',
    },
    observed_to_persisted_seconds: {
      label: 'Persistence',
      description: 'Collector overhead before the event is durably written to SQLite.',
    },
    persisted_to_classification_seconds: {
      label: 'Classification',
      description: 'OpenAI scoring and persistence after the post is stored.',
    },
    classification_to_relay_seconds: {
      label: 'Relay delivery',
      description: 'Time from finished classification to Telegram acknowledgement.',
    },
    end_to_end_seconds: {
      label: 'End to end',
      description: 'Full elapsed time from source publish to relay acknowledgement.',
    },
  }

  return copy[key]
}

function DetailContent({ event }: { event: EventDetail }) {
  const breakdown = event.analysis?.breakdown
  const categories = event.analysis?.categories ?? []

  return (
    <div className="detail-content">
      <div className="detail-header">
        <div className="event-card-meta">
          <Badge tone="neutral">{formatSourceLabel(event.source)}</Badge>
          {event.alert ? (
            <Badge
              tone={statusTone(event.alert.status)}
              className={statusBadgeClass(event.alert.status)}
            >
              {formatStatusLabel(event.alert.status)}
            </Badge>
          ) : null}
        </div>

        <h3>{event.analysis?.summary || event.text}</h3>
        <p className="detail-copy">{event.text}</p>

        {categories.length ? <p className="detail-meta-line">{formatCategoryLine(categories)}</p> : null}
      </div>

      <dl className="detail-stats">
        <div>
          <dt>Actor</dt>
          <dd>
            {event.display_name}
            <span>@{event.handle}</span>
          </dd>
        </div>
        <div>
          <dt>Score</dt>
          <dd>{event.analysis?.total_score ? event.analysis.total_score.toFixed(1) : 'Pending'}</dd>
        </div>
        <div>
          <dt>Decision</dt>
          <dd>{formatStatusLabel(event.analysis?.decision ?? event.alert?.status ?? 'pending')}</dd>
        </div>
        <div>
          <dt>Observed</dt>
          <dd>{formatDateTime(event.observed_at)}</dd>
        </div>
      </dl>

      <section className="detail-section">
        <h4>Reasoning</h4>
        <p>{event.analysis?.reasoning || 'Reasoning is not available for this item yet.'}</p>
      </section>

      <section className="detail-section">
        <h4>Breakdown</h4>
        {breakdown ? (
          <div className="breakdown-list">
            {Object.entries(breakdown).map(([key, value]) => (
              <div key={key} className="breakdown-row">
                <span>{humanizeMetricKey(key)}</span>
                <strong>{value}/100</strong>
              </div>
            ))}
          </div>
        ) : (
          <p>Breakdown is not available.</p>
        )}
      </section>

      <section className="detail-section">
        <h4>Relay outcome</h4>
        {event.alert ? (
          <dl className="detail-inline-list">
            <div>
              <dt>Status</dt>
              <dd>{formatStatusLabel(event.alert.status)}</dd>
            </div>
            <div>
              <dt>Message</dt>
              <dd>{event.alert.message_text}</dd>
            </div>
            <div>
              <dt>Suppression</dt>
              <dd>{event.alert.suppression_reason || 'None'}</dd>
            </div>
          </dl>
        ) : (
          <p>No alert record is available for this event yet.</p>
        )}
      </section>

      <section className="detail-section">
        <h4>Timing</h4>
        <dl className="detail-inline-list">
          <div>
            <dt>Published</dt>
            <dd>{formatDateTime(event.published_at)}</dd>
          </div>
          <div>
            <dt>Persisted</dt>
            <dd>{formatDateTime(event.latency.persisted_at)}</dd>
          </div>
          <div>
            <dt>Classified</dt>
            <dd>{formatDateTime(event.latency.classification_finished_at)}</dd>
          </div>
          <div>
            <dt>Relayed</dt>
            <dd>{formatDateTime(event.latency.relay_acked_at)}</dd>
          </div>
        </dl>
      </section>

      {(event.links.length || event.media_urls.length) && (
        <section className="detail-section">
          <h4>Linked content</h4>
          <ul className="link-list">
            {[event.canonical_url, ...event.links, ...event.media_urls]
              .filter((value, index, array): value is string => Boolean(value) && array.indexOf(value) === index)
              .map((url) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer">
                    {url}
                  </a>
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function CostSummary({ dashboard }: { dashboard: DashboardData }) {
  const costs = normalizeCostSummary(dashboard.costs as DashboardData['costs'] | Record<string, unknown>)
  const openai = costs.openai
  const xUsage = costs.x
  const showAvailableCredit = openai.credit.status === 'ok' && openai.credit.available_credit_eur !== null
  const showBilledCosts = openai.billed_costs.status === 'ok'
  const openaiNotes = [
    openai.usage.status !== 'ok'
      ? `Key-specific OpenAI usage is unavailable right now: ${humanizeMetricKey(openai.usage.reason || 'unknown')}`
      : null,
    openai.billed_costs.status !== 'ok' ? formatOpenAIBilledCostNote(openai) : null,
  ].filter((note): note is string => Boolean(note))
  const xNotes = [
    xUsage.official_usage.status !== 'ok'
      ? `Official X usage is unavailable right now: ${humanizeMetricKey(xUsage.official_usage.reason || 'unknown')}`
      : null,
  ].filter((note): note is string => Boolean(note))

  return (
    <div className="cost-provider-grid">
      <section className="cost-provider">
        <div className="cost-provider-header">
          <h3>OpenAI</h3>
        </div>
        {openaiNotes.length ? (
          <div className="cost-provider-notes">
            {openaiNotes.map((note) => (
              <p key={note} className="cost-provider-note">
                {note}
              </p>
            ))}
          </div>
        ) : null}
        <dl className="summary-grid">
          {showBilledCosts ? (
            <div>
              <dt>Billed 7d</dt>
              <dd>{formatCurrency(openai.billed_costs.billed_last_7d_eur)}</dd>
            </div>
          ) : null}
          {showBilledCosts ? (
            <div>
              <dt>Billed 30d</dt>
              <dd>{formatCurrency(openai.billed_costs.billed_last_30d_eur)}</dd>
            </div>
          ) : null}
          <div>
            <dt>Requests 7d</dt>
            <dd>{formatCompactNumber(openai.usage.last_7d.analysis_count)}</dd>
          </div>
          <div>
            <dt>Requests 30d</dt>
            <dd>{formatCompactNumber(openai.usage.last_30d.analysis_count)}</dd>
          </div>
          <div>
            <dt>Avg tokens / req 7d</dt>
            <dd>{formatTokenAverage(openai.usage.last_7d.average_total_tokens_per_request)}</dd>
          </div>
          <div>
            <dt>Avg tokens / req 30d</dt>
            <dd>{formatTokenAverage(openai.usage.last_30d.average_total_tokens_per_request)}</dd>
          </div>
          <div>
            <dt>Tracked spend 7d</dt>
            <dd>{formatCurrency(openai.costs.estimated_last_7d_eur)}</dd>
          </div>
          <div>
            <dt>Tracked spend 30d</dt>
            <dd>{formatCurrency(openai.costs.estimated_last_30d_eur)}</dd>
          </div>
          <div>
            <dt>Tracked month run-rate</dt>
            <dd>{formatCurrency(openai.costs.projected_monthly_cost_eur)}</dd>
          </div>
          {showAvailableCredit ? (
            <div>
              <dt>Global credit</dt>
              <dd>{formatCurrency(openai.credit.available_credit_eur)}</dd>
            </div>
          ) : null}
          <div>
            <dt>Model</dt>
            <dd>{openai.model}</dd>
          </div>
        </dl>
      </section>

      <section className="cost-provider">
        <div className="cost-provider-header">
          <h3>X</h3>
        </div>
        {xNotes.length ? (
          <div className="cost-provider-notes">
            {xNotes.map((note) => (
              <p key={note} className="cost-provider-note">
                {note}
              </p>
            ))}
          </div>
        ) : null}
        <dl className="summary-grid">
          <div>
            <dt>Post reads 7d</dt>
            <dd>{formatCountMetric(xUsage.official_usage.consumed_last_7d)}</dd>
          </div>
          <div>
            <dt>Post reads 30d</dt>
            <dd>{formatCountMetric(xUsage.official_usage.consumed_last_30d)}</dd>
          </div>
          <div>
            <dt>Billing cycle total</dt>
            <dd>{formatCountMetric(xUsage.official_usage.project_usage)}</dd>
          </div>
          <div>
            <dt>Read requests 7d</dt>
            <dd>{formatCompactNumber(xUsage.local_usage.read_requests_last_7d)}</dd>
          </div>
          <div>
            <dt>Read requests 30d</dt>
            <dd>{formatCompactNumber(xUsage.local_usage.read_requests_last_30d)}</dd>
          </div>
        </dl>
      </section>
    </div>
  )
}

function TrackedAccountsList({
  accounts,
  updatingAccountId,
  deletingAccountId,
  onUpdateAccount,
  onDeleteAccount,
}: {
  accounts: Account[]
  updatingAccountId: string | null
  deletingAccountId: string | null
  onUpdateAccount: (accountId: string, payload: UpdateAccountPayload) => Promise<void>
  onDeleteAccount: (accountId: string) => Promise<void>
}) {
  const sortedAccounts = [...accounts].sort((left, right) => {
    if (right.authority_rank !== left.authority_rank) {
      return right.authority_rank - left.authority_rank
    }
    return `${left.display_name}:${left.handle}`.localeCompare(`${right.display_name}:${right.handle}`)
  })

  return (
    <div className="panel-table account-table" role="table" aria-label="Tracked accounts">
      <div className="panel-table-header account-table-layout" aria-hidden="true">
        <span>Source</span>
        <span>Account</span>
        <span>Handle</span>
        <span>Authority</span>
        <span>Threshold</span>
        <span>Status</span>
        <span>Actions</span>
      </div>
      <div className="panel-table-body">
        {sortedAccounts.map((account) => (
          <AccountRow
            key={`${account.id}:${account.updated_at}`}
            account={account}
            isUpdating={updatingAccountId === account.id}
            isDeleting={deletingAccountId === account.id}
            onUpdate={(payload) => onUpdateAccount(account.id, payload)}
            onDelete={() => onDeleteAccount(account.id)}
          />
        ))}
      </div>
    </div>
  )
}

function AccountRow({
  account,
  isUpdating,
  isDeleting,
  onUpdate,
  onDelete,
}: {
  account: Account
  isUpdating: boolean
  isDeleting: boolean
  onUpdate: (payload: UpdateAccountPayload) => Promise<void>
  onDelete: () => Promise<void>
}) {
  const persistedThreshold = account.alert_threshold === null ? '' : String(account.alert_threshold)
  const [threshold, setThreshold] = useState(persistedThreshold)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const isSaving = isUpdating || isDeleting
  const validationError =
    threshold !== '' && (!/^\d+$/.test(threshold) || Number(threshold) < 0 || Number(threshold) > 100)
      ? 'Use 0 to 100 or leave blank.'
      : null

  useEffect(() => {
    if (!success) {
      return undefined
    }
    const timeout = window.setTimeout(() => {
      setSuccess(null)
    }, 1600)
    return () => window.clearTimeout(timeout)
  }, [success])

  const persistThreshold = useEffectEvent(async (nextThreshold: string) => {
    try {
      await onUpdate({ alert_threshold: nextThreshold === '' ? null : Number(nextThreshold) })
      setSuccess('Threshold saved automatically.')
    } catch (mutationError) {
      setError(readApiError(mutationError))
    }
  })

  useEffect(() => {
    if (isDeleting) {
      return undefined
    }
    if (threshold === persistedThreshold) {
      return undefined
    }
    if (validationError) {
      return undefined
    }
    if (isUpdating) {
      return undefined
    }

    const timeout = window.setTimeout(() => {
      void persistThreshold(threshold)
    }, 450)

    return () => window.clearTimeout(timeout)
  }, [isDeleting, isUpdating, persistedThreshold, threshold, validationError])

  const thresholdStatus = validationError ?? error ?? (isUpdating ? 'Saving threshold...' : success)

  function handleThresholdChange(value: string) {
    setThreshold(value)
    if (error) {
      setError(null)
    }
    if (success) {
      setSuccess(null)
    }
  }

  return (
    <article className="panel-table-row account-row">
      <div className="account-row-main account-table-layout">
        <div className="account-row-source">
          <Badge tone="neutral" className="badge-account-source">
            {formatSourceLabel(account.source)}
          </Badge>
        </div>
        <div className="account-row-actor">
          <strong>{account.display_name}</strong>
          <span>Updated {formatRelativeTime(account.updated_at)}</span>
        </div>
        <div className="account-row-handle">@{account.handle}</div>
        <div className="account-row-authority">{account.authority_rank}</div>
        <div className="account-row-threshold">
          <label className="field field-inline">
            <span className="sr-only">Alert threshold for {account.display_name}</span>
            <input
              aria-label={`Alert threshold for ${account.display_name}`}
              type="number"
              min="0"
              max="100"
              placeholder="Default"
              value={threshold}
              onChange={(event) => handleThresholdChange(event.target.value)}
              disabled={isSaving}
            />
          </label>
        </div>
        <div className="account-row-status">
          <Badge
            tone={account.active ? 'success' : 'neutral'}
            className={`badge-account-status${account.active ? '' : ' badge-account-status-paused'}`}
          >
            {account.active ? 'Active' : 'Paused'}
          </Badge>
        </div>
        <div className="account-row-actions">
          <button
            type="button"
            className="button button-secondary button-compact"
            disabled={isSaving}
            onClick={async () => {
              setError(null)
              setSuccess(null)
              try {
                await onUpdate({ active: !account.active })
                setSuccess(account.active ? 'Tracking paused.' : 'Tracking resumed.')
              } catch (mutationError) {
                setError(readApiError(mutationError))
              }
            }}
          >
            {account.active ? 'Pause' : 'Resume'}
          </button>
          <button
            type="button"
            className="button button-danger button-compact"
            disabled={isSaving}
            onClick={async () => {
              if (!window.confirm(`Remove ${account.display_name} from tracked accounts?`)) {
                return
              }
              setError(null)
              setSuccess(null)
              try {
                await onDelete()
              } catch (mutationError) {
                setError(readApiError(mutationError))
              }
            }}
          >
            {isDeleting ? 'Removing...' : 'Remove'}
          </button>
        </div>
      </div>

      {thresholdStatus ? (
        <p className={`inline-feedback ${error ? 'inline-feedback-danger' : 'inline-feedback-success'}`}>{thresholdStatus}</p>
      ) : null}
    </article>
  )
}

function AddAccountDrawer({
  isOpen,
  isSubmitting,
  error,
  onClose,
  onSubmit,
}: {
  isOpen: boolean
  isSubmitting: boolean
  error: unknown
  onClose: () => void
  onSubmit: (values: AddAccountFormValues) => Promise<void>
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddAccountFormValues>({
    resolver: zodResolver(addAccountSchema),
    defaultValues: {
      source: 'x',
      display_name: '',
      handle: '',
      authority_rank: 50,
      alert_threshold: '',
    },
  })

  useEffect(() => {
    if (!isOpen) {
      reset()
    }
  }, [isOpen, reset])

  if (!isOpen) {
    return null
  }

  return (
    <div className="overlay-backdrop overlay-backdrop-modal" role="presentation" onClick={onClose}>
      <section
        className="modal-drawer modal-window"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-account-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-heading">
          <div>
            <h2 id="add-account-title" className="section-heading">
              {formatSectionHeading('New account', 'Add tracked account')}
            </h2>
          </div>

          <button type="button" className="button button-secondary" onClick={onClose} disabled={isSubmitting}>
            Close
          </button>
        </div>

        <form
          className="drawer-form"
          onSubmit={handleSubmit(async (values) => {
            await onSubmit(values)
          })}
        >
          <label className="field">
            <span>Source</span>
            <select {...register('source')} disabled={isSubmitting}>
              <option value="x">X</option>
              <option value="truth_social">Truth Social</option>
            </select>
          </label>

          <label className="field">
            <span>Handle</span>
            <input {...register('handle')} disabled={isSubmitting} />
            {errors.handle ? <small>{errors.handle.message}</small> : null}
          </label>

          <label className="field">
            <span>Display name</span>
            <input {...register('display_name')} disabled={isSubmitting} />
            {errors.display_name ? <small>{errors.display_name.message}</small> : null}
          </label>

          <div className="field-row">
            <label className="field">
              <span>Authority</span>
              <input type="number" min="0" max="100" {...register('authority_rank')} disabled={isSubmitting} />
              {errors.authority_rank ? <small>{errors.authority_rank.message}</small> : null}
            </label>

            <label className="field">
              <span>Threshold</span>
              <input
                type="number"
                min="0"
                max="100"
                placeholder="Default"
                {...register('alert_threshold')}
                disabled={isSubmitting}
              />
              {errors.alert_threshold ? <small>{errors.alert_threshold.message}</small> : null}
            </label>
          </div>

          {error ? <p className="inline-feedback inline-feedback-danger">{readApiError(error)}</p> : null}

          <div className="drawer-actions">
            <button type="button" className="button button-secondary" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button type="submit" className="button button-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Adding account...' : 'Add account'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

function Badge({
  children,
  tone,
  className,
}: {
  children: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
  className?: string
}) {
  return <span className={`badge badge-${tone}${className ? ` ${className}` : ''}`}>{children}</span>
}

function StateNotice({
  title,
  description,
  tone,
  actionLabel,
  onAction,
}: {
  title: string
  description: string
  tone: 'neutral' | 'danger'
  actionLabel?: string
  onAction?: () => void
}) {
  return (
    <div className={`state-notice state-notice-${tone}`}>
      <strong>{title}</strong>
      <p>{description}</p>
      {actionLabel && onAction ? (
        <button type="button" className="button button-secondary" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  )
}

function ThumbIcon({ direction, filled }: { direction: 'up' | 'down'; filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={`thumb-icon thumb-icon-${direction}`}
      fill={filled ? 'currentColor' : 'none'}
      stroke={filled ? 'none' : 'currentColor'}
      strokeWidth={filled ? undefined : '1.8'}
      strokeLinecap={filled ? undefined : 'round'}
      strokeLinejoin={filled ? undefined : 'round'}
    >
      {filled ? (
        <path d="M3 10.75C3 9.78 3.78 9 4.75 9H7v10H4.75A1.75 1.75 0 0 1 3 17.25v-6.5Zm6 8.25V9.21l3.18-5.17A1.75 1.75 0 0 1 15.25 5v3h3.06c1.34 0 2.29 1.3 1.88 2.58l-1.92 6A2.5 2.5 0 0 1 15.89 19H9Z" />
      ) : (
        <path d="M4 10.75C4 10.33 4.33 10 4.75 10H7v8H4.75A.75.75 0 0 1 4 17.25v-6.5Zm5 7.25v-8.51l3.09-5.02A.75.75 0 0 1 13.5 4.86V9h4.81a.75.75 0 0 1 .72.98l-1.71 5.35A1.5 1.5 0 0 1 15.89 18H9Z" />
      )}
    </svg>
  )
}

function DetailSkeleton() {
  return (
    <div className="detail-content" aria-hidden="true">
      <div className="skeleton-item detail-skeleton detail-skeleton-hero" />
      <div className="skeleton-item detail-skeleton" />
      <div className="skeleton-item detail-skeleton" />
      <div className="skeleton-item detail-skeleton" />
    </div>
  )
}

function statusTone(value?: string | null): 'success' | 'warning' | 'danger' | 'neutral' {
  if (!value) return 'neutral'
  if (['sent', 'dry_run', 'alerted', 'ok', 'running', 'would_notify'].includes(value)) {
    return 'success'
  }
  if (['failed', 'error', 'forbidden', 'blocked'].includes(value)) return 'danger'
  if (['warning', 'below_threshold', 'historical_backfill', 'reconnecting'].includes(value)) return 'warning'
  return 'neutral'
}

function humanizeMetricKey(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function formatLatencyCellClass(metricKey: string, value: number | null, count: number): string {
  const classes = ['latency-value']
  if (!count || value === null) {
    classes.push('latency-value-muted')
    return classes.join(' ')
  }

  const thresholds: Record<string, { warning: number; danger: number }> = {
    source_to_observed_seconds: { warning: 3600, danger: 86400 },
    observed_to_persisted_seconds: { warning: 5, danger: 30 },
    persisted_to_classification_seconds: { warning: 10, danger: 30 },
    classification_to_relay_seconds: { warning: 5, danger: 30 },
    end_to_end_seconds: { warning: 300, danger: 1800 },
  }

  const threshold = thresholds[metricKey]
  if (!threshold) {
    return classes.join(' ')
  }
  if (value >= threshold.danger) {
    classes.push('latency-value-danger')
  } else if (value >= threshold.warning) {
    classes.push('latency-value-warning')
  }
  return classes.join(' ')
}

function humanizeComponentName(value: string): string {
  return formatStatusLabel(value)
}

function formatConnectorDetail(value: string | null | undefined): string {
  if (!value) return 'No recent detail'
  if (!/[_:]/.test(value)) return value

  const [prefix, suffix] = value.split(':', 2)
  const primary = formatStatusLabel(prefix)
  if (!suffix) return primary
  return `${primary}: ${suffix}`
}

function formatCategoryLine(categories: string[]): string {
  return categories.slice(0, 3).map((category) => formatStatusLabel(category)).join(' · ')
}

function formatEventMetaLine(event: EventListItem): string {
  if (event.categories.length) {
    return formatCategoryLine(event.categories)
  }

  if (event.reasoning) {
    return event.reasoning
  }

  return formatRelativeTime(event.observed_at)
}

function formatSectionHeading(prefix: string, title: string): string {
  return `${prefix} - ${title}`
}

function formatTokenAverage(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'No data'
  }
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: value >= 100 ? 0 : 1 }).format(value)} tokens`
}

function formatCountMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'Unavailable'
  }
  return formatCompactNumber(value)
}

function statusBadgeClass(value?: string | null): string | undefined {
  if (value === 'sent') {
    return 'badge-status-sent'
  }
  return undefined
}

function formatOpenAIBilledCostNote(openai: DashboardData['costs']['openai']): string {
  if (openai.billed_costs.reason === 'http_429') {
    return 'Official billed cost is temporarily rate-limited by OpenAI.'
  }

  if (openai.billed_costs.reason === 'http_400') {
    return 'Official billed cost is currently unavailable from OpenAI for this project.'
  }

  if (openai.billed_costs.reason === 'configured_project_no_recent_activity') {
    return 'Using Event Radar tracked spend from local analyses. Official billed project spend is not available yet for the configured OpenAI project.'
  }

  if ((openai.scope.project_api_key_count ?? 0) > 1) {
    return 'Official billed cost is hidden because this project still has multiple API keys.'
  }

  return 'Official billed cost is currently unavailable from OpenAI for this project.'
}

function mergeOperationalItems(items: ActivityItem[]): Array<ActivityItem & { duplicate_count: number }> {
  const merged = new Map<string, ActivityItem & { duplicate_count: number }>()

  for (const item of items) {
    const key = [item.kind, item.level, item.component, item.title, item.message].join('::')
    const existing = merged.get(key)
    if (existing) {
      existing.duplicate_count += 1
      continue
    }
    merged.set(key, { ...item, duplicate_count: 1 })
  }

  return Array.from(merged.values())
}

function normalizeCostSummary(raw: DashboardData['costs'] | Record<string, unknown>): DashboardData['costs'] {
  const costs = raw as Record<string, unknown> & {
    openai?: DashboardData['costs']['openai']
    x?: DashboardData['costs']['x']
    fx?: DashboardData['costs']['fx']
    model?: string
    pricing?: DashboardData['costs']['openai']['pricing']
    usage?: {
      analysis_count?: number
      input_tokens?: number
      output_tokens?: number
      cached_input_tokens?: number
      request_cost_usd?: number
    }
    costs?: Record<string, unknown>
    organization_costs?: Record<string, unknown>
    credit?: DashboardData['costs']['openai']['credit']
  }

  if (costs.openai && costs.x) {
    return raw as DashboardData['costs']
  }

  const legacyUsage = costs.usage ?? {}
  const legacyCosts = (costs.costs ?? {}) as Record<string, unknown>
  const legacyAllTime = {
    analysis_count: Number(legacyUsage.analysis_count ?? 0),
    input_tokens: Number(legacyUsage.input_tokens ?? 0),
    output_tokens: Number(legacyUsage.output_tokens ?? 0),
    cached_input_tokens: Number(legacyUsage.cached_input_tokens ?? 0),
    request_cost_usd: Number(legacyUsage.request_cost_usd ?? 0),
    total_tokens: Number(legacyUsage.input_tokens ?? 0) + Number(legacyUsage.output_tokens ?? 0),
    average_total_tokens_per_request: null,
    average_input_tokens_per_request: null,
    average_output_tokens_per_request: null,
    first_analysis_at: null,
    last_analysis_at: null,
  }

  return {
    fx: costs.fx ?? { eur_per_usd: 0.8666, reference_date: 'fallback' },
    openai: {
      model: costs.model ?? 'Unavailable',
      scope: {
        status: 'unavailable',
        reason: 'service_restart_required',
        api_key_name: 'Event Radar',
        api_key_id: null,
        api_key_last_used_at: null,
        project_id: null,
        project_name: null,
        project_api_key_count: null,
      },
      pricing: costs.pricing ?? {
        input_cost_per_million_usd: 0,
        output_cost_per_million_usd: 0,
        cached_input_cost_per_million_usd: 0,
      },
      usage: {
        status: 'unavailable',
        reason: 'service_restart_required',
        last_7d: legacyAllTime,
        last_30d: legacyAllTime,
      },
      costs: {
        estimated_last_7d_usd: 0,
        estimated_last_7d_eur: 0,
        estimated_last_30d_usd: Number(legacyCosts.actual_total_cost_usd ?? 0),
        estimated_last_30d_eur: Number(legacyCosts.actual_total_cost_eur ?? 0),
        projected_monthly_cost_eur: Number(legacyCosts.projected_monthly_cost_eur ?? 0),
      },
      billed_costs: {
        status: 'unavailable',
        reason: 'api_key_cost_isolation_unavailable',
        billed_last_7d_usd: null,
        billed_last_7d_eur: null,
        billed_last_30d_usd: null,
        billed_last_30d_eur: null,
        window_days: null,
      },
      credit: costs.credit ?? {
        status: 'unavailable',
        reason: 'service_restart_required',
        available_credit_usd: null,
        available_credit_eur: null,
      },
    },
    x: {
      official_usage: {
        status: 'unavailable',
        reason: 'service_restart_required',
        project_id: null,
        project_cap: null,
        project_usage: null,
        cap_reset_day: null,
        consumed_last_7d: null,
        consumed_last_30d: null,
        daily_usage: [],
      },
      local_usage: {
        read_requests_last_7d: 0,
        read_requests_last_30d: 0,
        successful_read_requests_last_7d: 0,
        successful_read_requests_last_30d: 0,
      },
    },
  }
}

function buildEntityKey(displayName: string, normalizedHandle: string): string {
  const normalizedDisplay = displayName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return normalizedDisplay || normalizedHandle
}

function hasLatencySamples(latency: DashboardData['latency']): boolean {
  return Object.values(latency).some((metric) => metric.count > 0)
}

function readApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}

export default App
