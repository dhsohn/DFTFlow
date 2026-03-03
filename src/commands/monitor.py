from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_config import MonitoringConfig, load_app_config
from notifier.telegram_client import send_with_retry
from ._helpers import human_bytes

logger = logging.getLogger(__name__)


@dataclass
class DirUsage:
    path: str
    size_bytes: int


@dataclass
class FilesystemInfo:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


@dataclass
class DiskReport:
    allowed_root: str
    allowed_root_bytes: int
    organized_root: str
    organized_root_bytes: int
    combined_bytes: int
    threshold_gb: float
    threshold_exceeded: bool
    top_dirs: list[DirUsage] = field(default_factory=list)
    filesystem: FilesystemInfo | None = None
    timestamp: str = ""


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _top_subdirs(root: Path, limit: int) -> list[DirUsage]:
    subdirs: list[Path] = []
    try:
        for entry in os.scandir(root):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(Path(entry.path))
            except OSError:
                continue
    except OSError:
        return []

    if not subdirs:
        return []

    usages: list[DirUsage] = []
    with ThreadPoolExecutor(max_workers=min(8, len(subdirs))) as executor:
        futures = {executor.submit(_dir_size, path): path for path in subdirs}
        for future in as_completed(futures):
            path = futures[future]
            try:
                size = future.result()
            except Exception:
                continue
            usages.append(DirUsage(path=str(path), size_bytes=size))

    usages.sort(key=lambda item: item.size_bytes, reverse=True)
    return usages[:limit]


def _get_filesystem_info(path: Path) -> FilesystemInfo | None:
    try:
        stat = os.statvfs(str(path))
    except OSError:
        return None

    total = stat.f_frsize * stat.f_blocks
    free = stat.f_frsize * stat.f_bavail
    used = total - free
    usage_percent = (used / total * 100.0) if total > 0 else 0.0
    return FilesystemInfo(
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        usage_percent=round(usage_percent, 1),
    )


def scan_disk_usage(
    allowed_root: str,
    organized_root: str,
    *,
    threshold_gb: float,
    top_n: int,
) -> DiskReport:
    allowed = Path(allowed_root).expanduser().resolve()
    organized = Path(organized_root).expanduser().resolve()

    allowed_size = 0
    organized_size = 0
    targets: list[tuple[str, Path]] = []
    if allowed.is_dir():
        targets.append(("allowed", allowed))
    if organized.is_dir():
        targets.append(("organized", organized))

    if targets:
        with ThreadPoolExecutor(max_workers=min(2, len(targets))) as executor:
            futures = {executor.submit(_dir_size, path): key for key, path in targets}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    size = future.result()
                except Exception:
                    size = 0
                if key == "allowed":
                    allowed_size = size
                else:
                    organized_size = size

    combined = allowed_size + organized_size
    combined_gb = combined / (1024 ** 3)
    exceeded = combined_gb >= threshold_gb

    top_dirs = _top_subdirs(organized, top_n) if organized.is_dir() else []
    fs_target = organized if organized.is_dir() else allowed
    fs_info = _get_filesystem_info(fs_target) if fs_target.is_dir() else None

    return DiskReport(
        allowed_root=str(allowed),
        allowed_root_bytes=allowed_size,
        organized_root=str(organized),
        organized_root_bytes=organized_size,
        combined_bytes=combined,
        threshold_gb=threshold_gb,
        threshold_exceeded=exceeded,
        top_dirs=top_dirs,
        filesystem=fs_info,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _report_to_dict(report: DiskReport) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "allowed_root": report.allowed_root,
        "allowed_root_bytes": report.allowed_root_bytes,
        "allowed_root_human": human_bytes(report.allowed_root_bytes),
        "organized_root": report.organized_root,
        "organized_root_bytes": report.organized_root_bytes,
        "organized_root_human": human_bytes(report.organized_root_bytes),
        "combined_bytes": report.combined_bytes,
        "combined_human": human_bytes(report.combined_bytes),
        "threshold_gb": report.threshold_gb,
        "threshold_exceeded": report.threshold_exceeded,
        "top_dirs": [
            {
                "path": usage.path,
                "size_bytes": usage.size_bytes,
                "size_human": human_bytes(usage.size_bytes),
            }
            for usage in report.top_dirs
        ],
        "timestamp": report.timestamp,
    }
    if report.filesystem is not None:
        payload["filesystem"] = {
            "total_bytes": report.filesystem.total_bytes,
            "used_bytes": report.filesystem.used_bytes,
            "free_bytes": report.filesystem.free_bytes,
            "usage_percent": report.filesystem.usage_percent,
        }
    return payload


