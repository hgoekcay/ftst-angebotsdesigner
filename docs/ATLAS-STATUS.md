# ATLAS and FTST project state

Updated: 2026-10-31. This file is the current continuity record, not an instruction
to perform unapproved external actions. Check live versions before deployment.

## Latest verified state

ATLAS 0.8.2 is installed and was verified through the authenticated Home Assistant
browser. A live local text request completed and appeared in chat automatically.
Piper playback/start advanced to microphone acquisition; this remote browser has
no microphone, so physical iPhone conversation remains unverified. Preparing 0.8.3
for accepted voice-job recovery and older Billomat open-item refresh. See the final
checkpoint for validation/deployment status. Online provider remains disabled.

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


Live0.5.0 installed with backup enabled. Primary-mail preview still returned ten messages after upgrade; no message content retained in the repository. The first live bookkeeping render exposed a missing HTML hint element in the release snapshot (local HTML had it). Corrective PR65 ships the element and adds a real HTML-vs-JavaScript ID check to browser CI. All six jobs passed; merged as b4af02a1781baa270639e83c94fe520705da56b6. Version0.5.1 corrective installation is in progress. All-mail/Billomat activation, daily Telegram reporting and public employee routing still await the required action-time access confirmation.


Final live checkpoint: ATLAS0.5.1 installed and running; backup option enabled for both upgrades. Live bookkeeping page renders without the missing-element error, shows the disabled authorization state and no imported data. Existing primary-mail preview was verified after0.5.0 and codepath unchanged in0.5.1. New owner sources, automatic sync, Telegram daily report and employee listener remain disabled. User-facing proof screenshot captured without customer mail contents.

Next concrete action after action-time confirmation: enable the five already configured STRATO accounts (do not implicitly include future accounts), owner-scoped Billomat GET access reusing Designer credentials only on the HA host, hourly invoice import with initial30-day lookback, optional09:00 Europe/Berlin report to the existing owner's Telegram, and an isolated upload origin. Proposed hostname `belege.ftsicherheit.org` would route only to `http://76b650ab-ftst-atlas:8100` through the existing Cloudflared additional-host facility. No such route has been created and hostname availability/DNS must be verified before applying. Preserve existing tunnel configuration and all credentials; never copy them into this repository. Personal invitations are created by the owner and grant upload-only scope. Do not represent the preparatory workflow as complete accounting or bank reconciliation.

Additional user request: inspect TikTok shortlink vm.tiktok.com/ZGdConLSD and explain that Jarvis. Search/open could not access the video and exact-link search returned no results. Asked for direct video upload; no claim to have seen its contents.


## Live activation after explicit confirmation (2026-10-28)

This checkpoint supersedes the inactive-state notes above. The user explicitly confirmed activation. ATLAS 0.5.1 now has the five existing STRATO accounts allowlisted, owner-scoped read-only Billomat access, persistent document ingestion, hourly synchronization with an initial 30-day lookback, and a daily Telegram report configured for 09:00 Europe/Berlin. Existing credentials were reused only within the Home Assistant host process; none were copied into the repository.

Supervisor option validation and restart succeeded. Billomat snapshots and a bounded batch of PDFs were imported; remaining PDFs are queued for subsequent runs. Mail ingestion is partial: the invoice mailbox's IMAP login was rejected; the personal mailbox authenticated but contains messages exceeding the current 8 MiB whole-message limit. The primary mailbox also reports an incomplete/error state; its precise cause is not yet confirmed in this record. Two other configured sources completed their current bounded checks without source errors. Do not silently advance blocked cursors, skip messages, or claim complete historical coverage. Corrected credentials must be entered into the masked service configuration, never into chat or repository files.

The existing Cloudflared configuration was preserved and extended with belege.ftsicherheit.org routing only to the isolated ATLAS upload listener on port 8100. HTTPS access was verified. A temporary owner-created invitation opened the upload-only form; revoking it caused access to be rejected. The temporary invitation is revoked and no employee invitations were distributed. No receipt was submitted in this live smoke test; actual storage is covered by the release tests. The owner can create personal employee links in Buchhaltung > Mitarbeiter-Zugaenge.

One activation/status message to the existing Telegram owner was accepted by the Telegram API. This does not establish that the owner read it. The scheduled first 09:00 delivery has not yet been observed. Online OpenAI access remains unconfigured pending an API key. Tax filing, bank reconciliation, and complete bookkeeping are not delivered by this activation.

