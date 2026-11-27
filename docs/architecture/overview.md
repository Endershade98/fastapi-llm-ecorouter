# Architecture

The domain owns model eligibility, ranking and usage accounting. It evaluates
catalog snapshots against routing constraints and calculates costs from priced
token usage.

The application layer uses those rules in `RouteInference`. It checks budget,
deadline and provider availability before dispatch. Each dispatched attempt has
a preceding ledger intent and a terminal accounting outcome. A confirmed
transient rejection may be retried within the two-call limit. An ambiguous
failure can lead to an eligible fallback and retains its budget reservation.

Provider, ledger and usage analytics interfaces live in
`src/eco_router/application/ports/inference.py`. Tests exercise these boundaries
with scripted implementations. The next increment adds infrastructure adapters.
