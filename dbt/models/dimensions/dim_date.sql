with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2026-01-01' as date)",
        end_date="cast('2028-01-01' as date)"
    ) }}
)

select
    cast(date_day as date) as date_day,
    {{ format_date('date_day', '%Y-%m') }} as year_month,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(quarter from date_day) as quarter,
    extract(isodow from date_day) in (6, 7) as is_weekend
from spine
