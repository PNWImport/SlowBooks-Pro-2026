# Kubernetes deployment

Plain manifests, applied with `kubectl apply -k`. No Helm — there is one
deployment shape here and a chart would add indirection without adding
choice. If you need per-environment variance, layer kustomize overlays on
top of this base.

`tests/test_k8s_manifests.py` checks these files for internal consistency
(replica count vs volume access mode, probe paths vs the auth-exempt list,
image parity between the app and the migrate Job, no committed secrets).
Several of the constraints described below are asserted there, so if you
change one deliberately the test tells you which assumption you just broke.

---

## What you get

| File | Purpose |
|------|---------|
| `namespace.yaml` | The `slowbooks` namespace |
| `configmap.yaml` | Non-secret config — workers, proxy trust, rate-limit storage |
| `secret.example.yaml` | Template. **Never commit a filled-in copy** |
| `pvc.yaml` | Uploads + backups volumes |
| `postgres.yaml` | StatefulSet + headless Service (delete if you use a managed DB) |
| `redis.yaml` | Shared rate-limit counters |
| `migrate-job.yaml` | `alembic upgrade head` + seed, once per deploy |
| `deployment.yaml` | The app |
| `service.yaml` | ClusterIP |
| `ingress.yaml` | TLS termination + routing (ingress-nginx) |

---

## Deploy

**1. Build and push the image.** The manifests reference `slowbooks:latest`;
point them at your registry via `images:` in `kustomization.yaml`.

```bash
docker build -t your-registry/slowbooks:v1 .
docker push your-registry/slowbooks:v1
```

**2. Create the namespace and the Secret.** Out of band, so no filled-in
copy touches git:

```bash
kubectl create namespace slowbooks

kubectl create secret generic slowbooks-secrets -n slowbooks \
  --from-literal=PAYROLL_ENCRYPTION_SECRET="$(openssl rand -base64 32)" \
  --from-literal=SESSION_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -base64 24)" \
  --from-literal=DATABASE_URL="postgresql://bookkeeper:THAT_PASSWORD@slowbooks-postgres:5432/slowbooks?sslmode=require" \
  --from-literal=EMPLOYER_EIN=""
```

> **Back up `PAYROLL_ENCRYPTION_SECRET` somewhere that is not this cluster.**
> It decrypts employee bank PII and the benefits ePHI. Lose it and you lose
> that data — there is no recovery path.

**3. Set the two values that depend on your cluster**, in `configmap.yaml`:

- `FORWARDED_ALLOW_IPS` — your ingress controller's pod CIDR
  (`kubectl get pods -n ingress-nginx -o wide`). Get this wrong and every
  request is attributed to the ingress: the login rate limiter degrades to
  one shared bucket for all users, and `login_attempts` / `portal_accesses`
  record the ingress address instead of the caller's. Never `0.0.0.0/0` —
  that lets any client forge its own source IP.
- `CORS_ALLOW_ORIGINS` — your real origin.

Also set the host in `ingress.yaml`.

**4. Apply, then wait for the migration.**

```bash
kubectl apply -k k8s/
kubectl wait --for=condition=complete job/slowbooks-migrate -n slowbooks --timeout=300s
kubectl rollout status deploy/slowbooks -n slowbooks
```

**5. First run.** The app has no users until you create one — open the URL
and the SPA prompts for initial setup (`POST /api/auth/setup`, which
refuses a second call).

---

## Upgrades

A Job's pod template is immutable, so delete it before re-applying:

```bash
kubectl delete job slowbooks-migrate -n slowbooks --ignore-not-found
kubectl apply -k k8s/
kubectl wait --for=condition=complete job/slowbooks-migrate -n slowbooks --timeout=300s
```

Migrations run **before** the new pods serve traffic. With `Recreate` there
is a brief gap where nothing serves — correct for a single-replica
deployment, and it avoids two pods disagreeing about the schema.

---

## Scaling past one replica

`replicas: 1` is not arbitrary. Two things pin it:

1. **Uploads and backups are on ReadWriteOnce volumes.** A second pod cannot
   mount them and sits `Pending` on volume attach.
2. **`Recreate` strategy**, which follows from the same constraint.

To scale out:

```yaml
# pvc.yaml — both claims
accessModes: ["ReadWriteMany"]     # needs EFS, Azure Files, CephFS, or NFS

# deployment.yaml
replicas: 3
strategy:
  type: RollingUpdate
```

Nothing else changes. Sessions are signed cookies, so no sticky routing is
needed, and rate-limit counters already live in Redis. `test_k8s_manifests.py`
enforces the replicas/access-mode pairing, so a half-done change fails loudly
rather than at 3am.

---

## Managed Postgres

`postgres.yaml` is a convenience, not a recommendation — it has no automated
backup, no failover, and no point-in-time restore. If you have RDS, Cloud SQL,
or Azure Database:

1. Delete `postgres.yaml` and drop it from `kustomization.yaml`.
2. Point `DATABASE_URL` in the Secret at the managed instance.

Keep `sslmode=require` in the URL — the app's startup checks refuse to boot
in production without TLS on the database connection.

---

## What this does not cover

- **NetworkPolicies.** Nothing restricts pod-to-pod traffic. Postgres and
  Redis are reachable from anything in the namespace.
- **PodDisruptionBudget / HPA.** Both are meaningless at one replica; add
  them alongside the RWX switch.
- **Backups.** `backups/` is a volume, not a backup strategy — nothing
  copies it off-cluster. See `docs/operations.md`.
- **Secret management.** These are plain Kubernetes Secrets, which are
  base64 in etcd, not encrypted. Use Sealed Secrets, External Secrets, or
  your cloud's secret store for anything real.
