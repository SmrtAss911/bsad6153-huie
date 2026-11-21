-- db/quality_checks.sql: Milestone 3 data quality checks.
-- SELECT only. Safe to run as app_reader, or paste into the Supabase SQL editor.
-- Each check starts with a "-- Qn:" line so docs/data_quality.md can cite it.

-- ============ A. Row counts ============

-- Q1: row counts per table, with the time of the check
select now() as checked_at, 'manufacturers' as table_name, count(*) as row_count from manufacturers
union all select now(), 'parts',            count(*) from parts
union all select now(), 'price_breaks',     count(*) from price_breaks
union all select now(), 'part_attributes',  count(*) from part_attributes
union all select now(), 'part_on_order',    count(*) from part_on_order
union all select now(), 'search_keywords',  count(*) from search_keywords
union all select now(), 'part_search_hits', count(*) from part_search_hits
union all select now(), 'sync_runs',        count(*) from sync_runs;

-- ============ B. Null and blank rates on key fields ============

-- Q2: null rates on parts (null meanings are in db/schema.sql)
select count(*) as parts,
       count(*) filter (where availability_text is null) as availability_null,
       round(100.0 * count(*) filter (where availability_text is null) / count(*), 1) as availability_null_pct,
       count(*) filter (where country_of_origin is null) as country_null,
       round(100.0 * count(*) filter (where country_of_origin is null) / count(*), 1) as country_null_pct,
       count(*) filter (where tariff_pct is null) as no_tariff_notice,
       round(100.0 * count(*) filter (where tariff_pct is null) / count(*), 1) as no_tariff_notice_pct,
       count(*) filter (where rated_amps is null) as rated_amps_null,
       round(100.0 * count(*) filter (where rated_amps is null) / count(*), 1) as rated_amps_null_pct,
       count(*) filter (where rack_width_in is null) as rack_width_null,
       round(100.0 * count(*) filter (where rack_width_in is null) / count(*), 1) as rack_width_null_pct
from parts;

-- Q3: placeholder and blank values that are not SQL nulls
select count(*) filter (where lifecycle_status = 'Unknown') as lifecycle_unknown,
       round(100.0 * count(*) filter (where lifecycle_status = 'Unknown') / count(*), 1) as lifecycle_unknown_pct,
       count(*) filter (where in_stock_qty = 0) as zero_stock,
       round(100.0 * count(*) filter (where in_stock_qty = 0) / count(*), 1) as zero_stock_pct,
       count(*) filter (where btrim(manufacturer_part_number) = '') as blank_mfr_part_number,
       count(*) filter (where btrim(description) = '') as blank_description,
       count(*) filter (where btrim(category) = '') as blank_category
from parts;

-- Q4: parts with no price breaks (no price at all)
select count(*) as parts_without_price
from parts p
where not exists (select 1 from price_breaks b where b.part_id = p.part_id);

-- ============ C. Duplicates ============

-- Q5: duplicates on each table's natural key (constraints should make every count 0)
select 'manufacturers.name' as natural_key, count(*) - count(distinct name) as extra_copies from manufacturers
union all select 'parts.mouser_part_number', count(*) - count(distinct mouser_part_number) from parts
union all select 'price_breaks(part_id, quantity)',
                 count(*) - count(distinct (part_id, quantity)) from price_breaks
union all select 'part_attributes(part_id, name, value)',
                 count(*) - count(distinct (part_id, attribute_name, attribute_value)) from part_attributes
union all select 'part_on_order(part_id, expected_date)',
                 count(*) - count(distinct (part_id, expected_date)) from part_on_order
union all select 'search_keywords.keyword', count(*) - count(distinct keyword) from search_keywords
union all select 'part_search_hits(keyword_id, part_id, run_started_at)',
                 count(*) - count(distinct (keyword_id, part_id, run_started_at)) from part_search_hits;

-- Q6: near duplicates that differ only in case or spaces
select 'manufacturers.name' as natural_key,
       count(*) - count(distinct lower(btrim(name))) as extra_copies from manufacturers
