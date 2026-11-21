# Data quality: Mouser run 1

## Source and scope

- **Run:** run 1 of `python ingest/fetch.py --source mouser`, 2026-10-28, 03:28:08–03:29:29 UTC. 34 API calls, all HTTP 200.
- **Records:** 12 keywords, up to 3 pages of 50 each. 1,655 part records, 1,456 unique `MouserPartNumber`.
- **Base for counts:** every count below is over the 1,456 unique parts (first copy kept), unless it says otherwise.
  Some counts in the data dictionary are over all 1,655 records, so they run higher (for example, 375 vs. 361 `"None"`).
- **Fields:** see [data_dictionary.md](data_dictionary.md).
- **Method:** a read-only script over the saved raw JSON in `data/raw/mouser/` (gitignored). No API calls were made.

## Findings

### 1. Listed prices exclude tariffs on 407 of 1,456 parts (28.0%)
- **What:** these parts carry a `SurchargeMessages` notice (code `TARIFF_US`): "A tariff of X% may be applied if shipping to
  the United States." The quoted rates run from 7% to 120%. The most common are 38% (134 parts), 8% (125), and 11% (64).
  4 parts quote 120%. `PriceBreaks` never includes the tariff.
- **Why it matters:** a US buyer may pay up to 2.2 times the listed price. A $100 part with a 38% notice can cost $138.
  Comparing parts on listed price alone ranks them wrong.

### 2. "No stock" comes in three forms
- **What:** `Availability` is missing on 104 parts (7.1%) and is the string `"None"` on 361 (24.8%).
  `AvailabilityInStock` is `"0"` on 464 (31.9%). Of the 465 parts where `Availability` is missing or `"None"`, 464 have
  `AvailabilityInStock` = `"0"`.
- **Why it matters:** code that checks for null misses all of them. Nearly a third of the parts can't ship today.

### 3. Lifecycle is unknown for 792 parts (54.4%)
- **What:** `LifecycleStatus` is null on 792 parts. The known values are New at Mouser (415), New Product (238),
  Factory Special Order (6), and End of Life (5).
- **Why it matters:** a null value doesn't mean the part is active. A buyer can't tell whether it is being phased out.

### 4. Keyword search returns unrelated parts
- **Rule:** a part matches its keyword if its `Category` or `Description` contains one of that keyword's intent terms
  (for example, "pdu", "outlet strip", or "power distribution" for "rack pdu").
- **"cable manager 1u":** 15 of 149 parts are unrelated: 13 voltage regulators (8 LDO, 5 switching), 1 LiPo battery
  manager, and 1 24-port patch panel. The rule first flagged 71. A hand check showed that 56 of them are real cable
  management hardware described with abbreviations ("MGR", "CBL"). Many results are not 1U (for example, 42U vertical
  managers), so the size in the keyword isn't enforced.
- **Other keywords (flagged by the rule, not checked by hand):**
  - keystone jack cat6: 9 of 90 (test plugs and jacks 5, PCB hardware 4)
  - rack pdu: 5 of 149
  - server rack shelf: 3 of 149
  - rack cage nut: 2 of 63
  - The other 7 keywords: 0.
- **Total:** 34 of 1,643 keyword-part pairs (2.1%).
- **Why it matters:** a buyer or agent could be shown a voltage regulator when they asked for a cable manager.

### 5. Pages overlap within a keyword
- **What:** 12 extra copies in total, exactly 1 in each of the 12 keywords, including the two keywords with only 2 pages.
  That fits an overlap at the page boundary. The cause is not confirmed: it could be how `fetch.py` sets `startingRecord`,
  or how Mouser pages results.
- **Separately:** 137 parts appear under 2 or more keywords. That is expected, not an error.
- **Why it matters:** without deduping, part counts and totals are inflated.

### 6. 2 parts have no price breaks (0.1%)
- **What:** `PriceBreaks` is empty on 2 parts. One of them is marked as not sold in this region
  (see [data_dictionary.md](data_dictionary.md)).
- **Why it matters:** a missing price must not be read as $0, which would rank the part as the cheapest.

