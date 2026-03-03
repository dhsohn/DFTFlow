from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app_config import load_app_config
from runner.orchestrator import cmd_run_inp as _cmd_run_inp
from runner.orchestrator import cmd_status as _cmd_status


_BACKGROUND_ENV = "PYSCF_AUTO_RUN_INP_BACKGROUND"
_FALSEY = {"0", "false", "no", "off"}
_LOG_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _wants_background(args: Any) -> bool:
    if bool(getattr(args, "foreground", False)):
        return False
    if bool(getattr(args, "background", False)):
        return True
    raw = str(os.environ.get(_BACKGROUND_ENV, "")).strip().lower()
    if not raw:
        return False
    return raw not in _FALSEY


def _default_log_dir() -> Path:
    return Path.home() / ".pyscf_auto" / "logs"


def _safe_label(path_text: str) -> str:
    raw = Path(path_text).name.strip() or "runinp"
    label = _LOG_LABEL_RE.sub("_", raw)
    return label.strip("._-") or "runinp"


def _launch_background_run(args: Any) -> int:
    log_dir = _default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = _safe_label(str(getattr(args, "reaction_dir", "")))
    log_path = log_dir / f"run_inp_{timestamp}_{label}.log"

    child_cmd = [sys.executable, "-m", "cli_new"]
    config_path = getattr(args, "config", None)
    if config_path:
        child_cmd.extend(["--config", str(config_path)])
    if bool(getattr(args, "verbose", False)):
        child_cmd.append("--verbose")
    child_cmd.extend(
        [
            "run-inp",
            "--reaction-dir",
            str(args.reaction_dir),
            "--foreground",
        ]
    )
    max_retries = getattr(args, "max_retries", None)
    if max_retries is not None:
        child_cmd.extend(["--max-retries", str(int(max_retries))])
    if bool(getattr(args, "force", False)):
        child_cmd.append("--force")
    if bool(getattr(args, "json", False)):
        child_cmd.append("--json")

    with log_path.open("a", encoding="utf-8") as handle:
        proc = subprocess.Popen(  # noqa: S603
            child_cmd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    print("status: started")
    print(f"pid: {proc.pid}")
    print(f"log: {log_path}")
    return 0


def cmd_run_inp(args: Any) -> int:
    if _wants_background(args):
        return _launch_background_run(args)

    cfg = load_app_config(getattr(args, "config", None))
    return int(
        _cmd_run_inp(
            reaction_dir=args.reaction_dir,
            max_retries=args.max_retries,
            force=args.force,
            json_output=args.json,
            app_config=cfg,
        )
    )


def cmd_status(args: Any) -> int:
    cfg = load_app_config(getattr(args, "config", None))
    return int(
        _cmd_status(
            reaction_dir=args.reaction_dir,
            json_output=args.json,
            app_config=cfg,
        )
    )
