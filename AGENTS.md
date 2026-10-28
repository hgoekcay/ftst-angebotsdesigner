# FTST project continuity

Before changing code, read `docs/ATLAS-STATUS.md` and `docs/ZUSAMMENARBEIT.md`.
Use `docs/ARBEITSPROTOKOLL.md` for older history; its version statements are historical.
Verify current code, branch and live versions instead of assuming a prior handover is current.

After meaningful work, update `docs/ATLAS-STATUS.md` with implemented behavior,
validation evidence, deployment status and the next concrete step. Distinguish
planned, implemented, tested and installed. Never record credentials, mailbox
contents, customer documents or private identifiers in this public repository.

For changes spanning modules, use Code Review Graph if available: verify its index
matches the checkout, inspect affected callers/imports/tests, then read source.
If unavailable, use `rg`, diffs and targeted tests; do not claim graph analysis ran.
The code graph records structure, not product decisions or conversation memory.

Use the reviewed Apple design principles for UI work while preserving FTST branding,
accessible controls, existing behavior and separate print/PDF styling.
Reference: https://github.com/emilkowalski/skills/tree/main/skills/apple-design

Keep parallel agent file ownership explicit. Never overwrite another agent's or
the user's changes. Run relevant checks and verify the delivered UI when changed.
