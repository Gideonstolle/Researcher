# Researcher

Academic researcher for Psychology. Ask Codex to find papers, document its searches, and turn the evidence into candidate study questions. Start with the short **[prompt guide](docs/prompt-guide.md)**; no coding is required to use it through your Researcher environment. Durable agent instructions live in [AGENTS.md](AGENTS.md).

It executes PubMed searches through NCBI E-utilities, supports an auditable assisted Google Scholar workflow, offers an optional Web of Science Starter API connector, and imports authorized PsycINFO and Web of Science RIS exports. Search runs preserve citations and an audit trail. Review workspaces combine runs and prepare an evidence table and gap-analysis template for the agent to complete from material actually read.

No OpenAI API key or extra Python packages are needed. PubMed works without an API key; Web of Science requires an authorized `WOS_API_KEY`. Google Scholar requires actual permitted user/browser-assisted observations; preparing a link does not execute a Scholar search.

## Choose an engine in your prompt

For example: "Search PubMed for empirical studies on pretend play and self-regulation in preschool children. Document the exact searches, build an evidence table, verify candidate gaps with follow-up searches, and suggest three feasible study questions. Label any capped search as exploratory."

Specify `PubMed`, `Google Scholar`, `Web of Science`, or `PsycINFO` (and its platform). If omitted, PubMed is the stated default. The agent must report inaccessible sources instead of silently substituting another engine. See [prompt examples](docs/prompt-guide.md) and [cloud setup and diagnosis](docs/cloud-setup.md). Use a new task with the updated repository; this change does not automatically modify cloud settings or an existing task's checkout.

## Quick start

Use Python 3.10 or newer from the repository root:

```sh
bash scripts/setup.sh
python3 -m researcher doctor --online
python3 -m researcher search --engine pubmed --query-file queries/pubmed-demo.txt --max-records 5 --allow-partial --sort relevance --reason "Connectivity demonstration"
```

The last command is a **partial demonstration**, not a complete literature review. The sample topic is cognitive behavioral therapy and insomnia; replace it with your actual search strategy. Exact file contents, including the final newline, are submitted and logged without trimming. UTF-8 byte-order marks are rejected to avoid silently changing a query.

On this Mac, `/usr/bin/python3` is 3.9. Use the installed newer interpreter if `python3` selects that version:

```sh
PYTHON_BIN=/opt/homebrew/bin/python3 bash scripts/setup.sh
/opt/homebrew/bin/python3 -m researcher doctor --online
```

