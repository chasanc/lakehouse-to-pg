select
    u.user_id,
    u.user_name,
    u.role,
    u.manager_user_id,
    m.user_name as manager_name,
    case when u.manager_user_id is null then 1 else 2 end as hierarchy_level
from {{ ref('stg_users') }} as u
left join {{ ref('stg_users') }} as m
    on u.manager_user_id = m.user_id
