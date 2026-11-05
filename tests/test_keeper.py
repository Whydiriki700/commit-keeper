"""Scenario tests for the Commit Keeper core.

Run: python3 tests/test_keeper.py   (no dependencies, uses real git in tmp dirs)
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import keeper  # noqa: E402

CASES = []


def case(name):
    def wrap(fn):
        CASES.append((name, fn))
        return fn

    return wrap


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="ck-test-"))
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)
    return repo


@case("sensitive path detection by name")
def _():
    assert keeper.is_sensitive_path(".env")
    assert keeper.is_sensitive_path("gateway/google.env")
    assert keeper.is_sensitive_path("certs/server.key")
    assert keeper.is_sensitive_path("app/client_secret.json")
    assert keeper.is_sensitive_path("signing/app.keystore")
    assert not keeper.is_sensitive_path("src/server.js")
    assert not keeper.is_sensitive_path("docs/environment-guide.md")


@case("clean repo is skipped")
def _():
    repo = make_repo()
    result = keeper.checkpoint(str(repo))
    assert result["action"] == "skipped" and result["reason"] == "working tree clean"


@case("changed file is checkpointed")
def _():
    repo = make_repo()
    (repo / "work.txt").write_text("real work\n")
    result = keeper.checkpoint(str(repo))
    assert result["action"] == "committed" and result["files"] == 1 and result["commit"]
    assert keeper.checkpoint(str(repo))["action"] == "skipped"


@case("sensitive file is dropped, never committed")
def _():
    repo = make_repo()
    (repo / "work.txt").write_text("real work\n")
    (repo / ".env").write_text("TOKEN=abc\n")
    result = keeper.checkpoint(str(repo))
    assert result["action"] == "committed"
    assert result["dropped_sensitive"] == [".env"]
    names = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "work.txt" in names and ".env" not in names


@case("only sensitive changes means no commit")
def _():
    repo = make_repo()
    (repo / ".env").write_text("TOKEN=abc\n")
    result = keeper.checkpoint(str(repo))
    assert result["action"] == "skipped"


@case("non repo path is skipped")
def _():
    plain = Path(tempfile.mkdtemp(prefix="ck-plain-"))
    result = keeper.checkpoint(str(plain))
    assert result["action"] == "skipped" and "not a git" in result["reason"]


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
