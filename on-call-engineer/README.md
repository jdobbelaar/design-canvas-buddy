# On-call engineer

A script that watches the observability stack's alerts and, when one fires, hands it
to a headless coding agent (Claude Code) that investigates and writes a report.

```
Grafana (alert rules) --every minute--> poll.py --new alert--> claude -p (headless agent)
                                                                    | read-only tools only
                                          reports/<time>-<alert>.md <-- its findings
```

It is a **first-responder aid, not a pager**. It tells nobody anything: the report lands
in `reports/` and in the log, for a human to read. It does not fix anything, and it is
deliberately unable to.

## Run it

You need Python 3.10+ (standard library only) and [Claude Code](https://claude.com/claude-code)
installed and logged in (`claude` on your PATH).

```
python3 on-call-engineer/poll.py                # run until stopped, polling every 60 s
python3 on-call-engineer/poll.py --once         # a single poll (cron, or to try it)
python3 on-call-engineer/poll.py --dry-run      # show what the agent would be given; run nothing
```

Locally, Grafana is open, so nothing else is needed. Against the AWS Grafana, create a
read-only credential first: in Grafana, Administration -> Users and access -> Service
accounts -> Add service account (role **Viewer**) -> Add token, then

```
export GRAFANA_URL=https://<the GrafanaUrl output of the observability stack>
export GRAFANA_TOKEN=<the token>
```

(PowerShell: `$env:GRAFANA_URL = "..."`.) A Viewer token cannot change anything in Grafana.

| Setting | Default | |
|---|---|---|
| `GRAFANA_URL` | `http://localhost:3000` | where Grafana is |
| `GRAFANA_TOKEN` | none | Viewer service-account token |
| `ON_CALL_INTERVAL` | 60 | seconds between polls |
| `ON_CALL_MAX_BUDGET_USD` | 1.50 | spending cap for one investigation |
| `ON_CALL_TIMEOUT` | 900 | seconds before an investigation is stopped |
| `ON_CALL_MAX_RUNS_PER_HOUR` | 4 | investigations per hour, across all alerts |
| `ON_CALL_MODEL` | Claude Code's default | e.g. `sonnet` |
| `ON_CALL_AGENT_COMMAND` | Claude Code, restricted | another headless agent; see "Other agents" |

A typical investigation took about 2 minutes and cost about $0.50.

## What it does

- Asks Grafana's Alertmanager API for **firing** alerts each minute. Silenced alerts are
  ignored: a silence is a person saying "I know".
- Investigates each **episode** once. The same alert firing again later (Grafana gives it
  a new start time) is a new episode. Progress is kept in `.state/state.json`, so a
  restart does not repeat work.
- One investigation at a time. A failed one is retried once (`max_attempts`), then given up
  on and reported in the log. At most `ON_CALL_MAX_RUNS_PER_HOUR` per hour; the rest wait.
- If Grafana cannot be reached it says so loudly and keeps trying. A watcher that has silently
  stopped watching is worse than none.
- Writes `reports/<time>-<alert>.md`: the alert, when and how it was investigated (and what
  it cost), and the agent's findings with the exact queries behind them.

## What the agent can and cannot do

The alert text and the logs the agent reads contain text from the outside world (a request
path in an access log is chosen by whoever sent the request), so the agent is treated as
something that could be misled, and is **limited by construction, not by asking it to behave**:

- **No built-in tools at all**: no shell, no file reading, no writing or editing, no web.
  It starts with `--tools ""`.
- **Its only tools are the ten in `mcp_server.py`**, all read-only: firing alerts, PromQL,
  LogQL, TraceQL, and the code and git history *as committed* (through git, at HEAD or a
  commit you name). Files that are not committed (`.env`, credentials, these reports)
  simply do not exist to it.
- **Isolated from your own setup**: `--strict-mcp-config` (none of your other MCP servers, for
  example Atlassian) and `--setting-sources project` (none of your user-level settings, which
  can carry permissive rules and hooks). It gets a small environment: no cloud credentials.
- **Anything not allowed is refused**, not asked about (`--permission-mode dontAsk`).
- **Bounded**: one run at a time, `--max-budget-usd`, a timeout, and the hourly limit.
- It **recommends** actions with exact commands (for example the rollback workflow); a human runs them.

I tested this against the real Claude Code CLI rather than assuming it: an agent told to try
writing a file, running a command, reading credentials, and fetching a web page was refused
every time, and could use exactly the ten tools. That test overturned two earlier designs
(allowing one shell command let a second be chained on; the built-in `Read` tool opened any
file the account could, including credentials), which is why the design is what it is.
Re-run that kind of check if you change the command in `poll.py:claude_command`.

To let it do more (open pull requests, roll back), change the tools on purpose, in
`claude_command` and `mcp_server.py`, after deciding what damage a misled agent could do.
There is no flag for it by design.

### Things to know

- **What leaves your machine.** The agent's inputs (the alert, and the metrics, log lines,
  traces, and code it queries) are sent to the model provider. Reports can contain log
  excerpts; treat them accordingly and keep them out of tickets and chat unless that is fine.
- **Your global `CLAUDE.md` still loads.** Claude Code loads your user-level memory file
  whatever the settings flags say, so the agent knows what is in it. It has no way to read
  files, so it cannot see anything else. For a shared or always-on machine, run it as its
  own OS user (or with `CLAUDE_CONFIG_DIR` pointing at a clean directory and an
  `ANTHROPIC_API_KEY`), so it does not carry anyone's personal setup.
- **It is only as good as the evidence.** For example, the agent will tell you that a
  rejected message is counted but never logged, so it cannot say what was wrong with it.
  A report that says "unclear" and names the missing evidence is working as intended.
- **It runs where you start it.** Nothing here deploys it. For always-on use put it under a
  process supervisor (a systemd service, or a scheduled task running `--once` every minute).
  While an investigation runs (minutes), polling pauses; the next poll follows immediately.

### Other agents

`ON_CALL_AGENT_COMMAND="some-agent --headless"` runs another agent instead, with the whole
prompt on stdin. It then gets none of the restrictions above: configure them in that agent,
and give it `mcp_server.py` (a standard MCP server) as its only tools, or its own equivalent.

## Files

| | |
|---|---|
| `poll.py` | the loop, the once-per-episode bookkeeping, the limits, and how the agent is launched |
| `mcp_server.py` | the agent's tools (an MCP server on stdin/stdout, standard library only) |
| `observe.py` | what the tools do: Grafana queries and read-only git; also a command line for you |
| `instructions.md` | the agent's standing instructions and the report format |
| `tests/` | run with `python3 -m unittest discover -s on-call-engineer/tests` |
| `.state/`, `reports/` | created at run time; not committed |

`observe.py` is handy by hand too, for example
`python3 on-call-engineer/observe.py prometheus 'up'` or `... read backend/app/routers/ws.py`.
