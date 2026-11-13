-- db/schema.sql: Milestone 2 schema for Mouser datacenter part data.
-- Week 3 adds sync_runs. Week 6 adds agent_runs and agent_proposals.
--
-- first_seen_at and last_updated_at record when the row reached this database.
-- They are not when Mouser reported the data: use parts.data_as_of and
-- part_search_hits.run_started_at for that.

-- One brand name, spelled as Mouser spells it. Mouser gives no manufacturer ID.
create table manufacturers (
    manufacturer_id bigint generated always as identity primary key,
    name            text not null unique check (btrim(name) <> ''),
    first_seen_at   timestamptz not null default now(),
    last_updated_at timestamptz not null default now()
);

-- One product Mouser sells, holding the newest copy seen in the raw files.
create table parts (
    part_id                  bigint generated always as identity primary key,
    mouser_part_number       text not null unique,
    manufacturer_id          bigint not null references manufacturers (manufacturer_id),
    -- Not unique with manufacturer_id: packaging variants could share a maker's number.
    manufacturer_part_number text not null,
    description              text not null,
    category                 text not null,
    availability_text        text,          -- null when Mouser sends "None" or nothing
    in_stock_qty             integer not null check (in_stock_qty >= 0),
    lead_time_days           integer not null check (lead_time_days >= 0),
    lifecycle_status         text not null default 'Unknown',  -- null at Mouser, never "Active"
    min_order_qty            integer not null check (min_order_qty > 0),
    order_multiple           integer not null check (order_multiple > 0),
    tariff_pct               numeric(6,2) check (tariff_pct >= 0),  -- null = no tariff notice
    country_of_origin        text,          -- null when Mouser says "Not available"
    -- Parsed from description. Null means the description does not state it, not "no".
    -- rated_amps is the unit's stated rating, often its input, not its per-circuit breaker rating.
    rated_amps               integer check (rated_amps > 0),
    rack_width_in            integer check (rack_width_in in (19, 23)),
    product_url              text not null,
    data_as_of               timestamptz not null,  -- when this copy was fetched from Mouser
    raw                      jsonb not null,        -- the part exactly as the API sent it
    first_seen_at            timestamptz not null default now(),
    last_updated_at          timestamptz not null default now()
);

create index parts_manufacturer_idx on parts (manufacturer_id, manufacturer_part_number);

-- The unit price of one part when buying at least this quantity.
-- A part with no price breaks has no rows here, so a missing price can never read as $0.
create table price_breaks (
    price_break_id  bigint generated always as identity primary key,
    part_id         bigint not null references parts (part_id),
    quantity        integer not null check (quantity > 0),
    unit_price      numeric(12,4) not null check (unit_price > 0),
    currency        text not null check (currency = 'USD'),
    first_seen_at   timestamptz not null default now(),
    last_updated_at timestamptz not null default now(),
    unique (part_id, quantity)
);

-- One name/value fact about a part. Name alone repeats on 2 parts, so the value is in the key.
create table part_attributes (
    part_attribute_id bigint generated always as identity primary key,
    part_id           bigint not null references parts (part_id),
    attribute_name    text not null,
    attribute_value   text not null,
    first_seen_at     timestamptz not null default now(),
    last_updated_at   timestamptz not null default now(),
    unique (part_id, attribute_name, attribute_value)
);

-- One incoming shipment of a part, with its expected arrival date.
create table part_on_order (
    part_on_order_id bigint generated always as identity primary key,
    part_id          bigint not null references parts (part_id),
    expected_date    date not null,
    quantity         integer not null check (quantity > 0),
    first_seen_at    timestamptz not null default now(),
    last_updated_at  timestamptz not null default now(),
    unique (part_id, expected_date)
);

-- One search term used against the Mouser API.
create table search_keywords (
    keyword_id      bigint generated always as identity primary key,
    keyword         text not null unique,
    first_seen_at   timestamptz not null default now(),
    last_updated_at timestamptz not null default now()
);

-- One part returned for one keyword in one fetch run. The unique key removes page overlaps.
create table part_search_hits (
    part_search_hit_id bigint generated always as identity primary key,
    keyword_id         bigint not null references search_keywords (keyword_id),
    part_id            bigint not null references parts (part_id),
    run_started_at     timestamptz not null,  -- from the raw file's name
    fetched_at         timestamptz not null,  -- from inside the raw file
    first_seen_at      timestamptz not null default now(),
    last_updated_at    timestamptz not null default now(),
    unique (keyword_id, part_id, run_started_at),
    check (fetched_at >= run_started_at)
);

create index part_search_hits_part_idx on part_search_hits (part_id);
