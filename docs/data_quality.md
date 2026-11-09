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

---

Drafted with Claude from the saved Mouser data; verified by Anthony Huie.
