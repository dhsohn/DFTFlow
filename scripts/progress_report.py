#!/usr/bin/env python3
"""Build and optionally send a run progress summary from allowed_root."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _bootstrap_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@dataclass
class RunSummary:
    run_id: str
    reaction_dir: str
    status: str
    attempts: int
    reason: str
    updated_at: str
    age_minutes: int | None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="progress_report.py")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to pyscf_auto config (default loader order applies).",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print summary only and do not send Telegram message.",
    )
    parser.add_argument(
        "--max-running",
        type=int,
        default=10,
        help="Maximum running/retrying entries in text summary.",
    )
    parser.add_argument(
        "--max-terminal",
        type=int,
        default=5,
        help="Maximum completed/failed entries in text summary.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    return parser.parse_args()


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_minutes(value: Any) -> int | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def _build_run_summary(state: dict[str, Any], reaction_dir: Path) -> RunSummary:
    attempts = state.get("attempts")
    final_result = state.get("final_result")
    reason = ""
    if isinstance(final_result, dict):
        reason_value = final_result.get("reason")
        if isinstance(reason_value, str):
            reason = reason_value
    updated_at = state.get("updated_at")
    return RunSummary(
        run_id=str(state.get("run_id", "")),
        reaction_dir=str(reaction_dir),
        status=str(state.get("status", "unknown")),
        attempts=len(attempts) if isinstance(attempts, list) else 0,
        reason=reason,
        updated_at=str(updated_at or ""),
        age_minutes=_age_minutes(updated_at),
    )


def _collect_summaries(allowed_root: Path) -> list[RunSummary]:
    summaries: list[RunSummary] = []
    for state_file in sorted(allowed_root.rglob("run_state.json")):
        if state_file.is_symlink():
            continue
        state = _load_state(state_file)
        if state is None:
            continue
        summaries.append(_build_run_summary(state, state_file.parent))
    return summaries


def _group_counts(summaries: list[RunSummary]) -> dict[str, int]:
    counts = {
        "running": 0,
        "retrying": 0,
        "created": 0,
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "unknown": 0,
    }
    for item in summaries:
        status = item.status if item.status in counts else "unknown"
        counts[status] += 1
    return counts


def _format_summary_text(
    allowed_root: Path,
    summaries: list[RunSummary],
    *,
    max_running: int,
    max_terminal: int,
) -> str:
    counts = _group_counts(summaries)
    lines = [
        "[pyscf_auto] progress summary",
        f"allowed_root={allowed_root}",
        f"total={len(summaries)}",
        "counts: "
        + ", ".join(f"{key}={value}" for key, value in counts.items() if value > 0),
    ]

    running_statuses = {"running", "retrying", "created"}
    running_items = [item for item in summaries if item.status in running_statuses]
    terminal_items = [item for item in summaries if item.status in {"completed", "failed", "interrupted"}]
    running_items.sort(key=lambda item: (item.age_minutes is None, -(item.age_minutes or 0)))
    terminal_items.sort(key=lambda item: item.updated_at, reverse=True)

    if running_items:
        lines.append("")
        lines.append(f"active (top {max_running}):")
        for item in running_items[:max_running]:
            age_text = f"{item.age_minutes}m" if item.age_minutes is not None else "n/a"
            lines.append(
                f"- {item.status} | run_id={item.run_id or '?'} | age={age_text} | dir={item.reaction_dir}"
            )

    if terminal_items:
        lines.append("")
        lines.append(f"recent terminal (top {max_terminal}):")
        for item in terminal_items[:max_terminal]:
            reason = item.reason or "-"
            lines.append(
                f"- {item.status} | run_id={item.run_id or '?'} | attempts={item.attempts} | reason={reason}"
            )

    return "\n".join(lines)


def _send_telegram(config: Any, text: str) -> None:
    from notifier.telegram_client import send_with_retry

    if not bool(config.monitoring.enabled):
        return
    token = os.environ.get(config.monitoring.telegram.bot_token_env, "").strip()
    chat_id = os.environ.get(config.monitoring.telegram.chat_id_env, "").strip()
    if not token or not chat_id:
        return
    send_with_retry(
        token,
        chat_id,
        text,
        timeout=config.monitoring.telegram.timeout,
        max_retries=config.monitoring.telegram.max_retries,
        base_delay=config.monitoring.telegram.base_delay,
        jitter=config.monitoring.telegram.jitter,
    )


def main() -> int:
    _bootstrap_path()
    from app_config import load_app_config

    args = _parse_args()
    try:
        cfg = load_app_config(args.config)
    except ValueError as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 1

    allowed_root = Path(cfg.runtime.allowed_root).expanduser().resolve()
    if not allowed_root.exists() or not allowed_root.is_dir():
        print(f"allowed_root not found: {allowed_root}", file=sys.stderr)
        return 1

    summaries = _collect_summaries(allowed_root)
    counts = _group_counts(summaries)

    if args.json:
        payload = {
            "allowed_root": str(allowed_root),
            "counts": counts,
            "total": len(summaries),
            "runs": [item.__dict__ for item in summaries],
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        text = _format_summary_text(
            allowed_root,
            summaries,
            max_running=max(1, int(args.max_running)),
            max_terminal=max(1, int(args.max_terminal)),
        )
        print(text)
        if not args.print_only:
            _send_telegram(cfg, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
