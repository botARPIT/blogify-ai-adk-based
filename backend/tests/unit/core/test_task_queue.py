import pytest


@pytest.mark.asyncio
async def test_enqueue_rejects_job_when_redis_queue_is_at_capacity(mock_redis):
    from src.core.task_queue import BlogJob, QueueFullError, TaskQueue

    queue = TaskQueue()
    mock_redis.eval.return_value = 0  # Atomic Redis script reports LLEN >= max depth.
    job = BlogJob(
        session_id=1,
        user_id=2,
        adk_session_id="adk-session",
        topic="Queue backpressure",
        audience="developers",
        tone="direct",
        phase="fresh_generation",
    )

    with pytest.raises(QueueFullError, match="maximum 500"):
        await queue.enqueue(job)

    mock_redis.eval.assert_awaited_once()
    script, key_count, queue_key, max_depth, _job_json = mock_redis.eval.await_args.args
    assert "LLEN" in script
    assert "LPUSH" in script
    assert key_count == 1
    assert queue_key == queue.QUEUE_KEY
    assert max_depth == 500
    mock_redis.publish.assert_not_awaited()
