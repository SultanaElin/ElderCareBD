# Backend deployment safeguards

Install the bounded dependencies from `requirements.txt` and run the reviewed
prescription-foundation migration before starting code that uses the extended
prescription and medicine models.

The application rejects prescription upload requests larger than 8.5 MiB before
FastAPI parses their multipart form, buffers no more than that bounded request,
and separately limits decoded image input to 8 MiB and 25 megapixels. This
application check is defense in depth: the ASGI server still has to receive
network chunks, a client can omit or forge `Content-Length`, and the pre-parser
can validate only the shape of the Bearer header before downstream database-backed
authentication. A fake token can therefore force bounded network and memory work.
Production deployments must also configure a reverse proxy or gateway request-body
limit, request/header timeouts, connection limits, and rate limits. Keep the proxy
allowance at least large enough for the 8 MiB image plus multipart overhead, and
no larger than the application request limit.

`private_uploads/` must remain outside any static-file mount and should be backed
up with the authoritative database. Never expose its filesystem path as an API
contract.

## Task 14 assessment ML provenance migration

Before starting backend code that maps the Task 14 assessment ML fields, stop all
writers, resolve any SQLite WAL/journal sidecars, and make a byte-identical backup
of `eldercare_bd.db`. Run the additive migration with explicit paths:

```powershell
.\venv\Scripts\python.exe migrate_assessment_ml.py `
  --database eldercare_bd.db `
  --backup <verified-backup>
```

The command accepts only the authoritative basename, refuses
`eldercare_bd_2.db` (including aliases), verifies the backup and all existing
typed values, and leaves historical assessment provenance fields NULL. Retain
the verified backup named in the migration marker for future idempotent checks.

After the v1 marker is present, create a new byte-identical backup of that
post-v1/pre-DiaBD database and add the two DiaBD-v3 input-provenance fields:

```powershell
.\venv\Scripts\python.exe migrate_assessment_diabd.py `
  --database eldercare_bd.db `
  --backup <verified-post-v1-backup>
```

This second migration is also additive and idempotent. It adds only nullable
`diabetes_gender` and `diabetes_random_glucose_mmol_l`; assessment age, systolic
BP, diastolic BP, and BMI complete the immutable six-feature input record. The
legacy nullable `diabetes_ogtt_glucose` column is retained and is never populated
by DiaBD v3. The migration refuses `eldercare_bd_2.db`, verifies the backup and
pre-existing typed values, requires old assessment rows to remain NULL in the
new columns, and runs SQLite integrity and foreign-key checks.

The deployed model set is DiaBD diabetes v3 plus Cleveland Heart v2. Kidney
model integration was withheld because the audited dataset lacked defensible
target/provenance validity; no kidney prediction route or artifact is deployed.

## Task 15 caregiver OTP migration

Do not start OTP-capable backend code against an existing database until this
migration has been reviewed and applied. Stop all writers, resolve SQLite WAL or
journal sidecars, then make a byte-identical backup of the authoritative
`eldercare_bd.db` file. Run:

```powershell
.\venv\Scripts\python.exe migrate_caregiver_verification.py `
  --database eldercare_bd.db `
  --backup <verified-pre-task15-backup>
```

The migration marker is `task15_caregiver_otp_v1`. The migration refuses any
non-authoritative basename, `eldercare_bd_2.db` and aliases of it, non-identical
initial backups, SQLite sidecars, and partially applied OTP schemas. It preserves
all pre-existing columns and typed values, verifies the backup and secondary
database hashes, uses a single transaction, checks SQLite integrity and foreign
keys, verifies the committed database after reopening it, and makes a completed
rerun a byte-for-byte no-op.

The migration adds caregiver identity/verification columns, a unique normalized
identity index, and the `caregiver_verifications` challenge table with expiry,
attempt, resend, delivery, consumption, and invalidation state. Existing
caregivers are grandfathered as `verified` so historical accounts and sessions
are not locked out. Syntactically valid email identities are trimmed/lowercased;
strict E.164 phone identities are retained. Malformed or ambiguous historical
identities remain verified with a NULL normalized identity and channel so the
application can use an explicit exact-raw legacy-login fallback. Their original
identity value is not rewritten.

The authentication lifecycle is:

`registration -> pending caregiver -> OTP challenge -> provider delivery -> OTP
verification -> verified caregiver -> password login -> bearer session`.

OTP verification does not issue a bearer token. A verified caregiver must still
authenticate with the password. Challenges contain a salted HMAC-SHA256 verifier,
not the plaintext code. Codes are six cryptographically generated decimal digits,
expire after 10 minutes, allow at most five failed attempts, and are single-use.
Resends have a 60-second cooldown and are limited to five per rolling one-hour
challenge window; a successful resend invalidates the previous challenge.

