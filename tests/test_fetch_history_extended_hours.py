"""TODO #92 — fetch_history() must forward extended_hours to both the Schwab
primary path and the yfinance fallback path."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from consensus_engine.utils import prices


def _df():
    return pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]})


class TestSchwabPath:
    """Schwab primary path (features.schwab_ohlcv.enabled=True)."""

    def test_extended_hours_true_reaches_schwab(self):
        with patch("consensus_engine.config.get", return_value=True), \
             patch("consensus_engine.scanners.schwab_client.get_price_history",
                   return_value=_df()) as mock_get:
            prices.fetch_history("SPY", interval="5m", extended_hours=True)
        assert mock_get.call_args.kwargs["extended_hours"] is True

    def test_extended_hours_default_false_reaches_schwab(self):
        with patch("consensus_engine.config.get", return_value=True), \
             patch("consensus_engine.scanners.schwab_client.get_price_history",
                   return_value=_df()) as mock_get:
            prices.fetch_history("SPY", interval="5m")
        assert mock_get.call_args.kwargs["extended_hours"] is False


class TestYfinanceFallback:
    """yfinance fallback path (Schwab disabled/failed)."""

    def test_extended_hours_true_sets_prepost(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _df()
        with patch("consensus_engine.config.get", return_value=False), \
             patch("yfinance.Ticker", return_value=mock_ticker):
            prices.fetch_history("SPY", interval="5m", extended_hours=True)
        assert mock_ticker.history.call_args.kwargs["prepost"] is True

    def test_extended_hours_default_false_sets_prepost_false(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _df()
        with patch("consensus_engine.config.get", return_value=False), \
             patch("yfinance.Ticker", return_value=mock_ticker):
            prices.fetch_history("SPY", interval="5m")
        assert mock_ticker.history.call_args.kwargs["prepost"] is False
