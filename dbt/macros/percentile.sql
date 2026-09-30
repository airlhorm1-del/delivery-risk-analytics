{#
  Aggregate percentile (p between 0 and 1), e.g. the 90th percentile delivery time of a route.
  Both versions return an actual observed value (no interpolation between two orders). BigQuery's
  aggregate version is approximate in principle; on this data it matched DuckDB on all 124 ranked
  routes. (An interpolating version on DuckDB differed from BigQuery by up to 2.8 days on small routes.)
#}
{% macro percentile(column, p) -%}
    {{ return(adapter.dispatch('percentile')(column, p)) }}
{%- endmacro %}

{% macro default__percentile(column, p) -%}
    quantile_disc({{ column }}, {{ p }})
{%- endmacro %}

{% macro bigquery__percentile(column, p) -%}
    approx_quantiles({{ column }}, 100)[offset({{ (p * 100) | int }})]
{%- endmacro %}
