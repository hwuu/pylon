"""
Tests for request queue.
"""

import pytest
import asyncio
from pylon.services.queue import RequestQueue, QueueResult
from pylon.config import QueueConfig
from pylon.models.api_key import Priority


class TestRequestQueue:
    """Tests for RequestQueue class."""

    @pytest.mark.asyncio
    async def test_immediate_acquire_when_slot_available(self):
        """Test that request is immediately acquired when slot is available."""
        slot_available = True

        async def check_slot():
            nonlocal slot_available
            if slot_available:
                slot_available = False
                return True
            return False

        config = QueueConfig(max_size=10, timeout=5)
        queue = RequestQueue(config, check_slot)

        result = await queue.enqueue("user1", Priority.NORMAL)
        assert result == QueueResult.ACQUIRED

    @pytest.mark.asyncio
    async def test_queue_timeout(self):
        """Test that request times out when no slot becomes available."""
        async def check_slot():
            return False  # Never available

        config = QueueConfig(max_size=10, timeout=0.1)  # Short timeout
        queue = RequestQueue(config, check_slot)

        result = await queue.enqueue("user1", Priority.NORMAL)
        assert result == QueueResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """Test that higher priority requests are processed first."""
        acquired_order = []
        slot_count = 0

        async def check_slot():
            nonlocal slot_count
            # Only allow one slot at a time, with delay
            await asyncio.sleep(0.05)
            slot_count += 1
            return True

        config = QueueConfig(max_size=10, timeout=5)
        queue = RequestQueue(config, check_slot)

        async def enqueue_and_record(user_id, priority):
            result = await queue.enqueue(user_id, priority)
            if result == QueueResult.ACQUIRED:
                acquired_order.append(user_id)

        # Enqueue in order: low, normal, high
        # But they should be processed: high, normal, low
        tasks = [
            asyncio.create_task(enqueue_and_record("low_user", Priority.LOW)),
            asyncio.create_task(enqueue_and_record("normal_user", Priority.NORMAL)),
            asyncio.create_task(enqueue_and_record("high_user", Priority.HIGH)),
        ]

        await asyncio.gather(*tasks)

        # High priority should be first
        assert acquired_order[0] == "high_user"

    @pytest.mark.asyncio
    async def test_preemption(self):
        """Test that high priority can preempt low priority when queue is full."""
        async def check_slot():
            return False  # Never available, force queueing

        config = QueueConfig(max_size=1, timeout=0.5)
        queue = RequestQueue(config, check_slot)

        # Start a low priority request
        low_task = asyncio.create_task(
            queue.enqueue("low_user", Priority.LOW)
        )

        # Wait for it to be queued
        await asyncio.sleep(0.05)
        assert queue.size == 1

        # Now enqueue high priority - should preempt
        high_task = asyncio.create_task(
            queue.enqueue("high_user", Priority.HIGH)
        )

        # Wait for preemption
        await asyncio.sleep(0.05)

        # Low priority should be preempted
        low_result = await low_task
        assert low_result == QueueResult.PREEMPTED

        # High priority should timeout (no slots available)
        high_result = await high_task
        assert high_result == QueueResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_queue_full_no_preemption_possible(self):
        """Test queue full when preemption not possible (same priority)."""
        async def check_slot():
            return False

        config = QueueConfig(max_size=1, timeout=0.1)
        queue = RequestQueue(config, check_slot)

        # Queue a normal priority request
        task1 = asyncio.create_task(
            queue.enqueue("user1", Priority.NORMAL)
        )
        await asyncio.sleep(0.02)

        # Try to queue another normal priority - should fail immediately
        result = await queue.enqueue("user2", Priority.NORMAL)
        assert result == QueueResult.TIMEOUT

        await task1

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting queue statistics."""
        async def check_slot():
            return False

        config = QueueConfig(max_size=10, timeout=1)
        queue = RequestQueue(config, check_slot)

        # Start some requests
        tasks = [
            asyncio.create_task(queue.enqueue("user1", Priority.HIGH)),
            asyncio.create_task(queue.enqueue("user2", Priority.NORMAL)),
            asyncio.create_task(queue.enqueue("user3", Priority.LOW)),
        ]

        await asyncio.sleep(0.05)

        stats = queue.get_stats()
        assert stats["queue_size"] == 3
        assert stats["by_priority"]["high"] == 1
        assert stats["by_priority"]["normal"] == 1
        assert stats["by_priority"]["low"] == 1

        # Cancel tasks to clean up
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_slot_notification(self):
        """Test that slot notification triggers queue processing."""
        slot_available = False

        async def check_slot():
            return slot_available

        config = QueueConfig(max_size=10, timeout=5)
        queue = RequestQueue(config, check_slot)

        # Start a request that will wait
        async def delayed_enqueue():
            return await queue.enqueue("user1", Priority.NORMAL)

        task = asyncio.create_task(delayed_enqueue())
        await asyncio.sleep(0.05)

        # Make slot available and notify
        slot_available = True
        await queue.notify_slot_available()

        # Request should now complete
        result = await asyncio.wait_for(task, timeout=1)
        assert result == QueueResult.ACQUIRED