The additional TikTok link vm.tiktok.com/ZGdX18Bw6 was inaccessible through web retrieval. No video content was inspected; a direct upload is needed for a grounded explanation.


## Knowledge and mail reliability release preparation (2026-10-29)

ATLAS 0.6.0 adds owner-scoped knowledge search/tags, correction history with optimistic concurrency, and explicit task-to-knowledge links. Existing SQLite data migrates in place. Local answers use bounded current-note context with provenance; obsolete revisions are not used as current facts. Knowledge remains explicitly confirmed, not automatically extracted from incoming mail. Tasks remain a local list, not autonomous workflow execution.

STRATO 0.3.1 and ATLAS 0.6.0 align raw MIME32MiB, batch40MiB and bounded base64 response handling. Individual document attachments remain8MiB; skipped documents retain warnings. Larger raw messages still stop the cursor explicitly. Authentication, size and transport-limit failures propagate fixed non-secret error categories. This does not repair invalid mailbox credentials.

Validation: initial full Python suite1224 tests and101 subtests passed; independent review found a richly tagged note could exceed the prompt budget and disappear. Corrected with actual serialized-budget truncation and an additional regression; seven knowledge tests passed. Both Node UI harnesses passed. Real Playwright visual check unavailable locally because browser download was truncated. No live deployment at this checkpoint. Earlier activation remains as documented above.

Development graph2.3.9 available; existing import relationships source-checked. Release-tree graph rebuilt with staged new files and no embeddings; knowledge import into app.py verified. One intermediate concurrent validation snapshot was inconsistent; staged source was restored and validation rerun serially before release. Next: complete release validation, inspect UI, update installed addons with backup and verify bounded import/error behavior. No new external permissions, cloud context sharing or mail sending.


## Verified live knowledge release (2026-10-29)

PR66 merged as 9144ce66abf8a53d3d3fd9e86d0c63ec7d5fcd6c after all six CI jobs passed; Python3.13 reported1225 tests and104 subtests. Node suite29 checks passed. A stale static footer label found during live inspection was corrected in PR67, all six jobs passed, merged as e8cc39284cfab1321d25f2eca468e9bb335a544f.

Installed and observed running: ATLAS0.6.1 and local STRATO0.3.1. Supervisor updates used backup=true. The local STRATO source files were backed up separately and replacement files verified by SHA256 against the merged public source; credentials/options were preserved.

Live verification: existing knowledge survived migration; saved a confirmed public company-brand fact, found it by search, corrected its source, and observed both revisions. Created a linked development task; note/history/link survived the subsequent update and restart. Local Qwen answered a question using the stored company-brand fact correctly. Desktop dark UI was visually inspected and captured. Mobile/light rendering remains unverified.

The formerly size-blocked primary and personal mailbox imports now advance and yield additional document candidates. The primary mailbox's previously uncertain blocker was confirmed as an over8MiB message. Invoice-mailbox authentication still fails; the mail preview now explicitly displays the sanitized STRATO login-rejected message. Its saved credentials need correction by the owner. Bookkeeping's per-source summary still uses its generic incomplete-import error; do not claim that view has the detailed error. Further PDFs and unresolved attachment/document warnings remain; no complete or bank-reconciled accounting claim.

Next development: entity/project knowledge organization and bounded multi-step workflows, then voice integration and central dashboard. Current task links aid context retrieval but do not execute workflows. No automatic mail-to-memory ingestion or model training; optional cloud service still lacks a configured API key. Do not re-enable scopes or resend invitations merely because earlier historical sections describe disabled state.


## Workflow and voice release preparation (2026-10-29)

ATLAS0.7.0 implementation adds bounded briefing/monthly preparation workflows,
durable step progress, owner-scoped retained ZIP artifacts and explicit Telegram
start/status commands. Local Whisper/Piper voice uses fixed Wyoming endpoints;
recordings or uploaded audio produce a reviewable composer transcript, never an
automatic command. Speech output is explicit. Voice defaults off, owner-scoped,
5MiB/60s input and2000characters output, one request at a time.

Live prerequisite check: existing Whisper3.5.3 and Piper2.5.2 are running and TCP
reachable. This does not yet verify end-to-end transcription or speech generation.
Code integration, full validation and installation are pending at this checkpoint.
No new customer sends, payments, tax filing or external cloud access.

