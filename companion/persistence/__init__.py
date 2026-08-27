from typing import TYPE_CHECKING, Any

from companion.persistence.migrations import MigrationError, apply_migrations
from companion.persistence.postgres import LeaseLostError, PostgresRepository
from companion.persistence.proactive import ProactivePostgresStore
from companion.persistence.offline import Stage7PostgresStore
from companion.persistence.evaluation import Stage8PostgresStore
from companion.persistence.operations import Stage10PostgresStore
from companion.persistence.life_context import (
    ContextIdempotencyConflict,
    ContextIngestRejected,
    Stage12ContextStore,
    require_isolated_context_operator,
)

if TYPE_CHECKING:
    from companion.persistence.training import Stage9PostgresStore


def __getattr__(name: str) -> Any:
    if name == "Stage9PostgresStore":
        from companion.persistence.training import Stage9PostgresStore

        return Stage9PostgresStore
    raise AttributeError(name)

__all__ = [
    "LeaseLostError",
    "MigrationError",
    "PostgresRepository",
    "ProactivePostgresStore",
    "Stage7PostgresStore",
    "Stage8PostgresStore",
    "Stage9PostgresStore",
    "Stage10PostgresStore",
    "Stage12ContextStore",
    "ContextIngestRejected",
    "ContextIdempotencyConflict",
    "require_isolated_context_operator",
    "apply_migrations",
]
