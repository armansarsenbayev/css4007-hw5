# HW5: University IT helpdesk with LangGraph

A practice terminal helpdesk built with LangGraph for CSS-4007 (Artificial Intelligence). It answers Wi-Fi and password questions from local fictional data, checks a demo service status, prepares local ticket drafts (nothing is ever sent), and remembers both the conversation (per thread) and the user's reply language (per user).

* The original assignment text is in [ASSIGNMENT.md](ASSIGNMENT.md).
* Scenarios: [SCENARIOS.md](SCENARIOS.md) and [data/scenarios.json](data/scenarios.json).
* My explanations and results: [SUBMISSION.md](SUBMISSION.md).

## Requirements

* Python **3.11.1** (CI runs Python 3.11).
* Exact package versions are pinned in [requirements.txt](requirements.txt) (LangGraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-openai 1.7.4).
* An API key for a tool capable OpenAI model or an OpenAI compatible provider, for Parts 2 and 3 only. Part 1 and the tests need no key.

## Setup

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and fill in your settings:

| Variable | Meaning |
| --- | --- |
| `OPENAI_API_KEY` | Your API key (required for Parts 2 and 3). Never commit it; `.env` is ignored by git. |
| `MODEL_NAME` | A tool capable model, for example `gpt-5.6-luna`. |
| `OPENAI_BASE_URL` | Empty for OpenAI. Set it for an OpenAI compatible provider, for example `https://openrouter.ai/api/v1`. |
| `MODEL_TEMPERATURE` | Sampling temperature. Empty means it is not sent. `gpt-5.6-luna` accepts only `1`. |
| `MODEL_REASONING_EFFORT` | Reasoning effort. Empty means it is not sent. `gpt-5.6-luna` needs `none` for tool calls. |
| `HELPDESK_STORAGE_DIR` | Folder for the memory databases (default `local-storage`). |
| `HELPDESK_TICKET_DIR` | Folder for ticket drafts (default `outputs/tickets`). |
| `LANGSMITH_TRACING` | Keep `false`. |

## Run

All commands are run from the repository root with the virtual environment active.

### Part 1: rule based graph (no model, no key)

```bash
python -m helpdesk.part1 --variant original --message "I cannot connect to Wi-Fi."
python -m helpdesk.part1 --variant with_clarification --message "My Wi-Fi password does not work."
python -m helpdesk.part1 --variant original --message "I forgot my PASSWORD." --save outputs/part1-password.json
python -m helpdesk.part1 --variant with_clarification --mermaid
```

The program prints the node order and the state after each node. `--save` writes the trace as JSON, `--mermaid` prints the diagram generated from the compiled graph.

### Part 2: tools called directly (no model, no key)

```bash
python -m helpdesk.tools find_instructions wifi
python -m helpdesk.tools check_service_status wifi --profile wifi_outage
python -m helpdesk.tools prepare_ticket --category wifi --summary "Campus-Demo will not connect" --step "Enabled Wi-Fi" --step "Forgot the saved network"
```

`prepare_ticket` uses `--user demo-user-a --thread manual --profile normal` unless you pass other values.

### Parts 2 and 3: the terminal helpdesk (needs the key)

```bash
# interactive: type messages, /quit to exit
python -m helpdesk.cli --user demo-user-a --thread s10 --status normal

# one message, then exit
python -m helpdesk.cli --user demo-user-a --thread s10 --status normal --message "Which steps did I already try?"

# also append every turn's trace to a JSON file
python -m helpdesk.cli --user demo-user-a --thread s10 --status normal --trace outputs/my-session.json
```

* `--user` is the invented user id (`demo-user-a` or `demo-user-b`).
* `--thread` is the conversation id. The same thread continues the same conversation, even after restarting the program.
* `--status` selects a status snapshot: `normal`, `wifi_outage`, `recovery_outage` or `status_unavailable`.

After each reply, a one line trace shows the nodes visited, the tools that ran and where the information came from.

### All scenarios S01 to S14

```bash
python -m helpdesk.scenarios S06
python -m helpdesk.scenarios all
```

Each scenario writes `outputs/<ID>.json`. Events between `restart_process` events run in separate Python processes; each log records the process id of every segment. S01 to S05 need no key.

## Where data is saved and how to reset

| What | Where | In git |
| --- | --- | --- |
| Conversation memory (LangGraph `SqliteSaver`, by `thread_id`) | `local-storage/checkpoints.sqlite` | no |
| User memory (LangGraph `SqliteStore`, namespace `("users", user_id)`) | `local-storage/user_memory.sqlite` | no |
| Ticket drafts | `outputs/tickets/TKT-*.json` | yes (invented demo data only) |
| Scenario logs | `outputs/S01.json` to `outputs/S14.json` | yes |

Reset both memory databases:

```bash
python -m helpdesk.cli --reset
```

or delete the `local-storage/` folder. The scenario runner resets memory itself before each scenario that has `reset_before: true`, and removes old ticket drafts from an earlier run of the same scenario threads.

## Tests

```bash
pytest -q
```

The tests use a scripted fake model (`tests/fake_model.py`, clearly labelled as a test double) and temporary folders, so they need no API key and never touch `local-storage/`. GitHub Actions runs them on every push and pull request ([.github/workflows/tests.yml](.github/workflows/tests.yml)).

## Code layout

| Path | What it contains |
| --- | --- |
| `helpdesk/data.py` | Loads the JSON fixtures from `data/` |
| `helpdesk/part1_graph.py`, `helpdesk/part1.py` | Part 1 graph and its command line |
| `helpdesk/tools.py` | The tools as plain functions, their LangChain wrappers and a command line |
| `helpdesk/model.py` | Builds the chat model from `.env` |
| `helpdesk/agent_graph.py` | Model and tools graph with memory and the loop limit |
| `helpdesk/memory.py` | Storage paths, opening the saver and store, reset |
| `helpdesk/tracing.py` | Builds per turn traces and writes logs |
| `helpdesk/cli.py` | Terminal program |
| `helpdesk/scenarios.py` | Scenario runner with real process restarts |
| `tests/` | Pytest tests |
