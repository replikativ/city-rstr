# German model parameters from published estimates (probe report 2026-09-12)

The premise: the restricted microdata can be routed around by
using what the literature has already estimated from it. This note is the
result. Every number below is free to obtain and carries a citation.

**The restriction costs less than feared, and in one case nothing at all.** The
household expenditure survey has never had a public use file for any wave since
1962, but its own research data centre states that it *"keine (validen)
Ergebnisse für Regionen unterhalb der Länderebene bereitstellen kann"* — it is
quota-sampled only at state level. So the file we cannot have could not have
told us anything about Stuttgart specifically. The Mikrozensus is different: it
has **free campus files (1998, 2002, 2010) and public use files** that need no
application.

## Destination choice: the kernel we are guessing at has been fitted

Wieland (2017), *The R Journal* 9(1):298–323, gold open access, with data and
code shipped in the GPL-licensed `MCI` package. Fitted on a point-of-sale survey
in **Karlsruhe**, a Baden-Württemberg city with the same grocery chains as
Stuttgart.

| model | size exponent | decay exponent | R² |
|---|---|---|---|
| shares of shopping **trips** | 0.9413 | −1.2443 | 0.460 |
| shares of **expenditure** | 2.0409 | −2.3788 | 0.495 |

n = 122 origin-destination pairs, all coefficients p < 1e-6.

**Read the units before transferring anything.** The size variable is
**Verkaufsfläche in m²** — measured sales area, which is what the retail census
gives us per district and what building footprints would give per venue. The
decay variable is **travel time in minutes by car, network-routed**, not
distance. Our kernel decays on distance with an offset, `(1 + d/d₀)^−β`, so the
exponents are not interchangeable without converting through a speed, and a
pure power law on time needs a floor that our offset currently provides.

**The two rows differ for a reason that matters to us specifically.** Major
shopping trips carry money and tolerate distance; fill-in trips are frequent and
local. Since the economic layer allocates money rather than visits, the
expenditure row is the relevant one, and it has both a steeper decay and a
**superlinear** size effect — a shop twice the size draws four times the
spending, not twice.

**Our values at the time were the ones the paper warns against.** We used size
1.0 and decay −2.0.  (Since 2026-09-15 the size and decay exponents are inferred
per demand class; see `doc/model.md` §9.) The paper fits classical Huff with exactly those textbook defaults
and reports a poor result, pseudo-R² 0.51 with a mean absolute percentage error
of 0.64; one round of fitting the attraction term took it to 0.93 and 0.16.

Chain identity matters beyond size: with store dummies the fit improves to
R² 0.598, with one discount chain at +1.33 and another at −0.59, both
significant, while four other chains are not.

### A catchment distribution we can validate against

The same survey measured where customers of two centres come from, by
travel-time band:

| band | town centre, customers | town centre, expenditure | out-of-town centre, customers | out-of-town, expenditure |
|---|---|---|---|---|
| 0–10 min | **72.5 %** | **76.4 %** | 40.3 % | 34.4 % |
| 10–20 min | 16.1 % | 14.5 % | 43.1 % | 48.0 % |
| 20–30 min | 6.7 % | 7.6 % | 8.3 % | 5.7 % |
| over 30 min | 4.7 % | 1.6 % | 8.3 % | 12.0 % |

A town centre draws three quarters of its trade from within ten minutes. An
out-of-town centre draws two thirds from beyond it. That is a shape our model
can be scored against directly, and it is a warning: a centre is not simply
"attractive at long range", it is attractive at *medium* range.

### A scale check on our centrality target

The chamber of commerce publishes a city-level retail centrality for Stuttgart
of **110.1** on a base of 100, against purchasing power of 8,504 € per head
(index 108.2 with Germany at 100). That is a ratio of 1.101 for the city as a
whole, which is consistent with our district figure of **10.54 for Mitte alone**
on the same ratio definition: the city barely retains its own spending while its
centre draws ten times its residents'. The two are not in conflict, but the
scales differ by a factor of 100 and must not be mixed.

## Consumption: elasticities estimated on the restricted file, published freely

