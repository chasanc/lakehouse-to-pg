{# Format a date/timestamp column with a strftime-style pattern. Athena (Trino) has
   date_format with MySQL-style specifiers, so only the function name differs for the
   specifiers used here (%Y %m %d). #}
{% macro format_date(column, fmt='%Y-%m-%d') -%}
    {{ return(adapter.dispatch('format_date', 'lakehouse')(column, fmt)) }}
{%- endmacro %}

{% macro default__format_date(column, fmt) -%}
    strftime({{ column }}, '{{ fmt }}')
{%- endmacro %}

{% macro athena__format_date(column, fmt) -%}
    date_format({{ column }}, '{{ fmt }}')
{%- endmacro %}
