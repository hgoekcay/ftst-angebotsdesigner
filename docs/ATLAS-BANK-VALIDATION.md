# Bank import validation foundation

Prepared offline, not connected to production routes, application storage or UI. No live bank connector,
booking, tax journal, Billomat payment update or release is implemented here.

## Existing architecture

`bookkeeping.py` retains owner-scoped originals, document hashes, fields, review
state and audit entries in SQLite. `bookkeeping_sync.py` reads mail attachments
and Billomat snapshots. `bookkeeping_reports.py` reports those source snapshots;
`bookkeeping_export.py` produces preparation exports. A Billomat PAID/partial
source status is not bank evidence. Historical October statement preparation was
outside the application. PR64/65 implemented document preparation and rendering;
PR78/79 improved source refresh and reviewable extraction, not bank matching.

## Implemented pure validation

`ftst_atlas/bank_validation.py` has no I/O, persistence, routes or external calls.
`validate_csv` accepts only UTF-8 (optional BOM), comma-delimited canonical v1:

```
transaction_id,booking_date,amount,currency,reference
tx_1,2026-01-02,119.00,EUR,INV-1
```

Required caller metadata: opening/closing balances and inclusive date range.
Amounts use exact signed decimal strings with two fractional digits, never
binary floats. Incoming bank credits are positive, bank debits negative. Only
EUR is supported in this slice. IDs must be stable account-local identifiers;
no provider-specific CSV, PDF, CAMT or MT940 parsing is claimed. Reference text
preserves quoted continuation lines. The complete preview fails on malformed
rows, duplicate IDs, unsupported currencies, invalid dates or balance mismatch.
Bounds: 2 MiB input, 5,000 transactions, 2,000 characters per reference.
This checks internal consistency, not bank authenticity or statement completeness.
No persistent duplicate protection across overlapping files exists yet.

`preview_allocation` validates explicitly selected partial/batch allocations.
An outgoing customer invoice requires a positive bank credit; an incoming
supplier invoice requires a negative debit. Requested amounts must be positive,
within each supplied invoice balance and the supplied remaining transaction
amount. Duplicate invoice IDs within a batch are rejected. Unallocated money
and remaining invoice balances stay visible; results are unconfirmed previews,
not payment statuses. Refunds, credits, netted bank fees, FX and transfers need
separate explicit models and must not be forced into this path.

## Isolated staging follow-up (not application-integrated)

`bank_statements.StatementStore` requires an explicit SQLite path. There is no
production default, app import, route or automatic schema migration in the live
application. `import_csv` revalidates original bytes; stores bytes/hash, canonical
metadata, timestamp and normalized transactions in one write transaction. The API
has no mutation or deletion operation for saved statements.

The owner/account/source hash forms statement identity. Exact bytes and identical
metadata replay without writing again, including after restart or concurrent
retries. Contradictory metadata for the same bytes fails. Stable transaction IDs
are unique within owner/account: any overlap rejects the entire new statement,
not just duplicate rows. This is deliberately conservative; overlapping exports
need a reviewed adapter/reconciliation design before use. No fuzzy deduplication
or reuse of row-position IDs is safe.

Reads require owner/account/digest and return no record outside that scope.
Callers must still authenticate the owner and authorize account ownership; IDs
are not authorization. SQLite is local staging, not encrypted credential storage.
Storage permissions, quotas, schema lifecycle, audited corrections/retention and
production routes remain unresolved. Import success means `staged_unreconciled`,
never paid or booked. No allocation persistence is included.

Tests use temporary databases only: exact originals, replay after restart,
isolation, metadata conflict, complete rollback on overlaps, malformed input and
concurrent retries/conflicting imports.

## Read-only invoice selection bridge

