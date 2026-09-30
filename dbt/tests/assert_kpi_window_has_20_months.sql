-- The KPI window must hold exactly the 20 complete months from Jan 2017 to Aug 2018.
select count(*) as months
from {{ ref('mart_monthly_kpis') }}
having count(*) <> 20
