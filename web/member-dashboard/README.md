# Member interface

Isolated Next.js client for the existing `/api/v1` application. Deploy behind the same HTTPS origin as FastAPI. The reverse proxy routes `/api/v1` to the API; Next.js does not read databases, credentials or provider settings. All member content comes from independently authenticated, no-store API reads. Page shells are dynamic and contain no member data before client authentication. No service worker, analytics, external fonts or persistent browser content cache is used.

Node 24 and the exact lockfile are required. Scripts: `npm run dev`, `npm run build`, `npm start`, `npm run lint`, `npm run typecheck`, `npm run test:e2e`. `lint` invokes ESLint directly; official `@eslint/compat` adapts Next's current legacy plugin APIs without disabling rules.

## Synthetic browser proof

Build first (`npm run build`), then `npm run test:e2e`. Playwright starts the production build, a loopback-only Python API/worker fixture, and a loopback HTTPS proxy. It uses actual Secure cookies with an ephemeral self-signed certificate; Chromium accepts that certificate for these tests only. No certificate is installed in a machine trust store. All fixture accounts, source grants, data, settings and controls are synthetic and defined under `e2e/`. Those controls are never registered by the production app.

Set `MEMBER_TEST_PYTHON` to an absolute Python executable with locked web requirements. The fixture defaults to this task's documented private Python 3.12. Install Chromium into a task-local `PLAYWRIGHT_BROWSERS_PATH` with `playwright install chromium`; the controller's recorded commands use `.e2e/browsers`. `.e2e`, screenshots, traces, certificates, fixture databases, build output and dependencies are ignored. No real credentials or market database are needed. Test ports are localhost 3443 (HTTPS), 127.0.0.1:3444 (Next), and 127.0.0.1:3445 (API).

## Current boundaries

History, assistant conversations, administration and deployment composition are later tasks. Their working controls are intentionally absent. Terminal research stops two-second job polling and reads current access every 15 seconds while visible and on focus. Feed requests serialize opaque cursor pages and discard/reset on 409. Loss of access clears current payloads and image object URLs; this cannot retract information already seen by a member.

## Dependency audit

The recorded production-only audit has zero findings. Development dependencies currently report nine high entries, all from unpatched `braces <=3.0.3` via shadcn/Next ESLint tooling: [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). The registry has no patched release. No advisory is suppressed and no unsupported transitive override is applied. shadcn is a development-only CLI; its registry/glob tools and ESLint are never imported by `src/`. Member inputs only reach fixed API paths and strict DTO decoders, never CLI glob/config evaluation. Re-audit dependencies before launch.
