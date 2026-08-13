# -*- coding: utf-8 -*-
"""PostgreSQL/pgvector implementation of the AgentScope vector store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from sqlalchemy.engine import make_url

from ._vector_store import (
    DocumentSummary,
    VectorRecord,
    VectorSearchResult,
    VectorStoreBase,
)
from .._document import Chunk

if TYPE_CHECKING:
    from asyncpg import Connection, Pool


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_VECTOR_DIMENSIONS = 16_000
_HNSW_VECTOR_DIMENSIONS = 2_000
_HNSW_HALFVEC_DIMENSIONS = 4_000


@dataclass(frozen=True, slots=True)
class _CollectionInfo:
    """Physical PostgreSQL storage allocated for one knowledge base."""

    table_name: str
    dimensions: int


class PGVectorStore(VectorStoreBase):
    """Store every knowledge base in an isolated pgvector table.

    A small catalog in ``knowledge.vector_collections`` maps the logical
    AgentScope collection name to a deterministic physical table. Separate
    tables preserve the embedding dimension selected by each knowledge base
    while keeping collection create/drop semantics compatible with Qdrant.
    """

    def __init__(
        self,
        database_url: str,
        *,
        schema: str = "knowledge",
        min_pool_size: int = 1,
        max_pool_size: int = 10,
        command_timeout: float = 60.0,
    ) -> None:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("PGVectorStore requires a PostgreSQL database URL")
        if not _IDENTIFIER_PATTERN.fullmatch(schema):
            raise ValueError(
                "PGVectorStore schema must be a safe PostgreSQL identifier",
            )
        if min_pool_size < 0 or max_pool_size < 1:
            raise ValueError("Invalid PostgreSQL connection pool size")
        if min_pool_size > max_pool_size:
            raise ValueError("min_pool_size cannot exceed max_pool_size")

        query = dict(url.query)
        query.pop("options", None)
        self._database_url = url.set(
            drivername="postgresql",
            query=query,
        ).render_as_string(hide_password=False)
        self._schema = schema
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._command_timeout = command_timeout
        self._pool: "Pool | None" = None
        self._pool_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await self._get_pool()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _quote_identifier(value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"Unsafe PostgreSQL identifier: {value!r}")
        return f'"{value}"'

    @classmethod
    def _table_name_for_collection(cls, collection: str) -> str:
        digest = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:32]
        return f"kbv_{digest}"

    @staticmethod
    def _validate_collection_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Collection name must be a non-empty string")
        if len(name) > 255:
            raise ValueError("Collection name cannot exceed 255 characters")

    @staticmethod
    def _validate_dimensions(dimensions: int) -> None:
        if (
            not isinstance(dimensions, int)
            or isinstance(dimensions, bool)
            or dimensions < 1
            or dimensions > _MAX_VECTOR_DIMENSIONS
        ):
            raise ValueError(
                "Embedding dimensions must be between 1 and 16000",
            )

    @staticmethod
    def _vector_literal(
        vector: list[float],
        dimensions: int,
        *,
        require_non_zero: bool = False,
    ) -> str:
        if len(vector) != dimensions:
            raise ValueError(
                f"Expected vector dimension {dimensions}, got {len(vector)}",
            )
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Vector values must all be finite")
        if require_non_zero and not any(value != 0.0 for value in values):
            raise ValueError("Cosine search does not accept an all-zero vector")
        return "[" + ",".join(format(value, ".9g") for value in values) + "]"

    @staticmethod
    def _decode_json(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            decoded = json.loads(value)
            return dict(decoded)
        return dict(value)

    def _qualified_table(self, table_name: str) -> str:
        return (
            f"{self._quote_identifier(self._schema)}."
            f"{self._quote_identifier(table_name)}"
        )

    @property
    def _catalog_table(self) -> str:
        return self._qualified_table("vector_collections")

    async def _get_pool(self) -> "Pool":
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    import asyncpg

                    self._pool = await asyncpg.create_pool(
                        dsn=self._database_url,
                        min_size=self._min_pool_size,
                        max_size=self._max_pool_size,
                        command_timeout=self._command_timeout,
                        server_settings={
                            "search_path": f"{self._schema},public",
                        },
                    )
        return self._pool

    async def _lookup_collection(
        self,
        connection: "Connection",
        name: str,
        *,
        required: bool = True,
    ) -> _CollectionInfo | None:
        row = await connection.fetchrow(
            (
                "SELECT table_name, dimensions "
                f"FROM {self._catalog_table} WHERE name = $1"
            ),
            name,
        )
        if row is None:
            if required:
                raise ValueError(f"Vector collection {name!r} does not exist")
            return None
        return _CollectionInfo(
            table_name=str(row["table_name"]),
            dimensions=int(row["dimensions"]),
        )

    async def create_collection(
        self,
        name: str,
        dimensions: int,
    ) -> None:
        self._validate_collection_name(name)
        self._validate_dimensions(dimensions)
        pool = await self._get_pool()
        table_name = self._table_name_for_collection(name)
        qualified_table = self._qualified_table(table_name)
        document_index = self._quote_identifier(f"ix_{table_name}_doc")
        vector_index = self._quote_identifier(f"ix_{table_name}_cos")

        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))",
                    f"{self._schema}:{name}",
                )
                existing = await self._lookup_collection(
                    connection,
                    name,
                    required=False,
                )
                if existing is not None:
                    if existing.dimensions != dimensions:
                        raise ValueError(
                            f"Collection {name!r} already uses "
                            f"{existing.dimensions} dimensions",
                        )
                    return

                await connection.execute(
                    f"""
                    CREATE TABLE {qualified_table} (
                        id UUID PRIMARY KEY
                            DEFAULT public.gen_random_uuid(),
                        document_id TEXT NOT NULL,
                        chunk JSONB NOT NULL,
                        embedding public.vector({dimensions}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """,
                )
                await connection.execute(
                    f"""
                    CREATE INDEX {document_index}
                    ON {qualified_table} (document_id)
                    """,
                )
                if dimensions <= _HNSW_VECTOR_DIMENSIONS:
                    await connection.execute(
                        f"""
                        CREATE INDEX {vector_index}
                        ON {qualified_table}
                        USING hnsw (embedding public.vector_cosine_ops)
                        WITH (m = 16, ef_construction = 64)
                        """,
                    )
                elif dimensions <= _HNSW_HALFVEC_DIMENSIONS:
                    await connection.execute(
                        f"""
                        CREATE INDEX {vector_index}
                        ON {qualified_table}
                        USING hnsw (
                            (embedding::public.halfvec({dimensions}))
                            public.halfvec_cosine_ops
                        )
                        WITH (m = 16, ef_construction = 64)
                        """,
                    )

                await connection.execute(
                    (
                        f"INSERT INTO {self._catalog_table} "
                        "(name, table_name, dimensions) VALUES ($1, $2, $3)"
                    ),
                    name,
                    table_name,
                    dimensions,
                )

    async def delete_collection(self, name: str) -> None:
        self._validate_collection_name(name)
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))",
                    f"{self._schema}:{name}",
                )
                info = await self._lookup_collection(
                    connection,
                    name,
                    required=False,
                )
                if info is None:
                    return
                await connection.execute(
                    f"DROP TABLE IF EXISTS "
                    f"{self._qualified_table(info.table_name)} CASCADE",
                )
                await connection.execute(
                    f"DELETE FROM {self._catalog_table} WHERE name = $1",
                    name,
                )

    async def has_collection(self, name: str) -> bool:
        self._validate_collection_name(name)
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            info = await self._lookup_collection(
                connection,
                name,
                required=False,
            )
        return info is not None

    async def insert(
        self,
        collection: str,
        records: list[VectorRecord],
    ) -> None:
        if not records:
            return
        self._validate_collection_name(collection)
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            info = await self._lookup_collection(connection, collection)
            assert info is not None
            values = [
                (
                    record.document_id,
                    json.dumps(
                        record.chunk.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                    self._vector_literal(record.vector, info.dimensions),
                )
                for record in records
            ]
            async with connection.transaction():
                await connection.executemany(
                    (
                        f"INSERT INTO {self._qualified_table(info.table_name)} "
                        "(document_id, chunk, embedding) "
                        "VALUES ($1, $2::jsonb, $3::public.vector)"
                    ),
                    values,
                )

    async def delete(
        self,
        collection: str,
        document_id: str,
    ) -> None:
        self._validate_collection_name(collection)
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            info = await self._lookup_collection(connection, collection)
            assert info is not None
            await connection.execute(
                (
                    f"DELETE FROM {self._qualified_table(info.table_name)} "
                    "WHERE document_id = $1"
                ),
                document_id,
            )

    @staticmethod
    def _distance_expression(dimensions: int) -> str:
        if dimensions <= _HNSW_VECTOR_DIMENSIONS:
            return "embedding <=> $1::public.vector"
        if dimensions <= _HNSW_HALFVEC_DIMENSIONS:
            return (
                f"(embedding::public.halfvec({dimensions})) <=> "
                f"(($1::public.vector)::public.halfvec({dimensions}))"
            )
        return "embedding <=> $1::public.vector"

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        self._validate_collection_name(collection)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            return []

        pool = await self._get_pool()
        async with pool.acquire() as connection:
            info = await self._lookup_collection(connection, collection)
            assert info is not None
            vector = self._vector_literal(
                query_vector,
                info.dimensions,
                require_non_zero=True,
            )
            distance = self._distance_expression(info.dimensions)
            table = self._qualified_table(info.table_name)
            if metadata_filter:
                rows = await connection.fetch(
                    f"""
                    SELECT document_id, chunk, 1 - ({distance}) AS score
                    FROM {table}
                    WHERE chunk->'metadata' @> $2::jsonb
                    ORDER BY {distance}
                    LIMIT $3
                    """,
                    vector,
                    json.dumps(metadata_filter, ensure_ascii=False),
                    top_k,
                )
            else:
                rows = await connection.fetch(
                    f"""
                    SELECT document_id, chunk, 1 - ({distance}) AS score
                    FROM {table}
                    ORDER BY {distance}
                    LIMIT $2
                    """,
                    vector,
                    top_k,
                )

        return [
            VectorSearchResult(
                score=float(row["score"]),
                document_id=str(row["document_id"]),
                chunk=Chunk.model_validate(self._decode_json(row["chunk"])),
            )
            for row in rows
        ]

    async def list_documents(
        self,
        collection: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[DocumentSummary]:
        self._validate_collection_name(collection)
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            info = await self._lookup_collection(connection, collection)
            assert info is not None
            table = self._qualified_table(info.table_name)
            if metadata_filter:
                rows = await connection.fetch(
                    f"""
                    WITH ranked AS (
                        SELECT
                            document_id,
                            chunk,
                            row_number() OVER (
                                PARTITION BY document_id
                                ORDER BY created_at, id
                            ) AS row_number,
                            count(*) OVER (
                                PARTITION BY document_id
                            ) AS chunk_count
                        FROM {table}
                        WHERE chunk->'metadata' @> $1::jsonb
                    )
                    SELECT document_id, chunk, chunk_count
                    FROM ranked
                    WHERE row_number = 1
                    ORDER BY document_id
                    """,
                    json.dumps(metadata_filter, ensure_ascii=False),
                )
            else:
                rows = await connection.fetch(
                    f"""
                    WITH ranked AS (
                        SELECT
                            document_id,
                            chunk,
                            row_number() OVER (
                                PARTITION BY document_id
                                ORDER BY created_at, id
                            ) AS row_number,
                            count(*) OVER (
                                PARTITION BY document_id
                            ) AS chunk_count
                        FROM {table}
                    )
                    SELECT document_id, chunk, chunk_count
                    FROM ranked
                    WHERE row_number = 1
                    ORDER BY document_id
                    """,
                )

        summaries: list[DocumentSummary] = []
        for row in rows:
            chunk = self._decode_json(row["chunk"])
            summaries.append(
                DocumentSummary(
                    document_id=str(row["document_id"]),
                    source=str(chunk.get("source", "")),
                    chunk_count=int(row["chunk_count"]),
                    metadata=dict(chunk.get("metadata", {})),
                ),
            )
        return summaries
