export type SourcePlatform = 'x' | 'truth_social'
export type EventFeedbackVote = 'up' | 'down'
export type MarketImpactDirection = 'up' | 'down' | 'flat'

export interface AssetImpactPrediction {
  direction: MarketImpactDirection
  confidence: number
}

export interface MarketImpactSnapshot {
  dxy: AssetImpactPrediction
  btc: AssetImpactPrediction
  dow: AssetImpactPrediction
  spx: AssetImpactPrediction
  ndx: AssetImpactPrediction
  oil: AssetImpactPrediction
  metals: AssetImpactPrediction
  energy: AssetImpactPrediction
  nvda: AssetImpactPrediction
  aapl: AssetImpactPrediction
  msft: AssetImpactPrediction
  tsla: AssetImpactPrediction
  intc: AssetImpactPrediction
  asml: AssetImpactPrediction
  pltr: AssetImpactPrediction
}

export interface ActivityItem {
  id: number
  kind: string
  level: string
  component: string
  title: string
  message: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface Account {
  id: string
  source: SourcePlatform
  entity_key: string
  display_name: string
  handle: string
  source_account_id: string | null
  source_url: string | null
  official: boolean
  active: boolean
  authority_rank: number
  alert_threshold: number | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ConnectorStatus {
  name: string
  enabled: boolean
  running: boolean
  auth_configured: boolean
  last_error: string | null
  last_success_at: string | null
  detail: string | null
  checkpoints: Array<Record<string, unknown>>
}

export interface Distribution {
  count: number
  p50: number | null
  p95: number | null
  p99: number | null
  min: number | null
  max: number | null
}

export interface CostSummary {
  fx: {
    eur_per_usd: number
    reference_date: string
  }
  openai: {
    model: string
    scope: {
      status: string | null
      reason: string | null
      api_key_name: string
      api_key_id: string | null
      api_key_last_used_at: number | null
      project_id: string | null
      project_name: string | null
      project_api_key_count: number | null
    }
    pricing: {
      input_cost_per_million_usd: number
      output_cost_per_million_usd: number
      cached_input_cost_per_million_usd: number
    }
    usage: {
      status: string | null
      reason: string | null
      last_7d: {
        analysis_count: number
        input_tokens: number
        output_tokens: number
        cached_input_tokens: number
        total_tokens: number
        average_total_tokens_per_request: number | null
        average_input_tokens_per_request: number | null
        average_output_tokens_per_request: number | null
      }
      last_30d: {
        analysis_count: number
        input_tokens: number
        output_tokens: number
        cached_input_tokens: number
        total_tokens: number
        average_total_tokens_per_request: number | null
        average_input_tokens_per_request: number | null
        average_output_tokens_per_request: number | null
      }
    }
    costs: {
      estimated_last_7d_usd: number
      estimated_last_7d_eur: number
      estimated_last_30d_usd: number
      estimated_last_30d_eur: number
      projected_monthly_cost_eur: number
    }
    billed_costs: {
      status: string | null
      reason: string | null
      billed_last_7d_usd: number | null
      billed_last_7d_eur: number | null
      billed_last_30d_usd: number | null
      billed_last_30d_eur: number | null
      window_days: number | null
    }
    credit: {
      status: string | null
      reason: string | null
      available_credit_usd: number | null
      available_credit_eur: number | null
    }
  }
  x: {
    official_usage: {
      status: string | null
      reason: string | null
      project_id: string | null
      project_cap: number | null
      project_usage: number | null
      cap_reset_day: number | null
      consumed_last_7d: number | null
      consumed_last_30d: number | null
      daily_usage: Array<{
        date: string
        consumed: number
      }>
    }
    local_usage: {
      read_requests_last_7d: number
      read_requests_last_30d: number
      successful_read_requests_last_7d: number
      successful_read_requests_last_30d: number
    }
  }
}

export interface DashboardData {
  summary: {
    status: string
    started_at: string
    database_path: string
    post_count: number
    alert_count: number
    connector_count: number
    running_connector_count: number
    attention_count: number
    last_activity_at: string | null
  }
  connectors: ConnectorStatus[]
  latency: Record<string, Distribution>
  costs: CostSummary
  attention: ActivityItem[]
  activity: ActivityItem[]
  accounts: Account[]
}

export interface EventListItem {
  normalized_post_id: number
  source: SourcePlatform
  handle: string
  display_name: string
  source_post_id: string
  canonical_url: string | null
  text: string
  published_at: string
  observed_at: string
  summary: string | null
  categories: string[]
  total_score: number | null
  decision: string | null
  reasoning: string | null
  request_cost_usd: number | null
  alert_id: number | null
  alert_status: string | null
  suppression_reason: string | null
  feedback_vote: EventFeedbackVote | null
  feedback_vote_updated_at: string | null
}

export interface EventDetail {
  normalized_post_id: number
  source: SourcePlatform
  account_id: string
  source_account_id: string
  handle: string
  display_name: string
  source_post_id: string
  canonical_url: string | null
  text: string
  links: string[]
  media_urls: string[]
  is_reply: boolean
  is_repost: boolean
  published_at: string
  observed_at: string
  analysis: {
    id: number | null
    model: string | null
    summary: string | null
    categories: string[]
    reasoning: string | null
    market_impacts: MarketImpactSnapshot
    breakdown: Record<string, number> | null
    total_score: number | null
    threshold: number | null
    decision: string | null
    input_tokens: number | null
    output_tokens: number | null
    cached_input_tokens: number | null
    request_cost_usd: number | null
    created_at: string | null
  }
  alert: {
    id: number
    status: string
    message_text: string
    suppression_reason: string | null
    relay_response: Record<string, unknown>
    created_at: string | null
    sent_at: string | null
    acked_at: string | null
  } | null
  feedback_vote: EventFeedbackVote | null
  feedback_vote_updated_at: string | null
  latency: {
    persisted_at: string | null
    classification_started_at: string | null
    classification_finished_at: string | null
    relay_sent_at: string | null
    relay_acked_at: string | null
  }
}

export interface EventFilters {
  limit?: number
  source?: SourcePlatform
  alert_status?: string
  decision?: string
  q?: string
}

export interface CreateAccountPayload {
  source: SourcePlatform
  entity_key: string
  display_name: string
  handle: string
  authority_rank: number
  alert_threshold?: number
}

export interface UpdateAccountPayload {
  active?: boolean
  alert_threshold?: number | null
  source_account_id?: string | null
  authority_rank?: number
}

export interface EventVotePayload {
  vote: EventFeedbackVote | null
}

export interface EventMutationResult {
  ok: boolean
  normalized_post_id?: number
  deleted?: number
}

export interface ManualEventTestResult {
  account: {
    id: string
    source: SourcePlatform
    display_name: string
    handle: string
    authority_rank: number
    alert_threshold: number | null
    active: boolean
  }
  analysis: {
    mode: string
    summary: string
    categories: string[]
    reasoning: string
    market_impacts: MarketImpactSnapshot
    breakdown: Record<string, number>
    total_score: number
    threshold: number
    decision: string
    request_cost_usd: number
  }
  outcome: {
    would_notify: boolean
    status: string
    reason: string | null
    message_text: string
  }
}

export type StreamMessage =
  | { type: 'activity.create'; activity: ActivityItem }
  | { type: 'connector.update'; connector: ConnectorStatus }
  | { type: 'event.upsert'; event: EventDetail }
  | { type: 'event.delete'; normalized_post_id: number }
  | { type: 'dashboard.invalidate'; at: string }
