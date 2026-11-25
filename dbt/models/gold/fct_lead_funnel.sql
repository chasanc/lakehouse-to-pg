-- Grain: one row per lead, with its funnel position and signup cohort.
select
    lead_id,
    owner_user_id,
    stage,
    case stage
        when 'new' then 1
        when 'contacted' then 2
        when 'qualified' then 3
        when 'won' then 4
        when 'lost' then 5
    end as stage_rank,
    stage = 'won' as is_converted,
    cast(date_trunc('month', created_at) as date) as cohort_month,
    created_at,
    updated_at
from {{ ref('stg_crm_leads') }}
