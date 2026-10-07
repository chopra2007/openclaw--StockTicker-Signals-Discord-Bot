# Builder brief: "polish" — Sign in, Assistant, History

Read `todo/member-dashboard-design-build-common.md` first, then `todo/member-dashboard-design-review.md`.
You own problems P1-P3 and P22-P26.

## Files you own
Web: `src/components/auth-form.tsx`, `chat.tsx`, `assistant-panel.tsx`, `history-list.tsx`, `src/app/login`,
`src/app/assistant`, `src/app/history` pages, sign-in/assistant/history CSS in `globals.css`, and the `.brand-mark`
CSS rule (draw a simple mark with CSS or an inline SVG data URI in that rule only; you may NOT edit `app-shell.tsx`,
another builder owns it).
Backend (only if History needs it): `member_dashboard/history.py`, `member_dashboard/routes/history.py`,
`tests/member_dashboard/test_history.py`.

## Fixes
- P1 brand mark: a real mark (e.g. a rising line / edge shape in white on the blue rounded square), same in light/dark.
- P2 phone sign-in: no card inside the page below 600 px wide; the form sits on the page background, full width,
  big title, like an iOS sign-in screen. Desktop keeps the card.
- P3 footer: "Need an invite or a password reset? Ask the person who invited you." (plain, human).
- P22 phone assistant: no card around the chat below 600 px; chat uses the full width; hide the "‹ Chats" back link
  when the chat is empty and has no history to go back to (or make it a clear "All chats" button at the top).
- P23 desktop recent chats: two-line rows (title wraps to 2 lines max) with a small date ("Oct 6").
- P24 history rows: each report row shows ticker, the signal (Bullish / Bearish / Neutral pill), the price at the
  time if stored, and the time; group repeated reports of the same ticker on the same day under one row with a
  count ("NVDA · 7 reports today") that expands. If the list endpoint doesn't return direction/price, add them in
  `history.py` from the stored analysis payload (keep it cheap: no extra provider calls) and test it.
- P25 delete: if deleting is supported by the API, show a Delete action on the opened report/chat (with a confirm);
  if not, remove the footer sentence about deleting.
- P26 desktop history detail: the empty detail pane becomes a proper empty state that fills the column height
  ("Pick a report to read it here.") and the opened report fills it.