For a complete retrieval, omit `--allow-partial` and set a cap sufficient for the query (maximum 10,000). If hits exceed the cap, the command records the count and fails before fetching citations. Narrow or deliberately partition broad queries; partitioning is not automatic. The `review` command can subsequently combine runs using strong identifiers. PubMed ESearch cannot return beyond its first 10,000 matches. [NLM limit](https://www.nlm.nih.gov/pubs/techbull/so22/so22_updated_pubmed_e_utilities.html)

PubMed's default sort is `pub_date`; use `--sort relevance` for a sample ordered by NCBI's relevance ranking. Neither the newest nor the highest-ranked subset establishes a research gap. Add `--reason "..."` to explain a search, and `--parent-run RUN_ID` to link a revision to its predecessor. These options are also available on import and Scholar commands. Keep the broader strategy and all run links in `private/<project>/search-strategy.md`.

Configure `NCBI_EMAIL` as your contact address in the environment settings when using E-utilities routinely. `NCBI_API_KEY` is optional; the workflow works without one and uses conservative request spacing, timeouts and finite retries. Credentials are excluded from request logs. Do not put keys in query files, Git, or prompts. [NCBI usage guidelines](https://eutilities.github.io/site/API_Key/usageandkey/)

## What each run saves

The command prints its new directory under `runs/`:

| File | Purpose |
| --- | --- |
| `query.txt` | Original query file bytes |
| `manifest.json` | Exact query, software/source hashes, start/end timestamps, database, counts, translation, warnings and status |
| `events.jsonl` | Timestamped query/request/retry/completion events; credentials redacted |
| `raw/` | API responses, the original authorized RIS, or supplied Scholar observations and evidence |
| `records.json` | Normalized citation records |
| `citations.ris`, `citations.bib` | Reference-manager exports |
| `checksums.json` | SHA-256 inventory for detecting accidental changes |

Failed runs keep their query, available responses, error and checksums. They do not claim to be zero-result successes. Complete, partial, failed and imported states are distinct; Scholar adds planned and blocked states. A plan has no retrieved citations.

```sh
python3 -m researcher verify runs/PASTE-THE-PRINTED-RUN-DIRECTORY-NAME
```

Snapshots let you inspect what happened even if database content later changes. Live reruns may produce different results. Checksums detect accidental changes; they are not signed proof against deliberate tampering. Run directories are never reused automatically, but remain ordinary editable files.

## Google Scholar: prepare, observe, record

Google Scholar's official help does not offer bulk access and asks automated software to respect its access rules. This project supplies no unattended Scholar scraper or CAPTCHA bypass. Use permitted user/browser-assisted searches, then record what was actually observed. [Scholar help](https://scholar.google.com/intl/en/scholar/help.html), [robots.txt](https://scholar.google.com/robots.txt).

Save a Scholar-appropriate query in `private/scholar-query.txt`; do not reuse PubMed field tags. Prepare it with:

```sh
python3 -m researcher scholar-plan --query-file private/scholar-query.txt --year-from 2015 --sort relevance
```

The equivalent engine-selector command is `python3 -m researcher search --engine google-scholar --query-file private/scholar-query.txt --year-from 2015 --sort relevance`. A planned run saves `search-url.txt`, `observation-template.json` and `instructions.md`. It is explicitly unexecuted. An optional `--year-to` sets the upper publication-year bound; `--sort date` requests date order.

Open the prepared link through permitted access. Copy its observation template into `private/`, fill it from the actual search, and preserve available screenshots, exports or other evidence. The observation records the exact query and actual URL, search timestamp with timezone, filters/sort, displayed count and original count text, inspected pages, timestamped steps, result ranks/metadata and stopping reason. Counts may be approximate or unknown. The template requires real observations; it is not demonstration data.

```sh
python3 -m researcher scholar-record --query-file private/scholar-query.txt --observation private/scholar-observation.json --evidence private/scholar-page.pdf
```

`--evidence` accepts saved evidence files. The recorded search is `partial`, or `blocked` if no results could be inspected. If blocked after retrieving some records, use `partial` and explain the interruption. The importer validates supplied observations and preserves their provenance, but does not independently prove a browser search occurred. Raw evidence strengthens the audit trail. It never claims exhaustive Scholar coverage. A general web search containing `site:scholar.google.com` remains a general web search, not a Scholar search.

Only include ranked hits from the recorded query in its observation's results. Log Cited by, Related articles and reference-list discoveries separately with the actual discovery URL and parent paper. This adapter does not import citation-only Scholar URLs; a new keyword query belongs in a new run.

## Build an evidence table and investigate gaps

Use verified run folders to create a **new** review directory:

```sh
python3 -m researcher review --runs runs/FIRST-RUN runs/SECOND-RUN --question "How is pretend play associated with preschool self-regulation?" --out private/play-review-v1
```

| Review output | Purpose |
| --- | --- |
| `search-log.csv`, `search-log.md` | Queries, platforms, counts, dates, statuses and limits across runs |
| `sources/` | Verified snapshots of the original runs, including exact query files |
| `records.json`, `citations.ris`, `citations.bib` | Consolidated records and citations, with discovery occurrences in JSON |
| `evidence.csv` | Citation rows with blank screening, evidence, findings and limitation fields |
| `gap-analysis.md` | A structured template for candidate gaps, contrary evidence, verification and study questions |
| `review.json` | Review question, counts and warnings |

Only strong DOI/PMID matches are used for deduplication; similar titles alone are not merged. Identifier conflicts are retained for review and metadata conflicts are flagged. Every discovery occurrence remains traceable. Planned, blocked and failed runs contribute coverage information, never retrieved records.

The CLI assembles the workspace; **Codex must read the available papers or abstracts to fill the evidence table and develop the analysis**. It records screening decisions and source locations, distinguishes abstract from full-text evidence, and executes targeted follow-up queries before proposing candidate gaps. It must state access and coverage limits, consider contrary findings, and avoid claiming that a small result set proves a topic is unstudied. New studies may resolve an apparent gap.

Keep complete run and review folders in approved storage. Use `private/` for review output so unpublished research is not accidentally added to this public repository.

## Web of Science Starter API

See [Web of Science account and cloud setup](docs/webofscience-setup.md) to obtain an API subscription and configure the `WOS_API_KEY` secret. A personal Web of Science website login is separate from API access. Starter is supported; Expanded API is not.

```sh
python3 -m researcher doctor --database webofscience --online
python3 -m researcher webofscience --query-file queries/webofscience-api-demo.txt --max-records 5 --allow-partial
```

Both commands save the usual audit artifacts and citation exports. The first is a one-record connectivity probe; the second is a capped demonstration. Credentials must be configured securely in the environment and are not command-line options. The connector sends HTTPS GET requests only to `api.clarivate.com`, with redirects disabled.

For real searches, save the exact API-supported query in its own file. The adapter searches Core Collection (`WOS`); optionally set `--edition 'WOS+SSCI'` or an appropriate comma-separated list of subscribed editions. Omitted editions use the account's entitlement, whose precise coverage is not inferred by the program. Dates and other restrictions belong in the exact query, such as `PY=2024` or a documented `DOP` range. All requests use the explicit sort `LD+A`.

The default record cap is 50 and request budget is 10 per run. `--max-requests` counts every attempt including retries, and is not a daily quota tracker. Page size stays fixed throughout a run; the final raw page may contain records beyond the output cap. The manifest distinguishes `downloaded_count` from `returned_count` (selected output records). The program stops on missing pages, duplicate identifiers, changing totals or exhausted request budgets rather than claiming complete retrieval. A successful count refers to the results accessible to the API account. Database changes between pages can still affect a live search; retained raw pages document the responses actually received.

Starter returns citation metadata rather than abstracts or full text. Topic searches can match abstracts even though abstracts are not returned. Validate the query and available fields for the review question. [Official API schema](https://developer.clarivate.com/apis/wos-starter/swagger)

## PsycINFO and Web of Science RIS imports

Use your institution's authorized platform to execute the search and export RIS. These import adapters do not log into databases or execute online searches. APA documents RIS exports from PsycNet; Clarivate documents RIS among Web of Science export formats. [APA export help](https://askpubs.apa.org/s/article/I-need-help-exporting-references-from-APA-PsycNet), [Clarivate export help](https://webofscience.zendesk.com/hc/en-us/articles/20135124532113-Search-Results)

Confirm that your intended processing and any AI use of the exported content are allowed under the relevant terms; export permission alone does not establish that. For Radboud PsycINFO, use its Ovid platform and matching syntax, not the generic EBSCOhost template.

1. Save the **actual submitted search string/history** into a query file. The included PsycINFO template is specifically for EBSCOhost; Ovid, PsycNet and ProQuest require their own syntax. The Web of Science template is separate. Review all templates in the platform before use.
2. Copy the appropriate metadata template from `examples/` into `private/`. Enter platform, the actual search timestamp with timezone, filters, displayed total, exported result range, collection/indexes and timespan. For example, a known timestamp has the form `2026-11-13T15:30:00+01:00`. Leave unknown fields `null`; do not guess.
3. Save the authorized RIS export in `exports/`. For multiple batches, import each batch separately with its true range. Combine the resulting runs with `review` if needed; it retains provenance and uses only strong DOI/PMID matches for deduplication.
4. Run the matching adapter:

```sh
python3 -m researcher import --database psycinfo --file exports/psycinfo.ris --query-file private/psycinfo-query.txt --metadata private/psycinfo-metadata.json
python3 -m researcher import --database webofscience --file exports/webofscience.ris --query-file private/webofscience-query.txt --metadata private/webofscience-metadata.json
```

`exported_range` is an inclusive one-based pair such as `[1, 100]`. Its length must match the file's record count. For selected noncontiguous results, set it to `null` and explain selection in `notes`. Use `filters: {}` only when no filters were applied; use `null` if filters are unknown. Imports label coverage as user-reported or unverified; they never prove the original search was run by this program.

Only UTF-8 RIS imports are supported. Preserve the original export if you must convert its encoding, and note the conversion. RIS is the import format; BibTeX is an output format. Raw tags and raw files preserve information that may not map into the minimal citation schema. Citation exports do not replace source metadata checks.

## Testing and boundaries

```sh
python3 -m unittest discover -s tests -v
```

Tests use synthetic fixtures and mocked network calls. `doctor --online` separately checks live PubMed access and writes a real, explicitly partial one-record run. Run it inside the selected cloud environment too; local success does not prove cloud networking works.

The executable tools retrieve metadata, preserve supplied observations and assemble review workspaces. They do not automatically retrieve full text, appraise quality or establish research gaps. Those tasks require evidence review by the agent/user, with unsupported fields left unknown. A completed metadata search is not a completed systematic review. Keep licensed exports and private research in approved storage; this repository is public and intentionally ignores output folders.

