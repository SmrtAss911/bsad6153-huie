# Golden questions

The questions I ask when deciding which datacenter parts to buy, including ones the data can't answer.
Query numbers refer to `db/queries.sql`. Data: Mouser Search API only, as of each part's fetch time.

## The data can answer these

| # | Question | From my baseline log | Answer comes from |
|---|---|---|---|
| 1 | Which in-stock PDUs state a 20 A rating? | Vertiv 16 A vs 20 A | Q1. This is the unit's stated rating. |
| 2 | How many power strips state an amp rating at all? | Vertiv 16 A vs 20 A | Q2 |
| 3 | Which full racks state a 19 or 23 inch width? | Illinois 23 inch racks | Q3 |
| 4 | How many commodity cables are in stock, and do out-of-stock ones have an ETA? | Commodity cables | Q4 |
| 5 | Which manufacturer is cheapest for 100 Cat6A 3 ft cables, before and after the quoted tariff? | Commodity cables | Q5 |
| 6 | What exact SFP part numbers are available, with stock and lead time? | Optics | Q6 |
| 7 | Does a keyword search return only the kind of part I asked for? | Cable management | Q7. It does not. |

## The data answers these only in part

| # | Question | From my baseline log | What is missing |
|---|---|---|---|
| 8 | Is this rack 19 or 23 inch when the description doesn't say? | Illinois 23 inch racks | 12 of 18 full racks state no width in inches. Needs the datasheet. |
| 9 | Is this cabinet a network rack or a server rack? | APC cabinets | No column for it. Only free-text descriptions, and I have not tested how often they say. |
| 10 | Which SFPs are 25G, or 10/25G auto-sensing? | Optics | Speed appears only in description text and is not parsed. Auto-sensing is not checked. |
| 11 | What will I actually pay after tariffs? | Commodity cables | Mouser quotes a tariff that "may be applied." The final amount is not in the data. |
| 12 | How long will an out-of-stock part take to arrive? | Commodity cables | `lead_time_days` is 0 on 290 of 457 out-of-stock parts, which most likely means no figure was given. |

## The data cannot answer these

| # | Question | From my baseline log | Why not |
|---|---|---|---|
| 13 | What is the amp rating of each circuit or breaker on this PDU? | Vertiv 16 A vs 20 A | Descriptions mostly give the unit's rating, and 194 of 257 power strips give none. Needs the datasheet. |
| 14 | Does this vendor's custom part number match the manufacturer's part? | APC cabinets | The data has only Mouser's and the manufacturer's numbers, not my vendors' numbers. |
| 15 | Is this part cheaper or sooner at another distributor? | Commodity cables | Only Mouser is loaded. The Digi-Key source is not configured. |
| 16 | What is in stock right now? | Commodity cables | The data is a snapshot from each part's last fetch. |
| 17 | What cable management do people want to use in their datacenters? | Cable management | That is a preference and a standard. It is not catalog data. |
| 18 | Did the parts arrive correct, install correctly, and avoid rework? | Reflection, value hypothesis | No order, delivery, or installation data. |

[ANTHONY: add any other questions you ask about this decision]
