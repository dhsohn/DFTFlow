from __future__ import annotations

from pathlib import Path

from app_config import load_app_config
from cli_new import main


def test_init_creates_config_roots_and_sample(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    allowed_root = tmp_path / "runs"
    organized_root = tmp_path / "outputs"

    exit_code = main(
        [
            "--config",
            str(config_path),
            "init",
            "--allowed-root",
            str(allowed_root),
            "--organized-root",
            str(organized_root),
            "--max-retries",
            "7",
            "--reaction-name",
            "demo_rxn",
            "--sample",
            "water_sp",
        ]
    )
    assert exit_code == 0

    assert config_path.exists()
    cfg = load_app_config(str(config_path))
    assert Path(cfg.runtime.allowed_root) == allowed_root
    assert Path(cfg.runtime.organized_root) == organized_root
    assert cfg.runtime.default_max_retries == 7

    sample_inp = allowed_root / "demo_rxn" / "water_sp.inp"
    assert sample_inp.exists()
    assert "! SP " in sample_inp.read_text(encoding="utf-8")


def test_init_preserves_existing_config_without_force(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "runtime:",
                f"  allowed_root: {tmp_path / 'custom_runs'}",
                f"  organized_root: {tmp_path / 'custom_outputs'}",
                "  default_max_retries: 11",
            ]
        ),
        encoding="utf-8",
    )
    before = config_path.read_text(encoding="utf-8")

    exit_code = main(
        [
            "--config",
            str(config_path),
            "init",
            "--sample",
            "none",
        ]
    )
    assert exit_code == 0
    after = config_path.read_text(encoding="utf-8")
    assert after == before


def test_init_refuses_runtime_override_without_force_when_config_exists(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "runtime:",
                f"  allowed_root: {tmp_path / 'runs'}",
                f"  organized_root: {tmp_path / 'outputs'}",
                "  default_max_retries: 5",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--config",
            str(config_path),
            "init",
            "--allowed-root",
            str(tmp_path / "new_runs"),
        ]
    )
    assert exit_code == 1
