# Bank-format safety boundary

No customer statement, real transactions or account identifiers belong in this
repository. The observations below are format-level requirements only.

## What PR98 actually accepts

| Input | Current behavior |
| --- | --- |
| Canonical `atlas-bank-csv/1`, UTF-8 with optional BOM, comma, ISO dates, decimal dot, stable transaction IDs | Validated single-account EUR staging |
| A derived BOM/semicolon list with German dates/decimal commas | Rejected; not a native bank export, no automatic header/locale mapping |
| Revolut text-readable PDF statement | Rejected; no PDF bank-import implementation |
| Unknown/native Revolut CSV | Not claimed supported until exact headers, semantics and transaction identity are verified |

Text-readable PDF is not evidence that text extraction preserves table geometry,
page continuations, account sections or transaction boundaries. The known derived
list is lossy for multiline references. Changing its delimiter does not recover
missing information or make it a reliable source for automatic reconciliation.
Do not silently enrich references, make up transaction IDs, or import the derived
list as if it were the original bank export.

## Verified safeguards in the canonical path

Quoted multiline references are preserved, including CR/LF, commas and semicolons.
Unknown headers, localized dates/amounts, PDF bytes and summary-like malformed
rows fail closed; no heuristic skipping or locale detection is performed.

Each statement is bound to one explicit owner/account and EUR. Giro, Pro and each
Pocket need separate stable account identities, even when labels or transaction
IDs coincide. The store scopes duplicates by owner/account, not by display name.
It cannot infer account type, distinguish a real separate account from a duplicate
alias, or authorize that account on the user's behalf. A trusted registry must
prevent accidental duplicate account mappings before production use.

Optional `control_totals` supplies exact positive decimal magnitudes `credits`,
`debits`, plus integer `transaction_count`. All three are required together. Gross
flows and count must match in addition to opening + net movement = closing. This
catches net-zero omission/duplication patterns that a closing-balance check misses.
Without this option, output explicitly reports `controls_checked: false`.
Controls are checked on every staging call, including exact-source retries. They
are not yet retained as independent audited source evidence in the staging DB.
Passing them does not prove completeness/authenticity or correct classification.

A canonical file's stored hash covers those exact canonical bytes. If a future
adapter converts a PDF or native export, it must separately retain and hash the
original bank source and link conversion evidence; do not relabel the canonical
hash as the original PDF hash.

## Acceptance gates for a future Revolut adapter

1. Inspect the chosen native export format privately, using a sanitized synthetic
   fixture for implementation. Document date meaning (booking versus value date),
   signs, decimal grouping, currency and provider transaction identity.
2. Separate Giro, Pro and every Pocket with source account identifiers. Do not
   concatenate consolidated summary sections with underlying detail transactions.
3. Preserve full multiline references, record page/row provenance for PDF, and
   surface ambiguous continuation/page-wrap rows for review instead of guessing.
4. Recognize summary/header/footer records explicitly. A repeated page summary is
   not a transaction; a legitimate same-date/same-amount transaction is not safely
   deduplicated by its text or amount alone. Never invent cross-file identity from
   row order. Overlapping exports require stable IDs or explicit duplicate review.
5. Validate opening/closing, gross credits/debits and transaction count per account
   and currency when available. Keep consolidated summaries as separate controls,
   never additional transactions. Explain any missing controls, rounding or FX.
6. Treat Giro/Pro/Pocket transfers as transfers, not customer or supplier payments.
   Preserve both account legs for account-level balances; do not double-count them
   as business income/expense. No automatic allocation from matching amounts.
7. Reconcile derived data with the original source before using it. The existing
   lossy list alone cannot establish full references or reliable provider IDs.
8. Test all supported layouts, duplicates, missing pages, reordered sections,
   multiline references, malformed/localized numerics and failed controls. On any
   uncertainty reject the complete import or require explicit human review.

No PDF parser or bank-specific adapter is implemented by this change. Choosing
future bank export format remains a user decision; development can continue with
synthetic canonical data without exposing the original financial documents.