Validation checkpoint: complete local suite1280 tests and104 subtests passed; all30 Node checks passed, targeted Python lint and whitespace checks clean. Independent module review corrected UI/server speech timeouts and added current-permission filtering for historical mixed briefing results. Code Review Graph rebuilt against the staged release tree:177files,2448nodes; app imports of workflow/voice/jobs and voice importer source-verified. No embeddings or production graph service. Release CI and live update remain pending.

Live0.7.0 installed with backup=true after all six CI jobs passed; PR68 merged1368e186cb4154966ccfb8160143455a7e16bbd5. Existing owner configured for local voice. Briefing completed all four steps. Piper produced local audio and Whisper transcribed the synthetic German test via local Wyoming; this is not a microphone accuracy guarantee. Monthly workflow reached export, which failed with a generic error. A bounded correction preserves only source-reviewed export error messages, with9tests and12subtests passing including101undated originals. Actual live failure cause not yet confirmed. Docker exec was blocked by terminal protection; protection remains enabled. No credentials or private content copied.

Live0.7.1 installed with backup after all six CI jobs passed; PR69 mergedd97c19d9becaae59f391f8bc7626ae77ee11d6b9. Exact export blocker confirmed: the100-document selection ceiling, including undated records. Preparing0.7.2 to align that count with the existing2000-record store ceiling while retaining cumulative100MiB original/snapshot/metadata limits and no omission. Synthetic audio-file upload through the actual ATLAS UI transcribed correctly into the composer without sending; browser automation timed out after the operation, but the resulting DOM text was verified. Local readaloud completed without UI error; physical microphone capture remains untested.

Live0.7.2 installed with backup; PR70 merged1d1f1090d7b268f1a4472d964aaa85ccbb33ceaf, all six CI jobs passed (Python3.13:1281 passed,4 ffmpeg-dependent skips,116 subtests; real codec tests were verified locally earlier). October workflow now completed all four steps and created an artifact with incomplete-source warnings preserved. Live large-download checks produced truncated ZIPs; investigating the handler's15-second socket-write timeout. Do not claim a verified downloadable package until CRC/hash checks succeed.


## Final verified workflow and voice checkpoint (2026-10-29)

PR71 merged394ab736955ae74667ffde3bad21e494bc8ea910 after all six CI jobs passed.
Python3.13:1284 passed,4 codec-dependent skips,116 subtests. The real codec tests
passed locally and a live uploaded synthetic WAV produced the expected composer
text without sending it. Piper/Whisper local protocol roundtrip was verified; live
readaloud completed without a UI error. Physical microphone capture, mobile and
light-mode visual checks remain unverified. Telegram command routing is covered by
tests; no new live owner Telegram command was sent during this release check.

Installed ATLAS0.7.3 observed started; all four release updates used backup=true.
Tagesüberblick completed all steps. Monthly preparation completed and preserved
incomplete-source warnings. The retained artifact survived the subsequent addon
update. After the scoped120-second attachment write timeout correction, the actual
monthly archive downloaded completely; ZIP CRC, all manifest original SHA256
hashes, month, CSV, unresolved report and documents/1 presence were verified. No
financial counts, invoice contents, credentials or private identifiers are stored
in this public record. Earlier truncated test downloads are not usable deliverables.

Current boundaries: up to2000 selected records including undated originals and
100MiB total original/snapshot/metadata budget. Incremental metadata checks prevent
unbounded accumulation across records; one record's history is still loaded eagerly,
so this is not a strict process-memory cap. Artifacts are owner-scoped, seven days,
latest three per owner and ten globally. No automatic replay of interrupted jobs,
no arbitrary tool execution, mail sends, payments, filing or bank reconciliation.

Next concrete work: resolve invoice-mailbox authentication through masked owner
configuration, review unresolved documents/coverage, then organize project/entity
knowledge and a consolidated dashboard. Optional online access still requires an
API key. Voice input is reviewed text, not a general autonomous action permission.


## Voice dialogue implementation checkpoint (2026-10-29)

ATLAS0.8.0 adds an explicit half-duplex conversation mode in the existing chat.
Local Whisper transcription is dispatched only while this mode is actively enabled;
Piper reads the result and the microphone reopens only after playback ends. Stop,
page change, backgrounding, failure and the ten-minute session limit stop future
turns. The original review-before-send recording mode remains available. Browser
silence detection uses bounded local audio levels, not semantic speech detection.

