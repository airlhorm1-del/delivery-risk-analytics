{#
  Great-circle distance in km between two points (haversine formula).
  Written with acos(-1) for pi because BigQuery has no radians() function.
#}
{% macro haversine_km(lat1, lng1, lat2, lng2) -%}
    (2 * 6371 * asin(sqrt(
        power(sin(({{ lat2 }} - {{ lat1 }}) * acos(-1) / 180 / 2), 2)
        + cos({{ lat1 }} * acos(-1) / 180) * cos({{ lat2 }} * acos(-1) / 180)
        * power(sin(({{ lng2 }} - {{ lng1 }}) * acos(-1) / 180 / 2), 2)
    )))
{%- endmacro %}
