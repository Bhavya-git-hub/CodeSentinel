# 0002. Store enums as VARCHAR with CHECK, not native PostgreSQL enums

**Status:** accepted — 2026-09-11

## Context

Four enumerations are stored: `ScanStatus`, `AnalyzerStatus`, `Severity`, `EdgeType`.
PostgreSQL native enum types cannot have values added inside a transaction, so
`ALTER TYPE ... ADD VALUE` has to run outside Alembic's transactional migration wrapper.
Several of these enumerations are expected to grow: `EdgeType` gains cases as phase 6
import resolution improves, and `AnalyzerStatus` may need finer failure categories.

SQLAlchemy 2.x defaults `Enum(create_constraint=...)` to **False**. Simply passing
`native_enum=False` therefore produces a plain `VARCHAR` with no validation at all --
the column would accept any string, which is worse than either alternative.

## Decision

Use `Enum(..., native_enum=False, create_constraint=True, values_callable=...)`, wrapped
in the `enum_column()` helper in `app/models/enums.py` so no call site can forget the
`create_constraint` argument.

`values_callable` stores the member *value* (`"pending"`) rather than the member *name*
(`"PENDING"`), so what is in the database matches what the API returns.

## Consequences

- Adding an enum value is an ordinary `ALTER TABLE ... DROP/ADD CONSTRAINT` migration.
- The column is genuinely constrained; an integration test asserts the CHECK rejects an
  unknown value, rather than trusting the declaration.
- Slightly larger storage than a native enum. Irrelevant at this scale.
