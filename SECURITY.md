# Security

This document records the security model of Bookmark Resurfacer, the findings
of the audit performed on the initial implementation, and the operational
requirements for running it safely.

## Threat model

The app is a small self-hosted service that stores URLs and **outbound SMTP
credentials** on behalf of one or more users. The assets worth protecting, in
order:

1. **Stored SMTP credentials.** They are reusable and often belong to a real
   mailbox. Disclosure lets an attacker send mail as the user.
2. **Session integrity.** A forged or stolen session grants full access to (1).
3. **Bookmark contents.** Private browsing data.
4. **Outbound mail capacity.** The scheduler and `/api/send-test` can be abused
   to send mail through the user's SMTP account.

Assumed *out of scope*: a hostile identity provider, a hostile host operator,
and physical access to the machine.

## Security model

| Area | Design |
|---|---|
| Authentication | Void Auth SSO (OAuth 2.0 authorization code + PKCE S256). Optional `ALLOWED_EMAILS` allowlist gates account creation. |
| Sessions | Stateless signed cookie (`br_session`), `HttpOnly`, `SameSite=Lax`, `Secure` when `COOKIE_SECURE`/production. Signed with `SESSION_SECRET`. |
| Authorization | Every query filters on `user_id`; there is no cross-user read path and no admin role. |
| CSRF | Per-session token required on every unsafe method, via `csrf_token` form field or `X-CSRF-Token` header. |
| Output encoding | Jinja2 autoescaping for HTML; explicit `html.escape` for email bodies. |
| Transport | The app speaks plain HTTP; **run it behind a TLS-terminating reverse proxy.** `VOID_AUTH_DOMAIN` is required to be `https`. |
| Secrets at rest | `SESSION_SECRET` from the environment. SMTP passwords are stored **unencrypted** in SQLite (see Known limitations). |

## Audit findings and remediation

### Critical

**C1 — `.env` was never loaded, so all documented configuration was ignored.**
Nothing called `load_dotenv()` and `docker-compose.yml` had no `env_file:`.
Every `os.getenv` call therefore fell through to its default: `SESSION_SECRET`
was always the literal `change-me-in-production` and `VOID_AUTH_CLIENT_ID` was
always empty, meaning **the app always ran with authentication disabled**, no
matter what the `.env` file said.
*Fixed:* all configuration moved into `app/config.py`, which loads
`.env` explicitly (real environment variables still take precedence);
`env_file: .env` added to `docker-compose.yml`.

**C2 — Forgeable sessions from a known signing key.**
With a default/short `SESSION_SECRET`, anyone can mint a valid `br_session`
cookie containing `{"user": {"id": "<victim>"}}` and take over any account.
*Fixed:* `app/config.py` refuses to start when the secret is missing, shorter
than 32 characters, or a known placeholder, in production *or* whenever SSO is
enabled. In development it falls back to a random ephemeral secret and warns.

**C3 — No CSRF protection, and a destructive `GET` endpoint.**
No mutating endpoint checked a token, and `GET /bookmarks/{id}/delete` deleted
data — reachable via cross-site navigation, link prefetching or a crawler.
*Fixed:* `verify_csrf` (`app/security.py`) is a dependency on every mutating
route; delete is now `POST /bookmarks/{id}/delete`; logout is `POST`;
redirect-after-POST uses `303`.

### High

**H1 — HTML injection into outgoing email.**
`build_email_body` interpolated `url`, `title`, `description`, `tags` and
`email_subject` into HTML with no escaping, and put `url` straight into an
`href`. Bookmark fields are attacker-supplied via the API, so this allowed
arbitrary HTML — and `javascript:`/`data:` links — in the recipient's mailbox.
*Fixed:* every value is `html.escape`d; link targets are rendered only when the
scheme is `http`/`https`, otherwise the title is emitted as inert text.

**H2 — SMTP header injection.**
`email_from`, `email_to` and `email_subject` were written directly to MIME
headers, so a CR/LF in a user-controlled value could inject extra headers
(e.g. `Bcc:`) and silently add recipients.
*Fixed:* `sanitize_header()` strips CR/LF/NUL and length-caps every value bound
for a header; addresses must match a single-address pattern.

**H3 — SMTP password disclosure.**
`GET /api/settings` returned the stored password verbatim, and `/settings`
rendered it into the HTML source of the page (a `type="password"` input hides it
visually only). Any XSS, cached page, proxy log or shoulder-surf leaked it.
*Fixed:* `get_settings_public()` never emits secrets; it returns
`smtp_password_set: bool` instead. The form field is always blank, blank means
"keep the stored value", and an explicit checkbox clears it.

**H4 — OAuth flow weaknesses.**
No PKCE, no `https` requirement on `VOID_AUTH_DOMAIN`, no HTTP timeouts, and
all provider errors silently swallowed.
*Fixed:* PKCE S256 is always sent and the verifier is popped from the session on
callback; `VOID_AUTH_DOMAIN` must be `https`; a 10s/5s timeout is applied;
failures are logged by exception type without echoing provider responses.

**H5 — Open redirect / Host-header trust.**
The post-login redirect stored `str(request.url)` — an absolute URL derived from
the client-supplied `Host` header — and no trusted-host check existed.
*Fixed:* `safe_relative_path()` reduces the target to a same-origin path;
`TrustedHostMiddleware` is enabled whenever `ALLOWED_HOSTS` is not `*`.

