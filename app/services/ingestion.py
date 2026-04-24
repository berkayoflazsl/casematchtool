from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import asyncpg
import httpx

from app.config import get_settings
from app.embedding_model import EMBEDDING_MODEL_NAME
from app.services import chunking, embedding, fcl

_CITATION_RE = re.compile(
    r"\[(\d{4})\]\s*([A-Z]+(?:Civ|HC|IPEC|Fam|Ch|QB|Comm|Admin|Crim)+(?:\s+\d+)?\s+\d+)",
    re.I,
)


def _first_citation(text: str) -> str | None:
    m = _CITATION_RE.search(text)
    if m:
        return f"[{m.group(1)}] {m.group(2)}".replace("  ", " ")
    return None


def _json_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


def _atom_url() -> str:
    s = get_settings()
    u = s.fcl_atom_base
    if "order=" not in u:
        u = u + ("&order=-date" if "?" in u else "?order=-date")
    return u


async def upsert_case_and_chunks(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    source_uri: str,
    public_url: str,
    data_url: str,
    title: str | None,
) -> bool:
    try:
        xml = await fcl.fetch_bytes(client, data_url)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 410):
            return False
        raise
    full_text = fcl.judgment_text_from_xml_bytes(xml)
    if len(full_text) < 200:
        return False

    s = get_settings()
    chunks = chunking.chunk_text(full_text)
    if not chunks:
        return False
    embs = await asyncio.to_thread(embedding.embed_passages, chunks)
    vec_literals = [embedding.to_vector_sql_literal(e) for e in embs]

    neutral = _first_citation(full_text) or _first_citation(title or "")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO cases (
                    source_uri, title, full_text, source_public_url,
                    neutral_citation, raw_metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (source_uri) DO UPDATE SET
                    title = EXCLUDED.title,
                    full_text = EXCLUDED.full_text,
                    source_public_url = EXCLUDED.source_public_url,
                    neutral_citation = EXCLUDED.neutral_citation,
                    raw_metadata = EXCLUDED.raw_metadata
                RETURNING id
                """,
                source_uri,
                title,
                full_text,
                public_url,
                neutral,
                _json_dumps({"ingestion": "fcl", "text_len": len(full_text)}),
            )
            case_id = int(row["id"])
            await conn.execute("DELETE FROM case_chunks WHERE case_id = $1", case_id)
            for i, (content, vlit) in enumerate(zip(chunks, vec_literals, strict=True)):
                await conn.execute(
                    """
                    INSERT INTO case_chunks (
                        case_id, chunk_index, kind, content, embedding, embedding_model
                    )
                    VALUES ($1, $2, $3, $4, $5::vector, $6)
                    """,
                    case_id,
                    i,
                    "body",
                    content,
                    vlit,
                    EMBEDDING_MODEL_NAME,
                )
    await asyncio.sleep(s.fcl_request_sleep)
    return True


async def _existing_uris(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT source_uri FROM cases")
    return {r["source_uri"] for r in rows}


async def run_ingestion(
    pool: asyncpg.Pool,
    limit: int = 10,
    max_feed_pages: int = 2,
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    s = get_settings()
    start_url = _atom_url()
    limit = max(0, limit)
    if limit == 0:
        return {
            "ingestion_run_id": None,
            "candidates": 0,
            "ingested": 0,
            "skipped_feed_duplicates": 0,
            "skipped_already_in_db": 0,
            "feed_items_scanned": 0,
            "error": None,
        }

    already: set[str] = set()
    if skip_existing:
        async with pool.acquire() as conn:
            already = await _existing_uris(conn)

    # Feed: stream içi mükerrer yok. DB'de olmayan + limit adet topla, yetmezse sonraki sayfaya.
    scan = 0
    skipped_in_db = 0
    entries: list[tuple[str, str, str, str | None]] = []
    async for row in fcl.stream_feed_entries(
        start_url, max_pages=max(1, max_feed_pages)
    ):
        scan += 1
        s_uri = row[0]
        if skip_existing and s_uri in already:
            skipped_in_db += 1
            continue
        entries.append(row)
        if len(entries) >= limit:
            break

    run_id: int | None = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO ingestion_runs (status, source, items_fetched, items_embedded)
            VALUES ('running', $1, $2, 0)
            RETURNING id
            """,
            start_url,
            len(entries),
        )

    ok = 0
    err: str | None = None
    try:
        try:
            async with httpx.AsyncClient() as client:
                for s_uri, pub, d_url, title in entries:
                    try:
                        if await upsert_case_and_chunks(
                            pool, client, s_uri, pub, d_url, title
                        ):
                            ok += 1
                            if skip_existing:
                                already.add(s_uri)
                    except Exception as e:  # noqa: BLE001
                        err = f"{e!s}"
                        break
        except (KeyboardInterrupt, asyncio.CancelledError) as e:  # noqa: BLE001
            err = f"interrupted: {e!s}"
    except Exception as e:  # noqa: BLE001
        err = f"{e!s}"
    finally:
        # Zorunlu: süreç öldüğünde (IDE timeout, Ctrl+C) de satır "running" kalmasın
        if run_id is not None:
            if err and "interrupted" in err:
                st = "interrupted"
            elif err and ok == 0:
                st = "failed"
            elif err and ok > 0:
                st = "completed"
            else:
                st = "completed"
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE ingestion_runs
                        SET completed_at = now(),
                            status = $2,
                            items_embedded = $3,
                            error = $4
                        WHERE id = $1
                        """,
                        run_id,
                        st,
                        ok,
                        err,
                    )
            except Exception:  # noqa: BLE001, S110
                pass
    return {
        "ingestion_run_id": run_id,
        "candidates_to_process": len(entries),
        "ingested": ok,
        "feed_items_scanned": scan,
        "skipped_already_in_db": skipped_in_db,
        "error": err,
    }
