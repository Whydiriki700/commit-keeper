"""Commit Keeper - uncommitted work is unfinished work.

A Hermes plugin that turns "update GitHub every time something changes"
into a mechanism: it counts tool activity in the session and, every
`interval` tool calls, writes a git checkpoint commit in each configured
workspace repo. Checkpoints can push automatically.

Safety rails, by design:
  - Credential-shaped file names (.env, *.key, *secret*, keystore, ...)
    are never staged, even when a repo's .gitignore forgot them.
  - A repo with unmerged paths is refused, never auto-resolved.
  - Clean repos are skipped quietly. Every outcome is ledgered.

Configuration (config: plugins.entries.commit-keeper.settings):
  - repos: list of repo paths to checkpoint (default: current directory)
  - interval: tool calls between automatic checkpoints (default 25)
  - push: push after each checkpoint commit (default false)
  - mode: on | off
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

try:
    from . import keeper, store
except ImportError:  # loaded as a top-level module in tests
    import keeper  # type: ignore
    import store  # type: ignore

logger = logging.getLogger(__name__)

_CTX: Any = None
_lock = threading.Lock()
_COUNTER = {"calls": 0}


def _cfg(key: str, default: Any) -> Any:
    if _CTX is not None:
        try:
            value = _CTX.get_config(key, default)
            if value is not None:
                return value
        except Exception:
            pass
    return default


def _mode() -> str:
    mode = _cfg("mode", "on")
    return mode.lower() if isinstance(mode, str) else "on"


def _repos() -> List[str]:
    repos = _cfg("repos", None)
    if isinstance(repos, list) and repos:
        return [str(r) for r in repos]
    if isinstance(repos, str) and repos.strip():
        return [repos.strip()]
    return [os.getcwd()]


def _interval() -> int:
    try:
        value = int(_cfg("interval", 25))
        return value if value > 0 else 25
    except Exception:
        return 25


def _push() -> bool:
    value = _cfg("push", False)
    return value is True or (isinstance(value, str) and value.lower() in {"true", "yes", "1"})


def run_checkpoints() -> List[Dict[str, Any]]:
    results = []
    for repo in _repos():
        try:
            result = keeper.checkpoint(repo, push=_push())
        except Exception as exc:  # a broken repo must not break the session
            logger.warning("commit-keeper: checkpoint failed for %s", repo, exc_info=True)
            result = {"repo": repo, "action": "failed", "reason": str(exc)[:300]}
        results.append(result)
        try:
            store.append_record(result)
        except Exception:
            logger.debug("commit-keeper: ledger append failed", exc_info=True)
    return results


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def on_post_tool_call(tool_name: str, args: Any = None, result: Any = None, **kwargs: Any) -> None:
    if _mode() == "off":
        return
    with _lock:
        _COUNTER["calls"] += 1
        due = _COUNTER["calls"] % _interval() == 0
    if due:
        run_checkpoints()


# ---------------------------------------------------------------------------
# Surfaces: /commitkeeper command, tools, CLI
# ---------------------------------------------------------------------------


def _format_results(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "No checkpoint ran."
    lines = []
    for r in results:
        extra = ""
        if r.get("action") == "committed":
            extra = f" commit={r.get('commit')} files={r.get('files')}"
            if r.get("push"):
                extra += " pushed=" + ("yes" if r.get("pushed") else "no")
        elif r.get("reason"):
            extra = " reason=" + str(r["reason"])
        if r.get("dropped_sensitive"):
            extra += f" dropped_sensitive={len(r['dropped_sensitive'])}"
        lines.append(f"- {r.get('action')} | {r.get('repo')}{extra}")
    return "\n".join(lines)


def commitkeeper_command(raw_args: str = "", **kwargs: Any) -> str:
    arg = (raw_args or "").strip().lower()
    if arg == "run":
        return "Commit Keeper checkpoints:\n" + _format_results(run_checkpoints())
    rows = store.read_recent(limit=100)
    if not rows:
        return "Commit Keeper ledger is empty. No checkpoint has run yet. Use /commitkeeper run to force one."
    lines = ["Commit Keeper recent checkpoints:"]
    lines.append(_format_results(rows[-5:]))
    return "\n".join(lines)


def commitkeeper_run_tool(params: Dict[str, Any] | None = None, **kwargs: Any) -> str:
    params = params or {}
    repo = params.get("repo")
    if repo:
        result = keeper.checkpoint(str(repo), push=_push())
        try:
            store.append_record(result)
        except Exception:
            pass
        return json.dumps({"success": True, "results": [result]})
    return json.dumps({"success": True, "results": run_checkpoints()})


def commitkeeper_status_tool(params: Dict[str, Any] | None = None, **kwargs: Any) -> str:
    rows = store.read_recent(limit=100)
    return json.dumps(
        {
            "success": True,
            "checkpoints_recent": len(rows),
            "latest": rows[-5:],
            "repos": _repos(),
            "interval": _interval(),
            "push": _push(),
            "note": "Full history lives in <HERMES_HOME>/commit-keeper/ledger.jsonl",
        }
    )


def _cli_setup(subparser: Any) -> None:
    sub = subparser.add_subparsers(dest="commitkeeper_action")
    sub.add_parser("run", help="Write checkpoints in all configured repos now")
    sub.add_parser("status", help="Show recent Commit Keeper checkpoints")


def _cli_handler(args: Any) -> int:
    if getattr(args, "commitkeeper_action", None) == "run":
        print(_format_results(run_checkpoints()))
    else:
        print(commitkeeper_command(""))
    return 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx

    ctx.register_hook("post_tool_call", on_post_tool_call)

    ctx.register_command(
        "commitkeeper",
        commitkeeper_command,
        description="Show Commit Keeper checkpoints, or run one with /commitkeeper run",
    )
    ctx.register_tool(
        name="commitkeeper_run",
        toolset="commit-keeper",
        schema={
            "name": "commitkeeper_run",
            "description": (
                "Write a git checkpoint commit now in the configured repos "
                "(or one repo given as 'repo'). Credential-shaped paths are "
                "always excluded; conflicted repos are refused."
            ),
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string"}},
            },
        },
        handler=commitkeeper_run_tool,
    )
    ctx.register_tool(
        name="commitkeeper_status",
        toolset="commit-keeper",
        schema={
            "name": "commitkeeper_status",
            "description": "Return Commit Keeper's recent checkpoints and active configuration.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=commitkeeper_status_tool,
    )
    ctx.register_cli_command(
        "commitkeeper",
        "Run or inspect Commit Keeper git checkpoints",
        _cli_setup,
        _cli_handler,
        description="Checkpoint configured repos, or show recent checkpoints",
    )
