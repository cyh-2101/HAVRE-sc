"""Add a pinned semantic index to exact current Memory revisions, preserving history."""

import argparse
from pathlib import Path
from uuid import UUID

from companion.memory.semantic import LocalSemanticEmbeddingProvider
from companion.persistence import PostgresRepository


def reindex(repository, *, owner_id, encoder) -> int:
    repository.register_embedding_version(encoder.version)
    count = 0
    with repository.pool.connection() as connection, connection.transaction():
        rows = connection.execute(
            """SELECT r.* FROM havre.memory_heads h JOIN havre.memory_revisions r
               ON r.owner_id=h.owner_id AND r.memory_id=h.memory_id
               AND r.revision=h.current_revision
               WHERE h.owner_id=%s AND h.status='active' AND NOT EXISTS (
                 SELECT 1 FROM havre.memory_embeddings e WHERE e.owner_id=r.owner_id
                  AND e.memory_id=r.memory_id AND e.memory_revision=r.revision
                  AND e.embedding_version_id=%s)
               ORDER BY r.memory_id FOR SHARE OF h,r""",
            (owner_id, encoder.version.embedding_version_id),
        ).fetchall()
        for row in rows:
            repository._insert_embedding(connection, repository._memory_from_row(row), encoder)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--owner-id", required=True, type=UUID)
    parser.add_argument("--model-root", type=Path, default=Path("var/models/memory-minilm-v1"))
    args = parser.parse_args()
    repository = PostgresRepository(args.database_url)
    repository.open()
    try:
        print({"indexed_current_revisions": reindex(repository, owner_id=args.owner_id,
                    encoder=LocalSemanticEmbeddingProvider(args.model_root))})
    finally:
        repository.close()


if __name__ == "__main__":
    main()
