{{ config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge'
) }}

-- Grain: one row per order. Merge on order_id picks up status changes (updated_at moves forward).
select
    o.order_id,
    o.lead_id,
    l.owner_user_id,
    o.amount,
    o.currency,
    o.status,
    o.ordered_at,
    o.updated_at,
    dd.year_month as order_month,
    dd.is_weekend as ordered_on_weekend
from {{ ref('stg_orders') }} as o
inner join {{ ref('stg_crm_leads') }} as l
    on o.lead_id = l.lead_id
{{ join_date_dimension('o.ordered_at') }}
{% if is_incremental() %}
where o.updated_at > (select max(updated_at) from {{ this }})
{% endif %}