`dialog.py` accepts only explicit task-create, briefing and monthly-preparation
commands. General questions use existing response routing; model output cannot
select or execute tools. Existing Ingress, CSRF, voice-owner and workflow grants
apply, with a new check before queued execution. UUID request keys are committed
atomically with jobs; retries reuse the original job. Retained bounded tombstones
prevent replay after seven-day result cleanup. A saved task is explicitly described
as an open list item, not completed real-world work. No new sends/payments/filing.

Source-verified graph baseline:169 files,2398 nodes at32b26a6 on the release branch;
app imports of jobs/workflows/voice checked. Graph is local tooling, not a running
business-memory service. Review and release validation continue below. Installation
remains0.7.3 at this implementation checkpoint; physical microphone capture and
mobile autoplay are unverified. Online access still lacks its API key. The invoice
mailbox again returned login rejection; no credential changes attempted.

Private document triage found mixed document classes and incomplete extraction;
do not interpret every imported document as an unpaid invoice or missing receipt.
No review statuses, tax amounts or payment states were changed by that read-only
inspection. Next accounting work: classification and extraction with provenance,
correction/duplicate relationships and owner/period review before missing-receipt
requests. Private findings are intentionally absent from this public repository.

Validation: complete local suite1322 tests and116 subtests passed; after the final
parser/test additions the affected dialog/HTTP/queue/workflow/voice suite72 tests
and17 subtests passed. All31 Node checks, targeted Python lint and whitespace
checks passed. Independent review found no blocking authorization/replay issue.
Physical microphone/iOS/autoplay remain unverified. Publication and installation
are pending at this checkpoint.


## Installed voice dialogue checkpoint (2026-10-29)

PR72 merged5400b3307ac947dcada26d35187bb909a4e3eccc after all six CI jobs passed.
Python3.13 reported1323 passed,4 codec-dependent skips and116 subtests. The release
was installed through Supervisor with backup=true; version0.8.0 and started state
were observed. Existing voice-owner options were retained, no scopes expanded.
Live UI displayed the enabled Gespräch starten button, command help and default-off
microphone state. A real click in the cloud browser returned no microphone device
and safely left dialogue stopped. This verifies failure handling, not a spoken
end-to-end conversation. Physical microphone/iOS/autoplay remain to be tested on
the user's device. Prior local Whisper/Piper protocol and synthetic-file tests do
not establish that hardware behavior. No new real-world task was sent for this test.

Final local graph rebuild:181files,2508nodes; app/test imports of dialog.py were
checked against source. Graph parsing has unresolved/ambiguous static imports and
is not proof of full dynamic call coverage. No graph service, embeddings or hooks.
Next voice check: start the installed mode on the owner's microphone device, ask a
simple question, verify playback/rearm, then explicitly save one task and verify it
once. Accounting classification/extraction and masked invoice-mailbox credential
correction remain outstanding; online access still needs a configured API key.


## Voice-start correction preparation (2026-10-29)

Owner reports no answer or greeting after clicking conversation. Source confirms
0.8.0 had no startup greeting and relied exclusively on an audio-level pause
heuristic to finish each utterance. The actual owner's device failure is not yet
identified; no claim that autoplay or permission was the observed root cause.

Preparing0.8.1: local Piper greeting before listening; the AudioContext is resumed
inside the start gesture and reused for decoded WAV playback. Explicit phase text,
German microphone/output errors and bounded waits avoid an unexplained silent
start. Jetzt antworten provides a deliberate recording finish independent of the
pause detector. Existing owner/CSRF boundaries and manual review mode remain.

Code Review Graph CLI is absent in the resumed environment; this change uses rg,
source/diff tracing and tests, not a claimed refreshed graph. The previously built
graph is historical. Cloud Browser now displays the HA sign-in page; live logs,
installation and physical microphone validation remain blocked by authentication.
Do not mark this release installed until Supervisor and UI are observed again.

Local validation:31 Node checks pass, including greeting-before-microphone, no
command after canceled greeting/decode, blocked resume timeout, manual quiet-input
finish and WebAudio start/cleanup failures. Python compileall and whitespace check
pass. pytest is not present in this resumed environment; Python and container
validation will run in release CI. No claim of an iPhone hardware fix is verified.

