# EVIDENCE EXCERPT — original path: consensus_engine/alerts/discord.py
# copied 2026-08-17 for TODO #87 (read-only evidence, do not edit)
# file is 1270 lines; excerpted below (line numbers preserved in the left column):
#   lines 36-37     _EMBED_LIMITS / _FIELD_LIMITS  — Discord embed size caps (title 256, description 4096, field name 256, field value 1024)
#   lines 41-88     _clip / _clamp_embeds / _safe_send_kwargs — the size guard: clips over-long embed text and attaches allowed_mentions
#   lines 89-93     _redact_secrets
#   lines 1020-1051 _DISCORD_MSG_LIMIT = 2000 + _split_for_discord — plain-text 2000-char splitter
#   lines 1133-1159 send_command_embed_reply — JSON embed reply (no attachment)
#   lines 1161-1243 send_command_embed_with_image — multipart embed + PNG upload used by !em/!emw

# ---- lines 36-93 ----
36	_EMBED_LIMITS = {"title": 256, "description": 4096}
37	_FIELD_LIMITS = {"name": 256, "value": 1024}
38	_EMBED_MAX_FIELDS = 25
39	
40	
41	def _clip(text: str, limit: int) -> str:
42	    return text if len(text) <= limit else text[:limit - 1] + "…"
43	
44	
45	def _clamp_embeds(payload: dict) -> None:
46	    """Trim embed parts to Discord's limits, in place. A trimmed card beats none."""
47	    for embed in payload.get("embeds", []) or []:
48	        if not isinstance(embed, dict):
49	            continue
50	        for key, limit in _EMBED_LIMITS.items():
51	            if isinstance(embed.get(key), str):
52	                embed[key] = _clip(embed[key], limit)
53	        fields = embed.get("fields")
54	        if isinstance(fields, list):
55	            if len(fields) > _EMBED_MAX_FIELDS:
56	                del fields[_EMBED_MAX_FIELDS:]
57	            for field in fields:
58	                if not isinstance(field, dict):
59	                    continue
60	                for key, limit in _FIELD_LIMITS.items():
61	                    if isinstance(field.get(key), str):
62	                        field[key] = _clip(field[key], limit)
63	
64	
65	def _safe_send_kwargs(payload: dict) -> dict:
66	    """Add allowed_mentions safety to any Discord POST payload.
67	
68	    Always-on defense-in-depth: every Discord-bound POST passes through this
69	    helper so the bot can never @everyone/@here/role/user-ping via an
70	    accidentally-rendered string from an LLM, scraped page, or contributor
71	    text. The caller's payload is mutated in-place AND returned so it can be
72	    used inline (e.g. ``json=_safe_send_kwargs({...})``).
73	
74	    It is also the one place every Discord-bound POST passes through, so embed
75	    parts get trimmed to Discord's limits here rather than at each call site.
76	    """
77	    payload.setdefault("allowed_mentions", {"parse": []})
78	    _clamp_embeds(payload)
79	    return payload
80	
81	
82	# Regex to redact token-like strings before posting error text to Discord.
83	_SECRET_RE = re.compile(
84	    r'(?:token|key|secret|password|MTQ[A-Za-z0-9_-]{20,})',
85	    re.IGNORECASE,
86	)
87	
88	
89	def _redact_secrets(text: str) -> str:
90	    """Replace secret-like substrings with [REDACTED] in error text."""
91	    return _SECRET_RE.sub("[REDACTED]", text)
92	
93	

# ---- lines 1020-1051 ----
1020	_DISCORD_MSG_LIMIT = 2000
1021	
1022	
1023	def _split_for_discord(content: str, limit: int = _DISCORD_MSG_LIMIT) -> list[str]:
1024	    """Split `content` into chunks ≤ `limit` chars. Prefer paragraph then line breaks.
1025	
1026	    Returns [] for empty input. Any single line longer than the limit is hard-cut
1027	    on a character boundary as a last resort.
1028	    """
1029	    if not content:
1030	        return []
1031	    if len(content) <= limit:
1032	        return [content]
1033	
1034	    chunks: list[str] = []
1035	    remaining = content
1036	    while remaining:
1037	        if len(remaining) <= limit:
1038	            chunks.append(remaining)
1039	            break
1040	        window = remaining[:limit]
1041	        cut = window.rfind("\n\n")
1042	        if cut < limit // 4:
1043	            cut = window.rfind("\n")
1044	        if cut < limit // 4:
1045	            cut = window.rfind(" ")
1046	        if cut < limit // 4:
1047	            cut = limit
1048	        chunks.append(remaining[:cut])
1049	        remaining = remaining[cut:].lstrip("\n").lstrip()
1050	    return chunks
1051	

