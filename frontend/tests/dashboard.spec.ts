import { expect, test } from '@playwright/test'

const dashboardPayload = {
  summary: {
    status: 'ok',
    started_at: '2026-03-27T09:00:00Z',
    database_path: 'var/event_radar.db',
    post_count: 1248,
    alert_count: 143,
    connector_count: 2,
    running_connector_count: 1,
    attention_count: 2,
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
    {
      name: 'truth_social',
      enabled: true,
      running: false,
      auth_configured: true,
      last_error: 'poll stalled while Cloudflare challenge reset the session cookie',
      last_success_at: '2026-03-27T09:52:00Z',
      detail: 'waiting_for_session_refresh',
      checkpoints: [],
    },
  ],
  latency: {
    end_to_end_seconds: { count: 82, p50: 4.4, p95: 6.1, p99: 6.3, min: 4.0, max: 6.5 },
    classification_seconds: { count: 82, p50: 1.7, p95: 2.8, p99: 3.0, min: 1.1, max: 3.4 },
    relay_seconds: { count: 82, p50: 0.6, p95: 1.2, p99: 1.4, min: 0.3, max: 1.7 },
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
          analysis_count: 97,
          input_tokens: 66100,
          output_tokens: 17100,
          cached_input_tokens: 0,
          total_tokens: 83200,
          average_total_tokens_per_request: 857.7,
          average_input_tokens_per_request: 681.4,
          average_output_tokens_per_request: 176.3,
        },
        last_30d: {
          analysis_count: 308,
          input_tokens: 210000,
          output_tokens: 54000,
          cached_input_tokens: 0,
          total_tokens: 264000,
          average_total_tokens_per_request: 857.1,
          average_input_tokens_per_request: 681.8,
          average_output_tokens_per_request: 175.3,
        },
      },
      costs: {
        estimated_last_7d_usd: 5.9,
        estimated_last_7d_eur: 5.31,
        estimated_last_30d_usd: 18.2,
        estimated_last_30d_eur: 16.38,
        projected_monthly_cost_eur: 226,
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
        read_requests_last_7d: 5100,
        read_requests_last_30d: 5100,
        successful_read_requests_last_7d: 5096,
        successful_read_requests_last_30d: 5096,
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
      message: 'Polling is degraded because the session cookie expired and the connector is waiting for a replacement jar.',
      metadata: {},
      created_at: '2026-03-27T10:00:00Z',
    },
    {
      id: 8,
      kind: 'classification',
      level: 'error',
      component: 'classifier',
      title: 'OpenAI classification unavailable',
      message: 'Live OpenAI classification is unavailable after repeated 400 responses from /v1/responses.',
      metadata: {},
      created_at: '2026-03-27T10:03:00Z',
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
    {
      id: 6,
      kind: 'relay',
      level: 'warning',
      component: 'telegram',
      title: 'Relay delayed',
      message: 'Telegram acknowledged the alert after 3.8 seconds, above the target latency budget.',
      metadata: {},
      created_at: '2026-03-27T10:04:00Z',
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
    {
      id: 'truth_account',
      source: 'truth_social',
      entity_key: 'press-office',
      display_name: 'Press Office With An Extraordinarily Long Name',
      handle: 'press.office.official',
      source_account_id: null,
      source_url: null,
      official: true,
      active: false,
      authority_rank: 62,
      alert_threshold: 75,
      metadata: {},
      created_at: '2026-03-27T09:00:00Z',
      updated_at: '2026-03-27T09:00:00Z',
    },
  ],
}