union all select 'parts.mouser_part_number',
       count(*) - count(distinct upper(btrim(mouser_part_number))) from parts;

-- Q7: manufacturer part number + manufacturer repeated across Mouser part numbers (summary)
select count(*) as repeated_groups, coalesce(sum(n), 0) as parts_in_groups
from (select count(*) as n from parts
      group by manufacturer_id, upper(btrim(manufacturer_part_number))
      having count(*) > 1) g;

-- Q8: the most repeated manufacturer part numbers (top 10)
select m.name as manufacturer, upper(btrim(p.manufacturer_part_number)) as manufacturer_part_number,
       count(*) as mouser_listings,
       string_agg(p.mouser_part_number, ', ' order by p.mouser_part_number) as mouser_part_numbers
from parts p join manufacturers m using (manufacturer_id)
group by m.name, upper(btrim(p.manufacturer_part_number))
having count(*) > 1
order by count(*) desc, m.name
limit 10;

-- ============ D. Out-of-range values ============

-- Q9: out-of-range values on parts
select count(*) filter (where lead_time_days > 365) as lead_time_over_365_days,
       max(lead_time_days) as max_lead_time_days,
       count(*) filter (where tariff_pct > 100) as tariff_over_100_pct,
       max(tariff_pct) as max_tariff_pct,
       count(*) filter (where in_stock_qty > 100000) as stock_over_100000,
       max(in_stock_qty) as max_in_stock_qty,
       count(*) filter (where data_as_of > now()) as data_as_of_in_future,
       count(*) filter (where min_order_qty > 1000) as min_order_over_1000
from parts;

-- Q10: price breaks where the unit price goes UP at a larger quantity
select count(*) as rising_steps, count(distinct part_id) as parts_affected
from (select part_id, unit_price,
             lag(unit_price) over (partition by part_id order by quantity) as prev_price
      from price_breaks) s
where unit_price > prev_price;

-- Q11: unit price spread (a very high or low price may be a unit-of-measure problem)
select min(unit_price) as min_unit_price,
       percentile_cont(0.5) within group (order by unit_price) as median_unit_price,
       max(unit_price) as max_unit_price,
       count(*) filter (where unit_price > 10000) as over_10000_usd
from price_breaks;

-- Q12: on-order shipments whose expected date has already passed
select count(*) as past_expected_dates, min(expected_date) as oldest_expected_date
from part_on_order
where expected_date < current_date;

-- ============ E. Orphans and gaps ============

-- Q13: orphans (foreign keys should make every count 0)
select 'parts without manufacturer' as check_name, count(*) as row_count
  from parts p where not exists (select 1 from manufacturers m where m.manufacturer_id = p.manufacturer_id)
union all select 'price_breaks without part', count(*)
  from price_breaks b where not exists (select 1 from parts p where p.part_id = b.part_id)
union all select 'part_attributes without part', count(*)
  from part_attributes a where not exists (select 1 from parts p where p.part_id = a.part_id)
union all select 'part_on_order without part', count(*)
  from part_on_order o where not exists (select 1 from parts p where p.part_id = o.part_id)
union all select 'part_search_hits without part', count(*)
  from part_search_hits h where not exists (select 1 from parts p where p.part_id = h.part_id)
union all select 'part_search_hits without keyword', count(*)
  from part_search_hits h where not exists (select 1 from search_keywords k where k.keyword_id = h.keyword_id);

-- Q14: gaps: rows that exist but have nothing linked to them
select 'parts with no search hit' as check_name, count(*) as row_count
  from parts p where not exists (select 1 from part_search_hits h where h.part_id = p.part_id)
union all select 'manufacturers with no parts', count(*)
  from manufacturers m where not exists (select 1 from parts p where p.manufacturer_id = m.manufacturer_id)
union all select 'keywords with no hits', count(*)
  from search_keywords k where not exists (select 1 from part_search_hits h where h.keyword_id = k.keyword_id);

