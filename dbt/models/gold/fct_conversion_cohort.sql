-- Grain: one row per lead-creation month.
select
    cohort_month,
    count(*) as leads,
    count(*) filter (where is_converted) as converted,
    round(count(*) filter (where is_converted) * 1.0 / count(*), 4) as conversion_rate
from {{ ref('fct_lead_funnel') }}
group by cohort_month
