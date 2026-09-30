{# Double-precision number. dbt's own type_float() is single precision on DuckDB, too coarse for coordinates. #}
{% macro type_double() -%}
    {{ return(adapter.dispatch('type_double')()) }}
{%- endmacro %}

{% macro default__type_double() -%} double {%- endmacro %}

{% macro bigquery__type_double() -%} float64 {%- endmacro %}
