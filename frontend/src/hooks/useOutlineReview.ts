import { useEffect, useState } from 'react';
import {
  getOutline,
  submitOutlineReview,
  type OutlineReviewDecision,
  type OutlineReviewRequest,
  type OutlineReviewView,
} from '../lib/api/blogs';

export function useOutlineReview(sessionId: string | undefined) {
  const [outlineView, setOutlineView] = useState<OutlineReviewView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    let isActive = true;
    setLoading(true);
    getOutline(sessionId)
      .then((data) => {
        if (!isActive) return;
        setOutlineView(data);
        setError(null);
      })
      .catch((err) => {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch outline');
      })
      .finally(() => {
        if (isActive) setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [sessionId]);

  const submit = async (
    action: 'approve' | 'revise',
    payload: Pick<OutlineReviewRequest, 'edited_outline' | 'feedback_text'>,
  ): Promise<OutlineReviewDecision> => {
    if (!sessionId) {
      throw new Error('Missing session id');
    }
    setSubmitting(true);
    try {
      const response = await submitOutlineReview(sessionId, {
        action,
        edited_outline: payload.edited_outline,
        feedback_text: payload.feedback_text,
      });
      setOutlineView((current) =>
        current
          ? {
              ...current,
              status: response.new_status,
              current_stage: response.current_stage,
              feedback_text: payload.feedback_text || null,
              outline: response.outline,
            }
          : current,
      );
      return response;
    } finally {
      setSubmitting(false);
    }
  };

  return {
    outlineView,
    loading,
    error,
    submitting,
    submit,
  };
}
