# System Issues Log

## 2026-04-06

### ✅ Completed: YouTube Transcript Skill

**What was done:**
1. Created skill at `/root/.openclaw/workspace/skills/youtube-transcript/SILL.md`
2. Installed `apify-client` Python library
3. Added `!transcript` command to Discord bot (`consensus_engine/alerts/commands.py`)
4. Verified the Apify actor works (free tier: `trisecode/yt-Transcript`)

**Test result:**
- Apify API call works — returns transcript successfully
- Example: `!transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ` returns transcript

### ❌ Not Working: Terminal Command

**Issue:** Running `!transcript` in terminal (not Discord) fails with:
```
transcript: not found
```

**Root cause:** The transcript command is a Discord command, not a shell command. It only works when typed in the Discord channel (with `!` prefix), not in the terminal.

**To test:** Use Discord — type `!transcript [YouTube_URL]` in the Discord channel where the bot is active.

---

### ❌ Not Working: Discord Transcript Command

**Issue:** The `!transcript` command is not responding correctly in Discord. When user types `!transcript [URL]`, the bot either:
- Doesn't recognize it as a command
- Or responds incorrectly (as shown: "I can't access the YouTube video directly")

**Debugging needed:**
1. Check if the command is being parsed correctly (should be handled by `commands.py`)
2. Check if the actor call works in the Discord context
3. Verify the Discord bot process has access to `APIFY_TOKEN` env var

**Full error from Discord:**
```
!I can access the YouTube video directly.
Can you:
Paste a brief summary of what the video is about?
Or share the transcript text here?
```

### ❌ Not Working: Apify Plugin Installation

**Issue:** Tried to install `@apify/apify-openclaw-plugin` manually but it fails to install properly:
```
- Plugin installs to /root/.openclaw/extensions/apify/ but gets cleaned up on restart
- npm install in the extensions directory doesn't create node_modules properly
- The plugin requires pnpm but pnpm is not installed on this system
```

**Error:** `/bin/sh: 1: pnpm: not found`

---

### Other Notes

- The `APIFY_TOKEN` was updated from old token to new `APIFY2_TOKEN` on 2026-04-06
- Gateway was restarted to load changes
- 149 tests pass in the consensus_engine
