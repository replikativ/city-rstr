# Simulations as marginals of reality (design, 2026-09-12)

The framing: reality is a joint distribution
over everything a city is, and any simulation is a **projection of it onto the
observables we can actually check**. So build several projections, each honest
about its own question, and only afterwards ask which of them are worth coupling
into one. The unified model does not have to integrate all of them.

This note says what that means for code that currently has exactly one pipeline.

## We already have marginals; they are just implicit

Every certified pass in `doc/simulator.md` is a marginal wearing a different
name. Each asks one question and is scored against one family of measurements.

| marginal | question | scored against | needs routing? |
|---|---|---|---|
| **mobility** | who moves where, when, by what mode | pedestrian and bicycle counts, trip rate, mode split | yes |
| **retail draw** | where spending is attracted | retail centrality, floor area | **no** |
| **firm demography** | entry, exit, size distribution | survival curve, size tail, birth and death rates | no |
| **labour** | who works where | commuting flows, jobs by district | no |
| household economy *(next)* | income, spending | median income by small area, retail sales by category | no |
| production network *(later)* | inter-firm flows | input-output totals, regional value added | no |

Only one of six needs a routed day. That is not a detail — it is the whole
argument, and we measured it today: the retail marginal scored from the gravity
table in **seconds** and predicted the published run to three decimals, where
the routed day cost **fifty-three minutes** and, at the one pedestrian sensor,
delivered nineteen legs of signal.

Running everything through one pipeline means every question pays the price of
the most expensive one.

## What separating them buys, and what it costs

**Buys.** Each marginal takes the fidelity its question needs and no more. A
change can be attributed, because a marginal that a change does not touch does
not move. And a marginal whose inputs are broken can be quarantined rather than
silently poisoning the rest — which is what happened when a synthesized headcount
sent the retail model's shoppers to a knitting shop while the mobility model
carried on fine.

**Costs.** Duplication of state, and the risk that two marginals quietly
disagree. That second risk is the real one and it is also the interesting part,
because it is checkable.

## What makes them a family rather than unrelated models

**Shared quantities.** Population by district appears in all of them. Employment
by district appears in the labour and production marginals. Money appears in the
household and firm marginals. Wherever two marginals name the same quantity they
must agree, and the disagreement is a number.

We already have one accidental instance of this and it was valuable: the retail
census implies a population per district, and it agreed with our synthesized
population to within 4.7 %. Nobody designed that check; it fell out of two
marginals touching the same quantity.

So the discipline is: **declare each marginal's shared quantities, and make
their agreement a scored target like any other.** An inconsistency between two
marginals is as much a finding as a miss against a published statistic.

**Money is the strictest shared quantity, and `kontor` enforces it.** A
double-entry kernel refuses a write whose legs do not sum to zero. That converts
"the household marginal and the firm marginal should agree about spending" from
a hope into something the database will not let us violate.

## The shape in code

Less than it sounds, because the pieces exist.

A marginal is three things: a **state** it constructs from the shared data
plane, a **step**, and a **scorer**. Today:

- `city.synth.*` and the store are the shared data plane. Unchanged.
- `day/prepare` already builds separable state — the gravity tables are the
  retail marginal's entire state, and `validate/retail-centrality` is already its
  scorer, needing no traced day.
- `city.sim.run` is the coupled pipeline, and it should become *one* marginal
  (the mobility one) rather than the only entry point.

The work is naming them, giving each an explicit constructor and scorer, and
making the expensive parts optional rather than implied. The retail marginal is
already separable in practice; making it explicit costs almost nothing and hands
us a calibration loop a thousand times faster than the one we have been using.

**This also maps exactly onto `dvergr`.** A marginal is an EnvironmentDef plus a
trusted Evaluator; a set of them is a DatasetDef; running a candidate model
across all of them is an Experiment; and the Scorecard shows where a change
helped one marginal and hurt another. That is precisely the information we
lacked this week, when the in-commuter fix moved the bicycle target up and a
pedestrian target down and it took a separate investigation to learn why.

## What "unified" should and should not mean

Not "run everything at once". The joint model is only worth building where the
coupling is load-bearing:

- **Retail draw and household economy are worth coupling**, because revenue is
  customers times basket and neither is meaningful alone.
- **Mobility and retail draw are worth coupling loosely**, because destination
  choice sets the customers, but the routed day adds nothing the retail marginal
  is scored on.
- **Firm demography and the production network want coupling**, since entry and
  exit should follow profit, which follows inter-firm flows.
- **Mobility and firm demography barely interact at all** and are best left as
  separate projections with an agreement check on employment by district.

The unified model is then the subset where coupling changes an answer, and every
uncoupled pair carries a documented agreement check instead. That is a weaker
claim than "one model of everything" and a far more defensible one.

## Branches are how marginals and scenarios are actually managed

The stack already has the mechanism, and it is not a design document. Datahike
0.8 exposes `branch!`, `branch-as-db`, `branches`, `merge-db!`, `delete-branch!`
alongside `history`, `as-of` and `since`. Verified on this project's own store,
1,465,576 entities:

```clojure
(d/branch! conn :db :scenario-test)                ;; fork the whole city
(d/transact sconn [[:db/retractEntity restaurant]]) ;; change it in the branch
;; places in Weilimdorf: branch 429, main still 430
(d/delete-branch! conn :scenario-test)
```

The fork is of the *database*, not of a copy of the data, and the main branch is
untouched while the scenario diverges. That is the whole scenario model, working
today on real data.

Three things follow, and together they are the story the wider stack has been
trying to tell.

**A scenario is a branch.** Pedestrianise a street, close a plant, add a tram
line, change a tax rate: fork, change, run, compare. The console already serves
several runs side by side by key; the branches give those runs a shared ancestor
and a diff, which is what turns "two runs" into "a counterfactual".

**A marginal is a branch too.** Each projection shares the base facts and
diverges only in what it adds. The retail marginal's venue sizes and the labour
marginal's workplace assignments do not need to live in the same database state,
and the common ancestor is exactly the shared data plane this note is built on.

**History makes provenance queryable rather than merely recorded.** Every entity
already carries the receipt it came from (`:entity/acq`) and the store keeps
history, so "what did the model believe before that source was reloaded" and
"which acquisition changed this claim" are queries, not archaeology. We record
provenance carefully and have never once *asked* it a question. That is a gap
worth closing, because it is the difference between an audit trail and an audit.

### How the stack composes here

- **datahike** gives branching and history over the world state.
- **yggdrasil** branches the data and the code together, so a scenario carries
  the model version that produced it.
- **raster** is what makes running many branches affordable, which is the point
  at which "several marginals, many scenarios" stops being a slogan.
