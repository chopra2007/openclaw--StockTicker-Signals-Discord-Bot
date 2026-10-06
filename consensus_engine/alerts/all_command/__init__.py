"""!all command package — data layer (PR4a) + orchestration (PR4b).

Modules:
- levels: anchor extraction, clustering, ranking, suppression
- gap_fill: output-field-driven SearXNG fan-out
- structured_fields: code-derived direction/confidence/timeframe/magnitude
- output_filter: narrative sanitization, contradiction detection, fallback render
- embed: Discord embed builder
- narrator: hostile-text sanitization + synthesis LLM call
- cache: 15-min TTL via xref_cache key_prefix="all" + single-flight
- discord_history: #chat 24h ticker-filtered + #brief last 3 fetchers
- vault_writer: render + atomic write of <TICKER>-all.md
- aggregator: top-level handle_all() orchestrator
"""

def __getattr__(name):
    if name == "handle_all":
        from consensus_engine.alerts.all_command.aggregator import handle_all
        return handle_all
    raise AttributeError(name)

__all__ = ["handle_all"]
