# Commit Keeper

**Uncommitted work is unfinished work.**

Commit Keeper is a Hermes Agent plugin that writes automatic git checkpoint commits while the agent works, so a finished change is never left sitting uncommitted in a workspace when the session ends, the machine sleeps, or the context rolls over.

It exists because of a simple house rule: every update goes to git right away, not later. Rules people have to remember get forgotten. Commit Keeper is the rule as a mechanism.

## How it works

1. **Activity counter.** A `post_tool_call` hook counts tool calls in the session. Every `interval` calls (default 25) a checkpoint run fires. You can also force one any time with the tool or the command below.
2. **Checkpoint per repo.** For each configured repo the keeper stages changed files, commits them with a timestamped `commit-keeper: checkpoint ...` message, and pushes when `push` is on.
3. **Safety rails.**
   * Credential-shaped paths are never staged, by file name: `.env` files, `*.key`, `*.pem`, anything with `secret`, `credential`, `keystore`, or `private` in its name, even if the repo's `.gitignore` forgot them. Dropped paths are reported in the result, never silently swallowed.
   * A repo with unmerged (conflicted) paths is refused outright. A human resolves conflicts, never a checkpoint.
   * Clean repos are skipped. Non-repo paths are skipped.
4. **Ledger.** Every attempt, committed, skipped, refused, or failed, is appended to `$HERMES_HOME/commit-keeper/ledger.jsonl`.

## Surfaces

* `/commitkeeper` in chat: recent checkpoints. `/commitkeeper run`: force a checkpoint now.
* `commitkeeper_run` tool: checkpoint all configured repos, or one repo passed as `repo`.
* `commitkeeper_status` tool: recent checkpoints plus the active configuration.
* `hermes commitkeeper run|status` on the CLI.

## Install

```bash
hermes plugins install Whydiriki700/commit-keeper --enable
```

Or copy this directory into `~/.hermes/plugins/commit-keeper/` and run `hermes plugins enable commit-keeper`, then restart Hermes.

Verify any time with:

```bash
hermes plugins validate ~/.hermes/plugins/commit-keeper
hermes plugins doctor ~/.hermes/plugins/commit-keeper
```

## Configuration

In `config.yaml`:

```yaml
plugins:
  entries:
    commit-keeper:
      settings:
        repos:
          - ~/workspace/my-project
        interval: 25    # tool calls between automatic checkpoints
        push: false     # true pushes after every checkpoint commit
        mode: on        # on | off
```

* `repos` defaults to the current working directory when unset.
* Checkpoints commit with the identity `commit-keeper <commit-keeper@localhost>` unless the commit is made through your own configured identity outside the plugin. Checkpoint messages are deliberately plain so they are easy to squash later.

## Honest limitations

* Checkpoints are safety nets, not curated history. Expect timestamped checkpoint commits you may want to squash before a release.
* The credential filter works on file names, not file contents. A secret pasted into a normally named file is a job for [Secret Scan](https://github.com/Whydiriki700/secret-scan), which is why the two plugins pair well.
* Push failures (offline, auth) are recorded in the ledger and never retried in a loop. The commit is safe locally either way.

## Development

```bash
python3 tests/test_keeper.py   # 6 scenario tests, uses real git in tmp dirs
```

The keeper (`keeper.py`) is pure subprocess and stdlib with no Hermes imports, so the checkpoint logic can be tested and audited in isolation.

## License

MIT

---

**More by the same author**

- [ProofGate](https://github.com/Whydiriki700/proofgate): no proof, no done. Agent completion claims checked against tool evidence, fail closed.
- [Secret Scan](https://github.com/Whydiriki700/secret-scan): credential patterns redacted from agent replies before delivery, fail closed.
- [Context Keeper](https://github.com/Whydiriki700/context-keeper): session checkpoints that survive restarts, restored into the next session.
- [money-magnet](https://github.com/Whydiriki700/money-magnet): finance tracker, budget alerts, crypto portfolio PnL and arbitrage scanner for Hermes Agent.
- [Token Dashboard](https://github.com/Whydiriki700/token-dashboard): live token usage and cost dashboard for Hermes Desktop.
- Osvyn on Telegram: [t.me/osvynofficial](https://t.me/osvynofficial)
