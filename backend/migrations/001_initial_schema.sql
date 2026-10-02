-- 001_initial_schema.sql
--
-- IMPORTANT: this reconstructs the REAL, already-live Supabase schema for this project
-- (confirmed via an `information_schema.columns` dump from the team's own project on
-- 2026-09-30 - see the table below). It is written to be idempotent (CREATE TABLE IF NOT
-- EXISTS) so it is SAFE to run against the existing project (it will create nothing new
-- there) and also lets the team spin up a fresh Supabase project with the same schema.
--
-- Only column names + data types were confirmed, NOT constraints, defaults, or
-- nullability - primary keys, foreign keys, and `not null`/`default now()` below are this
-- migration's best-effort, reasonable reconstruction, not verified facts. Adjust freely.

create extension if not exists "pgcrypto";

-- Known reference products. `reference_product_id` is the business key used everywhere
-- else in the app (barcode/OCR matching); `id` is just the table's own bigint PK.
create table if not exists product_reference (
    id                     bigint generated always as identity primary key,
    reference_product_id   text not null,
    brand                  text not null,
    product_name           text not null,
    barcode                text,
    mrp                    numeric,
    net_weight             text,
    manufacturer           text,
    batch_no               text,
    pkd                    text,   -- packing date, kept as free text (label dates vary in format)
    best_before            text,
    use_by                 text,
    reference_ocr_text     text,
    reference_fields_json  jsonb,
    reference_image        text,
    reference_image_url    text,
    created_at             timestamptz not null default now()
);

-- Bulk/staging OCR dataset (spec section 13: "treat as raw/reference OCR data, not the
-- final compliance schema"). Doubles as an optional reference source when is_reference=true.
create table if not exists nutrition_ocr_raw (
    id                     bigint generated always as identity primary key,
    image                  text,
    text                   text,
    confidence             double precision,
    source                 text,
    reference_product_id   text,
    brand                  text,
    product_name           text,
    reference_image        text,
    is_reference           boolean not null default false,
    reference_fields_json  text,
    image_url              text,
    reference_image_url    text
);

-- One row per scan. This IS the audit/history record - id is the scan_id used by every
-- *_results table below. Summary columns (detected_*, ocr_confidence, tampering_score,
-- status) are denormalised here on purpose so history listing is a single query.
create table if not exists scan_records (
    id                      bigint generated always as identity primary key,
    created_at              timestamptz not null default now(),
    image_path              text,
    image_url               text,
    detected_barcode        text,
    detected_product_name   text,
    detected_brand          text,
    reference_product_id    text,
    ocr_confidence          numeric,
    tampering_score         numeric,
    status                  text
);

create table if not exists ocr_results (
    id               bigint generated always as identity primary key,
    scan_id          bigint references scan_records (id) on delete cascade,
    raw_text         text,
    confidence       numeric,
    structured_data  jsonb,
    created_at       timestamptz not null default now()
);

create table if not exists barcode_results (
    id          bigint generated always as identity primary key,
    scan_id     bigint references scan_records (id) on delete cascade,
    barcode     text,
    detected    boolean not null default false,
    confidence  numeric,
    created_at  timestamptz not null default now()
);

create table if not exists tampering_results (
    id                bigint generated always as identity primary key,
    scan_id           bigint references scan_records (id) on delete cascade,
    tampering_score   numeric,
    status            text,
    heatmap_path      text,
    created_at        timestamptz not null default now()
);

-- Data-driven rules - see app/services/compliance_engine.py for the operator/expected_value
-- vocabulary it evaluates (field_present, any_field_present, min_declarations,
-- tampering_score_below, reference_field_match).
create table if not exists compliance_rules (
    id                bigint generated always as identity primary key,
    rule_code         text not null,
    rule_name         text not null,
    category          text,
    field_name        text,
    operator          text not null,
    expected_value    text,
    severity          text not null default 'medium' check (severity in ('low', 'medium', 'high')),
    description       text,
    source_reference  text,
    source_url        text,
    effective_from    date,
    effective_to      date,
    version           text,
    is_active         boolean not null default true,
    created_at        timestamptz not null default now()
);

-- No separate compliance_checks child table in the live schema - individual rule outcomes
-- are stored inline as compliance_results.rule_results (jsonb list).
create table if not exists compliance_results (
    id                    bigint generated always as identity primary key,
    scan_id               bigint references scan_records (id) on delete cascade,
    overall_status        text,   -- PASS | REVIEW_REQUIRED | NON_COMPLIANT
    risk_level            text,   -- NONE | LOW | MEDIUM | HIGH
    reference_match       boolean,
    matched_fields        jsonb,
    mismatched_fields     jsonb,
    missing_fields        jsonb,
    rule_results          jsonb,
    explanation           text,
    engine_version        text,
    rules_version         text,
    processing_time_ms    integer,
    created_at            timestamptz not null default now()
);
