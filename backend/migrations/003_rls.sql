-- 003_rls.sql
-- Row Level Security. The FastAPI backend uses the service-role key, which BYPASSES RLS -
-- that key must never reach the browser. Enabling RLS with no client policy means
-- "deny all" for anon/authenticated clients, the safe default for scan/audit tables that
-- only the backend should touch.

alter table product_reference    enable row level security;
alter table nutrition_ocr_raw    enable row level security;
alter table scan_records         enable row level security;
alter table ocr_results          enable row level security;
alter table barcode_results      enable row level security;
alter table tampering_results    enable row level security;
alter table compliance_rules     enable row level security;
alter table compliance_results   enable row level security;

-- Reference catalogue + active rules are non-sensitive and safe to read from a client
-- (e.g. a future product-search box in the frontend).
drop policy if exists "product_reference readable by anyone" on product_reference;
create policy "product_reference readable by anyone" on product_reference for select using (true);

drop policy if exists "active rules readable by anyone" on compliance_rules;
create policy "active rules readable by anyone" on compliance_rules for select using (is_active);

-- scan_records / *_results / nutrition_ocr_raw: intentionally NO client policies => backend-only.

-- ---------------------------------------------------------------------------------------
-- Storage. Create the buckets in the dashboard (or below). Scan images are PRIVATE - the
-- backend serves them through short-lived signed URLs (see app/db/storage.py). Reference
-- product photos are public-read.
-- ---------------------------------------------------------------------------------------
insert into storage.buckets (id, name, public) values
    ('scan-images',        'scan-images',        false),
    ('scan-artifacts',     'scan-artifacts',     false),
    ('reference-products', 'reference-products', true)
on conflict (id) do nothing;

drop policy if exists "reference photos are publicly readable" on storage.objects;
create policy "reference photos are publicly readable" on storage.objects
    for select using (bucket_id = 'reference-products');
-- No policies for scan-images / scan-artifacts => only the service-role backend can read or write them.
