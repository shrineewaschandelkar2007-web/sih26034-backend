-- 002_indexes.sql
create index if not exists idx_product_reference_barcode  on product_reference (barcode) where barcode is not null;
create index if not exists idx_product_reference_brand    on product_reference (lower(brand), lower(product_name));
create index if not exists idx_product_reference_pid      on product_reference (reference_product_id);
create index if not exists idx_scan_records_created_at    on scan_records (created_at desc);
create index if not exists idx_scan_records_status        on scan_records (status);
create index if not exists idx_scan_records_ref_product    on scan_records (reference_product_id);
create index if not exists idx_ocr_results_scan_id        on ocr_results (scan_id);
create index if not exists idx_barcode_results_scan_id    on barcode_results (scan_id);
create index if not exists idx_tampering_results_scan_id  on tampering_results (scan_id);
create index if not exists idx_compliance_results_scan_id on compliance_results (scan_id);
create index if not exists idx_compliance_rules_active    on compliance_rules (is_active) where is_active;
create index if not exists idx_nutrition_ocr_raw_pid      on nutrition_ocr_raw (reference_product_id) where reference_product_id is not null;
