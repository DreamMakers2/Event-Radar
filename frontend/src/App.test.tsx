import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

import App from './App'
import type { DashboardData, EventDetail, EventListItem, ManualEventTestResult } from './types'

class MockEventSource {
  static instance: MockEventSource | null = null
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor() {
    MockEventSource.instance = this
  }

  close() {
    return undefined
  }
}

const dashboardPayload: DashboardData = {
  summary: {
    status: 'ok',
    started_at: '2026-03-27T09:00:00Z',
    database_path: 'var/event_radar.db',
    post_count: 12,
    alert_count: 4,
    connector_count: 2,
    running_connector_count: 1,
    attention_count: 1,
    last_activity_at: '2026-03-27T10:00:00Z',
  },
  connectors: [
    {
      name: 'x',
      enabled: true,
      running: true,
      auth_configured: true,
      last_error: null,
      last_success_at: '2026-03-27T10:00:00Z',
      detail: 'stream_connected',
      checkpoints: [],
    },
  ],
  latency: {
    end_to_end_seconds: { count: 2, p50: 4.4, p95: 6.1, p99: 6.3, min: 4.0, max: 6.5 },
  },
  costs: {
    fx: { eur_per_usd: 0.9, reference_date: '2026-03-27' },
    openai: {
      model: 'gpt-5-mini',
      scope: {
        status: 'ok',
        reason: null,
        api_key_name: 'Event Radar',
        api_key_id: 'key_event_radar',
        api_key_last_used_at: null,
        project_id: 'proj_default',
        project_name: 'Default project',
        project_api_key_count: 2,
      },
      pricing: {
        input_cost_per_million_usd: 0.25,
        output_cost_per_million_usd: 2,
        cached_input_cost_per_million_usd: 0.025,
      },
      usage: {
        status: 'ok',
        reason: null,
        last_7d: {
          analysis_count: 3,
          input_tokens: 1000,
          output_tokens: 200,
          cached_input_tokens: 0,
          total_tokens: 1200,
          average_total_tokens_per_request: 400,
          average_input_tokens_per_request: 333.3,
          average_output_tokens_per_request: 66.7,
        },
        last_30d: {
          analysis_count: 3,
          input_tokens: 1000,
          output_tokens: 200,
          cached_input_tokens: 0,
          total_tokens: 1200,
          average_total_tokens_per_request: 400,
          average_input_tokens_per_request: 333.3,
          average_output_tokens_per_request: 66.7,
        },
      },
      costs: {
        estimated_last_7d_usd: 2,
        estimated_last_7d_eur: 1.8,
        estimated_last_30d_usd: 2,
        estimated_last_30d_eur: 1.8,
        projected_monthly_cost_eur: 20,
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
      credit: {
        status: 'ok',
        reason: null,
        available_credit_usd: 2,
        available_credit_eur: 1.8,
      },
    },
    x: {
      official_usage: {
        status: 'ok',
        reason: null,
        project_id: 'project-1',
        project_cap: 2000000,
        project_usage: 97,
        cap_reset_day: 26,
        consumed_last_7d: 97,
        consumed_last_30d: 97,
        daily_usage: [
          { date: '2026-03-27T00:00:00.000Z', consumed: 81 },
          { date: '2026-03-29T00:00:00.000Z', consumed: 16 },
        ],
      },
      local_usage: {
        read_requests_last_7d: 14,
        read_requests_last_30d: 14,
        successful_read_requests_last_7d: 12,
        successful_read_requests_last_30d: 12,
      },
    },
  },
  attention: [
    {
      id: 7,
      kind: 'connector',
      level: 'warning',
      component: 'truth_social',
      title: 'Truth Social connector inactive',
      message: 'missing_truth_social_session',
      metadata: {},
      created_at: '2026-03-27T10:00:00Z',
    },
  ],
  activity: [
    {
      id: 5,
      kind: 'classification',
      level: 'info',
      component: 'classifier',
      title: 'Post classified',
      message: '@sample classified with score 82.00',
      metadata: {},
      created_at: '2026-03-27T10:05:00Z',
    },
  ],
  accounts: [
    {
      id: 'x_account',
      source: 'x',
      entity_key: 'sample',
      display_name: 'Sample Actor',
      handle: 'sample',
      source_account_id: null,
      source_url: null,
      official: true,
      active: true,
      authority_rank: 70,
      alert_threshold: 80,
      metadata: {},
      created_at: '2026-03-27T09:00:00Z',
      updated_at: '2026-03-27T09:00:00Z',
    },
  ],
}

const eventsPayload: EventListItem[] = [
  {
    normalized_post_id: 42,
    source: 'x',
    handle: 'sample',
    display_name: 'Sample Actor',
    source_post_id: '100',
    canonical_url: 'https://x.com/sample/status/100',
    text: 'Diplomatic talks resume this afternoon.',
    published_at: '2026-03-27T09:59:00Z',
    observed_at: '2026-03-27T10:00:00Z',
    summary: 'Diplomatic talks resume',
    categories: ['diplomacy'],
    total_score: 82.5,
    decision: 'alerted',
    reasoning: 'High-significance actor and immediate timing.',
    request_cost_usd: 0.04,
    alert_id: 11,
    alert_status: 'sent',
    suppression_reason: null,
    feedback_vote: null,
    feedback_vote_updated_at: null,
  },
]

const marketImpacts = {
  dxy: { direction: 'down', confidence: 72 },
  btc: { direction: 'up', confidence: 71 },
  dow: { direction: 'up', confidence: 68 },
  spx: { direction: 'up', confidence: 70 },
  ndx: { direction: 'up', confidence: 74 },
  oil: { direction: 'down', confidence: 77 },
  metals: { direction: 'down', confidence: 59 },
  energy: { direction: 'down', confidence: 75 },
  nvda: { direction: 'up', confidence: 76 },
  aapl: { direction: 'up', confidence: 67 },
  msft: { direction: 'up', confidence: 68 },
  tsla: { direction: 'up', confidence: 73 },
  intc: { direction: 'up', confidence: 65 },
  asml: { direction: 'up', confidence: 69 },
  pltr: { direction: 'flat', confidence: 45 },
} as const

const detailPayload: EventDetail = {
  normalized_post_id: 42,
  source: 'x',
  account_id: 'x_account',
  source_account_id: '1000',
  handle: 'sample',
  display_name: 'Sample Actor',
  source_post_id: '100',
  canonical_url: 'https://x.com/sample/status/100',
  text: 'Diplomatic talks resume this afternoon.',
  links: ['https://example.com/details'],
  media_urls: [],
  is_reply: false,
  is_repost: false,
  published_at: '2026-03-27T09:59:00Z',
  observed_at: '2026-03-27T10:00:00Z',
  analysis: {
    id: 9,
    model: 'gpt-5-mini',
    summary: 'Diplomatic talks resume',
    categories: ['diplomacy'],
    reasoning: 'High-significance actor and immediate timing.',
    market_impacts: marketImpacts,
    breakdown: {
      actor_importance: 90,
      event_severity: 80,
      immediacy: 78,
      novelty: 65,
      wider_impact: 84,
    },
    total_score: 82.5,
    threshold: 70,
    decision: 'alerted',
    input_tokens: 100,
    output_tokens: 30,
    cached_input_tokens: 0,
    request_cost_usd: 0.04,
    created_at: '2026-03-27T10:00:02Z',
  },
  alert: {
    id: 11,
    status: 'sent',
    message_text: 'Sent to relay.',
    suppression_reason: null,
    relay_response: {},
    created_at: '2026-03-27T10:00:03Z',
    sent_at: '2026-03-27T10:00:03Z',
    acked_at: '2026-03-27T10:00:04Z',
  },
  feedback_vote: null,
  feedback_vote_updated_at: null,
  latency: {
    persisted_at: '2026-03-27T10:00:01Z',
    classification_started_at: '2026-03-27T10:00:01Z',
    classification_finished_at: '2026-03-27T10:00:02Z',
    relay_sent_at: '2026-03-27T10:00:03Z',
    relay_acked_at: '2026-03-27T10:00:04Z',
  },
}

const manualTriggerPayload: ManualEventTestResult = {
  account: {
    id: 'x_account',
    source: 'x',
    display_name: 'Sample Actor',
    handle: 'sample',
    authority_rank: 70,
    alert_threshold: 80,
    active: true,
  },
  analysis: {
    mode: 'model',
    summary: 'Diplomatic talks resume this afternoon.',
    categories: ['diplomacy'],
    reasoning: 'High-significance actor and immediate timing.',
    market_impacts: marketImpacts,
    breakdown: {
      actor_importance: 90,
      event_severity: 80,
      immediacy: 78,
      novelty: 65,
      wider_impact: 84,
    },
    total_score: 82.5,
    threshold: 80,
    decision: 'alerted',
    request_cost_usd: 0.04,
  },
  outcome: {
    would_notify: true,
    status: 'sent',
    reason: null,
    message_text: 'Alert sent to relay.',
  },
}

let currentDashboardPayload: typeof dashboardPayload
let currentEventsPayload: typeof eventsPayload
let currentDetailPayload: typeof detailPayload

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  currentDashboardPayload = structuredClone(dashboardPayload)
  currentEventsPayload = structuredClone(eventsPayload)
  currentDetailPayload = structuredClone(detailPayload)
  globalThis.EventSource = MockEventSource as unknown as typeof EventSource
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/v1/dashboard')) {
      return new Response(JSON.stringify(currentDashboardPayload), { status: 200 })
    }
    if (url.includes('/api/v1/events?')) {
      return new Response(JSON.stringify(currentEventsPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42') && (!init?.method || init.method === 'GET')) {
      return new Response(JSON.stringify(currentDetailPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/test-trigger') && init?.method === 'POST') {
      return new Response(JSON.stringify(manualTriggerPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42/vote') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as { vote: 'up' | 'down' | null }
      await new Promise((resolve) => setTimeout(resolve, 25))
      const updatedAt = body.vote ? '2026-03-27T10:06:00Z' : null
      currentEventsPayload = currentEventsPayload.map((event) =>
        event.normalized_post_id === 42
          ? { ...event, feedback_vote: body.vote, feedback_vote_updated_at: updatedAt }
          : event,
      )
      currentDetailPayload = {
        ...currentDetailPayload,
        feedback_vote: body.vote,
        feedback_vote_updated_at: updatedAt,
      }
      return new Response(JSON.stringify(currentDetailPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42/refresh') && init?.method === 'POST') {
      currentDetailPayload = {
        ...currentDetailPayload,
        analysis: {
          ...currentDetailPayload.analysis,
          total_score: 86.2,
          decision: 'alerted',
        },
      }
      currentEventsPayload = currentEventsPayload.map((event) =>
        event.normalized_post_id === 42 ? { ...event, total_score: 86.2 } : event,
      )
      return new Response(JSON.stringify(currentDetailPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42') && init?.method === 'DELETE') {
      currentEventsPayload = currentEventsPayload.filter((event) => event.normalized_post_id !== 42)
      return new Response(JSON.stringify({ ok: true, normalized_post_id: 42 }), { status: 200 })
    }
    if (url.endsWith('/api/v1/activity') && init?.method === 'DELETE') {
      currentDashboardPayload = { ...currentDashboardPayload, activity: [] }
      return new Response(JSON.stringify({ ok: true, deleted: 1 }), { status: 200 })
    }
    if (url.endsWith('/api/v1/activity/attention') && init?.method === 'DELETE') {
      currentDashboardPayload = {
        ...currentDashboardPayload,
        attention: [],
        summary: { ...currentDashboardPayload.summary, attention_count: 0 },
      }
      return new Response(JSON.stringify({ ok: true, deleted: 1 }), { status: 200 })
    }
    if (url.endsWith('/api/v1/metrics/latency') && init?.method === 'DELETE') {
      currentDashboardPayload = { ...currentDashboardPayload, latency: {} }
      return new Response(JSON.stringify({ ok: true, deleted: 1 }), { status: 200 })
    }
    if (url.endsWith('/api/v1/accounts') && init?.method === 'POST') {
      return new Response(JSON.stringify(dashboardPayload.accounts[0]), { status: 200 })
    }
    if (url.endsWith('/api/v1/accounts/x_account') && init?.method === 'PATCH') {
      const payload = JSON.parse(String(init.body)) as { active?: boolean; alert_threshold?: number | null }
      currentDashboardPayload = {
        ...currentDashboardPayload,
        accounts: currentDashboardPayload.accounts.map((account) =>
          account.id === 'x_account'
            ? {
                ...account,
                ...(payload.active !== undefined ? { active: payload.active } : {}),
                ...(payload.alert_threshold !== undefined ? { alert_threshold: payload.alert_threshold } : {}),
                updated_at: '2026-03-27T10:06:00Z',
              }
            : account,
        ),
      }
      return new Response(
        JSON.stringify(currentDashboardPayload.accounts.find((account) => account.id === 'x_account')),
        { status: 200 },
      )
    }
    if (url.endsWith('/api/v1/accounts/x_account') && init?.method === 'DELETE') {
      const [removed] = currentDashboardPayload.accounts
      currentDashboardPayload = {
        ...currentDashboardPayload,
        accounts: currentDashboardPayload.accounts.filter((account) => account.id !== 'x_account'),
      }
      return new Response(JSON.stringify(removed), { status: 200 })
    }
    return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 })
  }) as typeof fetch
})

it('places tracked accounts above warnings in the sidebar', async () => {
  renderApp()

  const accountsHeading = await screen.findByRole('heading', { name: 'Accounts - Tracked accounts' })
  const warningsHeading = await screen.findByRole('heading', { name: 'Warnings - Attention required' })

  expect(
    accountsHeading.compareDocumentPosition(warningsHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).not.toBe(0)
})

it('renders events and opens inspector content', async () => {
  const user = userEvent.setup()
  renderApp()

  expect(await screen.findByRole('heading', { name: 'Primary queue - Recent events' })).toBeInTheDocument()
  expect(await screen.findByText('Diplomatic talks resume')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Selected event - Event inspector' })).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /Diplomatic talks resume/i }))

  expect(await screen.findByRole('heading', { name: 'Selected event - Event inspector' })).toBeInTheDocument()
  expect(await screen.findByText('High-significance actor and immediate timing.')).toBeInTheDocument()
})

it('hides latency rows without samples and omits unavailable credit', async () => {
  currentDashboardPayload = {
    ...currentDashboardPayload,
    latency: {
      observed_to_persisted_seconds: { count: 3, p50: 0.42, p95: 0.75, p99: 0.78, min: 0.39, max: 0.8 },
      classification_to_relay_seconds: { count: 0, p50: null, p95: null, p99: null, min: null, max: null },
      end_to_end_seconds: { count: 0, p50: null, p95: null, p99: null, min: null, max: null },
    },
    costs: {
      ...currentDashboardPayload.costs,
      openai: {
        ...currentDashboardPayload.costs.openai,
        credit: {
          status: 'unavailable',
          reason: 'browser_session_required',
          available_credit_usd: null,
          available_credit_eur: null,
        },
      },
    },
  }

  renderApp()

  expect(await screen.findByText('Persistence')).toBeInTheDocument()
  expect(screen.queryByText('Relay delivery')).not.toBeInTheDocument()
  expect(screen.queryByText('End to end')).not.toBeInTheDocument()
  expect(screen.queryByText('Available credit')).not.toBeInTheDocument()
})

it('splits the cost panel into openai and x usage sections', async () => {
  renderApp()

  expect(await screen.findByRole('heading', { name: 'OpenAI' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'X' })).toBeInTheDocument()
  expect(screen.getByText('Requests 7d')).toBeInTheDocument()
  expect(screen.getByText('Post reads 7d')).toBeInTheDocument()
  expect(screen.getByText('Billing cycle total')).toBeInTheDocument()
})

it('renders the cost panel from the legacy flat backend payload', async () => {
  currentDashboardPayload = {
    ...currentDashboardPayload,
    costs: {
      model: 'gpt-5-mini',
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
      pricing: {
        input_cost_per_million_usd: 0.25,
        output_cost_per_million_usd: 2,
        cached_input_cost_per_million_usd: 0.025,
      },
      usage: { analysis_count: 16, input_tokens: 22632, output_tokens: 7688, cached_input_tokens: 1152 },
      costs: {
        estimated_cost_per_post_eur: 0.000328,
        actual_total_cost_usd: 0.0208,
        actual_total_cost_eur: 0.018,
        projected_weekly_cost_eur: 1.4,
        projected_monthly_cost_eur: 6,
        projection_basis: 'observed_run_rate',
      },
      organization_costs: {
        status: 'unavailable',
        reason: 'missing_openai_admin_key',
        billed_last_7d_usd: null,
        billed_last_7d_eur: null,
        billed_last_30d_usd: null,
        billed_last_30d_eur: null,
        billed_total_window_usd: null,
        billed_total_window_eur: null,
        window_days: null,
      },
      credit: {
        status: 'unavailable',
        reason: 'missing_openai_admin_key',
        available_credit_usd: null,
        available_credit_eur: null,
      },
    } as unknown as DashboardData['costs'],
  }

  renderApp()

  expect(await screen.findByRole('heading', { name: 'OpenAI' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'X' })).toBeInTheDocument()
  expect(screen.getByText(/Official X usage is unavailable right now/i)).toBeInTheDocument()
})

it('merges duplicate recent activity rows', async () => {
  currentDashboardPayload = {
    ...currentDashboardPayload,
    activity: [
      currentDashboardPayload.activity[0],
      {
        ...currentDashboardPayload.activity[0],
        id: 99,
        created_at: '2026-03-27T10:04:30Z',
      },
    ],
  }

  renderApp()

  expect(await screen.findByText('Post classified')).toBeInTheDocument()
  expect(screen.getAllByText('Post classified')).toHaveLength(1)
  expect(screen.queryByText('Repeated 2 times')).not.toBeInTheDocument()
})

it('runs a manual trigger test from the top panel', async () => {
  const user = userEvent.setup()
  renderApp()

  await user.type(await screen.findByLabelText('Handle'), '@sample')
  await user.type(screen.getByLabelText('Message'), 'Diplomatic talks resume this afternoon.')
  await user.click(screen.getByRole('button', { name: 'Run test' }))

  const resultCard = await screen.findByText('Alert sent to relay.')
  const article = resultCard.closest('.trigger-result-card')
  expect(article).not.toBeNull()
  expect(resultCard).toBeInTheDocument()
  expect(within(article as HTMLElement).getByText('Sent')).toBeInTheDocument()
})

it('shows validation feedback when adding an invalid account', async () => {
  const user = userEvent.setup()
  renderApp()

  await user.click(await screen.findByRole('button', { name: 'Add account' }))
  const dialog = await screen.findByRole('dialog', { name: 'New account - Add tracked account' })
  await user.type(within(dialog).getByLabelText('Display name'), 'New Actor')
  await user.type(within(dialog).getByLabelText('Handle'), 'not valid!')
  await user.click(within(dialog).getByRole('button', { name: 'Add account' }))

  expect(await screen.findByText('Use a valid handle')).toBeInTheDocument()
})

it('surfaces reconnecting state when the stream errors', async () => {
  renderApp()

  await waitFor(() => expect(MockEventSource.instance).not.toBeNull())
  MockEventSource.instance?.onerror?.()

  expect(await screen.findByText('Reconnecting live updates')).toBeInTheDocument()
})

it('removes a tracked account from the accounts panel', async () => {
  const user = userEvent.setup()
  renderApp()

  const accountsHeading = await screen.findByRole('heading', { name: 'Accounts - Tracked accounts' })
  const accountsPanel = accountsHeading.closest('.panel')
  expect(accountsPanel).not.toBeNull()
  const accountName = await within(accountsPanel as HTMLElement).findByText('Sample Actor')
  const accountCard = accountName.closest('.account-row')
  expect(accountCard).not.toBeNull()

  await user.click(within(accountCard as HTMLElement).getByRole('button', { name: 'Remove' }))

  await waitFor(() =>
    expect(within(accountsPanel as HTMLElement).queryByText('Sample Actor')).not.toBeInTheDocument(),
  )
  expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/accounts/x_account', expect.objectContaining({ method: 'DELETE' }))
})

it('auto-saves threshold edits for tracked accounts', async () => {
  const user = userEvent.setup()
  renderApp()

  const thresholdInput = await screen.findByRole('spinbutton', { name: 'Alert threshold for Sample Actor' })
  await user.clear(thresholdInput)
  await user.type(thresholdInput, '72')

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/accounts/x_account',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ alert_threshold: 72 }),
      }),
    ),
  )
  expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
})

it('refreshes and deletes events from the queue', async () => {
  const user = userEvent.setup()
  renderApp()

  await user.click(await screen.findByRole('button', { name: 'Reload Sample Actor event' }))
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/events/42/refresh', expect.objectContaining({ method: 'POST' })),
  )

  await user.click(screen.getByRole('button', { name: 'Delete Sample Actor event' }))
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/events/42', expect.objectContaining({ method: 'DELETE' })),
  )
})

