#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _summarize_progress(progress):
    cases = progress.get("cases", {})
    counts = {"completed": 0, "failed": 0, "skipped": 0, "running": 0, "unknown": 0}
    failed = []
    for run_dir, entry in cases.items():
        status = entry.get("status") or "unknown"
        if status not in counts:
            counts["unknown"] += 1
        else:
            counts[status] += 1
        if status == "failed":
            failed.append((run_dir, entry.get("error", "")))
    return counts, failed


def _summarize_metadata(base_dir):
    failed = []
    total = 0
    for run_dir in sorted(base_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        total += 1
        metadata = _load_json(metadata_path)
        if not metadata:
            continue
        if metadata.get("status") == "failed":
            failed.append((str(run_dir), metadata.get("error", "")))
    return total, failed


def main():
    if len(sys.argv) < 2:
        print("Usage: smoke_report.py <run_dir>", file=sys.stderr)
        raise SystemExit(2)
    base_dir = Path(sys.argv[1]).expanduser().resolve()
    if not base_dir.exists():
        print(f"Run directory not found: {base_dir}", file=sys.stderr)
        raise SystemExit(2)
    progress_path = base_dir / "smoke_progress.json"
    if progress_path.exists():
        progress = _load_json(progress_path) or {"cases": {}}
        counts, failed = _summarize_progress(progress)
        total = sum(counts.values())
        print(f"Total: {total}")
        for key in ("completed", "failed", "skipped", "running", "unknown"):
            print(f"{key}: {counts.get(key, 0)}")
        if failed:
            print("\nFailed cases:")
            for run_dir, error in failed:
                suffix = f" ({error})" if error else ""
                print(f"- {run_dir}{suffix}")
        return
    total, failed = _summarize_metadata(base_dir)
    print(f"Total (metadata only): {total}")
    print(f"failed: {len(failed)}")
    if failed:
        print("\nFailed cases:")
        for run_dir, error in failed:
            suffix = f" ({error})" if error else ""
            print(f"- {run_dir}{suffix}")


if __name__ == "__main__":
    main()