## Fairness check

This data has no people in it, so fairness here means treating manufacturers and vendors evenly.
32 of 56 manufacturers have at least one tariffed part, and 24 have none.

| Manufacturer | Tariffed parts | Total parts | Share tariffed |
|---|---|---|---|
| Tripp Lite | 254 | 265 | 96% |
| APC by Schneider Electric | 27 | 60 | 45% |
| Stewart Connector | 25 | 26 | 96% |
| Eaton | 11 | 19 | 58% |
| HARTING | 10 | 11 | 91% |
| ATOP | 9 | 9 | 100% |
| Volex | 8 | 8 | 100% |
| Keystone Electronics | 7 | 11 | 64% |
| TE Connectivity / Schaffner | 5 | 5 | 100% |
| Amphenol Cables on Demand | 5 | 5 | 100% |

The largest manufacturers with no tariffed parts are StarTech (348 parts), Hammond Manufacturing (216), L-Com (170),
Amphenol ProLabs (85), and Panduit (46). Tripp Lite alone has 254 of the 407 tariffed parts (62%).

By country of origin (`TradeCompliance`):

| Country of origin | Parts | Tariffed | Share tariffed |
|---|---|---|---|
| China | 584 | 152 | 26% |
| Canada | 219 | 2 | 1% |
| Taiwan | 185 | 86 | 46% |
| Vietnam | 132 | 67 | 51% |
| United States | 128 | 0 | 0% |
| Not available | 99 | 57 | 58% |

**Fact:** a ranking on listed price alone favors tariffed parts, because their listed price understates what a US buyer
may pay. In this data, that tilts toward manufacturers like Tripp Lite (96% of its parts tariffed) and against
manufacturers with no tariffed parts, like StarTech.

The fairness check here would go vendor to vendor. If it was purely decided by price, products with tariffs would look cheaper than products without tariffs, and therefore might get selected just purely based off price alone, which obviously isn't a good thing

## If an agent acted on this unaware

- **Tariff:** recommends the cheapest listed part, which may cost more after a tariff of up to 120%.
- **No stock:** reports `"None"` parts as in stock or unknown, and recommends parts that can't ship.
- **Lifecycle:** treats a null lifecycle as active and recommends parts that may be near end of life.
- **Keyword noise:** recommends a voltage regulator when asked for a 1U cable manager.
- **Pagination overlap:** double counts parts and overstates how many options exist.
- **No price breaks:** reads a missing price as $0 and ranks the part as the cheapest.

## Handling plan

**`load.py`:**
- Dedupe on `MouserPartNumber`. Keep the keyword-to-part links in their own table.
- Treat `Availability` missing or `"None"` as zero stock. Store `AvailabilityInStock` as an integer.
- Flag tariffed parts: store `tariff_pct` parsed from `SurchargeMessages` (`TARIFF_US`), plus country of origin.
- Store a null `LifecycleStatus` as "Unknown", never as "Active".
- Store no price for parts with no price breaks, and leave them out of price ranking.

**Future agent:**
- Never rank on listed price alone. Show the listed price, the price with the quoted tariff, and a tariff flag.
- Show "Lifecycle: unknown" when the value is null.
- Drop parts whose category doesn't match the request, and check size (such as 1U) before recommending.
- Say that stock and prices are as of the fetch time.

## Database checks (Milestone 3)

- **When:** 2026-11-16 07:40 UTC, after 7 sync runs (the last one by GitHub Actions).
- **How:** `db/quality_checks.sql` (Q1–Q24), run with `scripts/run_quality_checks.py` as `app_reader` in a
  read-only session. SELECT only.
- **Rows (Q1):** 1,639 parts, 56 manufacturers, 8,551 price breaks, 2,249 attributes, 156 on-order rows,
  12 keywords, 14,504 search hits, 7 sync runs.

### What passed

