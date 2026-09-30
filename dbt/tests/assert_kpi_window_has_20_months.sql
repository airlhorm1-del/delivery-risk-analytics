-- The KPI window must hold exactly the 20 complete months from Jan 2017 to Aug 2018.
select months
from (select count(*) as months from {{ ref('mart_monthly_kpis') }}) as monthly
where months <> 20
