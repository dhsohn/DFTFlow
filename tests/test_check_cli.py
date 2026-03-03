from __future__ import annotations

import json
from pathlib import Path

from cli_new import main


def _write_config(path: Path, allowed_root: Path, organized_root: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "runtime:",
                f"  allowed_root: {allowed_root}",
                f"  organized_root: {organized_root}",
            ]
        ),
        encoding="utf-8",
    )


def _write_completed_dir(parent: Path, name: str = "rxn1", *, metadata_status: str = "completed") -> Path:
    reaction_dir = parent / name
    reaction_dir.mkdir(parents=True, exist_ok=True)

    selected_inp = reaction_dir / "mol.inp"
    selected_inp.write_text(
        "! SP B3LYP def2-SVP\n* xyz 0 1\nH 0.0 0.0 0.0\n*\n",
        encoding="utf-8",
    )
    attempt_dir = reaction_dir / "attempt_001"
    attempt_dir.mkdir()
    (attempt_dir / "final.xyz").write_text(
        "2\ncomment\nH 0.0 0.0 0.0\nH 0.0 0.0 0.8\n",
        encoding="utf-8",
    )
    (attempt_dir / "metadata.json").write_text(
        json.dumps(
            {
                "status": metadata_status,
                "summary": {"converged": metadata_status == "completed"},
                "optimizer": {"mode": "minimum"},
                "optimized_xyz_path": str(attempt_dir / "final.xyz"),
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    state = {
        "run_id": f"run_{name}",
        "status": "completed",
        "selected_inp": str(selected_inp),
        "attempts": [{"index": 1, "attempt_dir": str(attempt_dir)}],
        "final_result": {
            "status": "completed",
            "analyzer_status": "completed",
            "reason": "normal_termination",
        },
    }
    (reaction_dir / "run_state.json").write_text(
        json.dumps(state, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return reaction_dir


def test_check_mutually_exclusive_options(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)
    reaction_dir = _write_completed_dir(organized_root)

    rc = main(
        [
            "--config",
            str(config_path),
            "check",
            "--reaction-dir",
            str(reaction_dir),
            "--root",
            str(organized_root),
        ]
    )
    assert rc == 1


def test_check_single_reaction_dir_pass(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)
    reaction_dir = _write_completed_dir(organized_root)

    rc = main(
        [
            "--config",
            str(config_path),
            "check",
            "--reaction-dir",
            str(reaction_dir),
            "--json",
        ]
    )
    assert rc == 0


def test_check_root_scan(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)
    _write_completed_dir(organized_root, name="rxn1")
    _write_completed_dir(organized_root, name="rxn2")

    rc = main(
        [
            "--config",
            str(config_path),
            "check",
            "--root",
            str(organized_root),
            "--json",
        ]
    )
    assert rc == 0


def test_check_default_root_scan(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)
    _write_completed_dir(organized_root)

    rc = main(["--config", str(config_path), "check", "--json"])
    assert rc == 0


def test_check_default_root_missing_returns_error(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_missing = tmp_path / "organized_missing"
    allowed_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_missing)

    rc = main(["--config", str(config_path), "check"])
    assert rc == 1


def test_check_failing_metadata_returns_nonzero(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)
    reaction_dir = _write_completed_dir(organized_root, metadata_status="failed")

    rc = main(
        [
            "--config",
            str(config_path),
            "check",
            "--reaction-dir",
            str(reaction_dir),
            "--json",
        ]
    )
    assert rc == 1
