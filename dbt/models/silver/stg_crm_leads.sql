with ranked as (
    select
        *,
        row_number() over (
            partition by lead_id order by updated_at desc
        ) as rn
    from {{ source('bronze', 'crm_leads') }}
)

select
    cast(lead_id as integer) as lead_id,
    cast(user_id as integer) as owner_user_id,
    trim(full_name) as lead_name,
    lower(trim(email)) as email,
    {{ normalize_e164('phone_raw') }} as phone_e164,
    lower(trim(stage)) as stage,
    cast(created_at as timestamp) as created_at,
    cast(updated_at as timestamp) as updated_at
from ranked
where rn = 1