-- Q15: how long since each part's values last changed (data_as_of moves only when a value changes)
select case when data_as_of >= now() - interval '1 day'  then '1. under 1 day'
            when data_as_of >= now() - interval '7 days' then '2. 1 to 7 days'
            when data_as_of >= now() - interval '30 days' then '3. 7 to 30 days'
            else '4. over 30 days' end as last_changed,
       count(*) as parts
from parts
group by 1
order by 1;

-- ============ F. Fairness ============

-- Q16: tariffed share overall
select count(*) as parts,
       count(*) filter (where tariff_pct is not null) as tariffed,
       round(100.0 * count(*) filter (where tariff_pct is not null) / count(*), 1) as tariffed_pct
from parts;

-- Q17: tariffed share by manufacturer (10 largest manufacturers)
select m.name as manufacturer, count(*) as parts,
       count(*) filter (where p.tariff_pct is not null) as tariffed,
       round(100.0 * count(*) filter (where p.tariff_pct is not null) / count(*), 0) as tariffed_pct,
       count(*) filter (where p.in_stock_qty > 0) as in_stock,
       round(100.0 * count(*) filter (where p.in_stock_qty > 0) / count(*), 0) as in_stock_pct
from parts p join manufacturers m using (manufacturer_id)
group by m.name
order by count(*) desc, m.name
limit 10;

-- Q18: tariffed share by country of origin
select coalesce(country_of_origin, 'Not available') as country_of_origin, count(*) as parts,
       count(*) filter (where tariff_pct is not null) as tariffed,
       round(100.0 * count(*) filter (where tariff_pct is not null) / count(*), 0) as tariffed_pct
from parts
group by 1
order by count(*) desc
limit 8;

-- ============ G. Checks behind claims in docs/data_quality.md ============

-- Q19: is "no availability text" the same set of parts as "zero stock"?
select count(*) filter (where availability_text is null and in_stock_qty = 0)      as both,
       count(*) filter (where availability_text is null and in_stock_qty > 0)      as no_text_but_stock,
       count(*) filter (where availability_text is not null and in_stock_qty = 0)  as text_but_zero_stock
from parts;

-- Q20: tariff rates above 100%
select tariff_pct, count(*) as parts from parts where tariff_pct > 100 group by 1 order by 1;

-- Q21: parts by category (top 10), with amps and rack-width nulls per category
select category, count(*) as parts,
       count(*) filter (where rated_amps is null) as amps_null,
       count(*) filter (where rack_width_in is null) as width_null
from parts group by 1 order by 2 desc limit 10;

-- Q22: keyword visibility: parts whose most recent keyword-search hit is older than the latest run.
-- part_search_hits records keyword results only. A part found only by the part-number refresh pass gets
-- no hit, and a known part number that returns nothing is not recorded anywhere, so this does NOT
-- measure whether a part is gone from Mouser.
with last_seen as (select part_id, max(run_started_at) as last_seen_at
                   from part_search_hits group by part_id),
     latest as (select max(run_started_at) as latest_run from part_search_hits)
select (select latest_run from latest) as latest_run,
       count(*) filter (where last_seen_at = (select latest_run from latest)) as seen_in_latest_run,
       count(*) filter (where last_seen_at < (select latest_run from latest)) as not_seen_in_latest_run,
       min(last_seen_at) as oldest_last_seen
from last_seen;

-- Q23: brand coverage by category, with stock (brands from the baseline log and fairness check)
select m.name as manufacturer, p.category, count(*) as parts,
       count(*) filter (where p.in_stock_qty > 0) as in_stock
from parts p join manufacturers m using (manufacturer_id)
where m.name ~* '(apc|panduit|eaton|vertiv)'
group by 1, 2 order by 1, 3 desc, 2;

-- Q24: Vertiv and its brands (Geist, Liebert, Avocent), by manufacturer name or description
select (select count(*) from manufacturers where name ~* '(geist|liebert|avocent|vertiv)') as manufacturers,
       (select count(*) from parts where description ~* '(geist|liebert|avocent|vertiv)') as parts_mentioning;
