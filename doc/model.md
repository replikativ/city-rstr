# The probabilistic model

What the simulation is, as a joint distribution.  Every definition names the Clojure namespace that computes it (`city.sim.candidates`, for example); the source is in this repository, and `doc/architecture.md` maps each section below to its namespace.  Written 2026-09-15 against the Stuttgart world and kept current with the explorer.

## What is measured, what is drawn, what is inferred

The model has three kinds of quantity.  Measured inputs come from published
statistics, surveys and registers and are never fitted.  The world of people,
diaries and firms is drawn from those inputs once and then held fixed.  Nine
kernel numbers, three per demand class, are the only quantities inferred, and
they are inferred from the 69 published turnovers by district and class.  A
policy scenario changes the venue set and nothing else.

<figure>
<svg viewBox="0 0 640 372" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Pipeline of the model from published data through the simulated day and money to the likelihood, the posterior and the scenarios">
  <defs><marker id="pa" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M 0,0 L 8,3 L 0,6 Z" fill="var(--graphite)" opacity="0.8"/></marker>
  <marker id="pa-g" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M 0,0 L 8,3 L 0,6 Z" fill="var(--branch-green)"/></marker>
  <marker id="pa-b" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M 0,0 L 8,3 L 0,6 Z" fill="var(--memory-blue)"/></marker></defs>
  <g font-family="'IBM Plex Mono', monospace" font-size="10">
    <!-- measured sources -->
    <rect x="20" y="16" width="180" height="44" fill="var(--runtime-amber)" fill-opacity="0.12" stroke="var(--runtime-amber)"/>
    <text x="30" y="34" fill="var(--runtime-amber)">published marginals</text><text x="30" y="48" font-size="8" fill="var(--graphite)">Zensus 2022 · IFH · EZK 2024 · BA</text>
    <rect x="230" y="16" width="180" height="44" fill="var(--runtime-amber)" fill-opacity="0.12" stroke="var(--runtime-amber)"/>
    <text x="240" y="34" fill="var(--runtime-amber)">survey microdata</text><text x="240" y="48" font-size="8" fill="var(--graphite)">StatCan TUS 2022 · MiD</text>
    <rect x="440" y="16" width="180" height="44" fill="var(--runtime-amber)" fill-opacity="0.12" stroke="var(--runtime-amber)"/>
    <text x="450" y="34" fill="var(--runtime-amber)">buildings, firms, GTFS</text><text x="450" y="48" font-size="8" fill="var(--graphite)">OSM · Overture · registers</text>
    <!-- world, drawn once -->
    <rect x="20" y="90" width="180" height="44" fill="none" stroke="var(--rail)"/>
    <text x="30" y="108" fill="var(--ink)">persons i · 936,597</text><text x="30" y="122" font-size="8" fill="var(--graphite)">home cell, work, type, money</text>
    <rect x="230" y="90" width="180" height="44" fill="none" stroke="var(--rail)"/>
    <text x="240" y="108" fill="var(--ink)">diaries D · by type</text><text x="240" y="122" font-size="8" fill="var(--graphite)">when, and what kind of place</text>
    <rect x="440" y="90" width="180" height="44" fill="none" stroke="var(--rail)"/>
    <text x="450" y="108" fill="var(--ink)">firms j · 24,849 · A_j</text><text x="450" y="122" font-size="8" fill="var(--graphite)">3,637 retail, floor per class s</text>
    <path d="M 110,60 L 110,88" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 320,60 L 320,88" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 530,60 L 530,88" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <!-- the day -->
    <rect x="150" y="170" width="280" height="50" fill="none" stroke="var(--ink)"/>
    <text x="162" y="188" fill="var(--ink)">the day · anchor → choice</text>
    <text x="162" y="201" font-size="8" fill="var(--graphite)">P(j | c; θ_s) over every venue, u(s,i,k) addressed</text>
    <text x="162" y="212" font-size="8" fill="var(--graphite)">visits[j,h], legs, spend per visit</text>
    <path d="M 110,134 L 200,168" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 320,134 L 300,168" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 530,134 L 390,168" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <!-- theta -->
    <rect x="440" y="176" width="180" height="60" fill="none" stroke="var(--memory-blue)"/>
    <text x="450" y="194" fill="var(--memory-blue)">θ = (α_s, β_s, d₀,s)</text>
    <text x="450" y="208" font-size="8" fill="var(--graphite)">nine numbers, three per class</text>
    <text x="450" y="222" font-size="8" fill="var(--graphite)">prior → posterior, spindel MH / SMC</text>
    <path d="M 440,200 L 432,197" fill="none" stroke="var(--memory-blue)" marker-end="url(#pa-b)"/>
    <!-- expectation -->
    <rect x="150" y="252" width="280" height="44" fill="none" stroke="var(--rail)"/>
    <text x="162" y="270" fill="var(--ink)">T_{d,s}(θ) = Σ_c E_{c,s} Σ_{j∈d} P(j|c;θ_s)</text>
    <text x="162" y="284" font-size="8" fill="var(--graphite)">expected turnover per district and class, exact</text>
    <path d="M 290,220 L 290,250" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <!-- likelihood -->
    <rect x="20" y="252" width="120" height="44" fill="var(--runtime-amber)" fill-opacity="0.12" stroke="var(--runtime-amber)"/>
    <text x="30" y="270" fill="var(--runtime-amber)">Y_{d,s} observed</text><text x="30" y="284" font-size="8" fill="var(--graphite)">69 = 23 districts × 3</text>
    <rect x="150" y="322" width="280" height="34" fill="none" stroke="var(--rail)"/>
    <text x="162" y="343" fill="var(--ink)">log T_{d,s}(θ) ~ N(log Y_{d,s}, σ²)</text>
    <path d="M 290,296 L 290,320" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 80,296 L 80,339 L 148,339" fill="none" stroke="var(--graphite)" marker-end="url(#pa)"/>
    <path d="M 430,339 L 530,339 L 530,238" fill="none" stroke="var(--memory-blue)" marker-end="url(#pa-b)"/>
    <text x="538" y="300" font-size="8" fill="var(--memory-blue)">the likelihood</text><text x="538" y="311" font-size="8" fill="var(--memory-blue)">updates θ</text>
    <!-- scenario -->
    <rect x="20" y="170" width="120" height="50" fill="none" stroke="var(--branch-green)"/>
    <text x="30" y="188" fill="var(--branch-green)">do(R := R′)</text>
    <text x="30" y="201" font-size="8" fill="var(--graphite)">close or open venues,</text>
    <text x="30" y="212" font-size="8" fill="var(--graphite)">Δ under every particle</text>
    <path d="M 140,195 L 148,195" fill="none" stroke="var(--branch-green)" marker-end="url(#pa-g)"/>
  </g>
</svg>
<figcaption>Measured inputs (amber) are drawn once into a fixed world of people, diaries and firms.  The day places every person by the diary and the choice kernel.  Its expectation per district and class is what the likelihood compares with the 69 published turnovers, and that comparison updates the nine kernel numbers θ (blue).  A scenario (green) changes only the venue set and re-runs the day and its expectation under every posterior particle.</figcaption>
</figure>

## Index sets

| symbol | meaning | size (Stuttgart) |
|---|---|---|
| `i` | person | 936,597 = 610,444 residents + 326,153 in-commuters |
| `j` | firm | 24,849, of which 3,637 carry the retail flag |
| `c` | grid cell, 100 m | 34,650 = 175 × 198 |
| `d` | Stadtbezirk | 23 |
| `h` | hour of day | 24 |
| `k` | episode within a diary | 0 … K_D |

## 1. The world is drawn once

Germany publishes no microdata seed at city level, so persons are generated
from marginals directly (`city.synth.stuttgart`).
Per Zensus 2022 grid cell `c` the published population `N_c` is taken as given,
and each resident's attributes are drawn from that cell's marginals:

$$
(\mathrm{age}_i,\mathrm{sex}_i)\sim P(\mathrm{age},\mathrm{sex}\mid \text{cell marginals},\ \text{Kreis sex ratio}),\qquad
\mathrm{labour}_i\sim P(\text{employed}\mid \mathrm{age}_i)\ \ (\text{Zensus Gemeindetabelle}),\qquad
\mathrm{home}(i)=c\ \ (\text{exact, not sampled})
$$

This draw is **not** re-run per posterior sample. It is the world, fixed, and
its uncertainty is not currently propagated. That is a known gap, and the honest
way to close it is a second inference loop over synthesis seeds.

## 2. Workplaces, which are also the commute model

Each employed resident with home cell `c` draws a firm
(`city.sim.cityworld`):

$$
P(\mathrm{work}(i)=j)\;\propto\;\mathrm{cap}_j\,e^{-d(c,j)/\lambda_w},\qquad
\lambda_w = 6{,}000\ \mathrm{m},\ \text{top }48;\qquad
\mathrm{cap}_j=\max\bigl(\mathrm{employees}_j,\ 3\ \text{if storefront}\bigr)
$$

computed on a 300 m grid and sampled without replacement against `cap_j`.  A
full firm is retried four times; after that the worker draws a firm in
proportion to its remaining capacity.  The 326,153 in-commuters have no home,
so they draw in proportion to remaining capacity alone and are then placed at
the city edge on the corridor they arrive by.  Out-commuters are placed
symmetrically at their exit point.

## 3. Attractiveness is measured, not fitted

$$
A_j=\text{footprint share of firm } j \text{ from OSM buildings},\qquad
\sum_{j\in d,\ \mathrm{retail}} A_j=\text{Verkaufsfläche}_d\ \ (\text{EZK 2024 retail survey, raked per district})
$$

Shape from one source, level from another
(`city.synth.retail`).  About 89 % of firms match a building polygon; an
unmatched firm takes its district's median.  The floor areas come from the
Unternehmenserhebung 2021 published in the city's Einzelhandels- und
Zentrenkonzept 2024. This matters
for the prior on α: because `A` is raked to a measured level, α = 1 preserves
that level and α ≠ 1 destroys it.

## 4. Destination choice, the one kernel that carries parameters

For a person currently anchored in cell `c`, the probability of choosing retail
venue `j` (`city.sim.candidates`):

$$
w_{cj}(\theta)=A_j^{\alpha}\,\bigl(1+d_{cj}/d_0\bigr)^{-\beta},\qquad
P(j\mid c;\theta)=\frac{w_{cj}(\theta)}{\sum_{j'\in R} w_{cj'}(\theta)},\qquad R=\text{all 3,637 retail firms}
$$

This is Huff's gravity model of trade areas [1] in Fotheringham's competing-destinations
form [2], read as a random-utility choice [3] over the whole venue set. It is a
bounded-rationality model in Simon's sense [4]: a shopper does not optimise over
the city, they weigh size against distance with a decay the data must fix, and
the visitation law of human mobility finds that decay near \(\beta\approx 2\) [5].  The form
belongs to Wilson's family of spatial interaction models [12].

`d_cj` is the haversine distance from cell centre to firm, precomputed for all
34,650 × 3,637 pairs as float32, about 0.5 GB. The sum runs over **every**
candidate: the earlier top-K tables renormalised a minority of the kernel, since
the top 64 venues hold only 30 % of its mass, and K then became a behavioural
parameter by accident.

The other destination classes are not inferred; their kernels are fixed in
`city.sim.day/default-venue-kernels` (the run config, `city.sim.run`, can
override the store and restaurant entries), and each is a top-K table over its
own candidates:

| class | kernel | size term \(A_j\) | K | cap |
|---|---|---|---|---|
| restaurant | power, α = 1, β = 1.6, d₀ = 500 m | retail floor area of the venue | 64 | |
| school, clinic, outdoors, sports, culture, worship | exponential, λ = 400 m | none (OSM point) | 16 | |
| another resident's home | exponential, λ = 1,500 m | residents per cell | 64 | 1,500 m |
| street (a walk) | exponential, λ = 1,500 m | a fixed random weight per street node | 16 | 500 m |
| business | exponential, λ = 1,500 m | employees | 16 | |

These classes place legs and, for restaurants, visits; none of them carries
money or enters the likelihood.

## 5. The diary process

Each person has a type `t(i) = (activity, age band, sex)` with activity in
{worker, student, retired, home}.  The diaries are urban weekday diaries from
the Statistics Canada Time Use Survey 2022 public-use microdata, reweighted by
exponential tilting to Stuttgart's published trip rate of 2.861 trips per
person per day (MiD 2023) (`city.synth.timeuse`, `city.synth.tripgen`):

$$
P(D=D_m\mid t)\;\propto\;\omega_m\ \ (\text{survey weight}),\qquad
D=\bigl((\ell_1,\tau_1),\ldots,(\ell_K,\tau_K)\bigr),
$$
$$
\ell\in\{\text{home},\ \text{work-or-school},\ \text{store},\ \text{restaurant},\ \text{other-home},\ \text{neighbourhood},\ \text{outdoors},\ \text{culture},\ \text{sports},\ \text{worship},\ \text{clinic},\ \text{elsewhere},\ \text{business}\}
$$

The diary supplies *when* and *what kind of place*.  The kernel supplies *which
place*.  Nothing in the diary is German, only its trip rate is: daily rhythms
transferred from urban Canada are the largest single transfer assumption in the
model.  No German diary microdata is used; the Zeitverwendungserhebung is
available only through the research data centre.

## 6. The day

Randomness is counter-addressed, so a draw is a pure function of its address
rather than of execution order.  This is what makes paired scenario comparison
and a GPU port both possible:

$$
\kappa(s,i)=\mathrm{splitmix}\bigl(1000003\,s+i\bigr),\qquad
u(s,i,k)=\bigl\lfloor \mathrm{splitmix}\bigl(\kappa(s,i)+k\bigr)\,/\,2^{11}\bigr\rfloor\,/\,2^{53}
$$

The stream key \(\kappa\) is hashed per person, so indices added to it cannot line
up across seeds or persons, and draw indices are reserved by purpose (diary,
venue of episode \(k\), demand class, leakage, workplace) so one person's draws
never meet (`city.sim.day/uniform`).

Then for each person, with anchor `a` starting at the home cell
(`city.sim.day/step-day`):

$$
D_i=F_t^{-1}\bigl(u(s,i,0)\bigr)\qquad\text{the diary, by inverse cdf of the type's weights}
$$
$$
\text{episode } k,\ \text{place } \ell_k,\ \text{hour } h_k:\qquad
\begin{cases}
\ell_k=\text{home} & a\leftarrow\mathrm{home}(i)\\[2pt]
\ell_k=\text{work},\ i\ \text{employed} & \mathrm{visits}[\mathrm{work}(i),h_k]\mathrel{+}=1;\ \ a\leftarrow\mathrm{cell}(\mathrm{work}(i))\\[2pt]
\ell_k=\text{store} & j=F^{-1}_{\mathrm{retail}}\bigl(a,\,u(s,i,k{+}1)\bigr);\ \ \mathrm{visits}[j,h_k]\mathrel{+}=1\\[2pt]
\ell_k=\text{restaurant} & j=F^{-1}_{\mathrm{food}}\bigl(a,\,u(s,i,k{+}1)\bigr);\ \ \mathrm{visits}[j,h_k]\mathrel{+}=1\\[2pt]
\text{otherwise} & j=F^{-1}_{\ell_k}\bigl(a,\,u(s,i,k{+}1)\bigr);\ \ \text{a leg, no visit}
\end{cases}
$$

where \(F^{-1}_{\mathrm{class}}(a,u)\) is the inverse cdf of that class's kernel from
anchor \(a\) (§4), so one uniform draw picks one venue.

The anchor is the entire state: a destination is chosen relative to where the
person is now, which is home or work. Trips are then routed on the street graph
only when traces are requested, never inside the likelihood.

In the published run the traced weekday (the trips, people and visits on the
map) draws shops from one retail kernel at the run's defaults, α = 1, β = 1.6,
d₀ = 500 m, over all retail candidates.  The economic day of §12 draws them per
demand class at the posterior mean instead, so the two layers use different
store kernels.

## 7. Money

Purchasing power, shape assumed and level measured
(`city.econ.household`):

$$
w_i=\begin{cases}0.25&\text{age}<15\\0.45&15\le\text{age}<20\\1.30&\text{employed}\\0.85&\text{age}\ge 65\\0.70&\text{otherwise}\end{cases}\qquad
pp_i=w_i\,\frac{KK_d}{\sum_{i'\in d} w_{i'}}\ \ (\text{IFH Kaufkraft per district}),\qquad
pp_i=0\ \text{for in-commuters}
$$

Age is the census age group of the synthetic person, so the thresholds are
group boundaries.  The ratios are assumptions; only the district level is
measured.

Retail-relevant share, one measured scalar
(`city.econ.spending`):

$$
\sigma=\frac{\sum_d \text{EZK retail Kaufkraft}_d}{\sum_d \text{IFH Kaufkraft}_d}=\frac{4{,}650.9}{19{,}565.2}=0.2377,\qquad
m_i=\sigma\,pp_i\ \ [\text{€ / year}],\qquad
E_c=\sum_{i:\,\mathrm{home}(i)=c} m_i
$$

Citywide this gives 4,651 M € against the EZK's 4,650.9 M €, by construction.
One scalar stands for something that varies: the district ratios run 0.194 to
0.296 with a mean of 0.240, and they fall with income the way Engel's law says
they should. Making σ income-dependent would fit better and would also be
fitted against the very series it predicts, so the residual is left to carry
that signal as a finding.

## 8. What the likelihood actually sees

Predicted turnover is the **expected** allocation, integrated analytically over
the day rather than sampled from it:

$$
T_d(\theta)=\sum_c E_c\sum_{j:\ \mathrm{district}(j)=d} P(j\mid c;\theta)
$$

so the simulator in the inference loop is deterministic given θ, takes about
three seconds for the three classes on an eight-core machine, and contributes
no Monte Carlo noise to the likelihood.
Against the 2024 retail concept's published turnover `Y_d`
(`city.infer`):

$$
\log Y_d\;\sim\;\mathcal N\bigl(\log T_d(\theta),\ \sigma_{\mathrm{obs}}^2\bigr),\qquad d=1,\ldots,23
$$

σ_obs is recorded with each run (0.25 for the published posterior).  It is not
a taste parameter: the residual floor of the model on this data is RMS 0.24 in
log terms and does not move along the β ridge, so a smaller σ would score every
particle on noise the model cannot remove. Optionally a second
observe on the population's expected straight-line shopping distance:

$$
\mathbb E_\theta[d_{\mathrm{shop}}]\;\sim\;\mathcal N\bigl(3.6/1.25,\ 0.3^2\bigr)\quad[\mathrm{km}],\ \text{MiD 2017} \div \text{detour factor}
$$

The detour factor is an assumption of the caller and is recorded with the run.
Used as an observe it is fitted; left out it is a holdout. It cannot be both.

## 9. Priors and posterior

$$
\alpha\sim U(0,\,1.5),\qquad \beta\sim U(1,\,3.5),\qquad \log d_0\sim U(\log 200,\,\log 2000)\ [\mathrm{m}]
$$

(\(\alpha=0\) is no size term, \(\alpha=1\) classic Huff; the visitation law [5] puts
\(\beta\) near 2.) With the segment split of §12 there is one such triple per demand
class \(s\) and one observe per (district, class), 69 on Stuttgart, so the posterior is

$$
p(\theta\mid Y)\;\propto\;p(\theta)\prod_{d,s}\mathcal N\bigl(\log Y_{d,s};\ \log T_{d,s}(\theta_s),\ \sigma_{\mathrm{obs}}^2\bigr),\qquad
\theta=(\alpha_s,\beta_s,d_{0,s})_{s\in\{\text{short},\,\text{medium},\,\text{long}\}}.
$$

This is simulation-based inference in the sense of [8]: the likelihood is never
written down as a function of the data alone, it is the simulator's expected
allocation evaluated at each proposed \(\theta\). The particle methods are
Chopin's iterated batch importance sampling [9] with the resample-move
rejuvenation of Gilks and Berzuini [10], in the general SMC-sampler frame of
[11]; the MH alternative is plain random-walk Metropolis over the program's
trace.

Inference runs through spindel, one forked execution context per particle:

- **prior kernel**: importance sampling with a resampling barrier at each of
  the 23 observes. N evaluations, cheap, and degenerate: read `distinct-theta`,
  not ESS, because resampling duplicates survivors and never proposes new θ.
- **random-walk MH**: N independent chains, each perturbing one continuous
  site and re-executing, at N × (1 + iterations) evaluations. Chains are
  weighted uniformly; the diagnostic is the acceptance rate.

**The published posterior is approximate.**  The explorer's scenarios are drawn
under 48 independent random-walk Metropolis–Hastings chains of 30 single-site
moves each, started from prior draws, with σ_obs = 0.25 and seed 1
(`city.demo.stuttgart/fit-posterior`).  Thirty moves in nine dimensions are too
few to call the chains converged, and no between-chain diagnostic is recorded
beyond the acceptance rate; the particles are best read as a spread of
plausible kernels rather than as a calibrated posterior.  The model also
carries no class-level offset, so non-resident money (clothing turnover in the
centre that residents alone cannot account for) has to be absorbed by the
shape of the medium-class kernel.

## 10. Interventions

An intervention changes the candidate set and nothing else
(`city.sim.scenario`):

$$
\text{close } j:\ A_j\leftarrow 0\ (\text{never selectable}),\qquad
\text{open}:\ R\leftarrow R\cup\{\text{new}\}\ (\text{one more distance column})
$$
$$
\Delta(\theta)=\mathrm{outcome}(R';\theta)-\mathrm{outcome}(R;\theta),\qquad
\mathbb E[\Delta\mid Y]\approx\sum_p w^{(p)}\Delta(\theta^{(p)}),\quad
\text{band}=\bigl[Q_{0.05},\,Q_{0.95}\bigr]\text{ of }\{\Delta(\theta^{(p)})\}_p
$$

Setting the venue set is an intervention in Pearl's sense [6], \(\mathrm{do}(R:=R')\):
the arrows into \(R\) are cut, everything downstream is recomputed, and nothing
upstream (the population, its money, \(\theta\)) is touched. The graph below
is the model's causal structure; the three rungs [6, 7] are read off it.

<figure>
<svg viewBox="0 0 640 330" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Probabilistic graphical model of the city simulation with the venue set as an intervention node">
  <defs>
    <marker id="ah" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M 0,0 L 8,3 L 0,6 Z" fill="var(--graphite)" opacity="0.8"/></marker>
    <marker id="ah-g" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M 0,0 L 8,3 L 0,6 Z" fill="var(--branch-green)" opacity="0.9"/></marker>
  </defs>
  <g font-family="'IBM Plex Mono', monospace" font-size="10">
    <!-- plates -->
    <rect x="22" y="22" width="120" height="118" rx="4" stroke="var(--rail)" stroke-dasharray="4 3"/>
    <text x="30" y="132" fill="var(--graphite)" font-size="8">class s ∈ {short, medium, long}</text>
    <rect x="170" y="22" width="130" height="190" rx="4" stroke="var(--rail)" stroke-dasharray="4 3"/>
    <text x="178" y="204" fill="var(--graphite)" font-size="8">venue j ∈ R</text>
    <rect x="330" y="22" width="290" height="190" rx="4" stroke="var(--rail)" stroke-dasharray="4 3"/>
    <text x="338" y="204" fill="var(--graphite)" font-size="8">person i · episode k</text>
    <rect x="330" y="232" width="290" height="80" rx="4" stroke="var(--rail)" stroke-dasharray="4 3"/>
    <text x="338" y="304" fill="var(--graphite)" font-size="8">district d</text>
    <!-- latent: blue outline -->
    <circle cx="82" cy="70" r="28" stroke="var(--memory-blue)" stroke-width="1.5"/>
    <text x="82" y="67" text-anchor="middle" fill="var(--memory-blue)">θ_s</text>
    <text x="82" y="80" text-anchor="middle" fill="var(--memory-blue)" font-size="8">α, β, d₀</text>
    <!-- measured: amber filled -->
    <circle cx="235" cy="70" r="26" fill="var(--runtime-amber)" fill-opacity="0.18" stroke="var(--runtime-amber)" stroke-width="1.5"/>
    <text x="235" y="67" text-anchor="middle" fill="var(--runtime-amber)">A_j</text>
    <text x="235" y="80" text-anchor="middle" fill="var(--runtime-amber)" font-size="8">floor area</text>
    <!-- intervention: green -->
    <circle cx="235" cy="160" r="26" stroke="var(--branch-green)" stroke-width="1.8"/>
    <text x="235" y="157" text-anchor="middle" fill="var(--branch-green)">R</text>
    <text x="235" y="170" text-anchor="middle" fill="var(--branch-green)" font-size="8">do(R := R′)</text>
    <circle cx="390" cy="70" r="24" fill="var(--runtime-amber)" fill-opacity="0.18" stroke="var(--runtime-amber)" stroke-width="1.5"/>
    <text x="390" y="67" text-anchor="middle" fill="var(--runtime-amber)">c_i</text>
    <text x="390" y="80" text-anchor="middle" fill="var(--runtime-amber)" font-size="8">home cell</text>
    <circle cx="480" cy="70" r="24" stroke="var(--memory-blue)" stroke-width="1.5"/>
    <text x="480" y="67" text-anchor="middle" fill="var(--memory-blue)">D_i</text>
    <text x="480" y="80" text-anchor="middle" fill="var(--memory-blue)" font-size="8">diary</text>
    <circle cx="570" cy="70" r="24" stroke="var(--memory-blue)" stroke-width="1.5"/>
    <text x="570" y="67" text-anchor="middle" fill="var(--memory-blue)">m_i</text>
    <text x="570" y="80" text-anchor="middle" fill="var(--memory-blue)" font-size="8">money</text>
    <circle cx="450" cy="160" r="26" stroke="var(--memory-blue)" stroke-width="1.5"/>
    <text x="450" y="157" text-anchor="middle" fill="var(--memory-blue)">j_ik</text>
    <text x="450" y="170" text-anchor="middle" fill="var(--memory-blue)" font-size="8">venue chosen</text>
    <circle cx="560" cy="160" r="20" stroke="var(--graphite)" stroke-width="1.2" stroke-dasharray="3 2"/>
    <text x="560" y="164" text-anchor="middle" fill="var(--graphite)" font-size="9">u(s,i,k)</text>
    <circle cx="475" cy="270" r="26" fill="var(--runtime-amber)" fill-opacity="0.18" stroke="var(--runtime-amber)" stroke-width="1.5"/>
    <text x="475" y="267" text-anchor="middle" fill="var(--runtime-amber)">Y_{d,s}</text>
    <text x="475" y="280" text-anchor="middle" fill="var(--runtime-amber)" font-size="8">turnover</text>
    <!-- edges -->
    <path d="M 110,70 L 208,70" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 105,84 C 200,120 330,150 423,160" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 258,80 C 330,110 380,140 424,152" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 261,160 L 423,160" stroke="var(--branch-green)" stroke-width="1.6" marker-end="url(#ah-g)"/>
    <path d="M 400,93 L 437,136" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 473,94 L 457,134" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 414,70 L 455,70" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 405,55 C 460,20 530,25 561,47" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 539,160 L 477,160" stroke="var(--graphite)" stroke-width="1" stroke-dasharray="3 2" marker-end="url(#ah)"/>
    <path d="M 456,186 L 470,243" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <path d="M 565,94 C 560,180 520,220 500,250" stroke="var(--graphite)" stroke-width="1.2" marker-end="url(#ah)"/>
    <!-- legend -->
    <text x="30" y="240" fill="var(--memory-blue)" font-size="9">○ latent / drawn</text>
    <text x="30" y="256" fill="var(--runtime-amber)" font-size="9">● measured</text>
    <text x="30" y="272" fill="var(--branch-green)" font-size="9">○ intervention</text>
    <text x="30" y="288" fill="var(--graphite)" font-size="9">- - exogenous noise, counter-addressed</text>
  </g>
</svg>
<figcaption>The model as a graph. Measured nodes (amber) are read from the census, the registers and the retail concept; latent nodes (blue) are drawn by the simulator; θ_s is the only latent that is inferred. The venue set R is where policy acts: do(R := R′) cuts nothing upstream and recomputes every venue choice downstream. Because the choice noise u(s,i,k) is a pure function of its address, the same person's day can be replayed under R′ with the same draws: a paired simulation with common random numbers, in which people whose venue did not change can also move. Turnover Y_{d,s} is what the likelihood compares against; money m_i is fixed by the district's purchasing power, so a scenario moves euros, it never creates them.</figcaption>
</figure>

over the posterior branches (θ^(p), w^(p)).  The published scenarios report
turnover per venue and district and the expected straight-line shopping
distance per class (`city.sim.scenario`).  Because the outcome is an expectation
rather than a sampled day, baseline and scenario differ by exactly the
intervention, and the spread across branches is the model's uncertainty about
the kernel, not sampling noise.

With the segment split (§12) the same intervention acts on three attractiveness
vectors at once (`city.sim.scenario`): closing a
building removes its clothing floor from the medium class and its supermarket
from the short one, and the outcome is evaluated per class with that class's
money and kernel, then summed. The report gives, for every district and venue,
the weighted mean and the 5 / 50 / 95 % quantiles of Δ over the particles.

The three rungs the demo walks, in these terms:

| rung | in this model | what is computed |
|---|---|---|
| observe | \(p(\theta\mid Y)\), the particles | the posterior predictive of district turnover is the calibration |
| intervene | \(\mathrm{do}(R:=R')\) | `outcome3` under each particle: same money, same residents, \(\theta\) held, giving a band on \(\Delta\) |
| paired day | same seed, \(R'\) | the economic day re-run under \(R'\) at the posterior mean with the same draws for every person: a paired simulation with common random numbers |

The second rung is exact and noise-free.  The paired day is what the map's
visit-change layer shows.  It is not a minimal counterfactual: a venue is drawn
by walking the cumulative weights, so removing one venue shifts the intervals
of the venues after it, and a person whose venue did not close can also move.
A per-venue Gumbel-max draw would keep every unaffected choice fixed; that is
not implemented.

## 11. Measured, assumed, fitted

| quantity | status |
|---|---|
| cell populations, age and sex, employment rates | measured (Zensus 2022) |
| purchasing power per district | measured (IFH, via the city's statistical yearbook and the EZK 2024), raked |
| retail floor area per district and class | measured (Unternehmenserhebung 2021 in the EZK 2024), raked |
| turnover and retail potential per district and class | measured (EZK 2024), the observations |
| firm locations, categories and footprints | Overture Places and OSM buildings |
| purchasing-power ratios by age group and employment | **assumed**, declared in `city.econ.household` |
| retail share of purchasing power σ | measured as one scalar 0.2377, known to vary 0.194–0.296 |
| activity diaries | **transferred** from the Statistics Canada Time Use Survey 2022, reweighted to Stuttgart's trip rate |
| class shares of shopping trips π = (0.65, 0.20, 0.15) | **assumed**, a placeholder in `city.econ.day` |
| leakage and non-resident inflow per class | sizes measured (EZK class balances); attribution **assumed**: all inflow to in-commuters, all leakage to residents |
| share of person-days keeping the diary's travel modes, 0.5 | **assumed** |
| α, β, d₀ per class | **fitted**, the approximate posterior of §9 |
| commute λ_w, K, non-retail kernels | **assumed**, no prior, not inferred |

The rule the data plane exists to enforce is that a model parameter is
traceable to a measurement and a measurement to a receipt.  The assumed rows
of that table are where the rule is currently weakest.

## 12. Three demand classes

One destination kernel cannot reproduce Stuttgart: a kernel flat enough to
fill the centre with turnover makes shopping trips far longer than the mobility
survey reports.  The retail concept publishes the structure that resolves this,
three demand classes per district that reconcile to its own totals:

| class | turnover M € | resident potential M € | city centrality | Mitte centrality |
|---|---|---|---|---|
| short (food, convenience) | 2,168.7 | 2,443.1 | 0.89 | 4.49 |
| medium (clothing, shoes) | 1,331.7 | 732.5 | 1.82 | 36.72 |
| long (furniture, electronics) | 979.8 | 1,356.8 | 0.72 | 8.17 |

For each class \(s\):

$$
\mathrm{seg}(j)\in\{\text{short},\text{medium},\text{long}\}\ \ (\text{from the firm's category}),\qquad
A_{j,s}\ \text{raked within }(d,s)\text{ to the class's floor area}
$$
$$
\kappa_{d,s}=\frac{\text{EZK Kaufkraft}_{d,s}}{\sum_{s'}\text{EZK Kaufkraft}_{d,s'}},\qquad
E_{c,s}=\kappa_{d(c),s}\,E_c,\qquad
\theta_s=(\alpha_s,\beta_s,d_{0,s})
$$
$$
T_{d,s}(\theta)=\sum_c E_{c,s}\sum_{j\in d}P_s(j\mid c;\theta_s),\qquad
\log Y_{d,s}\sim\mathcal N\bigl(\log T_{d,s}(\theta),\ \sigma_{\mathrm{obs}}^2\bigr),\quad 23\times 3=69\ \text{observations}
$$

A venue selling across classes, a department store or Overture's generic
`shopping` category, has its floor split across the three
(`city.synth.segments`), and the class floor areas sum to 99.9 % of the district
totals, so the raking partitions cleanly.  `candidates/reduce-dense` evaluates a
class without materialising its choice table, and `city.infer/segmented-model`
is the nine-parameter program with one keyed observe per (district, class).

**Money on the day.**  In the economic day (`city.sim.kernel/spend-day!`) a store
episode first draws its class with probability \(\pi_s\), then its venue from
that class's kernel, and carries the person's spend per class visit:

$$
P(\text{class of a store episode}=s)=\pi_s,\qquad
\text{spend per visit}_{i,s}=\frac{m_{h(i)}\,\kappa_{d,s}}{365\,\sum_{i'\in h(i)} E[\text{class-}s\text{ visits of }i'\text{ per day}]}
$$

pooled over the household \(h(i)\), so that 365 days reproduce the class
potential in expectation.  The class balances of the retail concept size the
money that crosses the city boundary: medium-term goods draw 599 M € more than
residents can spend, while short-term goods leak 274 M € and long-term goods
377 M € out.  In the day, a resident's class-\(s\) purchase leaves the city with
the measured leakage share, and in-commuters carry the class's measured net
inflow, spent from wherever their day anchors them: their entry point on the
city boundary or their workplace.  How that money is attributed between residents, in-commuters and
visitors is assumed; visitors are not modelled.

## References

1. Huff, D. L. (1963). A probabilistic analysis of shopping center trade areas. *Land Economics* 39(1), 81–90.
2. Fotheringham, A. S. (1983). A new set of spatial-interaction models: the theory of competing destinations. *Environment and Planning A* 15(1), 15–36.
3. McFadden, D. (1974). Conditional logit analysis of qualitative choice behavior. In P. Zarembka (ed.), *Frontiers in Econometrics*, 105–142. Academic Press.
4. Simon, H. A. (1955). A behavioral model of rational choice. *Quarterly Journal of Economics* 69(1), 99–118.
5. Schläpfer, M., Dong, L., O'Keeffe, K., Santi, P., Szell, M., Salat, H., Anklesaria, S., Vazifeh, M., Ratti, C. & West, G. B. (2021). The universal visitation law of human mobility. *Nature* 593, 522–527.
6. Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*, 2nd ed. Cambridge University Press.
7. Pearl, J. & Mackenzie, D. (2018). *The Book of Why*. Basic Books. The ladder of association, intervention and counterfactual.
8. Cranmer, K., Brehmer, J. & Louppe, G. (2020). The frontier of simulation-based inference. *PNAS* 117(48), 30055–30062.
9. Chopin, N. (2002). A sequential particle filter method for static models. *Biometrika* 89(3), 539–552.
10. Gilks, W. R. & Berzuini, C. (2001). Following a moving target — Monte Carlo inference for dynamic Bayesian models. *Journal of the Royal Statistical Society B* 63(1), 127–146.
11. Del Moral, P., Doucet, A. & Jasra, A. (2006). Sequential Monte Carlo samplers. *Journal of the Royal Statistical Society B* 68(3), 411–436.
12. Wilson, A. G. (1971). A family of spatial interaction models, and associated developments. *Environment and Planning* 3(1), 1–32.

Data (none of it ships with the code; see `DATA.md` for access, licences and attribution):

- Statistisches Bundesamt (Destatis), Zensus 2022: 100 m grid and Gemeindetabellen (dl-de/by-2-0).
- Landeshauptstadt Stuttgart: *Einzelhandels- und Zentrenkonzept 2024* (turnover, potential and floor area by district and class; figures cited); Kleinräumige Gliederung (district boundaries); Statistisches Jahrbuch (purchasing power by district, IFH Retail Consultants).
- Statistik der Bundesagentur für Arbeit: employment and commuter statistics.
- Statistics Canada: Time Use Survey 2022, public-use microdata file (Statistics Canada Open Licence).
- infas / BMDV: *Mobilität in Deutschland* 2017 and 2023 (trip rate, trip length, mode shares; figures cited).
- © OpenStreetMap contributors (ODbL 1.0): buildings, street network.
- Overture Maps Foundation: Places (CDLA-Permissive-2.0).
- NVBW: GTFS timetable for Baden-Württemberg.

## What this model does not have

No prices, no wages paid to workers, no inventory, no capacity constraint on a
shop, no congestion feeding back into travel cost, no transit timetable or line
topology, no housing market, no day-to-day learning or habit, and no firm
entry or exit: the firm register is fixed for the day. The destination kernel uses straight-line distance, not network impedance, so a
road closure cannot currently change where anyone shops.
