# Operations Runbook

Day-2 operational tasks: backups, restores, key rotation, monitoring.
For first-time install see [INSTALL.md](../INSTALL.md); for the full
production-launch checklist see
[docs/release-checklist.md](release-checklist.md).

---

## Backups

### Quick local backup

```bash
./scripts/backup.sh
```

- Output: `~/bookkeeper-backups/bookkeeper-YYYY-MM-DD-HHMM.sql.gz`
- Compression: gzip
- Retention: keeps the 30 most recent dumps; older ones are pruned
  automatically.

### Scheduled production backup

```cron
0 2 * * *  /opt/slowbooks/scripts/backup.sh
```

**Always encrypt** dumps before they leave the host:

```bash
gpg --encrypt --recipient your-key@example.com bookkeeper-2026-05-23.sql.gz
```

Store the encrypted copy somewhere physically separate from the
database server (S3, Backblaze B2, an offsite NAS — anywhere that isn't
the same machine). A backup you've never restored from isn't a backup;
test restore quarterly.

### Docker backups

When running under `docker compose`, backups land in a Docker volume
inside the container. To copy them out to your host:

```bash
docker compose cp slowbooks:/app/backups ./my-backups
```

To take a one-off backup from a running container:

```bash
docker compose exec slowbooks ./scripts/backup.sh
```

### Restore

Native:

```bash
gunzip -c bookkeeper-2026-05-23.sql.gz | psql -U bookkeeper bookkeeper
```

Docker:

```bash
docker compose exec -T postgres psql -U bookkeeper bookkeeper \
    < <(gunzip -c bookkeeper-2026-05-23.sql.gz)
```

`pg_dump` not found?
- Docker: included automatically; nothing to do.
- Native Linux: `sudo apt install postgresql-client`
- Native macOS: `brew install postgresql@17`

---

## Encryption key rotation

Bank PII (routing + account numbers) and the benefits ePHI columns
(carrier name, dependent identifiers, plan kind, coverage window) are
Fernet-encrypted with a versioned ciphertext prefix (`v1:`), supporting
zero-downtime rotation. The new key reads existing ciphertexts via the
PREV fallback while you rewrap.

### One-time rotation

```bash
# 1. Generate the new master key
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Set in env (do NOT remove the old key yet)
export PAYROLL_ENCRYPTION_SECRET="<new key>"
export PAYROLL_ENCRYPTION_SECRET_PREV="<old key>"

# 3. Restart the app — all reads work (new + prev tried in order),
#    all writes use the new key.

# 4. Rewrap existing rows under the new key (idempotent, safe to
#    re-run, supports --dry-run):
python -m app.services.encryption rewrap --dry-run
python -m app.services.encryption rewrap

# 5. Confirm nothing left on PREV, then unset PREV.
```

Master key files (`.slowbooks-master.key`, `.slowbooks-session.key`)
are excluded in `.gitignore` — never commit them. Losing the master
key means losing every encrypted secret in the database.

### Blind-index key rotation

Encrypted columns that still have to be queryable carry a second,
deterministic column — a blind index. It has its own key, so rotating
the encryption secret does **not** touch it, and vice versa:

```bash
export PAYROLL_BLIND_INDEX_SECRET="<new key>"
python -m app.services.blind_index reindex --dry-run
python -m app.services.blind_index reindex
```

There is no PREV fallback here on purpose. A blind index is derived
data — it can always be rebuilt from plaintext the app can still
decrypt — so recomputing everything is both simpler and correct.

Run this **before** the app serves traffic under the new key. Between
setting the key and finishing the reindex, queries that filter on an
index (the ACA 1095 derivation, which filters on plan kind) compute the
new hash and find the old one stored, so they return nothing. That
failure is quiet: an empty 1095 looks like "nobody had coverage".

`PAYROLL_BLIND_INDEX_SECRET` is optional — unset, the index key is
derived from `PAYROLL_ENCRYPTION_SECRET` with a separate salt. Setting
it explicitly is better: leaking the index key then only lets an
attacker test guesses, rather than sharing fate with the key that
decrypts everything. Note that rotating `PAYROLL_ENCRYPTION_SECRET`
while the index key is *derived* from it changes both, so run `reindex`
after `rewrap` in that case.

---

## Monitoring + audit

The app emits enough breadcrumbs to back-trace any change. Wire these
into your SIEM, or just `tail -f` them for small deployments:

- **`audit_log`** — every model insert/update/delete with
  old/new values. Source = `api`.
- **`login_attempts`** — every admin login attempt with IP +
  user-agent, success or failure.
- **`portal_accesses`** — every employee-portal hit (cookieless and
  authed), with the resolved employee_id when known.
