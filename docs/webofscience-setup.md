# Web of Science API setup for Researcher

The supported integration is **Web of Science Starter API v1**, searching Core Collection (`WOS`). It is optional; PubMed and RIS imports still work without it. No Web of Science password belongs in this repository.

Prepared on 13 November 2026: the full offline suite passes (67 tests). No live Web of Science request has been made because no API key is configured. Cloud secret substitution and account entitlement must be checked using the live probe below.

## 1. Obtain an API subscription

1. Visit the [Clarivate Developer Portal](https://developer.clarivate.com/apis/wos-starter) and sign in or register. A personal Web of Science website account does not itself establish an API subscription.
2. Open Applications and register an application named **Researcher**, choosing an available unique application ID (for example, `gideonstolle-researcher`).
3. Subscribe that application to **Web of Science Starter API**. For a personal evaluation without institutional API access, the currently listed **Free Trial Plan** allows 50 requests per day and one request per second. Other plans require the stated eligibility; do not select an institutional plan solely because you have a personal login.
4. Review the applicable agreement yourself and describe the intended cloud AI literature-search use accurately wherever a use case is requested. A key proves technical access, not that every downstream use is permitted. If the offered terms do not clearly permit this use, ask Clarivate before sending licensed results to the agent. The public API terms links could not be fetched during preparation, so AI-use permission has not been verified here.
5. After the subscription is active/approved, open the application's subscription and obtain its API key. Keep it for the secure cloud field below. Do not put it in a prompt, screenshot, Git commit or a copied shell command.

The portal associates subscriptions and credentials with applications. Use this application's key for Researcher. [Clarivate application instructions](https://developer.clarivate.com/help/application), [API-key authentication](https://developer.clarivate.com/help/api-access)

## 2. Configure the existing cloud environment

In **Set up researcher**, use the latest `main` of `Gideonstolle/Researcher` and read AGENTS.md.

In the current Cloud configuration, request a **personal network secret / HTTP secret** named `WOS_API_KEY`, with allowed destination `api.clarivate.com`. Enter the actual key through the secret interface or Personal vault, scoped to this environment. Make sure the environment requests that same name: unrequested personal values are not passed to a task. The program sends its value as the `X-ApiKey` header; network-secret substitution keeps the actual value out of the process.

Allow HTTPS to `api.clarivate.com` on port 443 and GET requests. `developer.clarivate.com` is for human account management; the program's API calls do not use it. `www.webofscience.com` is only needed if you open result links in a browser.

Save, test, publish/republish, and verify in a new task. Existing tasks can retain old state. [Official Cloud configuration instructions](https://learn.chatgpt.com/docs/environments/cloud-environments#configure-environment-variables-and-network-secrets)

If your interface only has legacy setup secrets that disappear before the agent phase, that is insufficient for this runtime connector. Use a supported runtime credential mechanism; do not work around it by saving the key in source files or printing it into setup logs.

## 3. Test once the key is configured

From the repository root, with Python 3.10+:

```sh
bash scripts/setup.sh
python3 -m researcher doctor --database webofscience --online
```

The online probe normally makes one API request (up to three attempts on transient failure), asks for one record, and labels a capped result set `partial`. Verify the actual output folder printed by the command:

```sh
python3 -m researcher verify runs/PASTE-THE-ACTUAL-RUN-DIRECTORY-NAME
```

Inspect the query, raw page, total accessible matches, returned UID, status, RIS and BibTeX. Never print the key while troubleshooting. A correct result requires an API response and saved artifacts; successful offline tests or a visible login page are not live API verification.

Optional five-record example after the initial check succeeds:

```sh
python3 -m researcher webofscience --query-file queries/webofscience-api-demo.txt --max-records 5 --allow-partial --max-requests 3
```

## 4. Interpret failures and coverage

| Result | Action |
| --- | --- |
| Missing WOS_API_KEY | Check the requested secret name and selected environment scope; no request was sent |
| HTTP 401 | Check the active application's Starter key; website passwords and Expanded keys are not interchangeable |
| HTTP 403 | Check subscription approval, collection/edition entitlement, permitted use and network policy |
| HTTP 400 | Inspect the archived error; correct the exact API query without silently changing its meaning |
| HTTP 429 / quota message | Check the plan's remaining quota/reset; retries count as requests |
| DNS, connection or TLS error | Check the exact API hostname and configured proxy/certificates; do not disable TLS verification |
| Record cap exceeded | Narrow the query, increase the cap within your quota, or explicitly permit a partial result |
| Request budget exhausted | Preserve the failed run; plan a narrower query or explicit larger budget after checking the daily allowance |

The adapter spaces requests conservatively, retrieves pages of at most 50 records, and uses a per-run request budget. That budget does not track your full account's daily usage. A successful run does not prove comprehensive coverage outside the API account's entitlements.

Starter does not supply abstracts or full text in its documented record schema. The adapter cannot produce evidence summaries requiring those sources from citation metadata alone. [Official API specification](https://developer.clarivate.com/apis/wos-starter/swagger)

Keep raw responses and citations under ignored `runs/` and in approved research storage. They are not uploaded to this public repository.
