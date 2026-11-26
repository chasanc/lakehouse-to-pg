select
    cast(user_id as integer) as user_id,
    trim(full_name) as user_name,
    lower(trim(role)) as role,
    cast(manager_id as integer) as manager_user_id
from {{ source('bronze', 'users') }}
