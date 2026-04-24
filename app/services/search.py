from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

import asyncpg

from app.config import chat_model_id, get_settings
from app.schemas import SearchHit, SearchRequest, SearchResponse
from app.services import embedding
from app.services.llm_client import get_async_openai_client


def _client_hash(s: str | None) -> str | None:
    if not s:
        return None
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _public_url(r: dict[str, Any]) -> str:
    p = r.get("source_public_url")
    if p:
        return str(p)
    su = r.get("source_uri") or ""
    if su:
        return f"https://caselaw.nationalarchives.gov.uk/{su}"
    return ""


async def _vector_search(
    pool: asyncpg.Pool,
    qvec: str,
    fetch_chunks: int,
) -> list[dict[str, Any]]:
    q = """
    SELECT
        cc.id AS chunk_id,
        cc.case_id,
        cc.content AS chunk_excerpt,
        1.0 - (cc.embedding <=> $1::vector) AS sim,
        c.source_uri,
        c.source_public_url,
        c.title,
        c.neutral_citation,
        c.court,
        c.decision_date,
        c.outcome_label
    FROM case_chunks cc
    JOIN cases c ON c.id = cc.case_id
    ORDER BY cc.embedding <=> $1::vector
    LIMIT $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, qvec, fetch_chunks)
    return [dict(r) for r in rows]


def _dedupe_cases(
    rows: list[dict[str, Any]], max_cases: int
) -> list[dict[str, Any]]:
    by_case: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_case[int(r["case_id"])].append(r)
    best: list[dict[str, Any]] = []
    for _cid, chunk_rows in by_case.items():
        best.append(max(chunk_rows, key=lambda x: float(x["sim"])))
    best.sort(key=lambda x: -float(x["sim"]))
    return best[:max_cases]


def _fmt_date(d: object) -> str | None:
    if d is None:
        return None
    return str(d)


log = logging.getLogger(__name__)

_LLM_SYSTEM = (
    "You are a UK legal research helper. Return one JSON object: "
    'key "results" = array of objects with case_id (int), similarity (0-100), '
    "short_summary (2-3 conservative sentences, excerpt only; do not invent facts), "
    "why_similar (1-2 sentences on overlap with the user query). "
    "Order from most to least useful. This is not legal advice."
)


def _parse_llm_json(raw: str) -> dict[str, Any]:
    t = (raw or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t)
    return json.loads(t)


def _rows_from_parsed(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    arr = data.get("results", [])
    out: list[dict[str, Any]] = []
    for item in arr:
        if not isinstance(item, dict) or "case_id" not in item:
            continue
        sim = item.get("similarity", 0)
        if isinstance(sim, (int, float)) and 0.0 <= float(sim) <= 1.0 + 1e-6:
            sim = float(sim) * 100.0
        out.append(
            {
                "case_id": int(item["case_id"]),
                "similarity": round(float(sim or 0.0), 1),
                "short_summary": str(item.get("short_summary", ""))[:2000],
                "why_similar": str(item.get("why_similar", ""))[:2000],
            }
        )
    return out


def _fallback_llm(
    cands: list[dict[str, Any]],
    *,
    no_key: bool = False,
    llm_skipped: bool = False,
) -> list[dict[str, Any]]:
    if llm_skipped:
        msg = "LLM disabled for this request; results ranked by embedding only."
    elif no_key:
        msg = (
            "Set OPENAI_API_KEY (e.g. OpenRouter key) and LLM_SERVICE_URL for AI summaries."
        )
    else:
        msg = "LLM off or timeout; showing embedding order only."
    return [
        {
            "case_id": c["case_id"],
            "similarity": round(100.0 * float(c["sim"]), 1),
            "short_summary": msg,
            "why_similar": "Ranked by local embedding (BGE) only.",
        }
        for c in cands
    ]


async def _llm_rerank(
    user_query: str, candidates: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    s = get_settings()
    if not s.openai_api_key:
        return _fallback_llm(candidates, no_key=True), False

    client = get_async_openai_client()
    model_id = chat_model_id(s)
    ex_max = s.search_llm_excerpt_chars
    brief = [
        {
            "case_id": c["case_id"],
            "title": c.get("title") or "",
            "citation": c.get("neutral_citation") or "",
            "excerpt": (c.get("chunk_excerpt") or "")[:ex_max],
            "embedding_rank_score_0_1": float(c["sim"]),
        }
        for c in candidates
    ]
    user = json.dumps(
        {"user_query": user_query, "candidates": brief},
        ensure_ascii=False,
    )
    max_out = s.search_llm_max_output_tokens

    last_err: str | None = None
    for use_json in (True, False):
        try:
            kwargs: dict[str, Any] = {
                "model": model_id,
                "temperature": 0.2,
                "max_tokens": max_out,
                "messages": [
                    {"role": "system", "content": _LLM_SYSTEM},
                    {"role": "user", "content": user},
                ],
            }
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            comp = await client.chat.completions.create(**kwargs)
            raw = comp.choices[0].message.content or "{}"
            data = _parse_llm_json(raw)
            out = _rows_from_parsed(data)
            if out:
                return out, True
        except Exception as e:  # noqa: BLE001
            last_err = f"{e!s}"[:500]
            log.warning("LLM call failed (json_mode=%s): %s", use_json, last_err)
            continue
    if last_err:
        log.warning("LLM gave no usable results; last error: %s", last_err)
    return _fallback_llm(candidates, no_key=False), False


def _by_case_id(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    d: dict[int, dict[str, Any]] = {}
    for r in rows:
        d[int(r["case_id"])] = r
    return d


def _build_hit(
    base: dict[str, Any], meta: dict[str, Any] | None
) -> SearchHit:
    ex = base.get("chunk_excerpt")
    ex_s = str(ex) if ex is not None else None
    if ex_s and len(ex_s) > 500:
        ex_s = ex_s[:500] + "…"
    if meta:
        return SearchHit(
            case_id=int(base["case_id"]),
            source_uri=str(base.get("source_uri", "")),
            public_url=_public_url(base) or None,
            title=base.get("title"),
            neutral_citation=base.get("neutral_citation"),
            court=base.get("court"),
            decision_date=_fmt_date(base.get("decision_date")),
            outcome_label=base.get("outcome_label"),
            similarity=float(meta.get("similarity", 0.0)),
            short_summary=meta.get("short_summary", ""),
            why_similar=meta.get("why_similar", ""),
            chunk_excerpt=ex_s,
        )
    return SearchHit(
        case_id=int(base["case_id"]),
        source_uri=str(base.get("source_uri", "")),
        public_url=_public_url(base) or None,
        title=base.get("title"),
        neutral_citation=base.get("neutral_citation"),
        court=base.get("court"),
        decision_date=_fmt_date(base.get("decision_date")),
        outcome_label=base.get("outcome_label"),
        similarity=round(100.0 * float(base["sim"]), 1),
        short_summary="",
        why_similar="",
        chunk_excerpt=ex_s,
    )


async def run_search(
    pool: asyncpg.Pool,
    body: SearchRequest,
    client_ip: str | None = None,
) -> SearchResponse:
    s = get_settings()
    cand_k = body.candidate_k or s.search_candidate_k
    final_n = body.final_n or s.search_final_n
    t0 = time.perf_counter()

    qe = (await asyncio.to_thread(embedding.embed_queries, [body.query]))[0]
    qvec = embedding.to_vector_sql_literal(qe)

    raw_rows = await _vector_search(pool, qvec, min(cand_k * 4, 200))
    deduped = _dedupe_cases(raw_rows, cand_k)
    if not deduped:
        return SearchResponse(results=[], used_llm=False, query=body.query)

    to_rank = deduped[: min(cand_k, 50)]

    if not body.use_llm:
        take = deduped[:final_n]
        fbm = _fallback_llm(take, llm_skipped=True)
        ordered = [
            _build_hit(b, m) for b, m in zip(take, fbm, strict=True)
        ]
        openai_ok = False
    else:
        llm_cands = to_rank[: s.search_llm_max_cases]
        try:
            rank_meta, openai_ok = await asyncio.wait_for(
                _llm_rerank(body.query, llm_cands),
                timeout=s.search_llm_timeout_sec,
            )
        except TimeoutError:
            rank_meta, openai_ok = _fallback_llm(
                llm_cands, no_key=False, llm_skipped=False
            ), False
        by_id = _by_case_id(to_rank)
        ordered = []
        for m in rank_meta:
            b = by_id.get(int(m["case_id"]))
            if b is None:
                continue
            ordered.append(_build_hit(b, m))
        if len(ordered) < final_n:
            done = {h.case_id for h in ordered}
            for b in to_rank:
                if len(ordered) >= final_n:
                    break
                cid = int(b["case_id"])
                if cid in done:
                    continue
                ordered.append(_build_hit(b, None))
                done.add(cid)

    lat = int(1000 * (time.perf_counter() - t0))
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO search_events (query, result_count, client_hash, latency_ms)
                VALUES ($1, $2, $3, $4)
                """,
                body.query[:2000],
                len(ordered),
                _client_hash(client_ip),
                lat,
            )
    except Exception:  # noqa: BLE001, S110
        pass

    return SearchResponse(
        results=ordered[:final_n],
        used_llm=openai_ok,
        query=body.query,
    )