it('clears activity, attention, and latency panels', async () => {
  const user = userEvent.setup()
  renderApp()

  const clearButtons = await screen.findAllByRole('button', { name: 'Clear' })
  await user.click(clearButtons[0])
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/activity', expect.objectContaining({ method: 'DELETE' })),
  )

  await user.click(clearButtons[1])
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/activity/attention', expect.objectContaining({ method: 'DELETE' })),
  )

  await user.click(await screen.findByRole('button', { name: 'Reset latency' }))
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/metrics/latency', expect.objectContaining({ method: 'DELETE' })),
  )
})

it('stores and changes event vote selection', async () => {
  const user = userEvent.setup()
  renderApp()

  const upvoteButton = await screen.findByRole('button', { name: 'Upvote Sample Actor event' })
  const downvoteButton = screen.getByRole('button', { name: 'Downvote Sample Actor event' })

  await user.click(upvoteButton)
  expect(screen.getByRole('button', { name: 'Upvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'true')
  expect(downvoteButton).toHaveAttribute('aria-pressed', 'false')
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/events/42/vote', expect.objectContaining({ method: 'PATCH' })),
  )

  await user.click(downvoteButton)
  expect(await screen.findByRole('button', { name: 'Downvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Upvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'false')

  await user.click(screen.getByRole('button', { name: 'Downvote Sample Actor event' }))
  expect(await screen.findByRole('button', { name: 'Downvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getByRole('button', { name: 'Upvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'false')
})

it('keeps vote selection visible if the save request fails', async () => {
  const user = userEvent.setup()
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/v1/dashboard')) {
      return new Response(JSON.stringify(currentDashboardPayload), { status: 200 })
    }
    if (url.includes('/api/v1/events?')) {
      return new Response(JSON.stringify(currentEventsPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42')) {
      return new Response(JSON.stringify(currentDetailPayload), { status: 200 })
    }
    if (url.endsWith('/api/v1/events/42/vote') && init?.method === 'PATCH') {
      return new Response(JSON.stringify({ detail: 'save_failed' }), { status: 500 })
    }
    return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 })
  }) as typeof fetch

  renderApp()

  const upvoteButton = await screen.findByRole('button', { name: 'Upvote Sample Actor event' })
  await user.click(upvoteButton)

  expect(screen.getByRole('button', { name: 'Upvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'true')
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/events/42/vote', expect.objectContaining({ method: 'PATCH' })),
  )
  expect(screen.getByRole('button', { name: 'Upvote Sample Actor event' })).toHaveAttribute('aria-pressed', 'true')
})
