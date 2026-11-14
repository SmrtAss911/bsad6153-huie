# Implementation Brief: Datacenter Parts Sourcing
Anthony Huie · BSAD 6153 · 4.3 · November 2026

## My workflow
I decide which datacenter parts to buy (part number, spec and vendor) for each item on a pick list, based on spec, stock, lead time and price. I make this decision anywhere from several times a day to once a week, depending on workload.

Today it is manual: email the vendor for a quote, wait about half a day, reply "yes, order," wait another half day. My baseline log (`docs/baseline_log.md`) has 6 entries, all reconstructed or estimated; timed measurement starts with the Milestone 4 usage log.

| Decision | Hands on time | Outcome |
|---|---|---|
| APC cabinets | about 120 min, a week or more calendar | Wrong rack type received (network instead of server) |
| Vertiv PDUs | about 120 min | Ten 16 A units received instead of 20 A |
| Racks, Illinois site | unknown; one month wait plus rework | 23 inch racks instead of 19 inch |
| Commodity cables | 5 to 10 min; a couple of days calendar | Correct but slow |
| SFP optics | about 15 min so far | Waiting on a quote from a generic description |
| Cable management | 2 to 3 weeks on and off | On hold, no standards |

In 3 of 6 decisions the wrong part was ordered, and my confidence was 4 or 5 out of 5 on all three. Confidence did not predict correctness. My main frustrations: the research takes too long by hand, AI answers are generic and miss installation nuances, and vendor titles look the same while the specs differ.

## Should this use AI?
| Option | Solves | Costs | Could go wrong |
|---|---|---|---|
| **A. No new technology:** approved model list (20 A PDUs, 19 inch racks) and preferred vendor checklist | Wrong spec orders, my most expensive mistakes | A few hours; $0 | Stock, price and lead time still checked by hand; list goes stale |
| **B. Data without AI:** scheduled Mouser sync into Supabase plus saved SQL reports (in stock, lowest price, long lead time, missing amps or rack width) | Lookup and comparison work; exact answers (Q1 already lists 18 in stock 20 A strips) | $0 on free tiers | Only as fresh as the last sync; a Mouser format change can load silently wrong values; personal use terms |
| **C. LLM chatbot (M5) and agent (M6)** that drafts a recommended order for my approval | Loosely worded requests matched to real parts; drafting the recommendation | LLM usage; more testing | Picks a part that only looks equivalent (my 16 A vs 20 A mistake), invents a part number, sounds too certain |

**Conclusion.** Most of the value is in A plus B: fixed standards and exact database answers. The LLM only helps match plain language specs to commodity parts and draft a recommendation. I should be choosing the rack model and PDU to get it accurate, but have the data that the database has to support it.

## Value hypothesis
1. **Wrong part orders:** baseline 3 of 6 logged decisions. Target: 0 wrong spec orders on decisions made with the tool.
2. **Time to a budgetary number:** baseline about 2 days of calendar time for an emailed commodity quote. Target: a budgetary number in under 15 minutes.

Measurement: from Milestone 4, every real sourcing decision goes in `docs/usage_log.md` with a timer, the tool used, whether I still checked the vendor, and whether the part was correct on arrival.

## Early cost estimate
Prices checked 2026-11-13.

| Item | Assumption | Per month |
|---|---|---|
| Supabase, GitHub Actions, Render | Free tiers (500 MB database; public repo; 750 instance hours, sleeps when idle) | $0 |
| Mouser Search API | 1,000 calls per day; 2 syncs of 34 calls use 68 (6.8%) | $0 |
| LLM: Claude Haiku 5.5 | $0.10 in and $0.50 out per million tokens; 8,000 tokens in, 600 out per question | $0.33 at 10 questions a day (Sonnet 5.5 would be $6.60) |

**Spending cap:** a $5 monthly spend limit set in the Claude Console. At the limit the API refuses requests; the chatbot shows "Assistant unavailable, use the saved reports," and the Option B reports keep working.

## Risks and governance
A wrong answer could mean the wrong part, overpaying (tariffs not in the listed price apply to 407 of 1,456 parts), or a missed lead time that delays a job. Public site visitors could be misled by a stale price, so every page shows the last sync time and says to confirm on Mouser. The data is about parts, not people; no employer, customer or patient data goes in. The AI must never place an order, send a quote request or email, or write to the data tables; it reads through the read only `app_reader` role and drafts a recommendation I approve.

## Scorecard self assessment (version 1)
| Factor | Rating | Why |
|---|---|---|
| Real user and workflow | Yellow | It's just me using it so far, but I don't believe the data is as complete as I need it to be to become a green. |
| Data access | Green | A thousand calls a day is just fine for me personally, and with it storing in my personal database, I don't really need to change a lot. If I ever did take it to the office, which I'm planning on doing, I'll have to get the office to pay for a commercial license. |
| Data understanding | Red | Because none of the racks said 19, I had to go back and do additional research as to why. That caused additional manual labor, but also confusion and distrust of the data. |
| Freshness and monitoring | Yellow | I have to manually run it, but at least it's human in the loop and I have to manually force it to run. |
| Grounding | Red | It's not built yet. |
| Bounded autonomy | Green | It's read only, and therefore people can't screw it up. |
| Evaluation | Green | I have the golden questions. |
| Measured value and cost | Yellow | I just need to put some statistics or quantification to that. |
| Adoption | Yellow | I don't know if I can get a license. |
| Governance and accountability | Green | No patient data goes into it, and right now it's under my control, so no one else can screw it up. |

**Two weakest factors and plans**
- **Data understanding:** I want to either find additional sources of data or a way to interpret the description that's there to get the data. For example, it's 750 millimeters wide, therefore it can't be a 23 inch rack, therefore it is a 19 inch rack. And put it in a way that can give better confidence in the data.
- **Grounding:** Build it in Milestone 5 and test it against my golden questions and my own experience.

*AI use: parts of this brief were drafted with Claude (Anthropic) from my baseline log and repo and checked against provider pricing pages. Scorecard ratings, reasons, plans, targets and the conclusion are mine.*

**Sources (checked 2026-11-13):** [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [Anthropic spend limits](https://platform.claude.com/docs/en/api/rate-limits) · [Supabase pricing](https://supabase.com/pricing) · [Render free tier](https://render.com/docs/free) · [Mouser Search API](https://www.mouser.com/api-search/)
