{#
  Every calendar day from start_date to end_date (inclusive), one row each, column `date_day`.
  Built from a 0-9999 number table in plain SQL, so it runs the same on DuckDB and BigQuery and,
  unlike dbt_utils.date_spine, needs no query against the warehouse while dbt compiles.
  Covers up to 10,000 days (about 27 years).
#}
{% macro calendar_days(start_date, end_date) -%}
    with digits as (
        {% for digit in range(10) -%}
        select {{ digit }} as d{% if not loop.last %} union all {% endif %}
        {%- endfor %}
    ),

    numbers as (
        select ones.d + 10 * tens.d + 100 * hundreds.d + 1000 * thousands.d as n
        from digits as ones
        cross join digits as tens
        cross join digits as hundreds
        cross join digits as thousands
    ),

    days as (
        select cast({{ dbt.dateadd('day', 'n', "cast('" ~ start_date ~ "' as date)") }} as date) as date_day
        from numbers
    )

    select date_day
    from days
    where date_day <= cast('{{ end_date }}' as date)
{%- endmacro %}