| Check | Query | Result |
|---|---|---|
| Duplicates on every natural key | Q5 | 0 |
| Duplicates differing only in case or spaces | Q6 | 0 |
| Same manufacturer part number listed twice for one manufacturer | Q7 | 0 groups |
| Unit price rising at a larger quantity | Q10 | 0 |
| On-order dates already past | Q12 | 0 |
| Orphan rows (6 foreign keys) | Q13 | 0 |
| Parts with no search hit, manufacturers with no parts, keywords with no hits | Q14 | 0 |

The constraints in `db/schema.sql` enforce the Q5 and Q13 results, so these confirm the constraints are in place
rather than finding anything new.

### Findings

1. **Zero stock: 488 of 1,639 parts (29.8%)** (Q3). These are exactly the 488 parts with no
   `availability_text` (Q2, Q19: 488 in both, 0 in only one), so the load handles all three "no stock"
   forms the same way.
2. **Lifecycle unknown: 885 parts (54.0%)** (Q3), about the same as Oct 28 (54.4%).
3. **Amps and rack width are mostly null** (Q2): `rated_amps` 95.8%, `rack_width_in` 96.6%. About half the parts
   (868, 53.0%) are Ethernet cables, fiber assemblies, power cords and transceivers (Q21), which have no rack
   width, and whose current rating `rated_amps` doesn't track. The gaps are also inside the categories that need
   them: only 69 of 281 power outlet strips have `rated_amps`, and only 56 of 316 rack and cabinet parts have
   `rack_width_in` (Q21). A null means the description doesn't say, so these columns can narrow PDUs and racks
   but can't rule a part out.
4. **2 parts have no price** (Q4). They have no `price_breaks` rows, so they can't be read as $0.
5. **Out of range** (Q9): 1 part has a 435-day lead time, 5 parts carry a 120% tariff notice (all exactly
   120%, Q20; 4 on Oct 28), and 3 parts have a minimum order over 1,000. These look like real Mouser values,
   not load errors: they pass the schema checks and the 120% tariffs were already in the Oct 28 raw data.
   I have not yet hand-checked the lead time and minimum orders on mouser.com.
