from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app_config import RuntimeConfig, load_app_config
from ._helpers import is_subpath

logger = logging.getLogger(__name__)


_SAMPLE_INPUTS: dict[str, str] = {
    "water_sp": "\n".join(
        [
            "# pyscf_auto sample input",
            "# TAG: Demo_Water_SP",
            "! SP B3LYP def2-SVP D3BJ SMD(water)",
            "",
            "%runtime",
            "  threads 4",
            "  memory_gb 8",
            "end",
            "",
            "* xyz 0 1",
            "O   -0.1659811139  2.0308399200 -0.0000031757",
            "H   -2.5444712639  1.0182403326  0.6584512591",
            "H   -1.0147968531  2.4412472248 -2.0058431625",
            "*",
            "",
        ]
    ),
    "water_opt": "\n".join(
        [
            "# pyscf_auto sample input",
            "# TAG: Demo_Water_OPT",
            "! Opt B3LYP def2-SVP D3BJ PCM(water)",
            "",
            "%scf",
            "  max_cycle 300",
            "  conv_tol 1e-10",
            "end",
            "",
            "%optimizer",
            "  steps 300",
            "  fmax 0.05",
            "end",
            "",
            "%runtime",
            "  threads 4",
            "  memory_gb 8",
            "end",
            "",
            "* xyz 0 1",
            "O   -0.1659811139  2.0308399200 -0.0000031757",
            "H   -2.5444712639  1.0182403326  0.6584512591",
            "H   -1.0147968531  2.4412472248 -2.0058431625",
            "*",
            "",
        ]
    ),
}


def _render_runtime_config(runtime: RuntimeConfig) -> str:
    return "\n".join(
        [
            "# pyscf_auto user configuration",
            "runtime:",
            f"  allowed_root: {json.dumps(runtime.allowed_root)}",
            f"  organized_root: {json.dumps(runtime.organized_root)}",
            f"  default_max_retries: {int(runtime.default_max_retries)}",
            "",
            "monitoring:",
            "  enabled: false",
            "",
        ]
    )


def _emit_init(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    keys = [
        "action",
        "config_path",
        "config_written",
        "config_preserved",
        "allowed_root",
        "organized_root",
        "sample",
        "sample_reaction_dir",
        "sample_inp",
    ]
    for key in keys:
        if key in payload:
            print(f"{key}: {payload[key]}")
    for step in payload.get("next_steps", []):
        print(f"next_step: {step}")


def cmd_init(args: Any) -> int:
    config_path = Path(getattr(args, "config", "~/.pyscf_auto/config.yaml")).expanduser().resolve()
    config_exists = config_path.exists()

    try:
        existing_cfg = load_app_config(str(config_path))
    except ValueError as exc:
        logger.error("Invalid config file: %s", exc)
        return 1

    allowed_root = Path(
        getattr(args, "allowed_root", None) or existing_cfg.runtime.allowed_root
    ).expanduser().resolve()
    organized_root = Path(
        getattr(args, "organized_root", None) or existing_cfg.runtime.organized_root
    ).expanduser().resolve()
    max_retries = int(
        getattr(args, "max_retries", None)
        if getattr(args, "max_retries", None) is not None
        else existing_cfg.runtime.default_max_retries
    )

    if max_retries < 0:
        logger.error("--max-retries must be >= 0 (got %s)", max_retries)
        return 1
    if allowed_root == organized_root or is_subpath(allowed_root, organized_root) or is_subpath(organized_root, allowed_root):
        logger.error(
            "allowed_root and organized_root must not contain each other: allowed_root=%s organized_root=%s",
            allowed_root,
            organized_root,
        )
        return 1

    has_overrides = any(
        value is not None
        for value in (
            getattr(args, "allowed_root", None),
            getattr(args, "organized_root", None),
            getattr(args, "max_retries", None),
        )
    )
    force = bool(getattr(args, "force", False))

    if config_exists and has_overrides and not force:
        logger.error("Config file already exists. Use --force to overwrite with new runtime values.")
        return 1

    runtime = RuntimeConfig(
        allowed_root=str(allowed_root),
        organized_root=str(organized_root),
        default_max_retries=max_retries,
    )

    config_written = False
    config_preserved = False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_exists or force:
        config_path.write_text(_render_runtime_config(runtime), encoding="utf-8")
        config_written = True
    else:
        config_preserved = True

    allowed_root.mkdir(parents=True, exist_ok=True)
    organized_root.mkdir(parents=True, exist_ok=True)

    sample_name = getattr(args, "sample", "water_sp")
    reaction_name = str(getattr(args, "reaction_name", "demo_water")).strip() or "demo_water"
    sample_reaction_dir = None
    sample_inp = None
    if sample_name != "none":
        sample_reaction_dir = allowed_root / reaction_name
        sample_inp = sample_reaction_dir / f"{sample_name}.inp"
        sample_reaction_dir.mkdir(parents=True, exist_ok=True)
        if not sample_inp.exists() or force:
            sample_inp.write_text(_SAMPLE_INPUTS[sample_name], encoding="utf-8")

    next_steps: list[str] = []
    if sample_reaction_dir is not None:
        next_steps = [
            f"pyscf_auto run-inp --reaction-dir {sample_reaction_dir}",
            f"pyscf_auto status --reaction-dir {sample_reaction_dir}",
            f"pyscf_auto organize --root {allowed_root}",
        ]

    payload: dict[str, Any] = {
        "action": "init",
        "config_path": str(config_path),
        "config_written": config_written,
        "config_preserved": config_preserved,
        "allowed_root": str(allowed_root),
        "organized_root": str(organized_root),
        "sample": sample_name,
        "next_steps": next_steps,
    }
    if sample_reaction_dir is not None:
        payload["sample_reaction_dir"] = str(sample_reaction_dir)
    if sample_inp is not None:
        payload["sample_inp"] = str(sample_inp)

    _emit_init(payload, as_json=bool(getattr(args, "json", False)))
    return 0

