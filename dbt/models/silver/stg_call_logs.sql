with ranked as (
    select
        *,
        row_number() over (partition by call_id order by started_at desc) as rn
    from {{ source('bronze', 'call_logs') }}
)

select
    cast(call_id as integer) as call_id,
    cast(lead_id as integer) as lead_id,
    cast(user_id as integer) as caller_user_id,
    cast(started_at as timestamp) as started_at,
    cast(duration_sec as integer) as duration_sec,
    lower(trim(direction)) as direction,
    lower(trim(outcome)) as outcome
from ranked
where rn = 1
