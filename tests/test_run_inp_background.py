from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import commands.run_inp as run_inp_cmd


def test_cmd_run_inp_background_spawns_subprocess(tmp_path: Path, monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 43210

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(run_inp_cmd, "_default_log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(run_inp_cmd.subprocess, "Popen", _fake_popen)

    args = SimpleNamespace(
        config=str(tmp_path / "config.yaml"),
        verbose=True,
        reaction_dir=str(tmp_path / "rxn"),
        max_retries=4,
        force=True,
        json=True,
        background=True,
        foreground=False,
    )
    rc = run_inp_cmd.cmd_run_inp(args)
    assert rc == 0

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "--foreground" in cmd
    assert "--max-retries" in cmd
    assert "--force" in cmd
    assert "--json" in cmd

    out = capsys.readouterr().out
    assert "status: started" in out
    assert "pid: 43210" in out
    assert "log:" in out


def test_cmd_run_inp_foreground_overrides_background_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYSCF_AUTO_RUN_INP_BACKGROUND", "1")

    captured: dict[str, object] = {}

    def _fake_load_app_config(_config):
        return "cfg"

    def _fake_cmd_run_inp(*, reaction_dir, max_retries, force, json_output, app_config):
        captured["reaction_dir"] = reaction_dir
        captured["max_retries"] = max_retries
        captured["force"] = force
        captured["json_output"] = json_output
        captured["app_config"] = app_config
        return 0

    monkeypatch.setattr(run_inp_cmd, "load_app_config", _fake_load_app_config)
    monkeypatch.setattr(run_inp_cmd, "_cmd_run_inp", _fake_cmd_run_inp)

    args = SimpleNamespace(
        config=str(tmp_path / "config.yaml"),
        reaction_dir=str(tmp_path / "rxn"),
        max_retries=None,
        force=False,
        json=False,
        background=False,
        foreground=True,
    )
    rc = run_inp_cmd.cmd_run_inp(args)
    assert rc == 0
    assert captured["app_config"] == "cfg"
    assert captured["reaction_dir"] == str(tmp_path / "rxn")
