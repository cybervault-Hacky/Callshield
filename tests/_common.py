"""Shared test helpers: redirect CALLSHIELD state into a temp directory."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any, Tuple

import callshield as _pkg
from callshield import config as config_mod
from callshield import database as db_mod
from callshield import cli as _cli
from callshield.config import Config, save_config


class IsolatedEnv:
    """Context-friendly fixture that redirects all runtime state to a tempdir."""

    def __init__(self) -> None:
        self._td = tempfile.TemporaryDirectory(prefix="callshield-test-")
        root = Path(self._td.name)
        self.root = root
        self.data = root / "data"
        self.logs = root / "logs"
        self.data.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self._orig_data = _pkg.DATA_DIR
        self._orig_logs = _pkg.LOG_DIR
        self._orig_config = config_mod.CONFIG_PATH
        self._orig_db_default = db_mod.DEFAULT_DB_PATH
        self._orig_env_data = os.environ.get("CALLSHIELD_DATA_DIR")
        self._orig_env_logs = os.environ.get("CALLSHIELD_LOG_DIR")

    def start(self) -> "IsolatedEnv":
        os.environ["CALLSHIELD_DATA_DIR"] = str(self.data)
        os.environ["CALLSHIELD_LOG_DIR"] = str(self.logs)
        _pkg.DATA_DIR = self.data
        _pkg.LOG_DIR = self.logs
        db_mod.DEFAULT_DB_PATH = self.data / "callshield.db"
        config_mod.CONFIG_PATH = self.data / "config.json"
        return self

    def stop(self) -> None:
        _pkg.DATA_DIR = self._orig_data
        _pkg.LOG_DIR = self._orig_logs
        config_mod.CONFIG_PATH = self._orig_config
        db_mod.DEFAULT_DB_PATH = self._orig_db_default
        if self._orig_env_data is None:
            os.environ.pop("CALLSHIELD_DATA_DIR", None)
        else:
            os.environ["CALLSHIELD_DATA_DIR"] = self._orig_env_data
        if self._orig_env_logs is None:
            os.environ.pop("CALLSHIELD_LOG_DIR", None)
        else:
            os.environ["CALLSHIELD_LOG_DIR"] = self._orig_env_logs
        self._td.cleanup()

    def make_config(self, **overrides: Any) -> Config:
        cfg = Config(
            database_path=str(self.data / "test.db"),
            pid_file=str(self.data / "test.pid"),
            log_file=str(self.logs / "test.log"),
            **overrides,
        )
        save_config(cfg, config_mod.CONFIG_PATH)
        return cfg


def run_cli(cfg: Config, *argv: str) -> Tuple[int, str]:
    """Invoke a CLI command, capturing stdout/stderr. Returns (exit_code, output)."""
    parser = _cli.build_parser()
    args = parser.parse_args(list(argv))
    ui = _cli._make_ui(args, cfg)
    handler = _cli._COMMANDS[args.command]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = handler(ui, args, cfg)
    return code, buf.getvalue()
