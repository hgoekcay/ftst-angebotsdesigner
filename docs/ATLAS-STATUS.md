# ATLAS and FTST project state

Updated: 2026-10-28. This file is the current continuity record, not an instruction
to perform unapproved external actions. Check live versions before deployment.

## Goal and decisions

- ATLAS is intended to become a company assistant for knowledge, tasks, mail drafts,
  research and preparation of bookkeeping documents for the tax adviser.
- Telegram is the first messaging channel. WhatsApp and telephony remain future work.
- Local inference remains available. The user also requested optional online advice
  and research. This uses a separate API; it cannot contact a private ChatGPT thread.
- The user requested Apple-inspired design across the programs and Code Review Graph
  for understanding dependencies. A code graph complements this decision record.
- Existing company branding and quotation/PDF output remain meaningful product inputs.

## Delivered before the current release

- ATLAS 0.3.0 was the installed starting point. Telegram and the explicit Qwen3 Instruct model were tested.
- STRATO mail preview, local summaries and reply drafts are implemented. ATLAS primary-mailbox access is now enabled for the owner; the existing separate mail service is running.
- AngebotsDesigner 0.27.4 was the installed starting point.

## Current release: PR 62

- ATLAS 0.4.0 adds owner-scoped OpenAI advice, optional web search with citations,
  a configurable daily request limit and explicit local/online/automatic modes.
- Online context is only the current question by default; the company profile is
  optional. Mail, saved memories and full conversation history are not sent automatically.
- Web requests use durable jobs; results remain available under Tasks for seven days.
  Interrupted running jobs are marked failed rather than replaying a possibly paid call.
  Telegram processing is still synchronous, not part of the durable queue.
- ATLAS receives adaptive light/dark styling and mobile navigation. AngebotsDesigner
  0.27.5 receives a shared screen-only stylesheet, keeping print/PDF styling separate.
- Local verification: 68 ATLAS unit tests, JavaScript syntax, Python syntax and diff checks passed.
- Full CI passed: 1128 tests and 35 subtests on Python 3.13, with all five workflow jobs successful. PR 62 merged as `80dd204722f130d904785ae0c00ec5f400f35484`. Both updates were installed with the Home Assistant backup option enabled. A local ATLAS job completed and its stored result was reopened successfully. All five ATLAS views were checked; desktop dark appearance was inspected. Mobile and light-mode rendering have not yet been visually verified.

## Remaining work and concrete blockers

1. ATLAS 0.4.1 and Designer 0.27.5 are installed and running. All five CI jobs passed (1131 tests plus 35 subtests on Python 3.13). PR 63 merged as `d0bff4a0c060c9c9d5a985939b0e02ce54725b05`. The local job and its answer remained accessible after the 0.4.1 update/restart. Designer shared interface was visually verified. Continue with API access and the remaining integrations below.
2. Online service needs an API key entered directly into the masked Home Assistant
   configuration. No key is available in this working session. Ten requests per day
   limits request count, not currency cost; actual provider access remains untested.
3. Activate the narrowly scoped mail bridge only through the applicable access-grant
   workflow. Do not expose existing tokens or copy them into project files.
4. Bookkeeping 0.5.0 implementation is in release validation (see below). Bank reconciliation, full historical coverage and tax filing remain future work.
5. Do not treat generated replies as sent mail or prepared documents as filed accounts.

## Component map

| Component | Main files | Validation |
| --- | --- | --- |
| ATLAS HTTP and local model | `ftst_atlas/app.py` | `tests/atlas/test_backend.py` |
| Telegram | `ftst_atlas/telegram_bridge.py` | `tests/atlas/test_telegram.py` |
| Online provider | `ftst_atlas/online_client.py` | `tests/atlas/test_online_client.py` |
| Durable work and routing | `ftst_atlas/jobs.py`, `app.py` | `test_jobs.py`, `test_routing.py` |
| Mail preview | `ftst_atlas/mail_client.py` | `test_mail_client.py` |
| ATLAS interface | `index.html`, `app.js`, `style.css` under `ftst_atlas/` | syntax and live UI |
| Designer shared interface | `ftst_angebotsdesigner/app.py`, `static/apple-design.css` | full CI and live UI |

Code Review Graph is development tooling. Do not add it to production addon images
or start automatic repository hooks merely to use a review skill.

## Development continuity and graph review

