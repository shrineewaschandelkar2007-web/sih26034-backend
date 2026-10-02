# Migrations

**These files reconstruct the REAL, already-live schema** in the team's Supabase project
("Docai780"), confirmed via an `information_schema.columns` dump on 2026-09-30 - they are
not a from-scratch design. Column names/types are exact; constraints/defaults/nullability
were not confirmed and are this migration's best-effort reconstruction.

All files use `create table if not exists` / existence checks, so they are **safe to run
against the already-live project** (they will create nothing there) and also let the team
spin up a second/fresh Supabase project with the same schema.

Run in order if setting up fresh:
1. `001_initial_schema.sql` - the 8 real tables (product_reference, nutrition_ocr_raw,
   scan_records, ocr_results, barcode_results, tampering_results, compliance_rules,
   compliance_results)
2. `002_indexes.sql`
3. `003_rls.sql` - RLS + storage buckets/policies (scan images are private)
4. `004_seed_demo_products.sql` - demo product catalogue (only Parle-G has real values)
5. `005_seed_compliance_rules.sql` - mirrors `models_data/compliance_rules.json`

The backend authenticates with the **service-role key** (server-side only, bypasses RLS).
Never put that key in the frontend or in git.

**scan_id is the bigint `scan_records.id`**, not a UUID - see
`app/api/routes/scan.py`'s module docstring for why the persistence order had to change
because of this (scan_records is written once, after the pipeline already has everything
to summarise, and its returned id is then used for the four detail tables).

Not yet verified end-to-end against the live project from this environment (no network
access to Supabase here) - run `pytest tests/integration/test_supabase_repository.py`
with real credentials in `.env` (the live round-trip test un-skips itself) before relying
on this.
