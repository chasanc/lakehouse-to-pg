with ranked as (
    select
        *,
        row_number() over (partition by order_id order by updated_at desc) as rn
    from {{ source('bronze', 'orders') }}
)

select
    cast(order_id as integer) as order_id,
    cast(lead_id as integer) as lead_id,
    cast(amount as decimal(12, 2)) as amount,
    upper(trim(currency)) as currency,
    lower(trim(status)) as status,
    cast(ordered_at as timestamp) as ordered_at,
    cast(updated_at as timestamp) as updated_at
from ranked
where rn = 1
