"""Atomic JSON export for YouTube transcripts."""

import hashlib
import json
import os
import time
from pathlib import Path


def export_transcript_json(
    channel_id: str,
    video_id: str,
    title: str,
    published_at: str,
    language: str,
    is_auto_generated: bool,
    transcript_text: str,
    export_dir: str = "artifacts/transcripts",
) -> str:
    """Write transcript as JSON file using atomic tmp→rename. Returns final path."""
    out_dir = Path(export_dir) / channel_id
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / f"{video_id}.json"
    tmp_path = final_path.with_suffix(".tmp")
    payload = {
        "channel_id": channel_id,
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "language": language,
        "is_auto_generated": is_auto_generated,
        "fetched_at": time.time(),
        "transcript_text": transcript_text,
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, final_path)
    return str(final_path)


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
