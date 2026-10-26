# Frozen current 023 private baseline

A private baseline generated from frozen current 023 source, containing synthetic historical data. This is not a normal-database backup or a retained historical production database.

Schema includes all 134 ORM tables, the migration ledger, FTS5 virtual/shadow tables, indexes, and existing triggers. No custom schema overlays are included. Vehicle immutability remains an ORM contract.

Seed data contains legacy text-only vehicle evidence, repeated capture bytes, changed raw bytes with unchanged facts, quarantine approval/reuse, parser rejection, garage references and pending work. No Parser run or release is completed. One synthetic historical bootstrap registration has database state=active; no bootstrap/activate command was run, and no normal application was enabled. The blocked offline plan deliberately rejects a quarantine as accepted evidence. All users and credential inventories remain empty. Embedded object/bundle bytes are private synthetic/source assets.

Replay uses only these static SQL/JSON files through the separately reviewed gate driver. It must not import tire_api or SQLAlchemy, initialize production metadata, contact a network or open a normal database. Gate 1 does not authorize schema 024, normal-database upgrade, HTTP acceptance, or real-source acceptance.
