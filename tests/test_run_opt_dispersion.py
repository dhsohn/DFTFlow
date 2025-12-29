import pytest

import run_opt_dispersion


def test_parse_dispersion_settings_dftd3_backend(monkeypatch):
    class DummyDFTD3:
        def __init__(self, method=None, damping=None, params_tweaks=None, **kwargs):
            pass

    def fake_loader(prefer_backend=None):
        return DummyDFTD3, "dftd3"

    monkeypatch.setattr(run_opt_dispersion, "load_d3_calculator", fake_loader)

    result = run_opt_dispersion.parse_dispersion_settings(
        "d3bj", xc="b3lyp", prefer_d3_backend="dftd3"
    )

    settings = result["settings"]
    assert result["backend"] == "d3"
    assert settings["damping"] == "d3bj"
    assert settings["method"] == "b3lyp"


def test_parse_dispersion_settings_ase_backend(monkeypatch):
    class DummyDFTD3:
        def __init__(self, xc=None, damping=None, **kwargs):
            pass

    def fake_loader(prefer_backend=None):
        return DummyDFTD3, "ase"

    monkeypatch.setattr(run_opt_dispersion, "load_d3_calculator", fake_loader)

    result = run_opt_dispersion.parse_dispersion_settings(
        "d3bj", xc="b3lyp", prefer_d3_backend="ase"
    )

    settings = result["settings"]
    assert result["backend"] == "d3"
    assert settings["damping"] == "bj"
    assert settings["xc"] == "b3lyp"


def test_parse_dispersion_settings_dftd3_damping_tweaks(monkeypatch):
    class DummyDFTD3:
        def __init__(self, method=None, damping=None, params_tweaks=None, **kwargs):
            pass

    def fake_loader(prefer_backend=None):
        return DummyDFTD3, "dftd3"

    monkeypatch.setattr(run_opt_dispersion, "load_d3_calculator", fake_loader)

    d3_params = {
        "damping": {"s6": 1.0, "s8": 1.2, "a1": 0.3, "a2": 4.5},
    }

    result = run_opt_dispersion.parse_dispersion_settings(
        "d3bj", xc="b3lyp", d3_params=d3_params, prefer_d3_backend="dftd3"
    )

    settings = result["settings"]
    assert settings["params_tweaks"] == {"s6": 1.0, "s8": 1.2, "a1": 0.3, "a2": 4.5}


def test_parse_dispersion_settings_ase_damping_tweaks(monkeypatch):
    class DummyDFTD3:
        def __init__(self, xc=None, damping=None, s6=None, s8=None, a1=None, a2=None):
            pass

    def fake_loader(prefer_backend=None):
        return DummyDFTD3, "ase"

    monkeypatch.setattr(run_opt_dispersion, "load_d3_calculator", fake_loader)

    d3_params = {
        "damping": {"s6": 1.0, "s8": 1.2, "a1": 0.3, "a2": 4.5},
    }

    result = run_opt_dispersion.parse_dispersion_settings(
        "d3bj", xc="b3lyp", d3_params=d3_params, prefer_d3_backend="ase"
    )

    settings = result["settings"]
    assert settings["s6"] == 1.0
    assert settings["s8"] == 1.2
    assert settings["a1"] == 0.3
    assert settings["a2"] == 4.5
    assert "params_tweaks" not in settings
