# Cloud setup and diagnosis

## Evidence from this setup

- Inspected repository: `Gideonstolle/Researcher`, branch `main`.
- Original commit: `53cd0751e0d2e2402c6538ffebf7cedeb676d59d`; only a two-line README was present.
- User-reported behavior: the research task chose Consensus despite database-specific instructions in a setup conversation. No task failure was reported.
- Local workspace initially had no files and was not a Git checkout. This workspace is a Mac, not the cloud VM.
- Cloud settings inspection reached a sign-in screen. No cloud task-reader or cloud-management connector was available in this chat. The setup conversation, saved environment configuration and runtime have therefore not been verified.

The confirmed repository gap is addressed by AGENTS.md, executable adapters and tests. Missing publication, wrong repository/branch, blocked NCBI access, or missing inherited instructions are **checks to perform**, not established causes. Selecting Consensus does not by itself establish a network failure.

## Validation recorded on 13 November 2026

- Python 3.14.5: all 41 offline tests passed, including exact query logging, mocked PubMed requests, response/identifier checks, both RIS import adapters, citation outputs and checksum verification.
- The initial local PubMed probe failed with `URLError: [Errno 61] Connection refused`. After the user approved the NCBI domain on their network, a network-enabled rerun succeeded without any code change.
- Successful live probe at 06:11:58 UTC: exact query `psychology[Title] AND 2020[Date - Publication]`, 560 matches, one requested record returned (PMID `32340885`), no query warnings. It was correctly labeled `partial` because this was a one-record connectivity test, not a complete search.
- RIS and BibTeX exports were produced, and checksum verification passed for all eight saved artifacts. Run: `runs/20261113T061158Z-450d1465a23b`. Both successful and failed artifacts remain in the local ignored `runs/` directory.
- This verifies the local PubMed workflow. A licensed database search and the cloud acceptance test remain unverified. Local network approval does not establish the cloud environment's network configuration; run the acceptance check below there too.

## Configure the existing environment

Use your existing **Set up researcher** environment/setup chat. Confirm it includes `Gideonstolle/Researcher` and the updated `main` branch. Read the saved repository files during setup; conversation-only instructions are harder to audit and reproduce.

For the current Cloud interface: edit the environment, run and verify setup, save, and publish/republish. Start a new task to verify the updated setup; existing tasks retain their own working state. Set the additional allowed hostname to `eutils.ncbi.nlm.nih.gov` and test it. Allowing a host does not confer a database subscription. See [current Cloud environment instructions](https://learn.chatgpt.com/docs/environments/cloud-environments).

For a legacy environment with setup/maintenance script fields, use `bash scripts/setup.sh`. Agent-phase internet access is separate from setup access: permit `eutils.ncbi.nlm.nih.gov` and HTTPS `POST`, which this adapter uses to send exact queries without URL-length limits. Legacy setup secrets are removed before the agent phase; do not depend on them for runtime API calls. This workflow needs no key. See [legacy environments](https://learn.chatgpt.com/docs/environments/cloud-environment) and [legacy network settings](https://learn.chatgpt.com/docs/cloud/internet-access).

Use Python 3.10+ (3.12 is a suitable choice if offered). No package installation is needed. Do not disable TLS verification to fix certificate errors; use the environment's documented certificate/proxy configuration. Do not assume an interactive browser is available or that university access carries into the VM.

## Paste into the existing setup conversation

```text
Configure this existing environment to use Gideonstolle/Researcher, updated main.
Read AGENTS.md and README.md from that checkout. Confirm the new files are present.
Use Python 3.10 or newer and run bash scripts/setup.sh.
Verify runtime HTTPS POST access to eutils.ncbi.nlm.nih.gov, then run:
python3 -m researcher doctor --online
Report the run directory, manifest status, returned PMID, and test results.
Do not substitute Consensus or general web search for a PubMed search.
Use authorized RIS exports for PsycINFO/Web of Science unless a separate,
authorized API adapter is implemented and tested. Do not assume browser or
subscription access. If a step fails, show the exact error and missing setting.
Save the tested configuration and report whether publication is still needed.
```

After setup is verified and published, create a new cloud task with this acceptance prompt:

```text
Read AGENTS.md. Run python3 -m researcher doctor --online and verify its output
folder with python3 -m researcher verify <the printed run directory>.
Then run the included PubMed demonstration query with --max-records 5
--allow-partial. Report it as a partial smoke test, not a complete review.
Show query.txt, the submitted term, NCBI query translation, timestamps,
total matched count, retrieved count, PMIDs, warnings, and citation paths.
Use the program's actual artifacts. Do not use Consensus for this check.
```

For real research, give the research question and requested databases. The agent should prepare and record database-specific searches, execute available adapters, and identify any still-unsearched databases.

## Interpret the checks

| Observation | Meaning / next action |
| --- | --- |
| AGENTS.md or `researcher/` missing | Wrong or stale checkout; inspect repository and commit before rerunning |
| Python below 3.10 | Select a newer interpreter; do not infer dependencies are missing |
| Offline tests pass, online probe fails | Read the saved failure and HTTP status; check exact hostname, proxy and runtime network policy |
| HTTP 429/5xx | NCBI may be rate limiting/unavailable; finite retries preserve each attempt; retry later without inventing results |
| TLS error | Check trusted certificates/proxy configuration without disabling verification |
| Search exceeds cap | Deliberate protection against silent truncation; narrow, partition, or explicitly request a partial demonstration |
| Setup works but task still selects Consensus | Inspect the task's actual checkout and AGENTS.md, and invoke the exact command; confirm updated environment publication |
| PsycINFO/WoS export unavailable | That database remains unsearched; obtain an authorized export or separately authorized API access |

Save needed run folders to approved storage. They are intentionally excluded from public Git commits. A saved environment or task filesystem is not your sole research archive.
