# Database schema

The database holds Mouser catalog data for datacenter parts. The tables are defined in [`db/schema.sql`](../db/schema.sql).

## Entity relationship diagram

```mermaid
erDiagram
    manufacturers ||--o{ parts : makes
    parts ||--o{ price_breaks : "priced at"
    parts ||--o{ part_attributes : "described by"
    parts ||--o{ part_on_order : "arriving as"
    parts ||--o{ part_search_hits : "returned in"
    search_keywords ||--o{ part_search_hits : returns

    manufacturers {
        bigint manufacturer_id PK
        text name UK
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    parts {
        bigint part_id PK
        text mouser_part_number UK
        bigint manufacturer_id FK
        text manufacturer_part_number
        text description
        text category
        text availability_text "nullable"
        integer in_stock_qty
        integer lead_time_days
        text lifecycle_status
        integer min_order_qty
        integer order_multiple
        numeric tariff_pct "nullable"
        text country_of_origin "nullable"
        integer rated_amps "nullable"
        integer rack_width_in "nullable, 19 or 23"
        text product_url
        timestamptz data_as_of
        jsonb raw
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    price_breaks {
        bigint price_break_id PK
        bigint part_id FK "unique with quantity"
        integer quantity
        numeric unit_price
        text currency
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    part_attributes {
        bigint part_attribute_id PK
        bigint part_id FK "unique with name and value"
        text attribute_name
        text attribute_value
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    part_on_order {
        bigint part_on_order_id PK
        bigint part_id FK "unique with expected_date"
        date expected_date
        integer quantity
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    search_keywords {
        bigint keyword_id PK
        text keyword UK
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    part_search_hits {
        bigint part_search_hit_id PK
        bigint keyword_id FK "unique with part_id and run_started_at"
        bigint part_id FK
        timestamptz run_started_at
        timestamptz fetched_at
        timestamptz first_seen_at
        timestamptz last_updated_at
    }
```

## What one row means

| Table | One row is |
|---|---|
| `manufacturers` | One brand name, spelled the way Mouser spells it. Mouser provides no manufacturer ID. |
| `parts` | One product Mouser sells, holding the newest copy seen in the raw files. `data_as_of` says when that copy was fetched. |
| `price_breaks` | The unit price of one part when buying at least a given quantity. A part with no price breaks has no rows, so a missing price can't read as $0. |
| `part_attributes` | One name and value fact about a part, such as Packaging = Bulk. The value is part of the key because the same name repeats on some parts. |
| `part_on_order` | One incoming shipment of a part, with its quantity and expected arrival date. |
| `search_keywords` | One search term used against the Mouser API. |
| `part_search_hits` | One part returned for one keyword in one fetch run. This many-to-many table keeps the search history and shows noisy results. |

`first_seen_at` and `last_updated_at` record when a row reached this database. For when Mouser reported the data, use `parts.data_as_of` and `part_search_hits.run_started_at`.

## Design decision: amps and rack width as parsed columns

Mouser has no structured field for amperage or rack width. Across all 1,462 parts, `ProductAttributes` holds only `Standard Pack Qty` and `Packaging`, so these specs appear only in description text.

Claude recommended leaving them out of the columns this week and searching descriptions in the queries, because parsing free text can present a guess as a spec. I rejected that and added nullable `rated_amps` and `rack_width_in` columns, because the biggest mistakes in my baseline log were 16 A vs 20 A PDUs and 19 vs 23 inch racks. Those specs have to be queryable.

**The trade-off.** Parsed columns make the specs easy to filter, but they can only be as good as the descriptions. A pattern test showed how this goes wrong, so the rules are strict:

- `rated_amps` is filled only for power strips. Two different values on one part stay null (3 dual-rated parts), and values above 63 are ignored.
- `rack_width_in` is filled only for the two rack categories. A number described as a depth is rejected, which removed 5 false "23 inch" values.
- Null means the description doesn't clearly state the value. It never means "no."

The result is 63 of 257 power strips with an amp rating and 51 of 301 rack products with a width. The column is named `rated_amps` and not `circuit_amps` because descriptions usually give the unit's rating, often its input, and not the per-circuit breaker rating that caused my PDU mistake. The original text stays in `parts.raw`.

[ANTHONY: confirm this matches what you decided]