New email identities are Unicode-normalized, trimmed, syntax-checked, and
lowercased without provider-specific dot or plus transformations. New phone
identities must already be strict E.164 values (for example `+8801XXXXXXXXX`);
the server never guesses a country code. API responses expose only a masked
destination. Pending duplicate registrations reuse the existing pending account,
verified duplicates are rejected, and a conflicting name is rejected.

### OTP environment variables

The repository contains no email/SMS credentials. Set a random secret of at least
32 characters in `ELDERCARE_OTP_HMAC_SECRET`; rotate it only with an explicit plan
for invalidating outstanding challenges. Set `ELDERCARE_ENVIRONMENT=production`
and `ELDERCARE_OTP_DELIVERY_MODE=smtp` for the included production email path.
Configure SMTP with:

- `ELDERCARE_SMTP_HOST` (required)
- `ELDERCARE_SMTP_PORT` (default `587`)
- `ELDERCARE_SMTP_FROM` (required)
- `ELDERCARE_SMTP_USERNAME` and `ELDERCARE_SMTP_PASSWORD` (both or neither)
- `ELDERCARE_SMTP_STARTTLS` (default `true`)
- `ELDERCARE_SMTP_SSL` (default `false`; cannot be combined with STARTTLS)
- `ELDERCARE_SMTP_TIMEOUT_SECONDS` (default `10`, allowed `1` through `60`)

For Gmail SMTP, first enable Google Account 2-Step Verification and create a
dedicated App Password for ElderCareBD. Never use the normal Google Account
password. Configure `smtp.gmail.com`, port `587`, STARTTLS enabled, SSL disabled,
and use the same Gmail address for `ELDERCARE_SMTP_FROM` and
`ELDERCARE_SMTP_USERNAME`. Keep the App Password only in the process environment
or a deployment secret manager; do not store it in `.env.example`, source code,
logs, screenshots, or the APK. Google may not offer App Passwords for some
managed, security-key-only, or Advanced Protection accounts.

The included SMS provider is intentionally a fail-closed adapter because no SMS
vendor or credentials were supplied. The channel provider interface is the
extension point for a real vendor adapter; production SMS registration returns a
sanitized delivery-unavailable response until such an adapter is configured.
Do not claim or enable production SMS delivery without that adapter and its
environment-only credentials.

For automated tests or explicit local development only, set
`ELDERCARE_ENVIRONMENT=test` (or `development`) and
`ELDERCARE_OTP_DELIVERY_MODE=capture`. The capture provider keeps codes only in
the current process for test assertions. Production startup rejects `capture`
and `disabled` modes and rejects missing OTP/SMTP configuration. There is no API
endpoint that exposes captured codes.

### Physical Android local-demo startup

For a trusted-LAN physical-device demo, the repository includes an explicit
terminal-only launcher. It never enables capture mode without the
`--capture-otp` acknowledgement, refuses an existing production environment,
and generates a process-local random HMAC secret only when a valid secret was
not already supplied:

```powershell
cd backend
.\venv\Scripts\python.exe run_local_demo.py --capture-otp `
  --host 0.0.0.0 --port 8000
```

After registration is submitted from the phone, type `otp` at the
`eldercare-demo>` prompt to reveal only the newest in-memory development code.
Type `status` to inspect the delivery count without revealing a code and `quit`
to stop the server. The code is not returned by an API, persisted, or exposed by
an HTTP endpoint. Protect the laptop console from screen sharing and logs. An
ephemeral generated secret changes on restart, so outstanding demo challenges
from the previous process cannot be verified after a restart.

The standard production command remains:

```powershell
.\venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000
```

It uses the explicit production SMTP configuration above and remains fail
closed when SMTP is missing or capture/disabled mode is selected.

Never log, return, or persist plaintext OTPs, passwords, password hashes, or full
destinations unnecessarily. SMTP and SMS provider logs must follow the same rule.
The current controls are challenge/account scoped; deployment-level IP/device
rate limiting, distributed throttling, provider failover, and delivery monitoring
remain production infrastructure responsibilities. Returning a resumable pending
state and distinct duplicate-verified response has a limited account-enumeration
trade-off required by the current UX.

On initial provider failure the registration transaction is rolled back, so no
orphan pending caregiver is retained. On resend delivery failure the previous
active challenge remains usable. Abandoned pending registrations remain stored;
an operational retention/cleanup job is not included in this task.

The authoritative database migration is a separate controlled deployment action;
the migration test suite operates only on disposable temporary databases.
