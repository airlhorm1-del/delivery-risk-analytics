{#
  True when an array column contains a value. The one place where DuckDB and BigQuery
  SQL differ in this project, so dbt picks the right version for the target warehouse.
#}
{% macro array_contains(array_column, value) -%}
    {{ return(adapter.dispatch('array_contains')(array_column, value)) }}
{%- endmacro %}

{% macro default__array_contains(array_column, value) -%}
    coalesce(list_contains({{ array_column }}, {{ value }}), false)
{%- endmacro %}

{% macro bigquery__array_contains(array_column, value) -%}
    coalesce({{ value }} in unnest({{ array_column }}), false)
{%- endmacro %}
