-- 004_seed_demo_products.sql
-- Demo reference catalogue for the SIH pitch.
--
-- IMPORTANT: only the Parle-G row carries real values (read from the team's own packet
-- during development). The other rows are PLACEHOLDERS with NULL mrp/net_weight/manufacturer
-- on purpose - fill them from YOUR reference photos before the demo. Never invent label
-- values for a real product.
--
-- No ON CONFLICT clause is used: the live table's unique constraints (if any) on
-- reference_product_id were not confirmed, so this checks for an existing row instead.
-- (scripts/seed_demo_products.py does the same check-then-insert in Python and is the
-- preferred way to run this - use this .sql file only if you need to seed via the SQL editor.)

insert into product_reference (reference_product_id, brand, product_name, barcode, mrp, net_weight, manufacturer, pkd, use_by)
select 'demo-parle-g-003', 'Parle', 'Parle-G', '8901719123870', 30.00, '250 g', 'Parle Biscuits Pvt Ltd', '08/08/2026', '05/01/2027'
where not exists (select 1 from product_reference where reference_product_id = 'demo-parle-g-003');

insert into product_reference (reference_product_id, brand, product_name)
select 'demo-parle-monaco-001', 'Parle', 'Monaco'
where not exists (select 1 from product_reference where reference_product_id = 'demo-parle-monaco-001');

insert into product_reference (reference_product_id, brand, product_name)
select 'demo-parle-bourbon-002', 'Parle', 'Bourbon'
where not exists (select 1 from product_reference where reference_product_id = 'demo-parle-bourbon-002');

insert into product_reference (reference_product_id, brand, product_name)
select 'demo-britannia-bourbon-004', 'Britannia', 'Bourbon'
where not exists (select 1 from product_reference where reference_product_id = 'demo-britannia-bourbon-004');

insert into product_reference (reference_product_id, brand, product_name)
select 'demo-britannia-good-day-005', 'Britannia', 'Good Day'
where not exists (select 1 from product_reference where reference_product_id = 'demo-britannia-good-day-005');
