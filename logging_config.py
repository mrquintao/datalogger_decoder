"""Configuracao central de logging da aplicacao."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


APP_NAME = "DataloggerDecoder"
LOG_FILENAME = "datalogger_decoder.log"


def _application_directory() -> Path:
    """Retorna a pasta do executavel congelado ou do projeto em modo Python."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidate_log_directories() -> list[Path]:
    candidates = [_application_directory() / "logs"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / APP_NAME / "logs")
    candidates.append(Path.home() / f".{APP_NAME.lower()}" / "logs")
    return candidates


def get_log_directory() -> Path:
    """Cria e retorna uma pasta gravavel para os logs."""
    last_error: OSError | None = None
    for directory in _candidate_log_directories():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return directory
        except OSError as exc:
            last_error = exc
    raise OSError("Nao foi possivel criar uma pasta de logs gravavel.") from last_error


def configure_logging() -> Path | None:
    """Configura logging em arquivo; se falhar, mantem logging em stderr."""
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    try:
        log_dir = get_log_directory()
        log_path = log_dir / LOG_FILENAME
        handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        log_path = None
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    return log_path
