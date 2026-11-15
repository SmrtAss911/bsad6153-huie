-- db/roles.sql: who may do what in the database.
--
-- NEVER PUT A PASSWORD IN THIS FILE. It is committed to GitHub.
-- Run this after db/schema.sql, in the Supabase SQL editor, as the owner.
-- Then set the password separately, in the SQL editor only:
--     alter role app_reader with password '...';
-- Put the connection string in .env as APP_DATABASE_URL (never in this repo).

-- Week 2/3: read-only role for the website, chatbot, status script, and golden-question checker.
-- Created only if missing, so the file can be run again safely.
do $$
begin
    if not exists (select from pg_roles where rolname = 'app_reader') then
        create role app_reader login;
    end if;
end
$$;

grant usage on schema public to app_reader;

grant select on
    manufacturers, search_keywords, parts, price_breaks,
    part_attributes, part_on_order, part_search_hits
to app_reader;

-- sync_runs is added to schema.sql in Week 3. This grant runs only once the table exists,
-- so the file works both before and after that migration.
do $$
begin
    if to_regclass('public.sync_runs') is not null then
        grant select on sync_runs to app_reader;
    end if;
end
$$;

-- Week 6 (not yet): the agent's own role (see the Week 6 page for the exact grants).
-- create role agent_writer login;
-- grant usage on schema public to agent_writer;
-- grant select on <your data tables>, sync_runs, agent_runs, agent_proposals to agent_writer;
-- grant insert on agent_runs, agent_proposals to agent_writer;
-- grant update on agent_runs to agent_writer;
--
-- Week 6: the one write your website may do, which covers only the review columns.
-- grant select on agent_runs, agent_proposals to app_reader;
-- grant update (status, reviewed_at, reviewer_note) on agent_proposals to app_reader;
