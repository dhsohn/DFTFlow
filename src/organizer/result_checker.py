"""Quality checks for completed reaction directories."""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inp.parser import parse_inp_file
from runner.state_machine import load_state

logger = logging.getLogger(__name__)

_XYZ_ATOM_RE = re.compile(
    r"^\s*([A-Z][a-z]?)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s*$"
)
_SHORT_CONTACT_THRESHOLD = 0.5
_FRAGMENTATION_NN_THRESHOLD = 3.5


@dataclass
class CheckItem:
    check_name: str
    severity: str  # ok | warning | error
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    reaction_dir: str
    run_id: str
    job_type: str
    overall: str  # pass | warn | fail
    checks: list[CheckItem] = field(default_factory=list)


@dataclass
class CheckSkipReason:
    reaction_dir: str
    reason: str


def check_single(
    reaction_dir: Path,
) -> tuple[CheckResult | None, CheckSkipReason | None]:
    state = load_state(str(reaction_dir))
    if state is None:
        return None, CheckSkipReason(str(reaction_dir), "state_missing_or_invalid")

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None, CheckSkipReason(str(reaction_dir), "state_schema_invalid")

    status = str(state.get("status", "")).strip().lower()
    if status != "completed":
        return None, CheckSkipReason(str(reaction_dir), "not_completed")

    metadata_path = _find_attempt_artifact(
        state,
        reaction_dir,
        file_name="metadata.json",
    )
    frequency_path = _find_attempt_artifact(
        state,
        reaction_dir,
        file_name="frequency_result.json",
    )
    metadata = _load_json_mapping(metadata_path)
    frequency_payload = _load_json_mapping(frequency_path)

    job_type = _infer_job_type(state, reaction_dir, metadata)

    checks: list[CheckItem] = []
    checks.append(_check_final_result_status(state))
    checks.append(_check_metadata_status(metadata, metadata_path))
    checks.append(_check_summary_convergence(metadata))

    if frequency_payload is not None:
        checks.extend(
            _check_frequency_quality(
                frequency_payload=frequency_payload,
                metadata=metadata,
                job_type=job_type,
            )
        )
    else:
        checks.append(
            CheckItem(
                check_name="frequency_payload",
                severity="ok",
                message="frequency_result.json not found; frequency-specific checks skipped",
            )
        )

    xyz_path = _find_best_xyz_path(state, reaction_dir, metadata)
    if xyz_path is None:
        checks.append(
            CheckItem(
                check_name="geometry_file",
                severity="warning",
                message="No XYZ geometry found for geometry sanity checks",
            )
        )
    else:
        atoms = _parse_xyz_atoms(xyz_path)
        if len(atoms) < 2:
            checks.append(
                CheckItem(
                    check_name="geometry_parse",
                    severity="warning",
                    message=f"XYZ has fewer than 2 atoms: {xyz_path}",
                )
            )
        else:
            checks.append(_check_short_contacts(atoms))
            checks.append(_check_fragmentation_hint(atoms))

    result = CheckResult(
        reaction_dir=str(reaction_dir),
        run_id=run_id,
        job_type=job_type,
        overall=_overall_from_checks(checks),
        checks=checks,
    )
    return result, None


def check_root_scan(root: Path) -> tuple[list[CheckResult], list[CheckSkipReason]]:
    results: list[CheckResult] = []
    skips: list[CheckSkipReason] = []
    root_resolved = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current_dir = Path(dirpath)
        dirnames[:] = [name for name in dirnames if not (current_dir / name).is_symlink()]

        if "run_state.json" not in filenames:
            continue

        state_file = current_dir / "run_state.json"
        if state_file.is_symlink():
            skips.append(CheckSkipReason(str(current_dir), "symlink_state_file"))
            continue

        try:
            current_resolved = current_dir.resolve()
        except OSError:
            skips.append(CheckSkipReason(str(current_dir), "resolve_failed"))
            continue

        if not _is_subpath(current_resolved, root_resolved):
            skips.append(CheckSkipReason(str(current_dir), "outside_root"))
            continue

        result, skip = check_single(current_resolved)
        if result is not None:
            results.append(result)
        if skip is not None:
            skips.append(skip)

    return results, skips


