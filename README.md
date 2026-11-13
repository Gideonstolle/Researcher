# Researcher

Academic researcher for Psychology. This is a small, executable literature-search workflow for Codex, with durable instructions in [AGENTS.md](AGENTS.md).

It runs PubMed searches through NCBI E-utilities, imports authorized PsycINFO and Web of Science RIS exports through separate adapters, and produces RIS/BibTeX citations plus an audit trail. No OpenAI API key, browser automation, subscription API entitlement, or extra Python packages are needed.

## What was missing

The repository initially contained only the title and description above. There was no search command, query logger or agent instruction file. The reported symptom was selection of Consensus instead of the requested databases, not a failed program. Instructions given in a setup conversation had not been committed here. The executable commands and AGENTS.md now make the requested workflow available to tasks checking out this repository.

The cloud setup chat itself has not been inspected from this local workspace. Its repository selection, publication status, network settings and instruction propagation remain to be verified. See [cloud setup and diagnosis](docs/cloud-setup.md).

## Quick start

Use Python 3.10 or newer from the repository root:

```sh
bash scripts/setup.sh
python3 -m researcher doctor --online
python3 -m researcher pubmed --query-file queries/pubmed-demo.txt --max-records 5 --allow-partial
```

The last command is a **partial demonstration**, not a complete literature review. The sample topic is cognitive behavioral therapy and insomnia; replace it with your actual search strategy. Exact file contents, including the final newline, are submitted and logged without trimming. UTF-8 byte-order marks are rejected to avoid silently changing a query.

On this Mac, `/usr/bin/python3` is 3.9. Use the installed newer interpreter if `python3` selects that version:

```sh
PYTHON_BIN=/opt/homebrew/bin/python3 bash scripts/setup.sh
/opt/homebrew/bin/python3 -m researcher doctor --online
```

For a complete retrieval, omit `--allow-partial` and set a cap sufficient for the query (maximum 10,000). If hits exceed the cap, the command records the count and fails before fetching citations. Narrow or deliberately partition broad queries; this version does not automate query partitioning or deduplication. PubMed ESearch cannot return beyond its first 10,000 matches. [NLM limit](https://www.nlm.nih.gov/pubs/techbull/so22/so22_updated_pubmed_e_utilities.html)

Configure `NCBI_EMAIL` as your contact address in the environment settings when using E-utilities routinely. `NCBI_API_KEY` is optional; the workflow works without one and uses conservative request spacing, timeouts and finite retries. Credentials are excluded from request logs. Do not put keys in query files, Git, or prompts. [NCBI usage guidelines](https://eutilities.github.io/site/API_Key/usageandkey/)

## What each run saves

The command prints its new directory under `runs/`:

| File | Purpose |
| --- | --- |
| `query.txt` | Original query file bytes |
| `manifest.json` | Exact query, software/source hashes, start/end timestamps, database, counts, translation, warnings and status |
| `events.jsonl` | Timestamped query/request/retry/completion events; credentials redacted |
| `raw/` | PubMed responses or the original authorized RIS and search metadata |
| `records.json` | Normalized citation records |
| `citations.ris`, `citations.bib` | Reference-manager exports |
| `checksums.json` | SHA-256 inventory for detecting accidental changes |

Failed runs keep their query, available responses, error and checksums. They do not claim to be zero-result successes. Complete, partial, failed and imported states are distinct.

```sh
python3 -m researcher verify runs/PASTE-THE-PRINTED-RUN-DIRECTORY-NAME
```

Snapshots let you inspect what happened even if database content later changes. Live reruns may produce different results. Checksums detect accidental changes; they are not signed proof against deliberate tampering. Run directories are never reused automatically, but remain ordinary editable files.

## PsycINFO and Web of Science

Use your institution's authorized platform to execute the search and export RIS. These import adapters do not log into databases or execute online searches. APA documents RIS exports from PsycNet; Clarivate documents RIS among Web of Science export formats. [APA export help](https://askpubs.apa.org/s/article/I-need-help-exporting-references-from-APA-PsycNet), [Clarivate export help](https://webofscience.zendesk.com/hc/en-us/articles/20135124532113-Search-Results)

1. Save the **actual submitted search string/history** into a query file. The included PsycINFO template is specifically for EBSCOhost; Ovid, PsycNet and ProQuest require their own syntax. The Web of Science template is separate. Review all templates in the platform before use.
2. Copy the appropriate metadata template from `examples/` into `private/`. Enter platform, the actual search timestamp with timezone, filters, displayed total, exported result range, collection/indexes and timespan. For example, a known timestamp has the form `2026-11-13T15:30:00+01:00`. Leave unknown fields `null`; do not guess.
3. Save the authorized RIS export in `exports/`. For multiple batches, import each batch separately with its true range. This version does not merge or deduplicate batches.
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

This minimum workflow retrieves metadata. It does not perform automatic full-text retrieval, quality assessment, screening, synthesis, deduplication or a complete systematic review. Keep licensed exports and private research local to approved storage; this repository is public and intentionally ignores output folders.
