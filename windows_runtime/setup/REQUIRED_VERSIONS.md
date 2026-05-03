# Required Software Versions

## Python

| Requirement | Value |
|-------------|-------|
| **Minimum** | 3.11 |
| **Maximum** | < 3.13 |
| **Recommended** | 3.11.x or 3.12.x |

**Reason:** Python 3.13 drops `distutils`, which `pywinauto 0.6.x` depends on indirectly via `setuptools` shims. Additionally, ctypes internal ABI changes in 3.13 break certain Win32 struct layouts that pywinauto relies on for UIA element queries. Stick to 3.11 or 3.12.

---

## pywinauto

| Requirement | Value |
|-------------|-------|
| **Version** | == 0.6.x (latest 0.6.8) |

**Reason:** pywinauto 0.7.x introduced breaking changes to the UIA (UI Automation) backend API — method signatures, element property accessors, and the `Application.connect()` interface all changed. The daemon is written against the 0.6.x API. Upgrading to 0.7.x will require non-trivial code changes to `find_discord_window()` and `get_channel_messages()`.

Install pinned version:
```powershell
pip install "pywinauto==0.6.8"
```

---

## Playwright (Python)

| Requirement | Value |
|-------------|-------|
| **Minimum** | >= 1.40 |

**Reason:** Playwright versions before 1.40 have known issues with Chromium headless detection in newer browser builds — sites including Google OAuth can reject the browser fingerprint. 1.40+ includes updated stealth patches.

Install:
```powershell
pip install "playwright>=1.40"
playwright install chromium
```

---

## Claude Desktop

| Requirement | Value |
|-------------|-------|
| **Minimum** | >= 1.0 stable |

**Reason:** The Routines API (used by the R1 routine) was not present in pre-1.0 preview builds. Only the stable 1.0+ channel exposes the routine trigger and execution interfaces. Beta/preview builds are not supported.

Download stable builds from [claude.ai/download](https://claude.ai/download).

---

## Windows OS

| Requirement | Value |
|-------------|-------|
| **Minimum** | Windows 10 version 1903 (build 18362 / 19H1) |
| **Recommended** | Windows 10 21H2+ or Windows 11 |

**Reason:** UIA3 (UI Automation v3) automation — which pywinauto uses for Discord element access — requires RS5/19H1 (the 1903 build) as the minimum. Earlier builds have incomplete UIA3 COM interfaces that cause silent failures when traversing complex application windows like Discord.

---

## Summary Table

| Component | Min | Max | Notes |
|-----------|-----|-----|-------|
| Python | 3.11 | < 3.13 | 3.12.x recommended |
| pywinauto | 0.6.x | 0.6.x | Pin to 0.6.8 |
| Playwright | 1.40 | latest | Install Chromium after |
| Claude Desktop | 1.0 | latest | Stable channel only |
| Windows | 1903 (19H1) | latest | Win11 preferred |
