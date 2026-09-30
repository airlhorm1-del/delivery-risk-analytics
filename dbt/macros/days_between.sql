{# Whole calendar days from one date to another (negative if the second is earlier). #}
{% macro days_between(start_date, end_date) -%}
    {{ dbt.datediff(start_date, end_date, 'day') }}
{%- endmacro %}

{# Elapsed time between two timestamps in hours, with minute precision. #}
{% macro hours_between(start_ts, end_ts) -%}
    ({{ dbt.datediff(start_ts, end_ts, 'minute') }} / 60.0)
{%- endmacro %}