def _check_final_result_status(state: dict[str, Any]) -> CheckItem:
    final_result = state.get("final_result")
    if not isinstance(final_result, dict):
        return CheckItem(
            check_name="final_result",
            severity="error",
            message="run_state.final_result is missing or invalid",
        )

    analyzer_status = str(final_result.get("analyzer_status", "")).strip().lower()
    if analyzer_status == "completed":
        return CheckItem(
            check_name="final_result",
            severity="ok",
            message="run_state final_result analyzer_status is completed",
        )
    if analyzer_status:
        return CheckItem(
            check_name="final_result",
            severity="error",
            message=f"run_state final_result analyzer_status is {analyzer_status}",
        )
    return CheckItem(
        check_name="final_result",
        severity="warning",
        message="run_state final_result analyzer_status is missing",
    )


def _check_metadata_status(metadata: dict[str, Any] | None, metadata_path: Path | None) -> CheckItem:
    if metadata is None:
        if metadata_path is None:
            return CheckItem(
                check_name="metadata_presence",
                severity="warning",
                message="metadata.json not found",
            )
        return CheckItem(
            check_name="metadata_presence",
            severity="warning",
            message=f"metadata.json is unreadable: {metadata_path}",
        )

    status_text = str(metadata.get("status", "")).strip().lower()
    if status_text in {"completed", "success"}:
        return CheckItem(
            check_name="metadata_status",
            severity="ok",
            message=f"metadata status is {status_text}",
        )
    if status_text in {"failed", "error", "timeout", "canceled", "cancelled"}:
        reason = _metadata_reason(metadata)
        return CheckItem(
            check_name="metadata_status",
            severity="error",
            message=f"metadata status is {status_text}",
            details={"reason": reason},
        )
    if status_text:
        return CheckItem(
            check_name="metadata_status",
            severity="warning",
            message=f"metadata status is {status_text}",
        )
    return CheckItem(
        check_name="metadata_status",
        severity="warning",
        message="metadata status is missing",
    )


def _check_summary_convergence(metadata: dict[str, Any] | None) -> CheckItem:
    if metadata is None:
        return CheckItem(
            check_name="summary_convergence",
            severity="warning",
            message="convergence check skipped (metadata missing)",
        )

    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        return CheckItem(
            check_name="summary_convergence",
            severity="warning",
            message="metadata.summary is missing",
        )

    converged = summary.get("converged")
    if isinstance(converged, bool):
        if converged:
            return CheckItem(
                check_name="summary_convergence",
                severity="ok",
                message="summary.converged is true",
            )
        return CheckItem(
            check_name="summary_convergence",
            severity="error",
            message="summary.converged is false",
        )

    final_sp_converged = summary.get("final_sp_converged")
    if isinstance(final_sp_converged, bool):
        if final_sp_converged:
            return CheckItem(
                check_name="summary_convergence",
                severity="ok",
                message="summary.final_sp_converged is true",
            )
        return CheckItem(
            check_name="summary_convergence",
            severity="error",
            message="summary.final_sp_converged is false",
        )

    return CheckItem(
        check_name="summary_convergence",
        severity="warning",
        message="No converged flag found in metadata.summary",
    )


