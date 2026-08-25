"""Structural checks on the Kubernetes manifests in k8s/.

No cluster is involved. These catch the class of mistake that YAML
validity does not: a manifest that parses perfectly and still deploys a
broken or insecure app — app pods racing migrations, a replica count the
storage cannot support, probes pointed at an authenticated path, or a
real secret committed to the repo.

Several assertions here encode a constraint the manifests document in
comments. If you deliberately change one (e.g. moving to ReadWriteMany
and scaling up), update the paired assertion — that is the point.
"""

from pathlib import Path

import pytest
import yaml

K8S = Path(__file__).resolve().parents[1] / "k8s"


def _load(name: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((K8S / name).read_text()) if d]


def _one(name: str, kind: str) -> dict:
    docs = [d for d in _load(name) if d.get("kind") == kind]
    assert len(docs) == 1, f"expected exactly one {kind} in {name}"
    return docs[0]


def _app_container() -> dict:
    dep = _one("deployment.yaml", "Deployment")
    return dep["spec"]["template"]["spec"]["containers"][0]


def test_every_manifest_parses_and_is_namespaced():
    """A manifest without a namespace lands in `default` when applied
    directly rather than through kustomize."""
    for path in sorted(K8S.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for doc in [d for d in yaml.safe_load_all(path.read_text()) if d]:
            if doc["kind"] == "Namespace":
                continue
            assert (
                doc["metadata"].get("namespace") == "slowbooks"
            ), f"{path.name}: {doc['kind']} is not namespaced"


def test_app_pods_do_not_run_migrations():
    """Every replica running `alembic upgrade head` on rollout means they
    contend for the version row. The migrate Job owns schema changes."""
    cfg = _one("configmap.yaml", "ConfigMap")["data"]
    assert cfg["RUN_MIGRATIONS"] == "0"
    assert _one("migrate-job.yaml", "Job")


def test_migrate_job_runs_migrations_and_seed():
    job = _one("migrate-job.yaml", "Job")
    args = " ".join(job["spec"]["template"]["spec"]["containers"][0]["args"])
    assert "alembic upgrade head" in args
    assert "seed_database.py" in args


def test_replicas_match_volume_access_mode():
    """ReadWriteOnce volumes cannot be mounted by a second pod. If someone
    raises replicas without switching to ReadWriteMany, the new pods sit
    Pending forever on volume attach."""
    dep = _one("deployment.yaml", "Deployment")
    replicas = dep["spec"]["replicas"]
    modes = {mode for pvc in _load("pvc.yaml") for mode in pvc["spec"]["accessModes"]}
    if "ReadWriteMany" not in modes:
        assert replicas == 1, (
            f"replicas={replicas} but uploads/backups PVCs are {sorted(modes)}. "
            "Switch pvc.yaml to ReadWriteMany before scaling out."
        )


def test_rollout_strategy_is_safe_for_rwo():
    """RollingUpdate on a single RWO volume blocks: the new pod cannot
    attach until the old one releases it."""
    dep = _one("deployment.yaml", "Deployment")
    modes = {m for pvc in _load("pvc.yaml") for m in pvc["spec"]["accessModes"]}
    if "ReadWriteMany" not in modes:
        assert dep["spec"]["strategy"]["type"] == "Recreate"


def test_probes_target_an_auth_exempt_path():
    """Probes carry no session. A probe on an authenticated path gets 401
    and the pod never becomes ready."""
    main_py = (K8S.parent / "app" / "main.py").read_text()
    container = _app_container()
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert probe in container, f"{probe} missing"
        path = container[probe]["httpGet"]["path"]
        assert (
            f'"{path}"' in main_py
        ), f"{probe} hits {path}, which is not in main.py's auth-exempt list"


def test_rate_limit_counters_are_shared():
    """In-process counters multiply every limit by the replica count."""
    cfg = _one("configmap.yaml", "ConfigMap")["data"]
    assert cfg.get("RATE_LIMIT_STORAGE_URI", "").startswith("redis://")


def test_proxy_trust_is_configured():
    """Behind an ingress, unset FORWARDED_ALLOW_IPS makes every request
    look like it came from the ingress controller."""
    cfg = _one("configmap.yaml", "ConfigMap")["data"]
    trust = cfg.get("FORWARDED_ALLOW_IPS", "")
    assert trust, "FORWARDED_ALLOW_IPS must be set when behind an ingress"
    assert trust != "0.0.0.0/0", "0.0.0.0/0 lets any client forge its source IP"


def test_one_worker_per_pod():
    """Scale with replicas. Multi-worker pods split the rate-limit
    counters again and muddy CPU requests."""
    cfg = _one("configmap.yaml", "ConfigMap")["data"]
    assert cfg["APP_WORKERS"] == "1"


def test_production_gates_are_on():
    cfg = _one("configmap.yaml", "ConfigMap")["data"]
    assert cfg["APP_DEBUG"] == "false"
    assert cfg["FORCE_HTTPS"] == "true"
    assert cfg["RATE_LIMIT_ENABLED"] == "1"


@pytest.mark.parametrize(
    "manifest,kind",
    [
        ("deployment.yaml", "Deployment"),
        ("migrate-job.yaml", "Job"),
    ],
)
def test_containers_run_unprivileged(manifest, kind):
    doc = _one(manifest, kind)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    sec = container["securityContext"]
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"]["drop"] == ["ALL"]


def test_deployment_runs_as_nonroot():
    pod_sec = _one("deployment.yaml", "Deployment")["spec"]["template"]["spec"][
        "securityContext"
    ]
    assert pod_sec["runAsNonRoot"] is True
    assert pod_sec["runAsUser"] == 1000, "must match the Dockerfile's slowbooks uid"


def test_secret_template_holds_no_real_values():
    """The example must stay an example."""
    for doc in _load("secret.example.yaml"):
        for key, value in doc.get("stringData", {}).items():
            assert value in ("", "REPLACE_ME") or "REPLACE_ME" in value, (
                f"secret.example.yaml key {key} looks like a real value — "
                "never commit a filled-in secret"
            )


def test_kustomization_excludes_the_secret_template():
    """Applying the template would create a Secret full of REPLACE_ME,
    which the app would then use as an encryption key."""
    kust = yaml.safe_load((K8S / "kustomization.yaml").read_text())
    assert "secret.example.yaml" not in kust["resources"]


def test_kustomization_lists_every_other_manifest():
    listed = set(yaml.safe_load((K8S / "kustomization.yaml").read_text())["resources"])
    on_disk = {
        p.name
        for p in K8S.glob("*.yaml")
        if p.name not in ("kustomization.yaml", "secret.example.yaml")
    }
    assert on_disk == listed, f"kustomization.yaml out of sync: {on_disk ^ listed}"


def test_app_and_migrate_share_the_same_image():
    """A migrate Job on a different image than the app applies the wrong
    schema version."""
    app_image = _app_container()["image"]
    job_image = _one("migrate-job.yaml", "Job")["spec"]["template"]["spec"][
        "containers"
    ][0]["image"]
    assert app_image == job_image
