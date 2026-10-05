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