def _check_frequency_quality(
    *,
    frequency_payload: dict[str, Any],
    metadata: dict[str, Any] | None,
    job_type: str,
) -> list[CheckItem]:
    checks: list[CheckItem] = []
    results = frequency_payload.get("results")
    results_mapping = results if isinstance(results, dict) else {}

    imaginary_count = results_mapping.get("imaginary_count")
    imaginary_check = results_mapping.get("imaginary_check")
    imaginary_mapping = imaginary_check if isinstance(imaginary_check, dict) else {}
    imaginary_status = str(imaginary_mapping.get("status", "")).strip().lower()

    ts_mode = _is_ts_job(job_type, metadata)
    if ts_mode:
        if imaginary_status == "one_imaginary" or imaginary_count == 1:
            checks.append(
                CheckItem(
                    check_name="imaginary_frequency_count",
                    severity="ok",
                    message="TS imaginary frequency count looks valid",
                    details={"imaginary_count": imaginary_count},
                )
            )
        else:
            checks.append(
                CheckItem(
                    check_name="imaginary_frequency_count",
                    severity="error",
                    message="TS expected one imaginary frequency",
                    details={"imaginary_count": imaginary_count, "status": imaginary_status},
                )
            )
    else:
        if isinstance(imaginary_count, int) and imaginary_count > 0:
            checks.append(
                CheckItem(
                    check_name="imaginary_frequency_count",
                    severity="warning",
                    message=f"Imaginary frequencies detected ({imaginary_count})",
                )
            )
        elif isinstance(imaginary_count, int):
            checks.append(
                CheckItem(
                    check_name="imaginary_frequency_count",
                    severity="ok",
                    message="No imaginary frequencies detected",
                )
            )
        else:
            checks.append(
                CheckItem(
                    check_name="imaginary_frequency_count",
                    severity="warning",
                    message="Imaginary frequency count is unavailable",
                )
            )

    ts_quality = results_mapping.get("ts_quality")
    ts_quality_mapping = ts_quality if isinstance(ts_quality, dict) else {}
    ts_quality_status = str(ts_quality_mapping.get("status", "")).strip().lower()
    if not ts_quality_status:
        checks.append(
            CheckItem(
                check_name="ts_quality",
                severity="ok",
                message="TS quality payload not present",
            )
        )
    elif ts_quality_status in {"pass", "ok"}:
        checks.append(
            CheckItem(
                check_name="ts_quality",
                severity="ok",
                message="TS quality checks passed",
            )
        )
    elif ts_quality_status in {"warn", "warning"}:
        checks.append(
            CheckItem(
                check_name="ts_quality",
                severity="warning",
                message="TS quality checks returned warning",
            )
        )
    else:
        checks.append(
            CheckItem(
                check_name="ts_quality",
                severity="error",
                message=f"TS quality checks failed ({ts_quality_status})",
            )
        )
    return checks


def _check_short_contacts(atoms: list[tuple[str, float, float, float]]) -> CheckItem:
    short: list[dict[str, Any]] = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            distance = _distance(atoms[i], atoms[j])
            if distance < _SHORT_CONTACT_THRESHOLD:
                short.append(
                    {
                        "i": i,
                        "j": j,
                        "symbol_i": atoms[i][0],
                        "symbol_j": atoms[j][0],
                        "distance": round(distance, 4),
                    }
                )

    if short:
        return CheckItem(
            check_name="short_contacts",
            severity="error",
            message=f"{len(short)} atom pair(s) below {_SHORT_CONTACT_THRESHOLD} A",
            details={"pairs": short},
        )
    return CheckItem(
        check_name="short_contacts",
        severity="ok",
        message="No short contacts detected",
    )


def _check_fragmentation_hint(atoms: list[tuple[str, float, float, float]]) -> CheckItem:
    if len(atoms) < 2:
        return CheckItem(
            check_name="fragmentation_hint",
            severity="ok",
            message="Too few atoms for fragmentation check",
        )

    nearest_distances: list[float] = [float("inf")] * len(atoms)
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            distance = _distance(atoms[i], atoms[j])
            if distance < nearest_distances[i]:
                nearest_distances[i] = distance
            if distance < nearest_distances[j]:
                nearest_distances[j] = distance

    max_nn = max(nearest_distances)
    atom_index = nearest_distances.index(max_nn)
    if max_nn > _FRAGMENTATION_NN_THRESHOLD:
        return CheckItem(
            check_name="fragmentation_hint",
            severity="warning",
            message=(
                f"Atom {atom_index} ({atoms[atom_index][0]}) nearest-neighbor distance "
                f"is {max_nn:.2f} A (> {_FRAGMENTATION_NN_THRESHOLD:.1f} A)"
            ),
            details={"atom_index": atom_index, "nn_distance": round(max_nn, 4)},
        )
    return CheckItem(
        check_name="fragmentation_hint",
        severity="ok",
        message="No fragmentation hint",
    )


def _distance(
    atom_a: tuple[str, float, float, float],
    atom_b: tuple[str, float, float, float],
) -> float:
    dx = atom_a[1] - atom_b[1]
    dy = atom_a[2] - atom_b[2]
    dz = atom_a[3] - atom_b[3]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _parse_xyz_atoms(xyz_path: Path) -> list[tuple[str, float, float, float]]:
    atoms: list[tuple[str, float, float, float]] = []
    try:
        lines = xyz_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return atoms

    for line in lines:
        match = _XYZ_ATOM_RE.match(line)
        if not match:
            continue
        atoms.append(
            (
                match.group(1),
                float(match.group(2)),
                float(match.group(3)),
                float(match.group(4)),
            )
        )
    return atoms


