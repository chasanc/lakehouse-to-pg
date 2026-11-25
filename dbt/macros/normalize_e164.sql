{# Best-effort E.164: '+' passthrough, '00' prefix, or bare 10-digit number using default_cc.
   Anything that is not 8-15 digits afterwards becomes NULL. #}
{% macro normalize_e164(column, default_cc='1') -%}
{%- set digits = "regexp_replace(" ~ column ~ ", '[^0-9]', '', 'g')" -%}
nullif(
    case
        when {{ column }} is null then null
        when trim({{ column }}) like '+%' then '+' || {{ digits }}
        when {{ digits }} like '00%' then '+' || substr({{ digits }}, 3)
        when length({{ digits }}) = 10 then '+{{ default_cc }}' || {{ digits }}
        else ''
    end,
    ''
)
{%- endmacro %}
