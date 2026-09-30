{#
  ISO day of week (1 = Monday ... 7 = Sunday). Counted from a known Monday (3 Jan 2000)
  because DuckDB and BigQuery number weekdays differently.
#}
{% macro iso_day_of_week(date_column) -%}
    (mod({{ dbt.datediff("cast('2000-01-03' as date)", date_column, 'day') }}, 7) + 1)
{%- endmacro %}
