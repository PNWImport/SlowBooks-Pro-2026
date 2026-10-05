"""Exercise spec metadata helpers without importing PyInstaller or building."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def helpers():
    source = (ROOT / "packaging/macos/SlowBooksPro-mac.spec").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("_build_sha", "_bundle_version")
    ]
    scope = {"os": os, "ROOT": str(ROOT)}
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), "spec-helpers", "exec"),
        scope,
    )
    return scope


def test_ci_sha_is_preferred_without_git(monkeypatch):
    monkeypatch.setenv("APP_BUILD_SHA", "a" * 40)
    monkeypatch.setenv("APP_VERSION", "2.9.4")

    def forbidden(*args, **kwargs):
        raise AssertionError("CI SHA must avoid a git subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert helpers()["_bundle_version"]() == "2.9.4+" + "a" * 12


def test_local_build_uses_checkout_sha(monkeypatch):
    monkeypatch.delenv("APP_BUILD_SHA", raising=False)

    def git(command, **kwargs):
        assert command == ["git", "-C", str(ROOT), "rev-parse", "HEAD"]
        assert kwargs["check"] is True
        return SimpleNamespace(stdout="b" * 40 + "\n")

    monkeypatch.setattr(subprocess, "run", git)
    assert helpers()["_build_sha"]() == "b" * 12


def test_missing_git_is_marked_unknown(monkeypatch):
    monkeypatch.delenv("APP_BUILD_SHA", raising=False)

    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)
    assert helpers()["_build_sha"]() == "unknown"
