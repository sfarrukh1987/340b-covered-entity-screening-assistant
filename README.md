# 340B Covered Entity Screening Assistant

[![main tests](https://github.com/sfarrukh1987/340b-covered-entity-screening-assistant/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/sfarrukh1987/340b-covered-entity-screening-assistant/actions/workflows/tests.yml)

This course rough draft helps a reviewer assemble a source-linked research shortlist for at most 10 manually selected New York health-center candidates. The intended inputs are saved public HRSA OPAIS records and saved official service pages. The executable demo accepts synthetic records and `.example` source labels only. It does not crawl, send outreach, decide eligibility or contract fit, or write to a pharmacy system. A person checks the original sources before using any result.

## Setup and run

Use Python 3.12 (verified with 3.12.14). From the repository root, create a virtual environment and activate it:

```sh
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
```

On Windows PowerShell, activate it with `.\.venv\Scripts\Activate.ps1`.

```sh
python -m pip install -r requirements.txt
```

Then run the entire demonstration with one command:

```sh
python -m screening
```

The bundled six invented candidates produce **2 review, 2 verify, and 2 hold** results. `outputs/audit.html` records inputs, attempts, source quotes, decisions, and errors. `outputs/shortlist.csv` contains every candidate, including those on hold or awaiting verification. One candidate's first page has no usable service text; the second saved page is used and both attempts remain visible. The reference date is in the fixture config so the expected results do not change with the calendar.

Run the tests with `python -m pytest -v`. GitHub Actions runs the tests and the synthetic demonstration on pushes and pull requests, with the existing weekly schedule and manual trigger. The 20 earlier A1 tests are unchanged. The new suite tests the input, model reply, evidence, explanation, reporting, and orchestration contracts. No expected failures are needed. After installation the default command and test suite make no network or live model calls.

## Model boundary and limits

The two model steps are present. The default backend returns synthetic JSON for them so the demo and CI run without keys or a model server. Optionally, configure a local Ollama server with an already installed **local** model, then use `python -m screening --ollama-model YOUR_LOCAL_MODEL`. The adapter connects to loopback only. The request path is unit tested with a mock; the verified demo uses the synthetic backend. The Session 10 MCP service remains a future option.

A1 retains the Session 6 Beautiful Soup behavior. The workflow separately omits navigation from the service text used for evidence. It cannot render JavaScript or judge all the ways a real page describes a service; the demo only recognizes its narrow fixture wording. A missing quote or page is a prompt for verification, never proof a service is absent. Keep real records and credentials out of the repo and fixtures. Generated outputs and common local data/key paths are ignored.

- [Current wire diagram](docs/workflow.md) · [Workflow instructions](WORKFLOW.md) · [Original Session 5 wire diagram](docs/wire_diagram.png)
