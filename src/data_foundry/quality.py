"""Data-quality helpers used when assembling the final datasets (target area 5).

Covers: encoding normalization, duplicate detection (by document hash),
missing-field bookkeeping, and schema validation against schemas.py.
Every issue found is recorded in a report instead of failing silently or
crashing the whole run.
"""

import unicodedata
from typing import Any

from pydantic import BaseModel, ValidationError


def normalize_text(value: Any) -> Any:

    if not isinstance(value, str):
        return value
    text = value.replace("\ufeff", "").replace("\xa0", " ")
    text = unicodedata.normalize("NFC", text)
    return text.strip() or None


def normalize_record(record: dict) -> dict:
    out = {}
    for k, v in record.items():
        if isinstance(v, dict):
            out[k] = normalize_record(v)
        elif isinstance(v, str):
            out[k] = normalize_text(v)
        else:
            out[k] = v
    return out


def dedupe_by_key(records: list[dict], key_fn) -> tuple[list[dict], list[dict]]:
    seen: dict[Any, dict] = {}
    dropped: list[dict] = []
    for r in records:
        key = key_fn(r)
        if key is None:
            seen[id(r)] = r  # no dedup key available, always keep
            continue
        if key in seen:
            dropped.append(r)
        else:
            seen[key] = r
    return list(seen.values()), dropped


def validate_records(
    records: list[dict], model: type[BaseModel]
) -> tuple[list[dict], list[dict]]:

    valid, errors = [], []
    for r in records:
        try:
            parsed = model.model_validate(r)
            valid.append(parsed.model_dump())
        except ValidationError as e:
            errors.append({"id": r.get("id", "<unknown>"), "error": str(e)})
    return valid, errors


def build_quality_report(
    stage: str,
    total_in: int,
    duplicates_dropped: int,
    validation_errors: list[dict],
    missing_fields: dict[str, int] | None = None,
) -> dict:
    return {
        "stage": stage,
        "records_in": total_in,
        "duplicates_dropped": duplicates_dropped,
        "validation_errors": validation_errors,
        "missing_fields": missing_fields or {},
        "records_out": total_in - duplicates_dropped - len(validation_errors),
    }


def count_missing(records: list[dict], fields: list[str]) -> dict[str, int]:
    counts = {f: 0 for f in fields}
    for r in records:
        for f in fields:
            if not r.get(f):
                counts[f] += 1
    return counts
