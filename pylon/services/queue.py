"""
Priority queue for request scheduling.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional, Callable, Awaitable
import heapq

from pylon.config import QueueConfig
from pylon.models.api_key import Priority


class QueueResult(IntEnum):
    """Result of queue operations."""

    ACQUIRED = 0
    TIMEOUT = 1
    PREEMPTED = 2


@dataclass
class QueuedRequest:
    """A request waiting in the queue."""

    user_id: str
    priority: Priority
    enqueue_time: datetime
    event: asyncio.Event = field(default_factory=asyncio.Event)
    preempted: bool = False

    def __lt__(self, other: "QueuedRequest") -> bool:
        """Compare for priority queue ordering."""
        # Higher priority (lower enum value) comes first
        # For same priority, earlier enqueue time comes first
        priority_order = {"high": 0, "normal": 1, "low": 2}
        self_priority = priority_order.get(self.priority.value, 1)
        other_priority = priority_order.get(other.priority.value, 1)

        if self_priority != other_priority:
            return self_priority < other_priority

        return self.enqueue_time < other.enqueue_time


class RequestQueue:
    """
    Priority queue for managing requests when concurrency limit is reached.

    Features:
    - Priority-based ordering (high > normal > low)
    - FIFO within same priority
    - High priority can preempt low priority when queue is full
    - Configurable timeout
    """

    def __init__(self, config: QueueConfig, on_slot_available: Callable[[], Awaitable[bool]]):
        """
        Initialize the request queue.

        Args:
            config: Queue configuration
            on_slot_available: Async callback to check if a slot is available.
                             Returns True if slot acquired, False otherwise.
        """
        self.config = config
        self.on_slot_available = on_slot_available
        self._queue: list[QueuedRequest] = []
        self._lock = asyncio.Lock()
        self._processor_task: Optional[asyncio.Task] = None

    @property
    def size(self) -> int:
        """Get current queue size."""
        return len(self._queue)

    async def enqueue(
        self,
        user_id: str,
        priority: Priority,
    ) -> QueueResult:
        """
        Add a request to the queue and wait for a slot.

        Args:
            user_id: The API key ID
            priority: Request priority

        Returns:
            QueueResult indicating outcome.
        """
        request = QueuedRequest(
            user_id=user_id,
            priority=priority,
            enqueue_time=datetime.now(timezone.utc),
        )

        async with self._lock:
            # Check if queue is full
            if len(self._queue) >= self.config.max_size:
                # Try to preempt a lower priority request
                preempted = await self._try_preempt(priority)
                if not preempted:
                    # Queue is full and can't preempt
                    return QueueResult.TIMEOUT

            # Add to queue
            heapq.heappush(self._queue, request)

        # Start processor if not running
        self._ensure_processor_running()

        # Wait for our turn or timeout
        try:
            await asyncio.wait_for(
                request.event.wait(),
                timeout=self.config.timeout,
            )

            if request.preempted:
                return QueueResult.PREEMPTED

            return QueueResult.ACQUIRED

        except asyncio.TimeoutError:
            # Remove from queue on timeout
            async with self._lock:
                self._remove_request(request)
            return QueueResult.TIMEOUT

    async def _try_preempt(self, priority: Priority) -> bool:
        """
        Try to preempt a lower priority request.

        Must be called with _lock held.

        Returns:
            True if a request was preempted, False otherwise.
        """
        if priority == Priority.LOW:
            # Low priority can't preempt anyone
            return False

        # Find lowest priority request to preempt
        priority_order = {"high": 0, "normal": 1, "low": 2}
        incoming_order = priority_order.get(priority.value, 1)

        # Find a request with lower priority (higher order number)
        for i, req in enumerate(self._queue):
            req_order = priority_order.get(req.priority.value, 1)
            if req_order > incoming_order:
                # Found a lower priority request to preempt
                req.preempted = True
                req.event.set()
                self._queue.pop(i)
                heapq.heapify(self._queue)
                return True

        return False

    def _remove_request(self, request: QueuedRequest) -> None:
        """Remove a request from the queue. Must be called with _lock held."""
        try:
            self._queue.remove(request)
            heapq.heapify(self._queue)
        except ValueError:
            pass  # Already removed

    def _ensure_processor_running(self) -> None:
        """Ensure the queue processor task is running."""
        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(self._process_queue())

    async def _process_queue(self) -> None:
        """Process the queue, granting slots to waiting requests."""
        while True:
            async with self._lock:
                if not self._queue:
                    # Queue empty, stop processing
                    return

                # Check if slot is available
                if await self.on_slot_available():
                    # Grant slot to highest priority request
                    request = heapq.heappop(self._queue)
                    request.event.set()

            # Small delay to prevent tight loop
            await asyncio.sleep(0.01)

    async def notify_slot_available(self) -> None:
        """Notify the queue that a slot has become available."""
        self._ensure_processor_running()

    def get_stats(self) -> dict:
        """Get queue statistics."""
        priority_counts = {"high": 0, "normal": 0, "low": 0}
        for req in self._queue:
            priority_counts[req.priority.value] += 1

        return {
            "queue_size": len(self._queue),
            "by_priority": priority_counts,
        }
