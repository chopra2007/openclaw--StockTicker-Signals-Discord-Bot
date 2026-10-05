# Source permission registry

Reviewed October 5, 2026, Pacific time. No private account-specific agreement,
written approval or redistribution/model-input grant was supplied or inspected.
All real market sources remain unverified and disabled for member display,
derived output, retention and model input. API access, a public link, a working
library and bot delivery do not grant any of these permissions. Provider contact,
purchases and source ingestion were not performed.

| Source/product family | Verified official evidence / unresolved issue | Current member-use decision |
| --- | --- | --- |
| Finnhub quote/technical/derived data | [Official terms](https://finnhub.io/terms-of-service) require written approval for sharing data or derived results, describe personal-use plans, and require deletion when a data subscription ends. No relevant private written approval is present. | Unverified for all four uses; source-specific deletion-compliant backups must be proved before enablement. |
| Schwab market information/options | [Official online-services agreement](https://www.schwab.com/legal/terms) restricts redistribution and access to authorized recipients. Personal testing and a trading API key do not establish dashboard rights. | Unverified for all four uses; actual product/account grant remains necessary. |
| Yahoo/yfinance fallback | The selected options storage has no served-provider/product lineage. Library availability is not a data-use grant. The attempted official Yahoo API terms read returned `Failed to fetch https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html: (999) Unknown Status Code`. | Unverified; no claim about unavailable contract text. Historic fallback rows cannot be attributed to Schwab by current settings. |
| SEC direct public filings/government content | [SEC webmaster FAQ](https://www.sec.gov/files/about/webmaster-faq.htm) permits reuse of government-created and EDGAR public filing content, with exceptions such as stock art. [Access policy](https://www.sec.gov/about/privacy-information) separately controls automated access. | Stored mixed summaries remain unverified because exact filing/contributor lineage is absent. A future direct SEC product grant record and exact manifest can be verified separately; source label alone is insufficient. |
| X/TweetShift text and chart interpretations | [Official X developer policy](https://docs.x.com/developer-terms/policy) is a terms input, not evidence that this collection/account route is licensed. Post, image and upstream contributor rights are not in the rows. | Unverified; text/image/model uses require their own verified evidence. |
| YouTube transcripts/analysis | [Official YouTube terms](https://www.youtube.com/t/terms) limit content use; [copyright guidance](https://support.google.com/youtube/answer/2797466?hl=en) describes rights holders' control and permission routes. No contributor-specific permission was verified. | Unverified; a public video/transcript is not a model or redistribution grant. |
| Other social, news/search, technical, model-derived and multi-source bot output | Category scores/details and prose are not source/product manifests. Desktop/private source families are blocked by the adapter. | Unverified or denied as applicable; every contributor must pass independently. |

The private `SourcePermission` registry records source/product/provider,
account/grant references, audience, four independent use permissions, policy
version, attribution, delay, effective/expiry/review times, retention deadline,
official terms link, private verification evidence and deletion/tombstone
obligations. Only synthetic private references appear in tests. Nothing copies
real contracts, account identifiers or credentials into the repository or
public response models. Registry insertion is a trusted local code hook, not an
admin/member endpoint. A new policy record supersedes older records for the exact
source/product pair; saved content citing an older version cannot silently adopt
the new grant or receive new content.

`SourcePolicy.authorize(contributions,use,now)` accepts typed exact product
contributions and returns `allowed`, `denied` or `unverified`; only `allowed`
permits use. Missing/ambiguous product identity, unknown contributors, absent
verification, overdue review, non-member audience or expired permission fail
closed. `display_raw`, `display_derived`, `retain` and `model_input` are distinct.
A mixed result with any withheld contributor is withheld in full or must be
recomputed from a permitted manifest; removing its citation does not fix it.
`authorize_lineage` additionally enforces earliest stored/current retention and
display/model delay, requiring a real observation timestamp when a delay applies.
Attribution is escaped and supplied on current delivery. Permission version and
current decision status contribute to the returned cache fingerprint; cache age
or a saved snapshot never bypasses current checks.

Restore/current-authority and backup compliance are independent host callbacks,
both closed by default. They must come from current verified authority outside
the historical restored database. A source with expiry-deletion or finite
retention obligations cannot become allowed until its backup-deletion compliance
callback is independently verified. No Task 3 code declares real backups
compliant or sets these callbacks true in production. Task 12 owns destructive
backup exclusion/key-destruction proof and restore reconciliation. Backup,
deleted page/WAL and physical-media deletion cannot be proved by SQL DELETE;
these obligations keep affected sources disabled now.

`purge` is a bounded web-only logical deletion hook, with per-table cursors for
repeat sweeps. It checks current retention permission and deletes affected
publication versions/feed content copies, result caches, report snapshots,
private chart blobs and source-bearing derived messages. Member-authored text
without source lineage is not inferred to be provider content. The schema stores
no source content in audit/usage/heartbeat/log records; future code must keep
logs to fixed non-content codes/counters and attach lineage to any new storage
class. There is no separate stored model-prompt table in this task. Later
assistant code must use the source-bearing messages/result storage contracts or
extend the purge registry before persisting prompts.

Access is blocked immediately by current delivery checks even before a scheduled
purge completes. `purge` retains only an opaque ID/type/fixed reason/time tombstone
when every contributor explicitly permits such non-content retention; removal
notifications carry no original payload. Original content is never replaced by
current data. Callers repeat returned cursors until the sweep completes, then
start a fresh sweep. Task 4/7 scheduling must wire this hook before accepting any
real source. Source disappearance from normal bot pruning does not invoke this
deletion path. Bot-side contract/deletion obligations are an owner action outside
the dashboard: no bot rows/files are changed.

Source permission does not replace membership, ownership, feature switches or
quota admission. Later cached feeds/charts/reports, assistant retrieval/tools,
model inputs and final responses must all recheck the applicable policy; no
unrestricted stored dictionary is a public or model-input bypass. Task 4A owns
the additional quota inventory and cross-process admission portions of this
document.

## Provider capacity and activation policy

Reviewed October 5, 2026, Pacific time. **Every real dashboard source remains
disabled.** No production policy, endpoint mapping, emergency reservation or
source grant is supplied by this change. Synthetic test values are not provider
quotas. No private account, key, token or outbound address was inspected.

### Inventory and evidence gaps

| Product | Verified public evidence | Transport inventory | Activation gaps |
| --- | --- | --- | --- |
| SEC EDGAR | [SEC access policy](https://www.sec.gov/about/privacy-information) limits aggregate automated requests to 10/second regardless of machines and describes recovery after ten minutes below threshold. | Shared HTTP: ticker-map cold retries, submissions, every filing XML, 8-K watcher, Form 144, Form 4 cluster and research sources. Research scripts also make direct requests outside the shared session. | Automation/user scope, all hosts and egress, active jobs, complete participation, fixed bot demand and member use permission unverified. |
| Finnhub REST | [Official documentation](https://www.finnhub.io/docs/api/country) search-indexed rate-limit text describes an additional 30/second ceiling. This is not an account allowance. | Shared HTTP: quotes, company news, earnings, calendars, ticker profile and API adapters. Some research scripts bypass it. | Plan/product/key/account/IP intersections, minute/day/reset limits, live consumers and permissions unverified. |
| Schwab market data and OAuth | [Product portal](https://developer.schwab.com/products/trader-api--individual); no public numeric allowance verified. Existing source comments are not account evidence. | Guarded market GET covers quotes, history, expirations and chains. Refresh POST is separately guarded and completes before market admission. Options/history fallbacks may invoke Yahoo. | App/account/key/egress/OAuth intersections, licensed member use, contract, bot reservation and other hosts unverified. |
| Yahoo chart and SDK | No contractual quota or permission verified. | Direct shared-session chart requests can be classified. SDK metadata, history, chain, cookie, crumb, consent, retry and threaded download sends remain unmapped. | All shared SDK use denied in participating permitted dashboard paths. Daily jobs, direct SDK consumers and external scripts are not fully covered. |
| Groq | [Rate limits](https://console.groq.com/docs/rate-limits) apply organization/model request and token windows; [projects](https://console.groq.com/docs/projects) remain under organization capacity. | Shared HTTP includes bot model attempts and video models; races, fallbacks, scripts and external gateway also contribute. | No verified organization/model/project/token allocation or complete transport coverage. Separate keys alone do not prove independence. |
| OpenRouter | [Limits](https://openrouter.ai/docs/api_reference/limits) and [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) describe account/key/provider capacity and routing. | Bot model and video attempts, scripts, external gateway and upstream fallback. | Account/model/upstream/BYOK/credit limits, token charging and full participation unverified. Shared dashboard model calls remain off. |
| Other contributing news/search/social/video products | No deployment quota or member-use grant verified. | Some consumers use the shared session; other libraries and scripts bypass it. | Inventory incomplete; never inherit another product's allowance. |

The public SEC policy was read from its official page. The Finnhub numeric fact
was available in the current official search index; direct root documentation
returned HTTP 429 and the country page rendered no text. Neither establishes
deployment capacity. Independently licensed dashboard capacity is preferred only
when account, IP and upstream independence are proven.

Private launch inventory must record opaque product/account/key aliases, every
outbound host/IP and consumer, contract evidence/version/expiry, intersecting
request/burst/daily/token windows and reset semantics, measured bot peak demand,
fixed bot reservation, dashboard allocation and safety margin. Each scope must
satisfy `bot_reserved + dashboard_allocated + safety_margin <= verified_limit`.
Current values for all deployment-specific fields are **unverified**. There is
no emergency allocation. No real source is enabled while these facts are missing.

### Local admission contract

`BudgetClient.reserve(scope_ids, caller, endpoint, units, attempt_id)` returns
`Admission(allowed, admission_id, not_before, reason)`. `finish(admission_id,
outcome, retry_after)` records completion or uncertainty. Units are a positive
finite scalar for every scope, or an exact scope-to-units mapping (for example,
one request plus the full bounded token allowance). No post-completion token
refund occurs. Real model adapters still need independently reviewed token
reservation and participation before activation.

The broker owns the exact endpoint-to-scope mapping and minimum units. Missing,
unverified, expired, omitted or additional scopes fail closed. All scopes reserve
atomically in one web-store transaction. Strict per-role allocations cannot be
borrowed. Sliding windows conservatively cover bursts/fixed provider resets.
Finish frees only concurrency, never request/token consumption. Active policies
cannot be reallocated, and changing a window requires a new scope while retaining
the old intersecting scope until its charges expire.

Use a new attempt ID before every actual page, retry, fallback or OAuth send.
Reuse it only to retry the same admission RPC before sending that request. An
idempotent admission response is not authorization to send again after a prior
send. Attempt replay is bound to authenticated process identity and exact
endpoint/scopes/units. Uncertain work remains charged and holds concurrency after
restart. Replays after completion, expiry, window rollover, mapping withdrawal
or a newly shared cooldown are deferred; old permits cannot authorize new sends.
Unfinished work continues holding concurrency after
restart, even after its request window ends. A shared 429 cooldown applies to all
charged scopes; numeric and HTTP-date Retry-After values are not shortened.
Missing/invalid values cause a conservative 600-second hold. A 429 body failure
still persists the cooldown while retaining uncertain concurrency.

The Linux server requires a broker-owned directory restricted to 0750 or tighter
and binds a 0660 Unix socket. Deployment supplies a restricted shared group for
socket access and distinct bot/dashboard UIDs. Linux `SO_PEERCRED` determines the
role and PID; boot ID plus process start ticks distinguish reused PIDs. Member,
model and request payloads cannot assign roles. Socket mode, group membership and
UID mapping require deployment proof. No account/DB/configuration/reconciliation
RPC exists: only reserve and finish. The bot client has no web-store import or
database path. Frames are capped at 16 KiB, connections are serial with bounded
backlog, receive deadline and finite SQLite/RPC waits.

The authenticated loopback factory is for isolated synthetic Windows tests only.
It binds role-specific test credentials to identities; it is not production
process identity or a cross-host deployment route. A topology sharing limits
across hosts cannot activate until an authenticated central route is implemented.
Missing broker access defers participating bot/dashboard work. No fail-open
fallback or inferred emergency capacity exists.

### Transport and operation ownership

Trusted bootstrap may call `configure_transport_budget` before creating sessions
or starting any work. With no configuration, existing bot calls, calculations,
schedules and output are unchanged. With configuration, shared aiohttp requests
and Schwab market/OAuth sends require trusted static method/origin/path mappings.
Only opaque endpoint labels reach the broker; URLs, queries, headers and bodies
are not stored. Every matched request is separately charged. Implicit redirects
are disabled, and activated aiohttp requires its verified retry-disable mechanism.
Async context-manager ownership persists through response-body handling. Awaited
raw responses, streaming requests, custom retrying sessions and unknown SDKs are
unsupported. Missing exact route mappings defer rather than guess.

Yahoo fallback guards in prices, expected move and options deny before entering
the SDK in participating processes. This does not certify every other bot SDK
consumer: those inventory gaps keep Yahoo closed. The broad bot model transport
and external gateway were not changed, so generic HTTP coverage does not certify
model source participation. SEC/Finnhub direct research-script bypasses likewise
keep shared source activation closed.

`ProviderRuntime` remains the single authority for the dashboard's two actual
operations, shared by future analysis/model/summary lanes. The broker is a
separate per-transport budget authority; scanner invocation is not one request.
No second executor or coroutine-count concurrency mechanism is introduced.
Timeout of a waiting coroutine does not complete the real transport or refund
either authority's capacity.

### Supervisor reconciliation required at composition

Task 12 must contain the entire worker process tree, confirm its exit using exact
boot/PID/start identity, then invoke `QuotaBroker.reconcile_exited(owner,
confirmed_dead=trusted_tree_exit_predicate, limit=100)` in bounded batches. The
method returns the number of scope rows settled; repeat until zero before
settling runtime calls/probes and permitting replacement work. It is not exposed
to clients. Without the explicit trusted predicate it does nothing. Missing
heartbeat, RPC outage, elapsed time and broker restart are never exit proof.
`confirmed_process_exit` checks only an individual Linux identity and is not by
itself process-tree proof. Reconciliation records uncertain completed work and
retains every consumed request/token charge. Broker restart must not delete
unfinished admissions or replace a socket belonging to a live server.

Task 12 also owns separate service identities, safe socket lifecycle, permission
proof, health/deadline handling and retention of durable quota data. Source-use
grants from `source_policy.py` remain independent gates on live, cached, stored
and model-input use. None of this local implementation activates a provider.