const eventsPayload = [
  {
    normalized_post_id: 42,
    source: 'x',
    handle: 'sample',
    display_name: 'Sample Actor',
    source_post_id: '100',
    canonical_url: 'https://x.com/sample/status/100',
    text: 'Diplomatic talks resume this afternoon after overnight military coordination and new sanctions discussions.',
    published_at: '2026-03-27T09:59:00Z',
    observed_at: '2026-03-27T10:00:00Z',
    summary: 'Diplomatic talks resume after overnight military coordination and sanctions talks',
    categories: ['diplomacy', 'security', 'sanctions'],
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
  {
    normalized_post_id: 43,
    source: 'truth_social',
    handle: 'press.office.official',
    display_name: 'Press Office With An Extraordinarily Long Name',
    source_post_id: '101',
    canonical_url: 'https://truthsocial.com/@press.office.official/posts/101',
    text: 'Statement expected within the hour regarding energy infrastructure and cross-border retaliation reports.',
    published_at: '2026-03-27T09:45:00Z',
    observed_at: '2026-03-27T09:46:00Z',
    summary: 'Statement expected on energy infrastructure and retaliation reports',
    categories: ['infrastructure', 'retaliation'],
    total_score: 77.1,
    decision: 'dry_run',
    reasoning: 'Notable but lower confidence.',
    request_cost_usd: 0.03,
    alert_id: 12,
    alert_status: 'dry_run',
    suppression_reason: null,
    feedback_vote: null,
    feedback_vote_updated_at: null,
  },
  {
    normalized_post_id: 44,
    source: 'x',
    handle: 'regionaldesk',
    display_name: 'Regional Desk',
    source_post_id: '102',
    canonical_url: 'https://x.com/regionaldesk/status/102',
    text: 'Airspace restrictions issued for several provinces.',
    published_at: '2026-03-27T09:31:00Z',
    observed_at: '2026-03-27T09:32:00Z',
    summary: 'Airspace restrictions issued for several provinces',
    categories: ['aviation'],
    total_score: 65.4,
    decision: 'below_threshold',
    reasoning: 'Potentially significant but below threshold.',
    request_cost_usd: 0.02,
    alert_id: null,
    alert_status: null,
    suppression_reason: null,
    feedback_vote: null,
    feedback_vote_updated_at: null,
  },
]

const detailPayload = {
  normalized_post_id: 42,
  source: 'x',
  account_id: 'x_account',
  source_account_id: '1000',
  handle: 'sample',
  display_name: 'Sample Actor',
  source_post_id: '100',
  canonical_url: 'https://x.com/sample/status/100',
  text: 'Diplomatic talks resume this afternoon after overnight military coordination and new sanctions discussions.',
  links: ['https://example.com/details', 'https://example.com/context'],
  media_urls: [],
  is_reply: false,
  is_repost: false,
  published_at: '2026-03-27T09:59:00Z',
  observed_at: '2026-03-27T10:00:00Z',
  analysis: {
    id: 9,
    model: 'gpt-5-mini',
    summary: 'Diplomatic talks resume after overnight military coordination and sanctions talks',
    categories: ['diplomacy', 'security', 'sanctions'],
    reasoning: 'High-significance actor and immediate timing.',
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

const manualTriggerPayload = {
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
    summary: 'Diplomatic talks resume after overnight military coordination and sanctions talks',
    categories: ['diplomacy', 'security', 'sanctions'],
    reasoning: 'High-significance actor and immediate timing.',
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
    request_cost_usd: 0.04,
  },
  outcome: {
    would_notify: true,
    status: 'sent',
    reason: null,
    message_text: 'Alert sent to relay.',
  },
}

test.beforeEach(async ({ page }) => {
  let currentDashboardPayload = structuredClone(dashboardPayload)
  let currentEventsPayload = structuredClone(eventsPayload)
  let currentDetailPayload = structuredClone(detailPayload)

  await page.addInitScript(() => {
    class MockEventSource {
      constructor() {
        setTimeout(() => this.onopen && this.onopen(), 20)
      }

      close() {
        return undefined
      }
    }

    window.EventSource = MockEventSource
  })

  await page.route('**/api/v1/dashboard', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(currentDashboardPayload) })
  })

  await page.route(/.*\/api\/v1\/events\?.*/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(currentEventsPayload) })
  })

  await page.route('**/api/v1/events/42', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(currentDetailPayload) })
  })

  await page.route('**/api/v1/events/test-trigger', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(manualTriggerPayload) })
  })

  await page.route('**/api/v1/events/42/refresh', async (route) => {
    currentDetailPayload = {
      ...currentDetailPayload,
      analysis: { ...currentDetailPayload.analysis, total_score: 86.2, decision: 'alerted' },
    }
    currentEventsPayload = currentEventsPayload.map((event) =>
      event.normalized_post_id === 42 ? { ...event, total_score: 86.2 } : event,
    )
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(currentDetailPayload) })
  })

  await page.route('**/api/v1/events/42', async (route) => {
    if (route.request().method() !== 'DELETE') {
      await route.fallback()
      return
    }

    currentEventsPayload = currentEventsPayload.filter((event) => event.normalized_post_id !== 42)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, normalized_post_id: 42 }),
    })
  })

  await page.route('**/api/v1/events/42/vote', async (route) => {
    const body = route.request().postDataJSON() as { vote: 'up' | 'down' }
    currentEventsPayload = currentEventsPayload.map((event) =>
      event.normalized_post_id === 42
        ? { ...event, feedback_vote: body.vote, feedback_vote_updated_at: '2026-03-27T10:06:00Z' }
        : event,
    )
    currentDetailPayload = {
      ...currentDetailPayload,
      feedback_vote: body.vote,
      feedback_vote_updated_at: '2026-03-27T10:06:00Z',
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(currentDetailPayload) })
  })

  await page.route('**/api/v1/events/stream', async (route) => {
    await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
  })

  await page.route('**/api/v1/activity', async (route) => {
    if (route.request().method() !== 'DELETE') {
      await route.fallback()
      return
    }

    currentDashboardPayload = { ...currentDashboardPayload, activity: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, deleted: 2 }) })
  })

  await page.route('**/api/v1/activity/attention', async (route) => {
    currentDashboardPayload = {
      ...currentDashboardPayload,
      attention: [],
      summary: { ...currentDashboardPayload.summary, attention_count: 0 },
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, deleted: 2 }) })
  })

  await page.route('**/api/v1/metrics/latency', async (route) => {
    if (route.request().method() !== 'DELETE') {
      await route.fallback()
      return
    }

    currentDashboardPayload = { ...currentDashboardPayload, latency: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, deleted: 3 }) })
  })

  await page.route('**/api/v1/accounts/truth_account', async (route) => {
    if (route.request().method() !== 'DELETE') {
      await route.fallback()
      return
    }

    const removed = currentDashboardPayload.accounts.find((account) => account.id === 'truth_account')
    currentDashboardPayload = {
      ...currentDashboardPayload,
      accounts: currentDashboardPayload.accounts.filter((account) => account.id !== 'truth_account'),
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(removed) })
  })
})

