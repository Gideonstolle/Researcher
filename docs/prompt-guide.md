# How to ask Researcher to find literature

Open a **new task using the Researcher environment and the updated `main` branch**. Write your request in normal language; Codex prepares the queries, runs the available searches and records the steps. You do not need to write code.

For your first task, add: “Read AGENTS.md and check that PubMed works in this environment.” PubMed needs runtime HTTPS access to `eutils.ncbi.nlm.nih.gov`. Updating this repository does not itself change cloud network settings. See [setup](cloud-setup.md) if the check fails.

## The basic prompt

> Search **[engines]** for **[topic]**, focusing on **[population]**. Use **[dates, languages, study types]**. Retrieve **[all matches / a clearly labelled exploratory sample]**. Document the exact searches and selection decisions. Return **[a paper list / evidence table / candidate study questions]**.

Only the topic is essential. If you omit the engine, Researcher starts with **PubMed** and states that choice. If you omit other details, it states reasonable assumptions. For psychology questions, PubMed alone may miss relevant literature.

| Say this engine name | What Researcher can do |
| --- | --- |
| **PubMed** | Execute searches automatically, retrieve citation metadata and available abstracts, and save the exact query, NCBI translation, responses and counts. No API key is needed. |
| **Google Scholar** | Prepare exact search links and log actual user/browser-assisted observations. No automatic bulk scraper is included. If access is unavailable, you receive the link and the specific observations/export needed to continue. |
| **Web of Science** | Use the Starter API when an authorized key is configured; otherwise work from an authorized search and RIS export. Website login alone does not enable API access. |
| **PsycINFO** | Work from an authorized platform search and RIS export; specify the platform, such as **Ovid**. |

Naming several engines does not authorize silently replacing an inaccessible one. Search results, blocked attempts and unsearched sources remain distinct.

## Copy a prompt and change the topic

**Find papers using PubMed**

> Search PubMed only for empirical studies on pretend play and self-regulation in children aged 3–6, published from 2015 onward. Use a clearly labelled exploratory sample of at most 100 records per query. Record each query and why it was changed. Screen the retrieved abstracts and give me 10 relevant papers if enough qualify, with DOI/PMID links, study design and a short explanation of relevance. Do not invent missing information.

**Use Google Scholar**

> Use Google Scholar to look for studies on pretend play and self-regulation in preschool children from 2015 onward. Prepare suitable short queries and record the actual search settings, date, result ranks, pages checked and why each paper was selected. Review at most the first 30 results per query. If direct access is unavailable or restricted, give me the ready-to-open links and tell me exactly what observations or export to supply. Do not report a prepared link as an executed search.

**Use selected databases together**

> Search PubMed and PsycINFO on Ovid for social comparison and body image in university students, from 2015 onward. Keep separate database-specific queries and logs, combine the retrieved records and flag duplicates. Complete the PubMed work while identifying any Ovid access or export I need to provide. Do not add other engines.

**Explore a research gap and study question**

> Search PubMed and Google Scholar for pretend play and self-regulation in preschool children. Begin with an exploratory search and report its limits. Build an evidence table with study designs, populations, measures, findings, limitations and source locations. Identify three candidate gaps, check each with targeted follow-up searches, and suggest one feasible psychology bachelor study question for each. Explain what existing evidence supports or challenges each proposal, and distinguish a plausible gap from an unverified absence of studies.

**Ask for complete retrieval instead of a sample**

> Retrieve all PubMed matches for the agreed question. Do not truncate or switch to a sample. If the query is too broad for the retrieval limit, document narrower partitions before proceeding and retain every query version.

**Continue earlier work**

> Continue from [saved run folders or review folder]. Verify the saved search artifacts, reuse the existing criteria and preserve the earlier logs. Search PubMed for newer studies since [date], explain any query changes, and update the evidence table and candidate gaps in a new review version.

## What you receive

Ask for **“the search log and evidence table”** when you need work suitable for an assignment. Each run preserves the query, timestamps, counts/status, source responses or supplied observations, citations and checksums. A review also consolidates sources, records how each paper was found and provides an evidence table plus a gap-analysis document.

The review command initially creates blank screening and synthesis fields. Codex fills these only after reading the available evidence. A title or citation is not evidence for a study's findings; abstract-only reading must be labelled. A limited search can motivate a **candidate** gap, but cannot prove that a topic has never been studied.

Download or save the complete run/review folders before a temporary task ends. They are excluded from the public GitHub repository. Live search rankings and counts can change, so keep the original snapshots as well as the final report.
