"""Shared JSONL observability logger for pipeline instrumentation."""
import json
import time
import os
from pathlib import Path

_LOG_PATH = Path("/home/openclaw/.openclaw/workspace/.omc/logs/pipeline-obs.jsonl")


def obs_log(record: dict) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
