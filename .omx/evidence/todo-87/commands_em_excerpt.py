# EVIDENCE EXCERPT — original path: consensus_engine/alerts/commands.py
# copied 2026-08-17 for TODO #87 (read-only evidence, do not edit)
# file is 2977 lines; excerpted below:
#   lines 1213-1224  _handle_em          (entry point for !em / !emw)
#   lines 1227-1246  _em_and_reply       (proven pattern: compute -> embed -> chart in executor -> upload)
# no other helpers are local to this pair; the rest live in scanners/expected_move.py
# and alerts/discord.py (both also copied into this folder).

# ---- lines 1213-1246 ----
1213	                     horizon: str = "daily") -> None:
1214	    """Show the options-implied expected move (with chart) for a ticker.
1215	
1216	    horizon is "daily" (the default, next-session expiry) or "weekly" (the
1217	    listed expiry closest to one trading week out). Works on any optionable
1218	    ticker; tickers with no listed options or with quotes too poor for a
1219	    reliable straddle get a friendly message from compute_em."""
1220	    word = "weekly" if horizon == "weekly" else "daily"
1221	    await send_command_reply(
1222	        channel_id, message_id,
1223	        f"Calculating {word} expected move for `${ticker}`…")
1224	    return await _dispatch_inner(_em_and_reply(ticker, channel_id, message_id, horizon))
1225	
1226	
1227	async def _em_and_reply(ticker: str, channel_id: str, message_id: str,
1228	                        horizon: str = "daily") -> None:
1229	    from consensus_engine.scanners import expected_move as em
1230	    from consensus_engine.alerts.discord import send_command_embed_with_image
1231	    try:
1232	        result = await em.compute_em(ticker, executor=None, horizon=horizon)
1233	        embed = em.build_em_embed(result, with_image=True)
1234	        # Chart render is blocking (matplotlib) — run off the event loop.
1235	        loop = asyncio.get_running_loop()
1236	        image = await loop.run_in_executor(None, em.render_chart, result)
1237	        if image is None:
1238	            embed = em.build_em_embed(result, with_image=False)
1239	        await send_command_embed_with_image(
1240	            channel_id, message_id, embed, image, em.chart_filename(ticker),
1241	        )
1242	    except em.EMUnavailable as e:
1243	        await send_command_reply(channel_id, message_id, str(e))
1244	    except Exception as e:
1245	        log.error("EM command error for %s: %s", ticker, e)
1246	        await send_command_reply(channel_id, message_id, f"Expected-move lookup failed for `${ticker}`.")
