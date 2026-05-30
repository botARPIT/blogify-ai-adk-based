// Maps backend statuses to frontend routes
export function getRouteForStatus(sessionId: string, status: string): string {
  // Normalize status to lowercase for case-insensitive matching
  const normalizedStatus = status?.toLowerCase();

  switch (normalizedStatus) {
    case 'queued':
    case 'processing':
    case 'revision_requested':
    case 'failed':
    case 'rejected':
    case 'cancelled':
      return `/sessions/${sessionId}/progress`;
    case 'awaiting_outline_review':
      return `/sessions/${sessionId}/outline-review`;
    case 'awaiting_final_review':
      return `/sessions/${sessionId}/final-review`;
    case 'completed':
      return `/sessions/${sessionId}/output`;
    default:
      return `/sessions/${sessionId}/progress`;
  }
}
