"""Tests for SEC 8-K real-time watcher."""
import pytest
from consensus_engine.scanners.sec_watcher import _parse_8k_feed


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - NVIDIA CORP (0001045810) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1045810/000104581024000123/0001045810-24-000123-index.htm" rel="alternate" type="text/html"/>
    <summary>8-K filed by NVIDIA CORP</summary>
    <updated>2026-03-29T10:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2026:0001045810-24-000123</id>
  </entry>
  <entry>
    <title>10-Q - SOME CORP (0009999999) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/9999999/000099999924000001/index.htm" rel="alternate" type="text/html"/>
    <summary>10-Q filed by SOME CORP</summary>
    <updated>2026-03-29T09:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2026:0009999999-24-000001</id>
  </entry>
</feed>"""


def test_parse_8k_feed_extracts_8k_only():
    filings = _parse_8k_feed(SAMPLE_ATOM)
    assert len(filings) == 1
    assert filings[0]["cik"] == "0001045810"
    assert filings[0]["form"] == "8-K"
    assert "NVIDIA" in filings[0]["company"]


def test_parse_8k_feed_empty():
    filings = _parse_8k_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    assert filings == []


def test_parse_8k_feed_invalid_xml():
    filings = _parse_8k_feed("not xml")
    assert filings == []
