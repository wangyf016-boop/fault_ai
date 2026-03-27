from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List


def qdrant_doc_to_frontend_record(
    doc: Dict[str, Any],
    *,
    source: str = "qdrant",
    include_collection: bool = False,
    record_id: Any = None,
) -> Dict[str, Any]:
    safe_score = _safe_score(doc.get("score"))
    record: Dict[str, Any] = {
        "id": str(record_id if record_id is not None else doc.get("id", "")),
        "line": str(doc.get("line", "")),
        "station": str(doc.get("station", "")),
        "problem": str(doc.get("problem_description", "") or doc.get("problem", "")),
        "cause": str(doc.get("cause_analysis", "") or doc.get("cause", "")),
        "action": str(doc.get("containment_action", "") or doc.get("action", "")),
        "plan": str(doc.get("action_plan", "") or doc.get("plan", "")),
        "date": str(doc.get("date", "")),
        "score": safe_score,
        "score_percent": round((safe_score or 0) * 100, 2),
    }

    if source:
        record["source"] = source
    if include_collection:
        record["collection"] = doc.get("_collection", "")
    return record


def qdrant_docs_to_frontend_records(
    docs: Iterable[Dict[str, Any]],
    *,
    limit: int | None = None,
    source: str = "qdrant",
    include_collection: bool = False,
) -> List[Dict[str, Any]]:
    items = list(docs)
    if limit is not None:
        items = items[:limit]
    return [
        qdrant_doc_to_frontend_record(
            doc,
            source=source,
            include_collection=include_collection,
        )
        for doc in items
    ]


def _safe_score(value: Any) -> float | None:
    try:
        if value is None or math.isnan(value) or math.isinf(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None