`bank_reconciliation.preview_selected` now joins a scoped stored transaction to
explicitly selected `Bookkeeping.get(owner, invoice_id)` records. The caller may
supply only invoice IDs and chosen allocation amounts, never invoice balances.
Billomat source open amounts, direction and currency come from local snapshots;
only reviewed, issue-free, non-canceled OPEN/OVERDUE EUR records qualify. Source
amounts with extra decimal zeros are normalized exactly, never rounded. Unknown,
paid, draft or other unsupported source states fail closed. Missing originals
are not resolved by this preview and still need the existing review/export checks.

A source fingerprint changes when relevant fields change, but is neither a lock
nor authorization. Returned `unconfirmed_source_snapshot`/`confirmation_supported:
false` explicitly describe the boundary: previous allocations and source freshness
are NOT reconciled. The apparent unallocated amount is only this isolated proposal
against the full stored transaction, not a confirmed available balance. No bank or
invoice updates occur. Tests include the real Bookkeeping SQLite class, checked
byte-for-byte via its SQL dump before/after a synthetic partial/batch preview.

## Atomic local draft reservations

`bank_allocations.DraftAllocations` extends isolated statement storage. A trusted
service provisions owner/account enrollment and reviewed invoice baselines with
revision, EUR open amount and direction. These methods must never be exposed as
arbitrary form inputs. Actor/owner comparison is a scope check, not authentication;
there are no shared-user roles or production account registry yet.

`reserve` accepts a request key and invoice ID/revision/amount selections. One
SQLite BEGIN IMMEDIATE transaction checks account enrollment, owner-scoped bank
row, active draft totals for the transaction and for each invoice across accounts,
then writes the whole batch. Wrong direction, stale revision, duplicate selections
or over-allocation reject everything. Same-key/same-payload retries return the
existing state; changed payloads fail. `reverse` retains lines and creation audit,
records reversal actor/time once and releases draft capacity. A replay of the
original key after reversal returns reversed, never silently reserves again.

Baseline changes while reservations are active, or contradictory content for an
existing revision, set a persistent blocked flag before returning a conflict.
Reservations against that invoice then fail. Returning to an old snapshot cannot
unblock it. After active drafts are reversed, trusted provisioning of a new
revision may establish a fresh baseline. Updates require `expected_revision`
matching the stored baseline, preventing delayed responses from replacing a newer
revision. Zero open amounts are valid closed baselines; they permit no reservation.
The trusted adapter must call `invalidate_invoice` for canceled/unusable/unknown
source states rather than dropping a refresh error and retaining old capacity.
No attempt is made to automatically
subtract reservations from refreshed open amounts that may already include them.

This is an unconfirmed draft lifecycle only. It is not connected to the read-only
preview bridge, source synchronization, routes or payment-status writes. Local
remaining draft capacity is NOT an authoritative financial open balance. External
invoice changes cannot yet be detected atomically; authentication, freshness,
account registry, cancellation/credit handling and production migrations remain
required before a confirmation API. Existing snapshots are never marked paid.

## Next safe integration

1. Add owner/account-scoped immutable statement storage and original SHA-256,
   alongside a normalized transaction table. Imports must be atomic; identical
   uploads idempotent. Overlapping statements need provider transaction identity
   or explicit duplicate review, not a hash of date/amount alone.
2. Store allocations separately from source Billomat status with actor/time and
   reversals. At confirmation, fetch owner-scoped authoritative balances and
   recompute availability inside the same SQLite write transaction. Guard invoice
   review/cancellation, transaction/reversal status, account/currency and stale
   revisions. Use idempotency keys, not repeated HTTP attempts as new allocations.
3. Only then add owner/CSRF-protected preview and confirmation routes and UI.
   Matching by amount/reference produces proposals, never automatic confirmation.
4. Test isolation, restart/retry, simultaneous allocations, changed invoice
   balances, overlapping imports and corrections before bank data acceptance.
5. Add conservative provider-specific import adapters and complete monthly export.

Only synthetic data is used in tests. Never commit statements, account numbers,
credentials or private customer documents. Do not install while the owner is
performing a Home Assistant backup or update.
