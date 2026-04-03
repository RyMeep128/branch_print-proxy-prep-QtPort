from pathlib import Path

import config


def test_load_config_returns_defaults_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "cwd", str(tmp_path))

    cfg = config.load_config()

    assert cfg.VibranceBump is False
    assert cfg.MaxDPI == 1200
    assert cfg.DefaultPageSize == "Letter"
    assert cfg.EnableUncrop is True
    assert cfg.DisplayColumns == 5
    assert cfg.HighResBackendURL == "https://mpcfill.com/"


def test_save_config_and_load_config_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "cwd", str(tmp_path))

    cfg = config.GlobalConfig()
    cfg.VibranceBump = True
    cfg.MaxDPI = 600
    cfg.DefaultPageSize = "A4"
    cfg.EnableUncrop = False
    cfg.DisplayColumns = 7
    cfg.HighResBackendURL = "https://example.com/"

    config.save_config(cfg)
    loaded = config.load_config()

    assert (tmp_path / "config.ini").exists()
    assert loaded.VibranceBump is True
    assert loaded.MaxDPI == 600
    assert loaded.DefaultPageSize == "A4"
    assert loaded.EnableUncrop is False
    assert loaded.DisplayColumns == 7
    assert loaded.HighResBackendURL == "https://example.com/"
