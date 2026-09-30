-- Real Olist customers and simulated live ones (SYNTHETIC DATA) in one table.
-- Both staging models have identical columns; data_source and is_synthetic say which feed a row came from.
select * from {{ ref('stg_olist__customers') }}
union all
select * from {{ ref('stg_simulated__customers') }}