Pothen & Tovar Reaños, ZEW Discussion Paper 18-022 (free) and *Ecological
Economics* 153 (2018). An EASI demand system on the expenditure survey
1993–2013, **n = 122,500 households**, ten purposes with an explicit mapping to
three-digit consumption classes. Adopted by the German Council of Economic
Experts.

Expenditure elasticities, by quartile of total spending:

| purpose | Q1 | Q4 | mean budget share |
|---|---|---|---|
| food | 0.543 | 0.756 | 0.15 |
| housing | 0.481 | 0.555 | 0.25 |
| transport | 1.455 | 1.775 | 0.11 |
| leisure | 1.764 | 1.136 | 0.16 |
| clothing | 1.164 | 0.987 | 0.05 |
| appliances | 1.731 | 1.395 | 0.05 |

Own-price elasticities are in the same paper and carry a counterintuitive
result worth keeping: they **rise** with affluence for every purpose except
transport and communication. Poorer households substitute less, not more.

Free official tabulations reach further than expected. The 2023 expenditure
survey publishes consumption at three-digit depth, about eighty rows, broken
down by household size, social position, income class, household type, number
of children, and **by federal state**. Budget shares by decile are published
separately. Baden-Württemberg's shares are within two percent of national on
every category while its level runs five percent higher.

**There is no city-size cut on consumption at any level**, federal or state,
and the microdata would not supply one. The urban adjustment therefore has to
come from elsewhere: the city-states as a proxy, where public transport spending
runs at twice the national share and motor fuel at 58 percent of it, or the
European survey's degree-of-urbanisation table.

## Prices: almost all German regional variation is housing

A 2023 index over 400 districts, built from about 690 web-scraped goods covering
more than 85 percent of the official basket, puts **Stuttgart at 114.8 overall,
fourth in Germany**. Split: **104.2 excluding housing, which is first in
Germany**, and 140.6 for housing.

The national range excluding housing is 98.3 to 104.2. The range for housing is
68.0 to 180.9. So a city model can treat non-housing prices as nearly uniform
and must treat housing as the entire story.

## Household dynamics: a GPL model with the rates already in it

SILO (github.com/msmobility/silo, GPL-2.0, actively maintained) hard-codes
German demographic rates: fertility by age **and parity**, a full single-year
life table by sex, marriage and divorce probabilities by five-year band and sex,
and leaving-home probabilities. Its housing market carries a moving probability
as a logistic in the gap between satisfaction and current dwelling utility, and
Cobb-Douglas dwelling utilities by household size and income class. Its
synthetic-population module already carries `"08"` for Baden-Württemberg, and
its one restricted input has a free campus file.

Measured German rates to check any of it against: 284 divorces per 1,000
marriages, mean marriage duration at divorce 14 years 7 months, mean age leaving
home 24.1, total fertility 1.32.

**Stuttgart's own mobility is unusually well measured**, and much higher than
the national statistic suggests because the national one counts only moves
across municipal boundaries. Including moves within the city, **14.8 percent of
residents change address in a year**: 80.2 in-moves per thousand from outside,
82.0 out, and 67.5 between districts. Mitte turns over hardest at 133.3 in-moves
per thousand with only 30.8 percent of adults resident more than fifteen years,
against 52.9 percent in Weilimdorf.

## Equivalence scales: pick one and say which

Nine published methods on the same pooled expenditure data give a second adult
anywhere between 1.16 and 2.34 relative to a single adult. Only three of the
nine are stable to the outlier rule. The policy scale used in German social
assistance is flatter than all of them because housing is reimbursed separately.
There is no "the German equivalence scale"; the modified OECD scale at
1.5 / 1.8 / 2.1 is a convention, and the choice must be stated as a parameter
with a prior rather than assumed.

## What this changes

1. The destination kernel has a fitted alternative from the same state, on the
   right size variable, with a warning that our exact current values fit badly.
2. The size variable in that fit is measured sales area, which the retail census
   supplies per district and footprints would supply per venue. Three independent
   lines now point at the same quantity.
3. Consumption elasticities for the basket layer exist at usable quality without
   any application.
4. Housing is the only price dimension that varies regionally, which simplifies
   the economic layer considerably.
