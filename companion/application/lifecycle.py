"""Cancellation-safe draining of already-owned interaction work."""

import asyncio

import anyio


INTERACTION_DEADLINE_SECONDS = 300


async def settle_cancelled_task(task: asyncio.Task) -> None:
    """Finish durable cleanup despite level or repeated parent cancellation.

    The caller re-raises its original cancellation afterward. Generation children
    are cancelled once; in-flight database threads are drained without cancelling
    their awaitable. Never abandon an in-flight database commit.
    """
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()  # consume errors; the original caller was cancelled