# ---- lines 1133-1243 ----
1133	async def send_command_embed_reply(
1134	    channel_id: str,
1135	    reply_to_msg_id: str,
1136	    embed: dict,
1137	) -> Optional[str]:
1138	    """Send an embed reply to a Discord command message (used by !all)."""
1139	    if cfg.dry_run:
1140	        log.info(
1141	            "[DRY-RUN] Embed reply to %s: %s",
1142	            reply_to_msg_id, embed.get("title", ""),
1143	        )
1144	        return "dry_run_reply_id"
1145	
1146	    token = cfg.get_api_key("discord_bot_token")
1147	    if not token:
1148	        log.warning("Discord bot token not configured")
1149	        return None
1150	
1151	    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
1152	    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
1153	    body = _safe_send_kwargs({
1154	        "embeds": [embed],
1155	        "message_reference": {"message_id": reply_to_msg_id},
1156	    })
1157	    data = await _safe_send(url, headers, body)
1158	    return data.get("id") if data else None
1159	
1160	
1161	async def send_command_embed_with_image(
1162	    channel_id: str,
1163	    reply_to_msg_id: str,
1164	    embed: dict,
1165	    image_bytes: Optional[bytes],
1166	    filename: str,
1167	) -> Optional[str]:
1168	    """Send an embed reply with an attached PNG (multipart upload, used by !em).
1169	
1170	    The embed should reference the image via ``{"image": {"url":
1171	    "attachment://<filename>"}}``. Mirrors send_command_embed_reply's
1172	    dry-run/token/allowed-mentions handling and retries on 429. If the image is
1173	    missing or the multipart upload fails, it falls back to the embed without
1174	    the image so the user still gets the numbers.
1175	    """
1176	    if cfg.dry_run:
1177	        log.info(
1178	            "[DRY-RUN] Embed+image reply to %s: %s (%s, %d bytes)",
1179	            reply_to_msg_id, embed.get("title", ""), filename,
1180	            len(image_bytes or b""),
1181	        )
1182	        return "dry_run_reply_id"
1183	
1184	    token = cfg.get_api_key("discord_bot_token")
1185	    if not token:
1186	        log.warning("Discord bot token not configured")
1187	        return None
1188	
1189	    # No chart bytes — degrade to an image-less embed rather than fail.
1190	    if not image_bytes:
1191	        embed_noimg = {k: v for k, v in embed.items() if k != "image"}
1192	        return await send_command_embed_reply(channel_id, reply_to_msg_id, embed_noimg)
1193	
1194	    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
1195	    headers = {"Authorization": f"Bot {token}"}  # aiohttp sets the multipart Content-Type
1196	    payload = _safe_send_kwargs({
1197	        "embeds": [embed],
1198	        "message_reference": {"message_id": reply_to_msg_id},
1199	        "attachments": [{"id": 0, "filename": filename}],
1200	    })
1201	
1202	    session = await get_session()
1203	    for attempt in range(4):
1204	        try:
1205	            # FormData is single-use; rebuild it each attempt.
1206	            form = aiohttp.FormData()
1207	            form.add_field("payload_json", json.dumps(payload),
1208	                           content_type="application/json")
1209	            form.add_field("files[0]", image_bytes, filename=filename,
1210	                           content_type="image/png")
1211	            async with session.post(
1212	                url, headers=headers, data=form,
1213	                timeout=aiohttp.ClientTimeout(total=20),
1214	            ) as resp:
1215	                if resp.status in (200, 201):
1216	                    data = await resp.json()
1217	                    return data.get("id")
1218	                if resp.status == 429 and attempt < 3:
1219	                    retry_after = float(resp.headers.get("Retry-After", 1.0))
1220	                    try:
1221	                        rbody = await resp.json()
1222	                        retry_after = float(rbody.get("retry_after", retry_after))
1223	                    except Exception:
1224	                        pass
1225	                    log.warning(
1226	                        "send_command_embed_with_image 429 — sleeping %.1fs (attempt=%d)",
1227	                        retry_after, attempt + 1,
1228	                    )
1229	                    await asyncio.sleep(retry_after)
1230	                    continue
1231	                error_body = await resp.text()
1232	                log.warning(
1233	                    "send_command_embed_with_image HTTP %d (attempt=%d): %s",
1234	                    resp.status, attempt, _redact_secrets(error_body[:300]),
1235	                )
1236	                break
1237	        except Exception as e:
1238	            log.error("send_command_embed_with_image exception (attempt=%d): %s", attempt, e)
1239	            break
1240	
1241	    # Multipart failed — send the embed without the image so the numbers land.
1242	    fallback = {k: v for k, v in embed.items() if k != "image"}
1243	    return await send_command_embed_reply(channel_id, reply_to_msg_id, fallback)

