from __future__ import annotations

from pathlib import Path

from cli_new import main


def _write_config(
    path: Path,
    allowed_root: Path,
    organized_root: Path,
    *,
    monitoring_enabled: bool = False,
    disk_threshold_gb: float | None = None,
    disk_interval_sec: int | None = None,
    disk_top_n: int | None = None,
) -> None:
    lines = [
        "runtime:",
        f"  allowed_root: {allowed_root}",
        f"  organized_root: {organized_root}",
        "monitoring:",
        f"  enabled: {'true' if monitoring_enabled else 'false'}",
    ]
    lines.extend(
        [
            "disk_monitor:",
            f"  threshold_gb: {disk_threshold_gb if disk_threshold_gb is not None else 50.0}",
            f"  interval_sec: {disk_interval_sec if disk_interval_sec is not None else 300}",
            f"  top_n: {disk_top_n if disk_top_n is not None else 10}",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_monitor_oneshot_below_threshold(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)

    rc = main(
        [
            "--config",
            str(config_path),
            "monitor",
            "--threshold-gb",
            "999",
            "--json",
        ]
    )
    assert rc == 0


def test_monitor_oneshot_above_threshold(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    (allowed_root / "data.bin").write_bytes(b"x" * 1024)
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)

    rc = main(
        [
            "--config",
            str(config_path),
            "monitor",
            "--threshold-gb",
            "0.0000001",
            "--json",
        ]
    )
    assert rc == 1


def test_monitor_invalid_threshold(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)

    rc = main(["--config", str(config_path), "monitor", "--threshold-gb", "0"])
    assert rc == 1


def test_monitor_invalid_interval(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)

    rc = main(["--config", str(config_path), "monitor", "--interval-sec", "5"])
    assert rc == 1


def test_monitor_watch_exits_on_keyboard_interrupt(tmp_path: Path, monkeypatch) -> None:
    import commands.monitor as monitor_cmd

    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root)

    monkeypatch.setattr(
        monitor_cmd.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    rc = main(["--config", str(config_path), "monitor", "--watch", "--json"])
    assert rc == 0


def test_monitor_watch_threshold_transition_sends_once(tmp_path: Path, monkeypatch) -> None:
    import commands.monitor as monitor_cmd

    allowed_root = tmp_path / "allowed"
    organized_root = tmp_path / "organized"
    allowed_root.mkdir()
    organized_root.mkdir()
    (allowed_root / "data.bin").write_bytes(b"x" * 4096)
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, allowed_root, organized_root, monitoring_enabled=True)

    monkeypatch.setenv("PYSCF_AUTO_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("PYSCF_AUTO_TELEGRAM_CHAT_ID", "chat")

    call_count = {"n": 0}

    def _fake_send(*_args, **_kwargs):
        call_count["n"] += 1

    sleep_calls = {"n": 0}

    def _fake_sleep(_seconds: int) -> None:
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr(monitor_cmd, "send_with_retry", _fake_send)
    monkeypatch.setattr(monitor_cmd.time, "sleep", _fake_sleep)

    rc = main(
        [
            "--config",
            str(config_path),
            "monitor",
            "--watch",
            "--threshold-gb",
            "0.0000001",
            "--json",
        ]
    )
    assert rc == 0
    assert call_count["n"] == 1
