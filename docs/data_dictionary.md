# Data dictionary: Mouser Search API (Milestone 1)

## Source

| | |
|---|---|
| Name | Mouser Electronics Search API (primary source) |
| Base URL | `https://api.mouser.com` |
| Endpoint used | `POST /api/v1/search/keyword` (body: `SearchByKeywordRequest` with `keyword`, `records`, `startingRecord`) |
| Also available, not used | `POST /api/v1/search/partnumber` (up to 10 Mouser part numbers per call, pipe-separated; no paging) |
| Auth | API key passed as the `apiKey` query parameter on every call; stored only in `.env` as `MOUSER_API_KEY` |
| Limits | Up to 50 results per call, 30 calls per minute, 1,000 calls per day ([api-search page](https://www.mouser.com/en/api-search/)) |
| Docs | [Search API page](https://www.mouser.com/en/api-search/), [Swagger spec](https://api.mouser.com/api/docs/v1), [Swagger UI](https://api.mouser.com/api/docs/ui/index) |
| Terms | [Search API Terms of Service](https://www.mouser.com/en/apiterms/) (last modified March 11, 2013) |

**Backup source:** Digi-Key Product Information API v4 (OAuth2 client credentials). `ingest/sources/digikey.py` is a
"not configured" stub; its endpoint, token URL, and paging limits are not yet verified. [VERIFY]

**How this data was collected:** `python ingest/fetch.py --source mouser`, 12 keywords about standard datacenter parts,
up to 3 pages of 50 per keyword, 2.5 s between calls. Two runs on 2026-10-28 (UTC 03:28 and 03:31), 34 calls each,
0 errors. Raw responses are in `data/raw/mouser/` (gitignored); a 3-part sample is in `data/sample/mouser_sample.json`.

## What one record means

| Record type | Count (run 1) | One record is... |
|---|---|---|
| Part | 1,655 (1,456 unique) | One product Mouser sells, as returned on one page of one keyword search. |
| Price break | 8,453 | The unit price for one part when you buy at least a given quantity. |
| Product attribute | 2,234 | One name/value fact about a part, such as Packaging = Bulk. |
| Manufacturer | 56 distinct | One brand name that appears in a part's `Manufacturer` field. Mouser gives no manufacturer ID. |
| Raw file | 34 per run | One API call's response, wrapped with the keyword, `startingRecord`, time, and HTTP status. |

## Fields

Counts are from run 1 (1,655 part records). "Null/empty" means missing, JSON null, `""`, or `[]`.

| Field | Type | Example from my data | Meaning | Nullable (observed) |
|---|---|---|---|---|
| `MouserPartNumber` | string | `"16-87L38400POWERCORD"` | Mouser's own part number; the key for a part at Mouser | No (0) |
| `ManufacturerPartNumber` | string | `"87L3-8400-POWER-CORD"` | The maker's model number; what PDUs and racks are specified by | No (0) |
| `Manufacturer` | string | `"StarTech"` | Brand name | No (0) |
| `Description` | string | `"AC Power Cords Power Extension Cord, Locking C13 to C14 PDU Style - 10A, 25..."` | Mouser's text description | No (0) |
| `Category` | string | `"AC Power Cords"` | Mouser's product category | No (0) |
| `Availability` | string | `"10 In Stock"` | Stock as display text | Yes: 119 missing, plus 375 that are the string `"None"` |
| `AvailabilityInStock` | string holding a number | `"10"` | Units in stock now | Yes (1 null) |
| `AvailabilityOnOrder` | list of `{Quantity, Date}` | `[{"Quantity": 33, "Date": "2026-11-23T00:00:00"}, ...]` | Incoming stock and expected dates | Yes (1,471 empty) |
| `FactoryStock` | string holding a number | `"0"` | Stock at the manufacturer | Yes (1 null) |
| `LeadTime` | string | `"17 Days"` | Time to get more if out of stock | No (0) |
| `LifecycleStatus` | string | `"New at Mouser"` | Seen: New at Mouser 422, New Product 251, Factory Special Order 6, End of Life 5 | Yes (971 null) |
| `Min` | string holding a number | `"1"` | Minimum order quantity | No (0) |
| `Mult` | string holding a number | `"1"` | Order in multiples of this | No (0) |
| `PriceBreaks` | list of `{Quantity, Price, Currency}` | `[{"Quantity": 1, "Price": "$17.12", "Currency": "USD"}, ...]` | Quantity tiers and unit prices (all USD in my data) | Yes (2 empty) |
| `ProductAttributes` | list of `{AttributeName, AttributeValue}` | `[{"AttributeName": "Packaging", "AttributeValue": "Bulk"}, ...]` | Extra facts about the part | Yes (46 empty) |
| `ROHSStatus` | string | `"RoHS Compliant"` | Hazardous-substance compliance | Yes (356 empty) |
| `DataSheetUrl` | string | `"https://www.mouser.com/datasheet/3/6177/1/87l3_8400_power_cord_datasheet.pdf"` | Link to the datasheet | Yes (326 empty) |
| `ProductDetailUrl` | string | `"https://www.mouser.com/en/ProductDetail/StarTech/87L3-8400-POWER-CORD?qs=..."` | Link to the part's Mouser page | No (0) |

## Identifiers and relationships

    Manufacturer (name only) 1 ──< Part (MouserPartNumber) >── keyword searches (many-to-many)
                                        │
                                        ├──< Price break   (MouserPartNumber + Quantity)
                                        └──< Attribute     (MouserPartNumber + AttributeName)

- **Part key:** `MouserPartNumber`. It was unique per part across both runs.
- **Natural key:** `Manufacturer` + `ManufacturerPartNumber`. This is what my decision compares across distributors.
  In run 1, each one mapped to exactly one `MouserPartNumber` (0 of 1,456 had more than one). A larger sample could still
  show packaging variants under separate Mouser part numbers.
- **Price break key:** `MouserPartNumber` + `Quantity`. **Attributes have no unique key:** `AttributeName` can repeat on one
  part. In run 1, 2 of 1,456 parts repeat `Packaging` (`584-LT3086IDHD#TRPBF` 3 times, `501-OCTI140505` twice), so a
  table of attributes needs its own row ID or must keep the order.
- **Keyword ↔ part:** many-to-many. 137 parts appeared under 2 or more keywords.

## Update behavior

- **Expected to change:** `AvailabilityInStock`, `Availability`, `AvailabilityOnOrder`, `FactoryStock`, `LeadTime`,
  `PriceBreaks`, `LifecycleStatus`, `SuggestedReplacement`.
- **Detecting new or changed records:** key on `MouserPartNumber`. A part not seen before is new. For a known part, compare
  the fields above (or a hash of them) with the last run.
- **Absent is not discontinued:** a part missing from a later run may only have dropped in keyword search ranking.
  Use `/search/partnumber` to re-check known parts.
- **Observed so far:** between the two runs about 3 minutes apart, 0 of 1,456 parts changed any of
  `Availability`, `AvailabilityInStock`, `LeadTime`, `PriceBreaks`, or `LifecycleStatus`. Runs days apart are needed to see real
  changes. [VERIFY]

## Surprises in the data

1. **Up to 9 price breaks, while the API page says "up to 4."** Per part: 0 breaks 2 · 1: 112 · 2: 136 · 3: 184 · 4: 193 · 5: 210 ·
   6: 372 · 7: 172 · 8: 207 · 9: 67. Over half the parts have more than 4.
2. **"No stock" comes in three forms.** `Availability` is missing on 119 parts and is the literal string `"None"` on 375.
   It's never a JSON null. Code that checks `is None` would miss all of them.
   In those cases `AvailabilityInStock` is `"0"` (464 of 465 unique parts), so `"None"` means zero stock, not unknown.
3. **Every number is a string.** Prices are `"$17.12"` with a dollar sign and commas (142 are over $1,000, like `"$9,999.99"`),
   and 50 have three decimals (`"$9.999"`). `Min`, `Mult`, and `AvailabilityInStock` are strings like `"1"`, and lead time is `"17 Days"`.
4. **Pagination overlaps.** The same part appeared twice within one keyword's pages 12 times, so paging is not a clean partition.
5. **Keyword search is noisy.** "cable manager 1u" returned 8 LDO voltage regulators (`Category` = "LDO Voltage Regulators").
6. **The documented schema doesn't match the real data.** `IsDiscontinued` is in the Swagger spec but appeared on 0 parts.
   Only 31 distinct part fields were returned. One attribute carried an undocumented `AttributeCost` field (part
   `584-LT3086IDHD#TRPBF`).
7. **`NumberOfResult` is off by one.** "keystone jack cat6" reported 90 and returned 91; "rack cage nut" reported 63 and returned 64.
8. **`LifecycleStatus` is null for 971 of 1,655 parts (59%).**
9. **Some results can't be bought here.** 1 of 1,456 unique parts (`584-LT8697IUDD#PBF`) carries "Mouser does not presently
   sell this product in your region." It is also one of the 2 parts with no price breaks.
10. **Tariffs aren't in the price.** 407 of 1,456 unique parts (28%) have a `SurchargeMessages` notice such as "A tariff of 38%
    may be applied if shipping to the United..." (full text not checked). The rates range from 7% to 120% (most common: 38% on 134 parts,
    8% on 125, 11% on 64). `PriceBreaks` doesn't include them.

## Ethics check

Factual notes only. My judgment goes after each.

### Terms of service: storage, display, commercial use, attribution
- **Storage:** Mouser §4: you may not "cache, record, pre-fetch, or otherwise store any portion" of Mouser content, run "bulk
  download" operations, or use it "to update or create your own database of business listing information." Mouser §5 and §7:
  on termination, all Mouser data must be deleted. Digi-Key §5.1(e): no using the data "to update or create your own database
  of information"; §5.1(d): no bulk download. In this project, raw responses are kept locally in `data/raw/` (gitignored) and only
  a 3-part sample is committed.
- **Display:** Mouser §5 licenses display "solely on your Application." Digi-Key §5.2: Digi-Key data may not be displayed on pages
  whose principal purpose is not driving sales of Digi-Key products; §2: a downstream website needs prior approval.
- **Commercial use:** Mouser §1: the API is for presenting data in ways that "compliment and enhance" Mouser's own products and
  services. §2: Mouser may reject applications whose principal purpose is not "advertising and marketing the Mouser Electronics
  Content and driving sales of Mouser Electronics products." §5: no other use "without Mouser Electronics's prior written
  consent." §6: no pay-per-click or keyword campaigns without prior written approval.
- **Attribution:** Mouser §5: "You must clearly and conspicuously attribute the source of all Mouser Electronics Data." Mouser §8:
  materials that reference Mouser, including "screen shots," need prior written consent. Digi-Key §3.1.4: "clearly and
  conspicuously attribute DigiKey as the source of all DigiKey Data."

**My answer:** Unless it's a legal requirement, it doesn't bother me. Since these files are all local, they're not exposed to the public, they're for my personal use, and they're not used for corporate or money-making opportunities. Therefore, it doesn't really matter.

### Identifiable people: does the data contain or reveal any person?
- The fields are product catalog data: part numbers, manufacturer (company) names, descriptions, stock, prices, and links.
- No employer (Ascension) data, part lists, pricing, or credentials were used; all searches are generic public keywords.
- A pattern search of every text field on all 1,456 unique parts in run 1 found 0 email addresses and 1 phone-shaped
  string, which was a Mouser part number. The message fields hold only Mouser system text (shipping, region, and tariff
  notices). People's names can't be detected by a pattern search. [VERIFY: names]

**My answer:** No. It's only product information and part numbers, no personal or identifying data. That's also why this kind of tool is fine to use for my employer's work.

### Worst realistic harm: what happens if this data leaks or is misread?
- **Misread:** stock and prices change over time; a saved run shows them only as of `fetched_at`. `Availability` can be the
  string `"None"` (375 of 1,655 parts in run 1), and prices are text like `"$17.12"`, so naive code can misread both.
  Keyword results include unrelated parts (8 LDO voltage regulators for "cable manager 1u").
- **Leak of the API key:** Mouser §2: "You are fully responsible for all activities that occur using your Key(s)." The key is
  in the request URL (`apiKey` query parameter), so logging URLs would expose it; this project never logs URLs.
- **Terms breach:** Mouser §5 and §7 allow termination and require deleting all Mouser data; Mouser §6: repeat call-limit
  violations "may result in revocation." Digi-Key §9: three suspensions can lead to termination.

**My answer:** Somebody gets a lot of data and part numbers and takes credit for the work I did assembling it.

### Who may read or change the data (repo, raw files, future database, website)?
- **Repo:** GitHub `SmrtAss911/bsad6153-huie`. Public (confirmed on GitHub).
  Committed Mouser data is only `data/sample/mouser_sample.json` (3 parts).
- **Raw files:** `data/raw/` stays on this computer only (gitignored); anyone with access to this computer can read or change it.
- **Future database** (from the course template, Weeks 2–6): only the sync uses the owner connection (`DATABASE_URL`); the
  website and chatbot use a read-only role (`APP_DATABASE_URL`); the agent uses its own limited role (`AGENT_DATABASE_URL`).
- **Website** (Week 4, per the template): public on Render; the chatbot and agent sit behind `APP_PASSWORD`.

**My answer:** Only I can change it. The public just sees the read-only site during the class. When the class is over, I'm going to bring this back internal, develop it in-house within my own security, and use what I'm doing with Google AppSheet as the future roadmap.

---

AI use: drafted with Claude Code from fetched data; verified and revised by Anthony Huie.
