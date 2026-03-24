import { request } from './base';

export interface GenerateBlogRequest {
  topic: string;
  audience?: string;
  tone?: string;
}

export interface GenerateBlogResponse {
  session_id: string;
  status: string;
  message: string;
  budget_reserved_usd: number;
}

export interface SessionStatusResponse {
  session_id: string;
  status:
    | 'queued'
    | 'processing'
    | 'awaiting_outline_review'
    | 'awaiting_human_review'
    | 'revision_requested'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'budget_exhausted';
  current_stage: string | null;
  iteration_count: number;
  topic: string;
  requires_human_review: boolean;
  budget_spent_usd: number;
  budget_spent_tokens: number;
  current_version_number: number | null;
}

export interface OutlineSection {
  id: string;
  heading: string;
  goal: string;
  target_words: number;
}

export interface OutlineSchema {
  title: string;
  sections: OutlineSection[];
  estimated_total_words: number;
}

export interface OutlineReviewView {
  session_id: number;
  status: string;
  current_stage: string | null;
  topic: string;
  audience: string | null;
  feedback_text: string | null;
  outline: OutlineSchema;
}

export interface OutlineReviewRequest {
  action: 'approve' | 'revise';
  edited_outline?: OutlineSchema;
  feedback_text?: string;
  reviewer_user_id?: string;
}

export interface OutlineReviewDecision {
  session_id: number;
  action: string;
  new_status: string;
  current_stage: string | null;
  requires_human_review: boolean;
  outline: OutlineSchema;
  message: string;
}

export interface BlogVersionView {
  version_id: number;
  session_id: number;
  version_number: number;
  source_type: string;
  title: string | null;
  content_markdown: string | null;
  word_count: number;
  sources_count: number;
  editor_status: string;
  created_by: string;
  created_at: string;
}

export interface HumanReviewRequest {
  action: 'approve' | 'request_revision' | 'reject';
  feedback_text?: string;
  reviewer_user_id?: string;
}

export interface HumanReviewDecision {
  session_id: number;
  version_id: number;
  action: string;
  new_status: string;
  iteration_count: number;
  requires_human_review: boolean;
  message: string;
}

export interface BlogContentView {
  session_id: number;
  version_id: number;
  title: string | null;
  content_markdown: string;
  word_count: number;
  sources_count: number;
  topic: string;
  audience: string | null;
  status: string;
}

export interface BudgetSnapshot {
  end_user_id: number;
  tenant_id: number;
  daily_spent_usd: number;
  daily_spent_tokens: number;
  daily_limit_usd: number;
  daily_limit_tokens: number;
  active_sessions: number;
  max_concurrent_sessions: number;
  remaining_revision_iterations: number;
}

export interface AgentRunSummary {
  run_id: number;
  stage_name: string;
  agent_name: string;
  status: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface HumanReviewEventView {
  event_id: number;
  session_id: number;
  version_id: number;
  reviewer_user_id: string;
  action: string;
  feedback_text: string | null;
  review_context: Record<string, unknown> | null;
  created_at: string;
}

export interface SessionDetailView {
  session: {
    session_id: number;
    status: string;
    current_stage: string | null;
    iteration_count: number;
    topic: string;
    audience: string | null;
    requires_human_review: boolean;
    budget_spent_usd: number;
    budget_spent_tokens: number;
    remaining_revision_iterations: number;
    current_version_number: number | null;
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  };
  outline: OutlineReviewView | null;
  latest_version: BlogVersionView | null;
  review_events: HumanReviewEventView[];
  agent_runs: AgentRunSummary[];
}

export async function generateBlog(input: GenerateBlogRequest): Promise<GenerateBlogResponse> {
  return request<GenerateBlogResponse>('/api/v1/blogs/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function getSession(sessionId: string): Promise<SessionStatusResponse> {
  return request<SessionStatusResponse>(`/api/v1/blogs/${sessionId}`);
}

export async function getOutline(sessionId: string): Promise<OutlineReviewView> {
  return request<OutlineReviewView>(`/api/v1/blogs/${sessionId}/outline`);
}

export async function submitOutlineReview(
  sessionId: string,
  payload: OutlineReviewRequest,
): Promise<OutlineReviewDecision> {
  return request<OutlineReviewDecision>(`/api/v1/blogs/${sessionId}/outline/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getLatestVersion(sessionId: string): Promise<BlogVersionView> {
  return request<BlogVersionView>(`/api/v1/blogs/${sessionId}/versions/latest`);
}

export async function submitFinalReview(
  sessionId: string,
  versionId: number,
  payload: HumanReviewRequest,
): Promise<HumanReviewDecision> {
  return request<HumanReviewDecision>(
    `/api/v1/blogs/${sessionId}/review?version_id=${versionId}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export async function getContent(sessionId: string): Promise<BlogContentView> {
  return request<BlogContentView>(`/api/v1/blogs/${sessionId}/content`);
}

export async function getSessionDetail(sessionId: string): Promise<SessionDetailView> {
  return request<SessionDetailView>(`/api/v1/blogs/${sessionId}/detail`);
}

export async function getBudget(): Promise<BudgetSnapshot> {
  return request<BudgetSnapshot>('/api/v1/budgets/me');
}
