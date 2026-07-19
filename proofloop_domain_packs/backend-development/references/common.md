# Backend common proof seams

Trace entry → validation → authorization → business rule → persistence/downstream call → serialization. Preserve input, output, error, security, transaction, and idempotency invariants unless the intent explicitly changes one.

Prefer contract tests at the narrowest stable boundary. Add integration evidence when routing, middleware, ORM behavior, transactions, or serialization is part of the criterion. Verify an invalid input and a downstream failure, not only the happy path.

Escalate when schema ownership, migration policy, authorization, or external compatibility is unknown. Framework defaults are not evidence that the repository uses them.
