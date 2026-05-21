# Frontend ↔ Backend Wiring Audit

The SPA lives in `app/static/js/*.js` and talks to FastAPI handlers in
`app/routes/*.py`. Each new tier we ship adds JS callers and Python
handlers in parallel, which is exactly the situation where the two sides
drift apart silently. This document records the audit methodology and
every disconnect we've found and fixed.

---

## Methodology — spider-web from both ends

Two grep passes, then cross-reference.

### From the SPA outward

```bash
# Calls that go through the centralized wrapper (auto-prefixed with /api):
grep -rEn "API\.(get|post|put|del)\s*\(" app/static/js/*.js

# Raw fetch() for file uploads and auth (URLs are absolute):
grep -rEn "fetch\s*\(" app/static/js/*.js index.html | grep -v "api\.js"
```

`app/static/js/api.js` exposes `API.get`, `API.post`, `API.put`, **`API.del`**
(not `API.delete`). Every call prepends `/api`, so `API.get('/employees')`
hits `/api/employees`. Raw `fetch()` URLs are absolute — `/api/...` is
already on the string.

### From the routers inward

```bash
# Find each router's prefix, then every decorator:
grep -n "APIRouter(" app/routes/*.py
grep -n "@router\." app/routes/*.py
```

Combine the prefix from `APIRouter(prefix="/api/foo", ...)` with the path
in each `@router.get("...")` to get the full URL.

### Cross-reference

Match by method + path. Path parameters match by position
(`/employees/{id}` matches `/employees/123`). Required query params should
also line up. Method matters: `POST /foo/approve` is not the same as
`PUT /foo/approve`.

---

## Findings — round 1 (the disconnects we fixed)

Four real breakages, all caught by `claude/payroll-system-roadmap-ZrfRj`.

### 1. `API.delete()` doesn't exist — three callers used the typo

| File | Line | Symptom |
|------|------|---------|
| `app/static/js/employees.js` | 367 | Delete bank account button throws `API.delete is not a function` |
| `app/static/js/employees.js` | 456 | Delete document button throws `API.delete is not a function` |
| `app/static/js/deductions.js` | 314 | Remove deduction button throws `API.delete is not a function` |

`api.js` exports `API.del` (line 52), matching the rest of the codebase.
**Fix:** rename all three callers to `API.del`.

### 2. `GET /api/pto/policies/{id}` was missing

`pto.js:97` loads a single policy for the edit form:
```js
if (id) p = await API.get(`/pto/policies/${id}`);
```
The backend had `GET /policies` (list) and `POST /policies` (create) but
no get-by-id and no update.

**Fix:** added `GET /policies/{policy_id}` (returns 404 when missing) and
`PUT /policies/{policy_id}` (uses the same `PTOPolicyCreate` schema for
the update payload, since the SPA submits the same fields on edit and
create).

### 3. PTO approve / reject hit non-existent routes

`pto.js:200` and `:208` fire `POST /pto/requests/{id}/approve` and
`/reject`. The backend exposed only the canonical
`POST /pto/requests/{id}/decision` with a `{status, approver_id}` payload.

**Fix:** added thin alias routes that forward into `decide_request()`
with a fixed status. The accrual draw-down logic stays in one place.

```python
@router.post("/requests/{request_id}/approve", ...)
def approve_request(request_id, db):
    return decide_request(request_id, PTORequestDecision(status="approved"), db)
```

### 4. Tax form JSON-vs-PDF mismatch (not a wiring fix — a known UX gap)

`tax_forms.js` opens the response as a `blob:` URL expecting a PDF, but
the backend currently returns JSON. The HTTP wiring is correct (every
URL hits a real handler), the response format is just a placeholder
until WeasyPrint templates are wired up. Tracked in
[payroll-hr-module.md](payroll-hr-module.md) under "Pending items."

---

## Tests that lock the wiring in place

Every fix has at least one test in `tests/test_tier3.py`:

```
test_pto_policy_get_by_id_endpoint_exists       # fix #2
test_pto_policy_put_endpoint_updates            # fix #2
test_pto_request_approve_alias_decisions_request  # fix #3
test_pto_request_reject_alias_decisions_request   # fix #3
```

The `API.delete()` → `API.del()` typos can't be unit-tested cheaply
(would need a Playwright/Selenium harness), so the protection there is
"the grep query above will surface any new instance in seconds."

---

## Re-running the audit later

```bash
# 1. Enumerate every SPA call:
grep -rEn "API\.(get|post|put|del)\s*\(" app/static/js/*.js \
    | sed -E "s|.*API\.(get|post|put|del)\(\`?'?([^'\`,)]+).*|\1 \2|" \
    | sort -u > /tmp/spa-calls.txt

# 2. Enumerate every handler (path + method):
python -c "
from app.main import app
for r in app.routes:
    if hasattr(r, 'methods'):
        for m in r.methods:
            print(f'{m.lower()} {r.path}')
" | sort -u > /tmp/handlers.txt

# 3. Diff. Anything in spa-calls.txt that doesn't resolve to a handler
#    is a candidate disconnect.
comm -23 /tmp/spa-calls.txt /tmp/handlers.txt
```

That third command is fuzzy because of path parameters, but it's a
good first-pass filter. The audit subagent in the conversation log walks
through the careful version.

---

## Orphan handlers that are intentional

These have no SPA caller and that's by design — they're either
employee-facing portals (token-accessed directly), batch utilities, or
webhooks:

| Handler | Why no SPA caller |
|---------|-------------------|
| `GET /portal/{token}*` and all sub-routes | Employees navigate directly via emailed link |
| `POST /api/stripe/webhook` | Stripe POSTs here; signed, not session-authed |
| `POST /api/deductions/types/seed-standard` | One-shot seed, not exposed in UI |
| `POST /api/pto/accruals/{id}/accrue` | Future batch flow (per-pay-period accrual run) |
| `POST /api/payroll/gross-up` | Future "what gross pays this net?" feature |

Anything else without a caller is suspect and worth investigating.