### Medium

| ID | Finding | Remediation |
|---|---|---|
| M1 | Session cookie had no `Secure` flag and a 30-day lifetime with no rotation. | `https_only` follows `COOKIE_SECURE` (default on in production); lifetime cut to 7 days and configurable; CSRF token rotated on login. |
| M2 | No security response headers. | CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cross-Origin-Opener-Policy`, `Permissions-Policy`, and HSTS when HTTPS. |
| M3 | Inline `<script>` and `onclick=` handlers made a strict CSP impossible. | JS moved to `static/bookmarks.js` and `static/settings.js`; show/hide uses the `hidden` attribute, so `script-src 'self'` and `style-src 'self'` hold. |
| M4 | `javascript:` URIs accepted and rendered as clickable links. | `validate_url()` on every write; `is_safe_url()` guards rendering of pre-existing rows. |
| M5 | Raw SMTP exception text returned to the browser. | Specific, non-revealing messages returned; full detail logged server-side. |
| M6 | No rate limiting; `/api/send-test` was an unbounded mail trigger. | `RateLimiter` on `/api/send-test` (per user) and on login (per IP). |
| M7 | `/docs`, `/redoc`, `/openapi.json` exposed unauthenticated. | Disabled unless `EXPOSE_DOCS=true`; default on only in development. |
| M8 | No length or range validation; unbounded description growth; `smtp_port`, `links_per_email`, `schedule_interval_hours` unchecked. | Bounds in `app/schemas.py`, clamping in `settings_service._normalize`, `maxlength` in templates, pagination on `GET /api/bookmarks`. |
| M9 | Container ran as root; DB with plaintext credentials was world-readable. | Non-root `USER app`, `cap_drop: ALL`, `no-new-privileges`, `read_only` rootfs; `data/` is `chmod 700` and the DB file `chmod 600`. |
| M10 | OAuth `code` written to access logs via the query string. | `QueryRedactionFilter` redacts `code`, `state` and token parameters from `uvicorn.access`. |
| M11 | Unpinned `>=` dependencies; `pydantic-settings` declared but unused. | Upper bounds added, vulnerable floors raised (`jinja2>=3.1.4`, `python-multipart>=0.0.18`), unused dependency removed. |
| M12 | `smtp_use_tls` form default of `True` meant an unchecked box still enabled TLS. | Corrected to `Form(False)`, with a warning in the UI that disabling TLS sends credentials in cleartext. |

### Low / hardening

- `LIKE` wildcards in the search term are now escaped, and the term is length-capped.
- The scheduler clamps intervals to 1–8760 hours and uses `max_instances=1` so
  jobs cannot overlap into a mail flood.
- Scheduled sends are registered as coroutines instead of bare
  `asyncio.create_task`, which could be garbage-collected mid-flight.
- Recipient addresses are no longer written to application logs.
- `uvicorn` in `__main__` binds `127.0.0.1` instead of `0.0.0.0`.
- The published compose port is `127.0.0.1:8000` instead of all interfaces.
- Extra JSON fields are rejected (`extra="forbid"`) instead of ignored.

## Known limitations

- **SMTP passwords are stored unencrypted.** They must be recoverable to
  authenticate to the SMTP server, and there is no key-management story here, so
  the mitigation is filesystem permissions (`data/` 0700, DB 0600) rather than
  encryption. Treat `data/bookmarks.db` as a secret: back it up encrypted, and
  prefer a provider-issued app password with send-only scope over a primary
  account password.
- **Sessions cannot be revoked.** They are stateless signed cookies, so a
  stolen cookie is valid until it expires. Keep `SESSION_MAX_AGE_SECONDS` short;
  rotating `SESSION_SECRET` invalidates all sessions immediately.
- **Rate limits are per process and in memory.** They reset on restart and do
  not coordinate across workers. Enforce real limits at the reverse proxy.
- **No audit log** of logins or settings changes.
- **No ID-token signature validation.** Identity is taken from the userinfo
  endpoint reached over TLS with a freshly obtained access token. Validating the
  `id_token` signature against the provider's JWKS would be stronger.
- **`ENVIRONMENT=development` with SSO disabled has no authentication at all.**
  Everyone shares one account. Only ever bind this to localhost.

## Deployment checklist

- [ ] `cp .env.example .env`, then `chmod 600 .env`.
- [ ] `SESSION_SECRET=$(openssl rand -hex 32)` — unique per deployment.
- [ ] `ENVIRONMENT=production`.
- [ ] `ALLOWED_HOSTS` set to your real hostname(s), not `*`.
- [ ] Void Auth configured (`https` domain and `https` redirect URI), otherwise
      the app is unauthenticated.
- [ ] `ALLOWED_EMAILS` set if your identity provider has more users than should
      have access here.
- [ ] TLS-terminating reverse proxy in front; `COOKIE_SECURE=true`.
- [ ] `EXPOSE_DOCS` left blank/false.
- [ ] `./data` owned by the container user (`APP_UID`/`APP_GID`) and `chmod 700`.
- [ ] Reverse-proxy request-size and rate limits configured.
- [ ] Rebuild regularly for base-image and dependency patches.

## Reporting a vulnerability

Open a private security advisory on the repository rather than a public issue.
