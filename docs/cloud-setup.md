# Cloud setup and diagnosis

## Use the updated literature workflow

Select `Gideonstolle/Researcher` and the updated `main` branch for a new environment task. Read [the prompt guide](prompt-guide.md) for ordinary-language requests: the agent handles queries and commands. Existing tasks can have stale checkouts; confirm `docs/prompt-guide.md` exists and `python3 -m researcher --help` lists `search`, `scholar-plan`, `scholar-record` and `review`.

PubMed runs automatically when runtime access to `eutils.ncbi.nlm.nih.gov` works. Google Scholar is an assisted workflow: it prepares links and records observed results, and does not install a browser or scraper. If direct permitted access is unavailable, the user can open the prepared link and supply actual observations/evidence. A Scholar plan can be generated offline, but must remain labelled unexecuted. Updating the repository does not change network settings, grant university access or republish your environment.

For a quick check in the selected environment, ask:

```text
Read AGENTS.md and docs/prompt-guide.md from the updated Researcher checkout.
Run the offline setup checks and the logged PubMed online probe.
Confirm that the Scholar planning and review commands are available.
Report the actual checkout, tests and network result, preserving any failure.
Do not treat a prepared Scholar link as a completed search.
```

Keep project strategy notes, evidence tables and analysis under `private/`. Save or download full search/review folders before a temporary task expires; a final paper list alone is not the audit trail.

## Historical setup evidence

- Inspected repository: `Gideonstolle/Researcher`, branch `main`.
- Original commit: `53cd0751e0d2e2402c6538ffebf7cedeb676d59d`; only a two-line README was present.
- User-reported behavior: the research task chose Consensus despite database-specific instructions in a setup conversation. No task failure was reported.
- Local workspace initially had no files and was not a Git checkout. This workspace is a Mac, not the cloud VM.
- Cloud settings inspection reached a sign-in screen. No cloud task-reader or cloud-management connector was available in this chat. The setup conversation, saved environment configuration and runtime have therefore not been verified.

The confirmed repository gap is addressed by AGENTS.md, executable adapters and tests. Missing publication, wrong repository/branch, blocked NCBI access, or missing inherited instructions are **checks to perform**, not established causes. Selecting Consensus does not by itself establish a network failure.

## Earlier validation recorded on 13 November 2026

The following describes the earlier adapter revision, not a current test count or a guarantee that the selected cloud environment is connected. Rerun the checks after updates.

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
Use the optional Web of Science Starter API adapter only when WOS_API_KEY
and suitable API permission are configured; see docs/webofscience-setup.md.
Otherwise use authorized RIS exports for Web of Science and PsycINFO. Do not
assume browser or subscription access. If a step fails, show the exact error
and missing setting.
Confirm the search, scholar-plan, scholar-record and review commands exist.
Use the Scholar planning/observation workflow only with permitted access;
it is not an automatic scraper. Read docs/prompt-guide.md for user prompts.
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

For real research, give the research question and requested databases. The agent should prepare and record database-specific searches, execute available adapters, and identify any still-unsearched databases. Ask for an evidence table and candidate study questions when needed; review assembly creates the table structure, and the agent must fill it from evidence actually read before interpreting gaps.

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
| Scholar run says `planned` | Only a query/link was prepared; execute a permitted search and record actual observations before claiming results |
| Scholar access is blocked | Preserve the blocked attempt; do not interpret it as zero matches or substitute a different engine silently |
| Evidence table contains blank findings | Review assembly does not read papers; ask the agent to screen/read sources and fill supported fields with locators |

Save needed run folders to approved storage. They are intentionally excluded from public Git commits. A saved environment or task filesystem is not your sole research archive.

