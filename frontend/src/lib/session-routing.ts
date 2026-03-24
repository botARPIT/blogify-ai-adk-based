// Maps backend statuses to frontend routes
export function getRouteForStatus(sessionId: string, status: string): string {
  switch (status) {
    case 'queued':
    case 'processing':
    case 'revision_requested':
    case 'failed':
    case 'cancelled':
    case 'budget_exhausted':
      return `/sessions/${sessionId}/progress`;
    case 'awaiting_outline_review':
      return `/sessions/${sessionId}/outline-review`;
    case 'awaiting_human_review':
      return `/sessions/${sessionId}/final-review`;
    case 'completed':
      return `/sessions/${sessionId}/output`;
    default:
      return `/sessions/${sessionId}/progress`;
  }
}