- **`document_audits`** — a linked hash chain over every generated document (tax forms, SUI, COBRA notices, e-signature seals).
  A printed form's footer carries the hash + audit ID; an auditor can
  verify the document hasn't been edited. Because each row commits to
  its predecessor, deleting or reordering rows is detectable too:
  `GET /api/document-audits/chain/verify`.
- **`audit_checkpoints`** — signed pins of the chain tip, so tail
  truncation is detectable. See the next section — these need a key and
  a cron job to be worth anything.
- **`/health`** — unauthenticated liveness probe. Wire to your load
  balancer or k8s readiness probe.

---

## Audit checkpoints: signing + off-box copies

The hash chain over `document_audits` catches alteration, deletion and
reordering on its own. Two things it cannot do alone, and what to set up:

**1. Detect a truncated tail.** A shortened chain is still internally
valid. `audit_checkpoints` pins `(tip id, tip hash, row count)` at a
moment in time so anything removed past that point shows up.

**2. Survive someone deleting the checkpoints too.** An attacker with
database write access can delete checkpoint rows. Signing stops them
*forging* one; only an off-box copy stops them *erasing* the evidence.

### Set the signing key

```bash
# .env — NOT the same value as PAYROLL_ENCRYPTION_SECRET
AUDIT_CHECKPOINT_SIGNING_SECRET=$(openssl rand -base64 48)
AUDIT_CHECKPOINT_KEY_ID=ops-2026
```

There is no development default on purpose. Leave it unset and
checkpoints still work, but every verification reports
`signature.status: "unsigned"` and `ok: false` — a signature under a
well-known key would look like proof while providing none.

Keep the key somewhere the application host is not the only copy: a
password manager, an HSM, a sealed envelope. An auditor holding it can
verify an artifact without a SlowBooks install at all.

### Schedule the export

```cron
# Weekly checkpoint, artifact written to append-only storage
0 3 * * 0  cd /opt/slowbooks && python -m app.services.document_audit \
             checkpoint --note "weekly" \
             --export /mnt/worm/slowbooks/cp-$(date +\%Y-\%m-\%d).json
```

`/mnt/worm` should be genuinely append-only — object storage with object
lock, a WORM NAS share, or a second machine the app host cannot write
to. A "backup" on the same volume the database lives on buys nothing
here.

The command exits non-zero if the chain is broken, if there is nothing to
checkpoint, or if no signing key is configured, so a failing cron job is
a real signal.

### Verify a copy

```bash
python -m app.services.document_audit verify-artifact /mnt/worm/slowbooks/cp-2026-08-16.json
```

Exit 0 means the live chain still contains everything that artifact
attests to. Exit 1 prints why not. The interesting field is
`checkpoint_row_present`: `false` means the database's own copy is gone
and only this artifact still knows what used to be there.

Same thing over HTTP, if that suits the workflow better:

```
GET  /api/document-audits/chain/checkpoints/{id}/export      # download artifact
POST /api/document-audits/chain/checkpoints/verify-artifact  # POST it back
```

### Rotate the signing key

```bash
# 1. old key becomes PREV, new key becomes current
AUDIT_CHECKPOINT_SIGNING_SECRET_PREV=<old>
AUDIT_CHECKPOINT_SIGNING_SECRET=<new>
AUDIT_CHECKPOINT_KEY_ID=ops-2027
# 2. bounce the app — old checkpoints verify as `valid_previous_key`
# 3. re-sign them
python -m app.services.document_audit resign
# 4. drop AUDIT_CHECKPOINT_SIGNING_SECRET_PREV
```

`resign` will not back-sign a checkpoint that was never signed. Signing
one now would assert that the current key attested to that tuple at that
time, which nobody can know — and would launder a checkpoint an attacker
had inserted. Take a fresh checkpoint instead.

**What this does not cover.** The MAC is symmetric, so an attacker who
owns the application host holds the signing key and can sign anything.
The defence against that is the artifact already sitting on append-only
storage, not the signature. `docs/hipaa-compliance.md`
§ 164.312(c)(1) has the full attack table.

---

## Stopping, restarting, log rotation

### Docker

```bash
docker compose down              # stop (data persists in volumes)
docker compose up -d             # restart in background
docker compose down -v           # stop AND delete all data — destructive
docker compose logs -f slowbooks # tail
```

Docker handles log rotation via its log driver. Configure rotation
size + count in `docker-compose.yml` if needed:

```yaml
services:
  slowbooks:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

### Native (systemd)

If running under systemd, logs go to the journal. Rotate normally
via `journalctl` retention settings.

---

## Production launch checklist

Use [docs/release-checklist.md](release-checklist.md) when going live
the first time. It covers secrets, TLS termination, required env vars,
HIPAA / tax-form caveats, and a final pre-flight test.