- Personal Code Review Graph skill installed and independently tested. CLI 2.3.9 is available in the development environment.
- Initial complete index: 154 parsed files; after the fix, an incremental refresh updated five files. The graph was built against the current working tree including new source files, rather than falsely claiming an exact clean release commit. The rebuildable `.code-review-graph/` cache is ignored by Git.
- Graph findings require source verification: dynamic Telegram calls were missing and a naming-based test query returned unrelated tests. Do not treat the graph as proof of complete call or test coverage.
- Review reproduced a queue finalization bug after temporary SQLite write failure. The fix retries local result persistence only, preserving exactly-once execution attempts.
- No graph service, development hook or embedding provider was installed in production.

## STRATO service repair (2026-10-28)

The existing local STRATO mail addon stopped during configuration validation after four additional accounts were entered with invalid account IDs (uppercase/spaces) and blank folders. Corrected only their logical IDs to lowercase underscore names and set folders to INBOX, preserving credentials and enabled states. Saved through Home Assistant and started the service. Live logs confirmed application startup and a successful mailbox monitor check. This verifies the primary monitored mailbox, not each additional account's authentication. ATLAS access was still disabled at this repair checkpoint; see the subsequent activation below.

## ATLAS mail connection enabled (2026-10-28)

After explicit user confirmation, enabled read-only primary-mailbox access for the existing owner HA account. Reused the existing bridge token entirely on the Home Assistant host without exposing it. Supervisor validated the options and restarted ATLAS. UI preview successfully returned ten messages and correctly indicated more matching messages outside the bounded preview. No mail was sent, deleted or marked read. Additional mailboxes and attachment ingestion are not included in this ATLAS connection.

Live follow-up: local summary of one retrieved message completed successfully. No customer content was copied into the project record.


## ATLAS 0.5.0 preparation (2026-10-28)

Implemented locally: explicit multi-mailbox selection, bounded invoice MIME import, immutable document store and review history, owner-scoped Billomat GET client, durable resumable periodic synchronization, monthly original/CSV/manifest/unresolved ZIP, upstream documents/1 export bridge, Telegram reporting and separate employee upload service. New access scopes, periodic jobs and public exposure default off. Existing primary-mail access is preserved when the mailbox allowlist is empty.

User additionally requested all configured mailboxes, Telegram open-items/missing-document reporting, and employee upload access. Personal upload links grant upload-only access; no employee receives company-mail or full-bookkeeping reads. URLs require a separately configured HTTPS origin, not an ingress-session URL. Tokens must never enter the public repository or logs.

Module map: `bookkeeping.py` stores/extracts/reviews; `bookkeeping_export.py` emits conservative AI Bookkeeping interchange; `atlas_billomat_client.py` avoids collision with Designer's distinct client; `bookkeeping_sync.py` persists bounded source cursors; `bookkeeping_reports.py` builds deterministic reports; `submissions.py` handles scoped invitation hashes and uploads; `submissions_server.py` serves only employee upload routes. `app.py` keeps owner routes behind ingress+CSRF. The existing Telegram owner gate also protects reports.

Original AI Bookkeeping skill installed in the user's skills, full upstream scripts/license/references at revision 8ccff9c7cbd1b568e3bd469a4d457b50ab381781. Synthetic upstream tests passed. This is separate from the production service. The upstream ready check warns rather than fails on missing receipts; ATLAS therefore retains its own unresolved status. The documents bridge was accepted by upstream staging and intentionally remained review-blocked with needs_tax=true. No inferred chart of accounts, payment reconciliation or tax filing.

Release validation and deployment are pending at this checkpoint. Live ATLAS remains0.4.1 until a verified update. New all-mail/Billomat access and external upload routing have not yet been activated. PDF/image/OCR, pagination and export limits are documented in addon DOCS.md. Avoid claiming complete books or a bank-reconciled OP list.


0.5.0 validation checkpoint: 154 ATLAS unit/integration tests passed locally, including owner/CSRF isolation, immutable originals/month exports, revocable employee access and separate public HTTP routes. JavaScript syntax and whitespace checks passed. Code Review Graph was refreshed against the working tree including new files via a temporary Git index; import edges for bookkeeping and submissions were inspected and source-verified. UI fragment-token adjustment is receiving its final integration check; full repository/container CI and live installation still pending.


Release 0.5.0 merged via PR64 as d927f552da55d45b9cedeaf6b8199fc951fe48b4. Final head21016f47f447425d7af62060d2e0d3c21a48dd9b passed all six GitHub Actions jobs, including both Python versions, ATLAS image wiring, mail image, local-AI image and browser tests. Python3.13:1216 tests and97 subtests passed. Local ATLAS:156 tests passed. Initial whole-suite import-path leakage was corrected and regression-checked; no Designer production change was needed. The employee browser-flow test is preserved as tests/atlas_upload_browser.cjs. Live update is next; new sensitive access remains unactivated.