6. **Freshness** (Q15, Q22). The database can answer two freshness questions but not a third:
   - **Last changed** (Q15): `data_as_of` moves only when a part's values, price breaks, attributes or
     on-order rows change (`UPSERT_PARTS` and `TOUCH_PARTS` in `ingest/sync.py`). 162 parts changed in the
     last day, 724 in 1–7 days and 753 in 7–30 days. An old `data_as_of` means "unchanged since then",
     not "not checked since then".
   - **Keyword visibility** (Q22): in the latest keyword search (run 7, 2026-11-16 01:29 UTC), 1,455 of
     1,639 parts appeared and 184 did not; the oldest last hit is the Oct 28 load. This measures whether a
     part still shows up in the first 3 pages of the 12 keywords, not whether Mouser still sells it:
     results shift between runs, and a part found only by the part-number refresh pass gets no hit.
   - **Part no longer found: not recorded.** Every run also looks up each known part number. When one
     returns nothing, `sync.py` only logs a count (`watched missing` in the run's console or Actions log)
     and fails the run if more than half are missing. The part numbers are not stored, so the database
     cannot list parts Mouser no longer returns. **Known limitation.** Not adding `last_found_at` in this
     milestone. Planned change: have the refresh pass record when each part was last found, so a later
     milestone can flag parts Mouser no longer returns.

### Fairness check (Milestone 3)

- **Tariffs** (Q16): 446 of 1,639 parts (27.2%) carry a tariff notice (Oct 28: 407 of 1,456, 28.0%).
- **By manufacturer** (Q17, 10 largest):

| Manufacturer | Parts | Tariffed | In stock |
|---|---|---|---|
| StarTech | 436 | 0% | 83% |
| Tripp Lite | 288 | 97% | 55% |
| Hammond Manufacturing | 225 | 0% | 61% |
| L-Com | 197 | 0% | 72% |
| Amphenol ProLabs | 87 | 0% | 93% |
| APC by Schneider Electric | 67 | 43% | 24% |
| Panduit | 47 | 0% | 28% |
| Stewart Connector | 28 | 96% | 93% |
| Bud Industries | 26 | 0% | 65% |
| Eaton | 21 | 62% | 33% |

- **By country** (Q18): Taiwan 48% tariffed, Vietnam 34%, China 26%, Canada 1%, United States 0%;
  "Not available" 56%.
- **Fact:** an "in stock only" filter keeps 83% of StarTech parts but only 24% of APC and 28% of Panduit.
- **Judgment:** filtering on stock tilts recommendations toward StarTech (83% in stock) and away from APC (24%),
  Panduit (28%) and Eaton (33%). The effect is in racks and cabinets, not PDUs: an in-stock filter keeps 4 of
  their 59 rack accessories and 0 of their 10 cabinets, but 20 of their 33 outlet strips (Q23). The data barely
  covers my baseline problems: it has 1 APC cabinet (out of stock), and no parts from Vertiv, the PDU brand in
  my baseline log, or its Geist, Liebert and Avocent brands (no manufacturer name or description mentions them;
  Q23, Q24). So for my decisions the bigger fairness risk is coverage, not the stock filter: this data barely
  covers the exact-model cabinets and PDUs I standardize on, so the tool must say when a required model isn't
  in the data instead of offering an in-stock lookalike. A ranking on listed price alone still favors Tripp
  Lite, whose parts carry a tariff notice on 97% of them, so their listed prices understate the US cost. The
  agent should show out-of-stock exact matches with their lead time rather than hide them.

## Freshness, ownership and alerting (Milestone 3)

Lineage (API to `sync.py` to each table) is in [data_dictionary.md](data_dictionary.md#lineage-milestone-3).
Runs 8–11, cited below, came after the 07:40 UTC database checks above.

### Worst-case freshness

- **Normal:** a scheduled sync at 11:41 and 23:41 UTC. A run takes about 8.5 minutes (runs 7, 9 and 11).
  If every run succeeds, the data is at most about 12 hours old plus GitHub's start delay.
- **GitHub's delay can exceed the 1 hour of slack** in `scripts/status.py`: scheduled Actions run #3
  (run 11) started 2026-11-16 21:06 UTC; it was the delayed 11:17 trigger, about 9 h 49 min late.
  My decision: record late runs and leave them, because my decisions only need same-day data.
- **One failed run:** nothing is written (runs 8 and 10), and the next try is 12 hours later, so the data
  is about 24 hours old.
- **No upper bound:** if runs keep failing or the schedule doesn't fire, the data keeps aging, and nothing
  says so until someone runs `scripts/status.py`. GitHub also disables scheduled workflows in a public repo
  after 60 days without repository activity. I will keep committing during the course.
- **Per part:** a part in a skipped batch, or one Mouser no longer returns, keeps its last values with no
  flag (Finding 6), so one part's worst case has no bound even when every run succeeds.

### Ownership

| What | Owner |
|---|---|
| Source data and its terms | Mouser Electronics |
| Sync code, schema, database, GitHub secrets, schedule | Anthony Huie |

Just me, no backup.

### Alerting

- **Failed run:** `sync.py` exits 1, so the Actions job fails and GitHub sends a failed-workflow email.
  The failure emails come to me; I have not checked the Actions notification setting yet. A run on my
  PC alerts no one.
- **Partial run:** exits 0, so the Actions job shows green. The reasons are only in `sync_runs.error_message`
  and the log. Not alerted.
- **Run that can't connect or never starts:** no `sync_runs` row (Actions run #1, `docs/sync_tests.md`),
  and if the schedule doesn't fire, no Actions run at all. Only `scripts/status.py` notices, as stale data
  after 13 hours, and only when someone runs it.
- **Mouser format change:** new field names print a WARNING in the log (run 9: `REACH-SVHC`,
  `RestrictionMessage`, `SalesMaximumOrderQty`). Not alerted.
- **Freshness check:** every sync run now reports freshness. The last step of
  `.github/workflows/sync.yml` runs `scripts/status.py` with `if: always()`, so it runs even when the
  sync step fails.
- **Change log:** see [data_dictionary.md](data_dictionary.md#change-log).

---

Drafted with Claude from the saved Mouser data; verified by Anthony Huie.
