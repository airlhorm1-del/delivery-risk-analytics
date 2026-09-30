{#
  Aggregate percentile (p between 0 and 1), e.g. the 90th percentile delivery time of a route.
  DuckDB computes it exactly; BigQuery's aggregate version is approximate (approx_quantiles),
  which differs by at most a fraction of a day here.
#}
{% macro percentile(column, p) -%}
    {{ return(adapter.dispatch('percentile')(column, p)) }}
{%- endmacro %}

{% macro default__percentile(column, p) -%}
    quantile_cont({{ column }}, {{ p }})
{%- endmacro %}

{% macro bigquery__percentile(column, p) -%}
    approx_quantiles({{ column }}, 100)[offset({{ (p * 100) | int }})]
{%- endmacro %}
