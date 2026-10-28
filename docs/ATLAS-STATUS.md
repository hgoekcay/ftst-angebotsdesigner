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

- ATLAS 0.3.0 is installed. Telegram and the explicit Qwen3 Instruct model were tested.
- STRATO mail preview, local summaries and reply drafts are implemented. ATLAS mail
  access is still disabled; the existing separate mail service is running.
- AngebotsDesigner 0.27.4 is installed.

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

1. Release 0.4.1 fixes a transient SQLite finalization failure found during review; its CI and deployment remain pending. Verify the Designer interface after its completed update.
2. Online service needs an API key entered directly into the masked Home Assistant
   configuration. No key is available in this working session. Ten requests per day
   limits request count, not currency cost; actual provider access remains untested.
3. Activate the narrowly scoped mail bridge only through the applicable access-grant
   workflow. Do not expose existing tokens or copy them into project files.
4. Bookkeeping ingestion, reconciliation, adviser exports, scheduled workflows and
   broader assistant actions are future implementation, not completed functionality.
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
- Initial complete index: 154 parsed files, built against the current working tree including new source files, rather than falsely claiming an exact clean release commit. The rebuildable `.code-review-graph/` cache is ignored by Git.
- Graph findings require source verification: dynamic Telegram calls were missing and a naming-based test query returned unrelated tests. Do not treat the graph as proof of complete call or test coverage.
- Review reproduced a queue finalization bug after temporary SQLite write failure. The fix retries local result persistence only, preserving exactly-once execution attempts.
- No graph service, development hook or embedding provider was installed in production.
