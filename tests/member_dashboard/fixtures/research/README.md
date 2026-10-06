# Original calculation fixtures

These eleven synthetic fixtures were captured before the extraction, from bot
source commit `e0f1d7534da52065231dbdbf24cc48bc6dc4f1bb`. Two independent runs
produced byte-identical fixture files. The fixed observation time is October 5,
2026, 9:00 AM Pacific. `manifest.json` records the original bytes' hashes.

The files contain actual original scores, structured fields, trade plans,
sanitizer/synthesis/model requests, and Discord/vault render output. All source
collection and model responses were synthetic. The strings labelled private bot
context are deliberate synthetic sentinels; no real conversations or credentials
are included. Member tests omit those fields and trap operational access.

Expected values must not be regenerated from the extracted implementation.
Original quirks are preserved, including the bearish and missing-price level
layouts. Equality proves fixed-input behavior, not investment correctness,
provider availability, source permissions, or score parity for different evidence.

The original capture did not exercise nonzero consolidation, accuracy weighting,
FINRA/PEAD score branches, smart-level flags, or every model retry. Existing
dependent tests and restricted-process branch tests cover those extraction seams.