def _overall_from_checks(checks: list[CheckItem]) -> str:
    severities = {item.severity for item in checks}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "warn"
    return "pass"


def _find_attempt_artifact(
    state: dict[str, Any],
    reaction_dir: Path,
    *,
    file_name: str,
) -> Path | None:
    for attempt_dir in _attempt_dirs_from_state(state, reaction_dir):
        candidate = attempt_dir / file_name
        if candidate.exists() and candidate.is_file():
            return candidate
    fallback = reaction_dir / file_name
    if fallback.exists() and fallback.is_file():
        return fallback
    return None


def _attempt_dirs_from_state(state: dict[str, Any], reaction_dir: Path) -> list[Path]:
    attempts = state.get("attempts")
    if not isinstance(attempts, list):
        attempts = []

    resolved: list[Path] = []
    seen: set[Path] = set()
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        text = attempt.get("attempt_dir")
        if not isinstance(text, str) or not text.strip():
            continue
        for candidate in _artifact_candidates(text, reaction_dir):
            try:
                resolved_candidate = candidate.resolve()
            except OSError:
                continue
            if resolved_candidate in seen:
                continue
            if not resolved_candidate.exists() or not resolved_candidate.is_dir():
                continue
            seen.add(resolved_candidate)
            resolved.append(resolved_candidate)

    if resolved:
        return resolved

    fallback_dirs = sorted(
        [d for d in reaction_dir.glob("attempt_*") if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    return fallback_dirs


def _infer_job_type(
    state: dict[str, Any],
    reaction_dir: Path,
    metadata: dict[str, Any] | None,
) -> str:
    selected_inp = state.get("selected_inp")
    if isinstance(selected_inp, str) and selected_inp.strip():
        for candidate in _artifact_candidates(selected_inp, reaction_dir):
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                return str(parse_inp_file(str(candidate)).job_type)
            except Exception:
                break

    if isinstance(metadata, dict):
        calculation_mode = metadata.get("calculation_mode")
        if isinstance(calculation_mode, str) and calculation_mode.strip():
            return calculation_mode.strip()
        optimizer = metadata.get("optimizer")
        if isinstance(optimizer, dict):
            optimizer_mode = optimizer.get("mode")
            if isinstance(optimizer_mode, str) and optimizer_mode.strip():
                return optimizer_mode.strip()

    return "unknown"


def _is_ts_job(job_type: str, metadata: dict[str, Any] | None) -> bool:
    normalized = job_type.strip().lower()
    if normalized in {"transition_state", "ts"}:
        return True
    if isinstance(metadata, dict):
        optimizer = metadata.get("optimizer")
        if isinstance(optimizer, dict):
            mode = str(optimizer.get("mode", "")).strip().lower()
            return mode in {"transition_state", "ts"}
    return False


def _find_best_xyz_path(
    state: dict[str, Any],
    reaction_dir: Path,
    metadata: dict[str, Any] | None,
) -> Path | None:
    candidates: list[Path] = []
    if isinstance(metadata, dict):
        for key in ("optimized_xyz_path", "xyz_file"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                candidates.extend(_artifact_candidates(value, reaction_dir))

    for attempt_dir in _attempt_dirs_from_state(state, reaction_dir):
        candidates.extend(
            sorted(
                [
                    p
                    for p in attempt_dir.glob("*.xyz")
                    if p.is_file() and not p.name.endswith("_trj.xyz")
                ],
                key=lambda p: p.name,
            )
        )

    candidates.extend(
        sorted(
            [
                p
                for p in reaction_dir.glob("*.xyz")
                if p.is_file() and not p.name.endswith("_trj.xyz")
            ],
            key=lambda p: p.name,
        )
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _artifact_candidates(path_text: str, reaction_dir: Path) -> list[Path]:
    raw = path_text.strip()
    if not raw:
        return []
    candidate = Path(raw)
    if candidate.is_absolute():
        return [candidate, reaction_dir / candidate.name]
    return [reaction_dir / candidate, reaction_dir / candidate.name]


def _load_json_mapping(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _metadata_reason(metadata: dict[str, Any]) -> str:
    summary = metadata.get("summary")
    if isinstance(summary, dict):
        for key in ("reason", "status_reason"):
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    error = metadata.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return ""


def _is_subpath(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

