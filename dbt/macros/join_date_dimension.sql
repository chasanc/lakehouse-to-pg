{# Left join dim_date on the calendar date of `column`; select columns via the alias. #}
{% macro join_date_dimension(column, alias='dd') -%}
left join {{ ref('dim_date') }} as {{ alias }}
    on cast({{ column }} as date) = {{ alias }}.date_day
{%- endmacro %}
