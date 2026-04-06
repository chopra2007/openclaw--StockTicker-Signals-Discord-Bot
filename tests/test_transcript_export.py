"""Tests for transcript_export utility."""
import json
import os
import time
import pytest
from pathlib import Path
from consensus_engine.utils.transcript_export import export_transcript_json, compute_hash


def test_export_creates_file(tmp_path):
    path = export_transcript_json(
        channel_id="UC123",
        video_id="abc",
        title="Test Video",
        published_at="2026-04-06T00:00:00Z",
        language="en",
        is_auto_generated=True,
        transcript_text="Hello world.",
        export_dir=str(tmp_path),
    )
    assert os.path.exists(path)


def test_export_path_format(tmp_path):
    path = export_transcript_json(
        channel_id="UCabc",
        video_id="vid999",
        title="Title",
        published_at="2026-04-06T00:00:00Z",
        language="en",
        is_auto_generated=False,
        transcript_text="Some text",
        export_dir=str(tmp_path),
    )
    p = Path(path)
    assert p.parent.name == "UCabc"
    assert p.name == "vid999.json"


def test_export_json_payload_contract(tmp_path):
    path = export_transcript_json(
        channel_id="UCtest",
        video_id="v1",
        title="My Title",
        published_at="2026-04-06T10:00:00Z",
        language="en",
        is_auto_generated=True,
        transcript_text="Transcript content here.",
        export_dir=str(tmp_path),
    )
    with open(path) as f:
        data = json.load(f)
    assert data["channel_id"] == "UCtest"
    assert data["video_id"] == "v1"
    assert data["title"] == "My Title"
    assert data["published_at"] == "2026-04-06T10:00:00Z"
    assert data["language"] == "en"
    assert data["is_auto_generated"] is True
    assert data["transcript_text"] == "Transcript content here."
    assert isinstance(data["fetched_at"], float)


def test_no_tmp_file_left_behind(tmp_path):
    export_transcript_json(
        channel_id="UCclean",
        video_id="vclean",
        title="T",
        published_at="",
        language="en",
        is_auto_generated=False,
        transcript_text="text",
        export_dir=str(tmp_path),
    )
    tmp_files = list(Path(tmp_path).rglob("*.tmp"))
    assert len(tmp_files) == 0


def test_hash_deterministic():
    h1 = compute_hash("same text")
    h2 = compute_hash("same text")
    assert h1 == h2


def test_hash_differs_on_different_text():
    assert compute_hash("text A") != compute_hash("text B")