Release0.8.1: PR73 merged10a2d2cfa423a812d4b382eef6357ebfd43d1a98 after
all six CI jobs succeeded. Independent review identified a stale recorder-stop
event affecting the next session; the live/recorder-identity guard and regression
test were added before publication and relevant UI tests passed again.

Installation is still pending. Secure browser login submitted but did not produce
a confirmed authenticated page; fresh verification returned the sign-in form.
Owner now clarifies that input produces text but no audible reply. This narrows
the symptom toward the output path, but the device-specific cause remains unknown.
The prepared release reuses the gesture-enabled WebAudio context for all automatic
replies. Next step: restore authenticated HA access, install with backup, verify
Piper greeting/output through the actual UI, then verify on the owner's device.


## Voice-first web app — implementation checkpoint (2026-10-31)

Prepared a JARVIS-inspired conversation surface in the existing ATLAS app:
- Conversation appears first, above example prompts and routing controls.
- Decorative teal orb follows explicit starting, listening, processing, speaking,
  stopped and error states from the existing dialogue lifecycle. Text labels remain
  available, motion respects prefers-reduced-motion, existing feature IDs retained.
- Start/stop remains explicit; manual answer is a secondary fallback. This change
  does not add full-duplex interruption, background microphone use or new tools.

Validation: dialogue, workflow/voice, knowledge and public upload Node UI suites
pass; JS syntax and whitespace checks pass. Browser screenshot validation was
attempted but could not run: this resumed environment has no Chromium executable.
Responsive layout therefore still needs rendered review and an actual iPhone test.
No Home Assistant deployment or device-level voice fix is claimed.

Separate draft PR #75 addresses transient result-polling failures. That patch is
not included here; combine and test before a release. User reports updating the
previous release, but current installed state has not been independently observed.


## 0.8.2 test update preparation (2026-10-31)

Owner explicitly requests a GitHub update for installation/testing. Combined the
voice-first UI from PR #76 with bounded GET-only result recovery from PR #75.
Version/config/container CI build argument are 0.8.2. No integration settings or
stored data are migrated. Existing experimental add-on stage remains unchanged.
Local dialogue regression suite verifies recovered text and spoken replies without
replaying POST, timeout of stalled response bodies, cancellation and phase states.
Browser rendering and physical iPhone verification remain outstanding. Release CI
must pass before merging; no installation on the user's Home Assistant is claimed.
The earlier separate-branch checkpoint above is superseded by this combined update.


## 0.8.3 reliability checkpoint (2026-10-31)

Implemented: accepted voice jobs retain one read-only status waiter after explicit
stop, navigation or backgrounding. Completed answers render once as text, without
restarting audio/microphone or contaminating a newer conversation's model history.
No POST is replayed. Full page reload still relies on the durable Tasks result.
Independent review reproduced a stale-history race; a red/green regression and
live-session history guard address it before release.

Known unresolved Billomat invoices now refresh by ID outside the rolling discovery
window. A durable owner-scoped cycle processes at most 25 per sync; failed IDs
remain pending without starving later IDs. Reports show incomplete refresh coverage.
Already closed invoices and never-imported historical invoices are outside this
repair. This is source-status reporting, not bank reconciliation.

Live evidence on 0.8.2: normal browser authentication works; local text roundtrip
returned successfully after a noticeable wait. Existing background jobs contain
valid model replies. Automated bookkeeping sync is active but source coverage is
incomplete, including a mailbox whose read-only preview explicitly reports rejected STRATO login.
Its credentials must be corrected through secure configuration. Some imported attachments are not invoices;
classification/review needs improvement. No company documents or identifiers are
recorded here. No production configuration, credentials or document reviews changed.

Validation/deployment: all 31 Node checks and 52 bookkeeping tests passed, along
with Python compileall and whitespace checks. Broad local unittest discovery ran
191 tests but four modules could not import because pytest is absent; full Python
validation is delegated to CI. CI release checks and 0.8.3 installation are pending. Do not claim
that the original active-screen iPhone symptom has been reproduced or fully solved.

Next: publish the tested patch, install with backup, verify version and text response;
then repair source-specific import errors, distinguish attachment intake from confirmed
invoices, add bank reconciliation and persistent mail drafts before claiming broader
automation. Employee upload service requires verified separate HTTPS routing. The
existing two workflows are briefing and monthly preparation, not a general autonomous
company operator. Online API access remains an owner-supplied configuration step.
