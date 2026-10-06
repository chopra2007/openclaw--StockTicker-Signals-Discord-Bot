# Member dashboard verification

Task 1 was checked on October 5, 2026, Pacific time, using Python 3.12.14 in a separate web environment. No production code, settings, database, service, invitation or account was changed.

The app receives explicit absolute `web_path` and `market_path` values through immutable `Settings`. Matching resolved paths, symbolic links and hard links are rejected before startup and checked again before migration. Startup migrates only the web store. It never opens the market store or discovers environment/credential files. `/healthz` returns exactly `{"status":"ok"}`. Public API responses have `Cache-Control: private, no-store` and `Referrer-Policy: no-referrer`; CORS is disabled.

The initial web migration creates the 27 planned domain tables plus its schema-version table. Each write transaction uses its own connection, foreign keys, WAL and a two-second busy timeout. Transactions commit or roll back atomically. Unique constraints protect normalized usernames, binary token digests, report-owner pairs, active job keys, result fingerprints and source/card versions. Immutable content requires new versions; deletion remains possible for later retention enforcement. UUID identifiers are required for private resources. Member and work authorization revisions are reserved for subsequent guards.

Results, report versions, publications/changes, assets and messages retain source/product/version/policy lineage, field-level feature dependencies, required features and retention deadlines. `ContentLineage` validates complete internal metadata. Empty stored lineage means unverified; later policy checks must withhold such content. Public `SectionResult` uses a strict discriminated payload union. It rejects arbitrary dictionaries, private extra fields, wrong section/horizon combinations and nonfinite numbers. Missing measurements remain null and measurements include units and methods. Frontend type generation belongs to Task 8.

All eight web features default enabled in this isolated staging store. No source permissions or provider capacity are granted by migration. These defaults do not approve licensing, production access or deployment. No member data routes exist in Task 1; later routes must use explicit owner predicates and current session, feature and source-policy checks.

## Dependencies

The root `requirements-web.in` and `requirements-web-dev.in` are human inputs. Their `.lock` files pin transitive packages and include artifact hashes. Resolve changes with pip-tools 7.6.1 on Python 3.12, retaining the approved major families. FastAPI selects its compatible Starlette version; the resolved Starlette 1.7.0 is recorded in both locks. The test client uses HTTPX2 because Starlette deprecated HTTPX for that client.

| Package | Checked version |
| --- | --- |
| FastAPI | 0.142.2 |
| Pydantic / pydantic-core | 2.13.5 / 2.46.5 |
| Starlette | 1.7.0 |
| Uvicorn | 0.54.0 |
| argon2-cffi | 25.1.0 |
| HTTPX2 / HTTPCore2 (tests) | 2.13.1 / 2.13.1 |
| pytest / pytest-asyncio / pytest-timeout | 9.1.1 / 1.4.0 / 2.4.0 |

Create a dedicated environment, upgrade its installer, and install with hashes:

```powershell
python -m venv .venv-web
& '.venv-web/Scripts/python.exe' -m pip install --upgrade 'pip>=26.2.1'
& '.venv-web/Scripts/python.exe' -m pip install --require-hashes -r requirements-web-dev.lock
& '.venv-web/Scripts/python.exe' -m pip check
& '.venv-web/Scripts/python.exe' -m pytest tests/member_dashboard/test_store.py -q
```

Use `requirements-web.lock` for runtime-only installs. Keep the bot environment separate. The clean hash-locked reinstall reported `No broken requirements found.` and **47 passed**, with no warnings. This includes a clean subprocess startup that forbids bot imports and machine configuration reads, missing/existing market-file isolation, hard/symbolic-link rejection, separate-connection writer contention, rollback and safe failure responses.

Both runtime and development lock audits using pip-audit 2.10.1 reported **No known vulnerabilities found**. The initially bundled pip 25.0.1 had published advisories; only dedicated web environment installers were upgraded to 26.2.1. Package audits are a dated check, not a future security guarantee. Supporting official documentation: [FastAPI version guidance](https://fastapi.tiangolo.com/deployment/versions/), [Starlette releases](https://starlette.dev/release-notes/), [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/) and [Python SQLite transaction control](https://docs.python.org/3.12/library/sqlite3.html#transaction-control).

## Regression status

The coordinating agent captured the pre-code full-suite Windows baseline and archived the pre-code revision before implementation. Windows could not collect 71 bot modules. The post-change bot-only comparison used the unchanged baseline environment and excluded the separately verified dashboard folder; it reproduced the exact same 71 collection-error IDs, with no additions/removals, 120 skipped and two deselected. `.test-baseline` was left unchanged. This comparison does not establish a passing full regression gate. An independent isolated Linux baseline/comparison is owned by the coordinating agent; authoritative full-suite verification remains a separate gate until that comparison succeeds.

Exact failing IDs, RED/GREEN output, dependency-audit JSON and installation logs are retained privately in the implementation workspace. Do not publish operational failures or test fixture identifiers as real member data. The required read-only service checks were owned and recorded by the coordinating agent. Production activation still requires all later tasks and the measured launch gates.
