"""Process-owned ordinary replies; a disconnected viewer is not a cancellation."""

import asyncio
import logging

import anyio

from companion.application import InferenceTimeoutError
from companion.application.lifecycle import INTERACTION_DEADLINE_SECONDS

logger = logging.getLogger(__name__)


class InteractionTasks:
    def __init__(self, *, timeout_seconds: float = INTERACTION_DEADLINE_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.tasks: set[asyncio.Task] = set()

    async def _execute(self, service, command):
        try:
            return await asyncio.wait_for(service.interact(command), self.timeout_seconds)
        except TimeoutError as error:
            raise InferenceTimeoutError('interaction deadline exceeded') from error

    async def run(self, service, command):
        task = asyncio.create_task(self._execute(service, command))
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning('background reply ended with %s', type(task.exception()).__name__)

    async def aclose(self):
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
