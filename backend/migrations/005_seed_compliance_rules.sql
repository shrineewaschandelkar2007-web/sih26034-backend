-- 005_seed_compliance_rules.sql
-- Mirrors models_data/compliance_rules.json exactly (same rule_codes). Only inserts rules
-- that don't already exist (checked by rule_code), since the live table's constraints
-- weren't confirmed.

insert into compliance_rules (rule_code, rule_name, category, field_name, operator, expected_value, severity, description, source_reference, source_url, effective_from, version, is_active)
select * from (values
  ('LM-001', 'MRP declaration present', 'mandatory_declaration', 'mrp', 'field_present', null,
     'high', 'Every packaged commodity must declare the Maximum Retail Price.',
     'Legal Metrology (Packaged Commodities) Rules, 2011', 'https://consumeraffairs.gov.in/pages/legal-metrology-act',
     date '2011-01-01', '1', true),
  ('LM-002', 'Net quantity declaration present', 'mandatory_declaration', 'net_quantity', 'field_present', null,
     'high', 'Every packaged commodity must declare its net quantity.',
     'Legal Metrology (Packaged Commodities) Rules, 2011', 'https://consumeraffairs.gov.in/pages/legal-metrology-act',
     date '2011-01-01', '1', true),
  ('LM-003', 'Manufacturer/packer/importer address present', 'mandatory_declaration', 'manufacturer_address', 'field_present', null,
     'high', 'The name and address of the manufacturer, packer or importer must be declared.',
     'Legal Metrology (Packaged Commodities) Rules, 2011', 'https://consumeraffairs.gov.in/pages/legal-metrology-act',
     date '2011-01-01', '1', true),
  ('LM-004', 'Manufacturing/packing date or use-by date present', 'mandatory_declaration', 'manufacturing_date_or_use_by', 'any_field_present', 'manufacturing_date,use_by,best_before',
     'medium', 'A month/year of manufacture, packing, use-by, or best-before date must be declared.',
     'Legal Metrology (Packaged Commodities) Rules, 2011', 'https://consumeraffairs.gov.in/pages/legal-metrology-act',
     date '2011-01-01', '1', true),
  ('LM-005', 'Consumer care contact present', 'mandatory_declaration', 'consumer_care_contact', 'field_present', null,
     'medium', 'Consumer complaint/care contact details must be declared.',
     'Legal Metrology (Packaged Commodities) Rules, 2011', 'https://consumeraffairs.gov.in/pages/legal-metrology-act',
     date '2011-01-01', '1', true),
  ('LM-006', 'Zero-declaration high-risk flag', 'risk_flag', 'declaration_count', 'min_declarations', '2',
     'high', 'Near-zero mandatory declarations detected - likely a completely unlabeled or non-compliant product.',
     'Internal risk heuristic (not a specific Legal Metrology clause)', null,
     date '2011-01-01', '1', true),
  ('TP-001', 'No significant tampering evidence', 'tampering', 'tampering_score', 'tampering_score_below', '0.55',
     'high', 'The image-tampering heuristic should not report a high anomaly score.',
     'Internal tampering heuristic (not ManTraNet - see README)', null,
     date '2011-01-01', '1', true),
  ('REF-001', 'Reference MRP consistency', 'reference_comparison', 'mrp', 'reference_field_match', 'mrp',
     'high', 'MRP should match the known reference value for this product.',
     'Internal reference-catalogue check', null,
     date '2011-01-01', '1', true),
  ('REF-002', 'Reference net quantity consistency', 'reference_comparison', 'net_quantity', 'reference_field_match', 'net_quantity',
     'medium', 'Net quantity should match the known reference value for this product.',
     'Internal reference-catalogue check', null,
     date '2011-01-01', '1', true)
) as new_rules(rule_code, rule_name, category, field_name, operator, expected_value, severity, description, source_reference, source_url, effective_from, version, is_active)
where not exists (select 1 from compliance_rules cr where cr.rule_code = new_rules.rule_code);