def _emit_monitor(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    keys = [
        "allowed_root",
        "allowed_root_human",
        "organized_root",
        "organized_root_human",
        "combined_human",
        "threshold_gb",
        "threshold_exceeded",
        "timestamp",
    ]
    for key in keys:
        if key in payload:
            print(f"{key}: {payload[key]}")
    for usage in payload.get("top_dirs", []):
        print(f"  {usage['path']}: {usage['size_human']}")
    fs = payload.get("filesystem")
    if isinstance(fs, dict):
        print(
            "filesystem: total={total}, used={used}, free={free}, usage={usage}%".format(
                total=human_bytes(int(fs.get("total_bytes", 0))),
                used=human_bytes(int(fs.get("used_bytes", 0))),
                free=human_bytes(int(fs.get("free_bytes", 0))),
                usage=fs.get("usage_percent", 0),
            )
        )


def _send_monitor_message(config: MonitoringConfig, message: str) -> None:
    if not config.enabled:
        return
    token = os.environ.get(config.telegram.bot_token_env, "").strip()
    chat_id = os.environ.get(config.telegram.chat_id_env, "").strip()
    if not token or not chat_id:
        return
    send_with_retry(
        token,
        chat_id,
        message,
        timeout=config.telegram.timeout,
        max_retries=config.telegram.max_retries,
        base_delay=config.telegram.base_delay,
        jitter=config.telegram.jitter,
    )


def _threshold_message(report: DiskReport) -> str:
    combined_gb = report.combined_bytes / (1024 ** 3)
    return (
        "[pyscf_auto] disk_threshold_exceeded | "
        f"combined_gb={combined_gb:.2f} | threshold_gb={report.threshold_gb:.2f} | "
        f"allowed_root={report.allowed_root} | organized_root={report.organized_root}"
    )


def _recovered_message(report: DiskReport) -> str:
    combined_gb = report.combined_bytes / (1024 ** 3)
    return (
        "[pyscf_auto] disk_threshold_recovered | "
        f"combined_gb={combined_gb:.2f} | threshold_gb={report.threshold_gb:.2f} | "
        f"allowed_root={report.allowed_root} | organized_root={report.organized_root}"
    )


def cmd_monitor(args: Any) -> int:
    cfg = load_app_config(getattr(args, "config", None))
    as_json = bool(getattr(args, "json", False))
    watch = bool(getattr(args, "watch", False))

    threshold_gb = getattr(args, "threshold_gb", None)
    if threshold_gb is None:
        threshold_gb = cfg.disk_monitor.threshold_gb

    interval_sec = getattr(args, "interval_sec", None)
    if interval_sec is None:
        interval_sec = cfg.disk_monitor.interval_sec

    top_n = getattr(args, "top_n", None)
    if top_n is None:
        top_n = cfg.disk_monitor.top_n

    threshold_gb = float(threshold_gb)
    interval_sec = int(interval_sec)
    top_n = int(top_n)

    if threshold_gb <= 0:
        logger.error("threshold_gb must be > 0, got %s", threshold_gb)
        return 1
    if interval_sec < 10:
        logger.error("interval_sec must be >= 10, got %s", interval_sec)
        return 1
    if not (1 <= top_n <= 100):
        logger.error("top_n must be in 1..100, got %s", top_n)
        return 1

    if not watch:
        report = scan_disk_usage(
            cfg.runtime.allowed_root,
            cfg.runtime.organized_root,
            threshold_gb=threshold_gb,
            top_n=top_n,
        )
        _emit_monitor(_report_to_dict(report), as_json=as_json)
        return 1 if report.threshold_exceeded else 0

    previous_exceeded = False
    try:
        while True:
            report = scan_disk_usage(
                cfg.runtime.allowed_root,
                cfg.runtime.organized_root,
                threshold_gb=threshold_gb,
                top_n=top_n,
            )
            _emit_monitor(_report_to_dict(report), as_json=as_json)

            if report.threshold_exceeded and not previous_exceeded:
                _send_monitor_message(cfg.monitoring, _threshold_message(report))
            elif not report.threshold_exceeded and previous_exceeded:
                _send_monitor_message(cfg.monitoring, _recovered_message(report))

            previous_exceeded = report.threshold_exceeded
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        logger.info("Monitor watch stopped by user.")
        return 0

