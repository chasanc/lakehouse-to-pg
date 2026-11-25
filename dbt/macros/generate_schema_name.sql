{# Use the custom schema as-is (bronze/silver/gold) instead of <target>_<custom>. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name is not none else target.schema }}
{%- endmacro %}
