# The economic layer (design, 2026-09-11)

The simulator moves people and opens and closes firms, but no money changes
hands anywhere in it. Firms live and die by an age hazard; a storefront's
simulated demand does not predict its closure (β ≈ 0, third pass). This file is
the design for closing that loop, from a person's wage to a firm's revenue to a
landlord's rent to the municipal budget.

It is written to be built in the same way as everything else here: each stock
and flow named, each parameter carrying its source, and each layer scored
against something published before the next one is added.

## Why it comes after trip generation, not before

Retail revenue is customers times basket. The customer count is the visit layer,
which is trips. Until the trip rate is right, every revenue number inherits a
factor-of-1.5 error that no price or basket calibration can absorb, and fitting
baskets against it would push that error into the prices. Trips first, then
money.

## The four agents and the flows between them

```
          wages                    rent
persons ─────────▶ firms ─────────────────▶ landlords
   │  ▲              │  ▲                        │
   │  │ spending     │  │ sales tax              │ property tax
   │  └──────────────┘  └────────────┐           │
   │     (visits × basket)           ▼           ▼
   └───── income tax, transfers ───▶ city ◀──────┘
                                     │
                                     └── services, which are firms too
```

Nothing here is a representative agent. Persons are the synthesized population,
firms are the resolved business register, landlords own actual parcels, and the
city is one accounting entity.

## What each layer needs, and what we already hold

### Persons: income and expenditure

**Have.** 670,883 synthesized Vancouver residents and 610,444 Stuttgart
residents, each carrying labour force status, occupation (NOC), industry
(NAICS), age, sex, household id, dwelling type and tenure (owner/renter).
Tenure is the hinge: a renter pays rent to a landlord, an owner pays a mortgage
and a property tax.

**Need.** A wage per worker and a transfer income per non-worker.

- Vancouver: the Census Profile already cached carries income per dissemination
  area, and the exact characteristic ids are (checked in the BC profile CSV,
  which holds 2,631 characteristics per area):

  | what | cid |
  |---|---|
  | median / average total income, persons 15+ | 113 / 128 |
  | median / average employment income | 119 / 134 |
  | employment income, full-year full-time, median / average | 143 / 144 |
  | employment income, part-year or part-time, median / average | 146 / 147 |
  | personal total-income distribution, 11 brackets | 158–170 |
  | composition of income: market, employment, transfers | 149, 150, 153 |
  | **median household income** | **243** |
  | average household income; one-person and larger households | 252, 246–250, 255–259 |
  | household income distribution | 260+ |

  Of these only 243–252 are in `census/curated-cids` today, so median household
  income — the *held-out target* for step 1 — is already in the marginals, and
  the distributions that would drive the synthesis are a one-line extension of
  the curated set followed by a re-run of `scripts/da_marginals.py` (not in the published repository). No new
  acquisition, and nothing to download.
- Stuttgart: no microdata. The Bundesagentur publishes median gross earnings
  of full-time employees by Kreis and by sector, which gives a sector-level
  wage; the dispersion has to be borrowed and documented, as the diaries were.

**Expenditure.** A household budget share by category, from the household
expenditure surveys: Statistics Canada's Survey of Household Spending for
Vancouver, and the Einkommens- und Verbrauchsstichprobe for Germany. Both
publish aggregate tables free. The categories must be the same ones the firm
layer classifies storefronts into, which is the join that makes visits into
revenue.

### Firms: revenue, wages, rent, profit

**Revenue** is where the existing machinery pays off. `daily2` already produces
each firm's visit count by hour from a customer's actual trip. Revenue is then

    revenue_j = Σ_visits basket(category, customer income)

so a shop's takings depend on who walks in, which depends on where people live
and how they travel. That is the first genuinely spatial economic quantity the
model would have, and it is the one the whole mobility layer was built to
support.

**Costs.** Wages from the employment column times the wage model. Rent from the
landlord layer below. Both are observable in aggregate: retail sales by
category and by month are published by Statistics Canada and by Destatis, and
that is the calibration target for the whole revenue side.

**Exit.** Replace the age hazard with a profit-driven one, keeping age as the
fallback where profit is unidentified. This is the test the third pass failed
with demand alone: demand is not revenue, because it carries no basket and no
costs. If profit does not predict exit either, that is a finding worth having.

### Landlords: the layer we are best equipped for and have not touched

**Have, already loaded and unused.** 94,960 Vancouver parcels with
`:parcel/land-value`, `:parcel/improvement-value`, the previous year's values,
`:parcel/tax-levy`, `:parcel/year-built`, `:parcel/zoning-district` and
`:parcel/zoning-class`, plus 222,000 strata lots keyed to their parcels. This
is an assessed value and an actual tax paid, per property, for the whole city.

**Need.** A rent. Two free sources:

- CMHC's Rental Market Survey publishes average rent by bedroom count for
  Vancouver survey zones, annually and free. That grounds residential rent.
- Commercial rent is not published per property anywhere open. The honest
  route is a yield assumption on assessed value, stated as a model parameter
  with a prior, and checked against whatever broker market reports can be
  cited.

**Behaviour.** A landlord sets rent, a household or firm pays or moves, and
vacancy is the feedback. The vacancy rate by zone is published by CMHC, so the
loop has a target. This is where displacement and gentrification become
emergent rather than assumed, which is the question a city government would
actually ask the model.

### The city: a budget that must balance

**Have.** The actual tax levy per parcel, which is the revenue side almost in
full. Business licence fees are in the licence records.

**Need.** The expenditure side, which Vancouver publishes as an annual budget by
service area. The city is the one agent whose accounts can be checked against a
published statement line by line, which makes it the best validation target in
the whole economic layer even though it is the least interesting behaviourally.

## Build order, each step scored before the next

1. **Income.** Add the income characteristics to the curated census marginals;
   give every worker a wage and every non-worker a transfer. Score: median
   household income by dissemination area against the census, held out.
2. **Expenditure and revenue.** Budget shares by category; revenue as visits
   times basket. Score: total retail sales by category against the published
   retail trade series. This is the first real test, and it tests the mobility
   layer as much as the economic one.
3. **Rent and the landlord.** Residential rent from the rental market survey,
   commercial rent as a yield on assessed value. Score: rent by zone, and the
   vacancy rate.
4. **Profit-driven firm exit.** Replace the age hazard. Score: the survival
   curve that the age hazard currently reproduces by construction, which it
   would now have to earn.
5. **The municipal budget.** Score: the published statement.

Only after (4) does the model have a loop rather than a chain: a firm's
survival depends on revenue, revenue on customers, customers on where people
live, where people live on rent, and rent on what firms and households can pay.
That loop is the thing worth showing, and it is also the thing that can
oscillate, so it needs the scaling-law checks on smaller worlds before it is
run at city scale.

## What this is not

It is not a general equilibrium model and should not be described as one. There
are no market-clearing prices, and wages are exogenous. What it is instead is
an accounting-consistent agent model: every euro or dollar leaves one agent's
balance and arrives on another's, and the aggregates are checked against
published statistics at every layer. That is a weaker claim and a checkable one.
