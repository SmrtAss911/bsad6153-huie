-- db/queries.sql: business questions from docs/baseline_log.md, answered from the Mouser data.
--
-- Notes for reading these results:
--   * rated_amps is the unit's stated rating, often its input, not its per-circuit breaker rating.
--   * A null rated_amps or rack_width_in means the description does not state it clearly.
--   * lead_time_days = 0 appears on 482 of 1,462 parts, including 290 of 457 out-of-stock parts.
--     It most likely means Mouser gave no figure, so these queries treat it as "not stated".
--   * Stock and prices are as of each part's data_as_of. They are not live.

-- Q1 (Vertiv PDU mix-up): Which in-stock power strips state a 20 A rating?
-- Interpretation: 18 in-stock parts state 20 A; check each datasheet, since this is the unit's rating.
select m.name as manufacturer, p.manufacturer_part_number, p.rated_amps, p.in_stock_qty,
       p.lead_time_days, p.description
from parts p
join manufacturers m using (manufacturer_id)
where p.category = 'Power Outlet Strips'
  and p.rated_amps = 20
  and p.in_stock_qty > 0
order by p.in_stock_qty desc;

-- Q2 (Vertiv PDU mix-up): How many power strips state an amp rating at all, and which ratings?
-- Interpretation: 194 of 257 (75.5%) state no rating, so a filter on amps alone misses most of them.
select coalesce(p.rated_amps::text, 'not stated') as rated_amps,
       count(*) as parts,
       count(*) filter (where p.in_stock_qty > 0) as in_stock,
       round(100.0 * count(*) / sum(count(*)) over (), 1) as pct_of_power_strips
from parts p
where p.category = 'Power Outlet Strips'
group by p.rated_amps
order by parts desc;

-- Q3 (Illinois 23 inch racks): Which full racks state a width, and which do not?
-- SURPRISING RESULT: of 18 full racks, 6 state a width, all 23 inch, and none states 19 inch.
-- Why it surprised me: 19 inch is the standard for our gear, so I expected it to be stated most often.
-- The width that caused my mistake is the only one spelled out; the other 12 racks need a datasheet check.
-- Limit: none of the 12 search keywords targeted full racks, so 18 is a small sample.
select coalesce(p.rack_width_in::text, 'not stated') as width_in, m.name as manufacturer,
       p.manufacturer_part_number, p.in_stock_qty, p.lead_time_days, p.description
from parts p
join manufacturers m using (manufacturer_id)
where p.category = 'Racks & Rack Cabinets'
order by p.rack_width_in nulls last, m.name;

-- Q4 (commodity cables): How many cables are in stock, and do the out-of-stock ones have an ETA?
-- Interpretation: all 151 fiber cords are in stock; 92 Ethernet and 34 power cords are out, and few have an ETA.
with next_arrival as (
    select part_id, min(expected_date) as next_date
    from part_on_order
    where expected_date >= current_date
    group by part_id
)
select p.category,
       count(*) as parts,
       count(*) filter (where p.in_stock_qty > 0) as in_stock,
       count(*) filter (where p.in_stock_qty = 0) as out_of_stock,
       count(*) filter (where p.in_stock_qty = 0 and n.part_id is not null) as out_of_stock_with_eta,
       min(n.next_date) filter (where p.in_stock_qty = 0) as soonest_eta,
       count(*) filter (where p.in_stock_qty = 0 and p.lead_time_days = 0) as out_of_stock_lead_not_stated,
       round(avg(p.lead_time_days) filter (where p.in_stock_qty = 0 and p.lead_time_days > 0)) as avg_lead_days_when_stated
from parts p
left join next_arrival n using (part_id)
where p.category in ('Ethernet Cables / Networking Cables', 'Fiber Optic Cable Assemblies', 'AC Power Cords')
group by p.category
order by p.category;

-- Q5 (commodity cables): Which manufacturer lists the cheapest 3 ft Cat6A cable when buying 100,
-- before and after the quoted tariff, and is that quantity available?
-- The price at 100 is the tier with the largest quantity at or below 100.
-- Interpretation: Taoglas lists the lowest at $7.27, but no part has 100 in stock (most is 99), and a 38% tariff moves Tripp Lite behind Amphenol ProLabs.
with price_at_100 as (
    select distinct on (b.part_id) b.part_id, b.unit_price
    from price_breaks b
    where b.quantity <= 100
    order by b.part_id, b.quantity desc
)
select m.name as manufacturer,
       count(*) as parts,
       round(min(a.unit_price), 2) as cheapest_listed,
       round(min(a.unit_price * (1 + coalesce(p.tariff_pct, 0) / 100)), 2) as cheapest_with_tariff,
       max(p.tariff_pct) as highest_tariff_pct,
       max(p.in_stock_qty) as most_in_stock
from parts p
join manufacturers m using (manufacturer_id)
join price_at_100 a using (part_id)
where p.category = 'Ethernet Cables / Networking Cables'
  and p.description ~* 'cat\s*-?6a'
  and p.description ~* '\m3 ?(ft|foot)\M'
  and p.min_order_qty <= 100
group by m.name
order by cheapest_with_tariff;

-- Q6 (optics, exact part numbers): Which SFP part numbers appeared in the last 7 days,
-- with their stock and lead time?
-- Interpretation: 50 exact part numbers to quote instead of a generic description; this returns nothing after about Nov 16 without a new fetch.
select *
from (
    select distinct on (p.part_id)
           m.name as manufacturer, p.manufacturer_part_number, p.mouser_part_number,
           p.in_stock_qty, p.lead_time_days, h.run_started_at, p.description
    from part_search_hits h
    join search_keywords k using (keyword_id)
    join parts p using (part_id)
    join manufacturers m using (manufacturer_id)
    where k.keyword = 'sfp transceiver'
      and h.run_started_at >= now() - interval '7 days'
    order by p.part_id, h.run_started_at desc
) recent_sfps
order by in_stock_qty desc;

-- Q7 (cable management): What categories does the search "cable manager 1u" actually return?
-- Interpretation: most results are rack accessories, but 13 are voltage regulators, so a keyword alone can't pick a part.
select p.category, count(distinct p.part_id) as parts
from part_search_hits h
join search_keywords k using (keyword_id)
join parts p using (part_id)
where k.keyword = 'cable manager 1u'
group by p.category
order by parts desc;
