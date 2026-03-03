from __future__ import annotations

import json
import logging
from typing import Any

from app_config import load_app_config
from organizer.result_checker import (
    CheckResult,
    CheckSkipReason,
    check_root_scan,
    check_single,
)
from ._helpers import validate_check_reaction_dir, validate_check_root_dir

logger = logging.getLogger(__name__)


def _check_item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "check_name": item.check_name,
        "severity": item.severity,
        "message": item.message,
        "details": item.details,
    }


def _result_to_dict(result: CheckResult) -> dict[str, Any]:
    return {
        "reaction_dir": result.reaction_dir,
        "run_id": result.run_id,
        "job_type": result.job_type,
        "overall": result.overall,
        "checks": [_check_item_to_dict(item) for item in result.checks],
    }


def _skip_to_dict(skip: CheckSkipReason) -> dict[str, Any]:
    return {"reaction_dir": skip.reaction_dir, "reason": skip.reason}


def _emit_check(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    for key in ("action", "checked", "skipped", "failed", "warned"):
        if key in payload:
            print(f"{key}: {payload[key]}")
    for result in payload.get("results", []):
        print(
            "  [{overall}] {reaction_dir} (run_id={run_id}, type={job_type})".format(
                overall=str(result.get("overall", "?")).upper(),
                reaction_dir=result.get("reaction_dir", "?"),
                run_id=result.get("run_id", "?"),
                job_type=result.get("job_type", "?"),
            )
        )
        for item in result.get("checks", []):
            if item.get("severity") == "ok":
                continue
            print(f"    {item.get('severity')}: {item.get('message')}")
    for skip in payload.get("skip_reasons", []):
        print(f"  SKIP {skip['reaction_dir']}: {skip['reason']}")


def cmd_check(args: Any) -> int:
    cfg = load_app_config(getattr(args, "config", None))
    as_json = bool(getattr(args, "json", False))

    reaction_dir_raw = getattr(args, "reaction_dir", None)
    root_raw = getattr(args, "root", None)
    if reaction_dir_raw and root_raw:
        logger.error("--reaction-dir and --root are mutually exclusive")
        return 1

    results: list[CheckResult]
    skips: list[CheckSkipReason]
    if reaction_dir_raw:
        try:
            reaction_dir = validate_check_reaction_dir(cfg, reaction_dir_raw)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        result, skip = check_single(reaction_dir)
        results = [result] if result is not None else []
        skips = [skip] if skip is not None else []
    else:
        if root_raw:
            try:
                root = validate_check_root_dir(cfg, root_raw)
            except ValueError as exc:
                logger.error("%s", exc)
                return 1
        else:
            root = validate_check_root_dir(cfg, cfg.runtime.organized_root)
        results, skips = check_root_scan(root)

    failed_count = sum(1 for result in results if result.overall == "fail")
    warned_count = sum(1 for result in results if result.overall == "warn")
    payload: dict[str, Any] = {
        "action": "scan",
        "checked": len(results),
        "skipped": len(skips),
        "failed": failed_count,
        "warned": warned_count,
        "results": [_result_to_dict(result) for result in results],
        "skip_reasons": [_skip_to_dict(skip) for skip in skips],
    }
    _emit_check(payload, as_json=as_json)
    return 1 if failed_count > 0 else 0

