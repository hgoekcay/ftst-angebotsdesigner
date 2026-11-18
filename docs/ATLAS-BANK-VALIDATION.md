# Bank import validation foundation

Prepared offline, not connected to routes, storage or UI. No live bank connector,
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
