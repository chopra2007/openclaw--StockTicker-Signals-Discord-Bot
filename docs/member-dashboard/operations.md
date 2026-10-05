# Member dashboard account operations

The API and worker use only the dashboard database. These commands never send invitations or Discord messages. Deployments and production accounts are outside the development task.

## Host authorization

Local account management is supported on Linux. Windows management fails closed; run synthetic auth tests on Windows and prove terminal recovery in the isolated Linux staging sandbox before launch.

A host administrator provisions `/etc/member-dashboard/recovery.json`. The directory and file must be owned by root. Neither may be writable by group or others. Recommended modes are directory `0700` and file `0600`. The service account must not have permission to change this file or directory. Run recovery from an authorized host operator's interactive terminal, using elevated access if the file permissions require it.

The file has exactly these fields:

```json
{
  "allowed_uids": [0],
  "service_uid": 65534,
  "web_path": "/srv/member-dashboard/private/web.sqlite3"
}
```

These are synthetic examples. Set the actual service UID and dashboard database path during authorized deployment. Do not allow the web service UID as an operator: the boundary explicitly denies it even if listed. Use a distinct service account, protect the application code from service-account writes, and keep the operator terminal outside the service's execution environment. Root owns the grant; browser roles, an environment variable, a CLI flag and a caller-supplied name cannot confer host authorization. There is no HTTP recovery or bootstrap endpoint.

The command verifies the actual effective OS UID and the protected grant inside the authentication service, including a second check after password hashing. It refuses noninteractive input, unknown targets and non-admin targets. The path comes exclusively from the host grant; the CLI does not create or migrate databases.

## Initial administrator

After initializing the web schema in the dedicated deployment process, run:

```bash
python -m member_dashboard.manage create-admin --username synthetic_admin
```

Enter a password twice at hidden prompts. Passwords must contain 15 to 128 characters; never place a password in a command line, environment variable or pipe. Creation aborts if any administrator already exists. Invitations always create ordinary members.

## Recovering an existing administrator

From a host-authorized interactive terminal:

```bash
python -m member_dashboard.manage recover-admin --username synthetic_admin
```

Recovery requires no browser session. It changes the existing administrator's password, removes all sessions, revokes unused reset tokens, increments the account authorization version and records one recovery event with the verified OS identity. These updates commit together or all roll back. Recovery preserves suspension and role; it never creates an account, promotes a member, reactivates an account or creates a session. Log in normally afterward.

## Session and request checks

Sessions use Secure, HttpOnly, SameSite=Lax host cookies with a 12-hour absolute lifetime and two-hour idle lifetime. Every API guard re-reads the account and session. Reset and recovery invalidate existing and pending private-delivery authority; workers must call `AuthService.revalidate(principal, now, con=completion_transaction)` immediately before attaching or delivering private output. Session deletion, suspension, authorization-version changes and expiry deny delivery.

Unsafe HTTP requests require the exact configured HTTPS Origin and an `X-CSRF-Token` obtained from `/api/v1/auth/csrf`. Anonymous forms receive a bounded server-side challenge valid for 15 minutes; restart discards anonymous challenges. Authenticated CSRF retrieval rotates the session token, so an older form may need to retrieve it again. Multiple API processes require an explicitly shared anonymous challenge store before deployment. CORS is disabled. Configure trusted proxy forwarding only at the server boundary; arbitrary `X-Forwarded-For` headers are ignored by the app.

One-time links must use browser fragments and be stripped before submission; the frontend task implements this flow. The backend stores only SHA-256 token digests and Argon2id password hashes. Do not log auth bodies, cookies or fragment tokens. Start the API server with access logging disabled (`--no-access-log` for Uvicorn), and configure the reverse proxy to omit auth query strings and request bodies. The deployment task must verify those settings before launch. Error responses contain no account-existence details. Private responses use `private, no-store` and `no-referrer`.

Authentication throttles use digests of normalized usernames and trusted client addresses, a five-attempt username limit and 50-attempt address limit per 15 minutes, and a short bounded failure backoff. Argon2 hashing/verification admits at most two operations per process. Deployment staging must measure the fixed Argon2id parameters (64 MiB, three passes, one lane) on the actual host and verify the intended 100-250 ms range before launch.