test('dashboard layout scales without horizontal overflow', async ({ page }, testInfo) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Primary queue - Recent events' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Accounts - Tracked accounts' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  const metrics = await page.evaluate(() => {
    const shell = document.querySelector('.app-shell')?.getBoundingClientRect()
    const firstEvent = document.querySelector('.event-card')?.getBoundingClientRect()
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      scrollWidth: document.documentElement.scrollWidth,
      shellWidth: shell?.width ?? 0,
      firstEventTop: firstEvent?.top ?? Number.POSITIVE_INFINITY,
    }
  })

  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewportWidth + 1)

  if (testInfo.project.name.startsWith('chromium-')) {
    const expectedWidth = Math.min(metrics.viewportWidth, 2800)
    expect(Math.abs(metrics.shellWidth - expectedWidth)).toBeLessThanOrEqual(2)
  }

  if (testInfo.project.name === 'chromium-1728x827') {
    expect(metrics.firstEventTop).toBeLessThan(metrics.viewportHeight)
  }
})

test('event inspector opens and closes from the queue', async ({ page }) => {
  await page.goto('/')

  const firstEvent = page.locator('.event-card').first()
  await firstEvent.click()

  const dialog = page.getByRole('dialog', { name: 'Selected event - Event inspector' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('High-significance actor and immediate timing.')).toBeVisible()

  await page.keyboard.press('Escape')

  await expect(page.getByRole('dialog', { name: 'Selected event - Event inspector' })).toHaveCount(0)
  await expect(firstEvent).toBeFocused()
})

test('tracked accounts can be removed from the accounts panel', async ({ page }) => {
  await page.goto('/')

  const accountsPanel = page
    .locator('.panel')
    .filter({ has: page.getByRole('heading', { name: 'Accounts - Tracked accounts' }) })
  const accountCard = accountsPanel
    .locator('.account-row')
    .filter({ has: page.getByText('Press Office With An Extraordinarily Long Name') })
  await expect(accountCard).toBeVisible()

  page.once('dialog', (dialog) => dialog.accept())
  await accountCard.getByRole('button', { name: 'Remove' }).click()

  await expect(
    accountsPanel
      .locator('.account-row')
      .filter({ has: page.getByText('Press Office With An Extraordinarily Long Name') }),
  ).toHaveCount(0)
})

test('manual trigger panel runs a simulation and votes can change', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Handle').fill('@sample')
  await page.getByLabel('Message').fill('Diplomatic talks resume after overnight military coordination and sanctions talks.')
  await page.getByRole('button', { name: 'Run test' }).click()

  const resultCard = page.locator('.trigger-result-card')
  await expect(resultCard.getByText('Alert sent to relay.')).toBeVisible()
  await expect(resultCard.locator('.badge').filter({ hasText: 'Sent' }).first()).toBeVisible()

  const upvote = page.getByRole('button', { name: 'Upvote Sample Actor event' })
  const downvote = page.getByRole('button', { name: 'Downvote Sample Actor event' })
  await upvote.click()
  await expect(upvote).toHaveAttribute('aria-pressed', 'true')
  await downvote.click()
  await expect(downvote).toHaveAttribute('aria-pressed', 'true')
})

test('event actions and panel controls mutate the dashboard state', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Reload Sample Actor event' }).click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete Sample Actor event' }).click()

  await expect(page.getByText('Diplomatic talks resume after overnight military coordination and sanctions talks')).toHaveCount(0)

  const clearButtons = page.getByRole('button', { name: 'Clear' })
  await clearButtons.nth(0).click()
  await clearButtons.nth(1).click()
  await page.getByRole('button', { name: 'Reset latency' }).click()
})
