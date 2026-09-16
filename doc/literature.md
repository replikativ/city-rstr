# Literature: large-scale economic/urban ABMs, calibration, scaling (survey 2026-09-10)

Corrections: the Santa Fe
Farmer/Axtell event was the SFI working group "Economic Agent-Based Models: Crossing Over the
Tipping Point" (4–29 Aug 2025; data ingestion, micro process validity, benchmarking); the 2024
Santa Fe meeting was CSSSA. No published city-scale ABM with validated storefront entry/exit
was found.

## Conference venues
- **CSSSA 2024 (Santa Fe, Oct 2024)**, proceedings Springer Proc. in Complexity 978-3-031-89692-7.
  Relevant: Malikov & Kavak "Scaling ABM outputs using network analysis" (DOI
  10.1007/978-3-031-89692-7_13, closed — worth obtaining for the N-ladder); Koch et al. "Graph
  neural ODEs for coarse-grained socioeconomic dynamics" (arXiv 2407.18108, saved); Olivera et
  al. network structure vs epidemiological parameters (poster); a validation SIG. Schedule saved
  as `csssa-2024-santa-fe-conference-schedule.pdf`.
- **ESSA SSC 2024 (Kraków)** programme and book of abstracts saved. Relevant: Vahana.jl (Fürst
  et al., synchronous graph dynamical systems, multi-node; arXiv 2406.14441); exascale ABSS
  roadmap workshop (Hare, Polhill, Batty, Heppenstall); WGAN synthetic populations on EU-SILC
  (Falck: fringe profiles under-represented); dynamic population synthesis (Sardinha et al.);
  "synthetic city" environment generation to match synthetic populations (Szufel & Kasiński —
  the same gap we face on the business side); calibration methods for a high-dimensional trade
  ABM (Li, Ge, Lomax, Polhill); UQ tutorial with GPs and history matching (Kimpton, Challenor,
  Salter); ABM+CGE coupling for national scale (Verbeek et al.).
- **SSC 2025 (Delft)**: calibration forensics of pandemic management, housing-market flood risk,
  firm carbon policy ABM, LLM-for-ABM papers (Vanhée; Malleson; Edmonds). All closed; nothing
  quantitative on scaling.
Net: neither venue adds quantitative scaling/calibration results; value is the exascale roadmap,
the synthetic-environment idea, and the Exeter UQ tutorial.

## Anchors by topic
- **Calibration / SBI (Farmer, INET Oxford):** Dyer et al. 2022 black-box NPE/NRE on raw
  multivariate series (10⁴ sims beat 10⁵ for ABC/MSM); GNN summaries over per-agent states
  (2022); path-signature kernels when sims are scarce; differentiable ABMs (Quera-Bofarull
  2023/2025: straight-through gradients fail, discrete choices are the hard part, reverse-mode
  memory ∝ agents×steps → truncated horizons); SVI on a JAX supply-chain ABM beats ABC 300 vs
  30,000 evaluations; interventionally consistent surrogates (train on intervention-varied sims);
  Bouchaud 2024: map stiff vs sloppy parameter directions first.
- **Data-driven city/macro ABMs:** Pangallo et al. 2024 NYC-metro epidemic–economy ABM (416k
  agents, 7 params by ABC, everything else from micro data) — the closest precedent; Pichler et
  al. 2022 dynamic IO model (−21.5 % vs −22.1 % actual UK GDP); Wiese et al. 2024 (38 OECD
  countries, 1:1000, NPE with 10⁶ sims); CANVAS (Bank of Canada, 1:100, recalibrated 39 times);
  BeforeIT.jl (8M agents, seconds/step CPU); ASCENT 2026 (columnar PyTorch, 30M agents × 365
  days < 15 min on 4 L4s; masks not branches, sort-then-segment).
- **Axtell:** 2016 120M agents (GPUs rejected because synchronous updating created artifacts;
  32-core shared memory, half a day/run); 2018 Handbook (36 empirical targets, ~12 params;
  top-firm size sublinear in N — "a 1M economy is not a 1/100 replica"); Axtell & Farmer JEL
  2025 survey (reduced-scale firm runs only partially successful; growth rates are fluctuations
  scaling nonlinearly with N); **Axtell & Guerrero 2025**: a one-parameter job-switch kernel
  (move to a larger firm w.p. p, smaller w.p. q) yields Pareto exponent exactly 1; θ≈0.61 US,
  0.41 Finland.
- **Scaling laws:** Mittal & Juneja (never scale outputs linearly from proportionally seeded
  runs; keep absolute seed counts, shift-and-scale); Covasim dynamic rescaling with per-agent
  weights; OpenABM (means converge by ~50k agents, variance scales with N); Wise 2023 (spatial
  peaks biased below 25 % samples); MATSim downscaling (≥25 % for capacity/queueing; rescale
  every rate); Thomas & Marvell (curve collapse, N_S ∝ P^−0.76); Park 2024 (regime shifts
  below N≈1,000); Alfarano (global-count imitation needs 1/N rate scaling); hybrid
  metapopulation/mean-FLAME (exact integers for low-count states).
- **LLM agents:** only as behavioural priors (under-dispersed, over-rational); CitySim validates
  on time-use shares; CoPB hybrid = LLM intentions + gravity placement (−97.7 % tokens); Park
  et al. 1,000 interview agents: demographics buy most of the accuracy.
- **Urban/retail:** UrbanSim/ActivitySim columnar pipeline; MATSim Berlin two-stage calibration
  (flows to counts, then behaviour); Schläpfer universal visitation law (density ∝ (r·f)^−2)
  as prior and target; Deep Gravity (POI utilities matter in cores; CPC metric); time-aware Huff
  (decay varies by hour and store type); Athey 2018 (closures redistribute demand to similar
  nearby stores — a testable storefront target); Seoul food-service survival (>50 % close within
  3 years); RAMP-UA OpenCL (700k people, 100 steps/s; scatter-add/gather/map loop).
- **Synthetic populations:** IPU/raking collapse N_eff (MaxEnt-PCD 2026); latent-variable
  generators (VAE/diffusion) scale past ~20 attributes; copula + zone marginals transfers across
  geographies; validate with SRMSE on n-way marginals plus precision/recall of attribute combos
  (Kim & Bansal 5 % protocol); Ng et al. 2026 IO-anchored synthetic firm networks.

## Lessons to build in early
1. Columnar state, masks not branches, sort-then-segment neighbourhoods; cost linear in edges.
2. Update order is a modelling choice: random activation subsets, deterministic conflict
   resolution by segmented scan, and a serial asynchronous reference to diff against.
3. Run the city 1:1 by default; downscaling is a calibration accelerator, not a necessity.
4. Log a fixed-shape multivariate series per run plus per-agent snapshots and intervention flags
   (the interface for NPE/NRE, GNN calibration, data assimilation, surrogates).
5. Population synthesis as a separate versioned stage with SRMSE/precision-recall checks; never
   reweight a small seed to 100 %.
6. Firm layer: start with the Axtell–Guerrero kernel and check the Zipf exponent emerges.
7. Sector-level dynamic IO as the top reduce step.
8. Pin from micro data, calibrate ≤10 behavioural parameters; history matching to prune, then
   NPE/NRE with ~10⁴ sims; map stiff directions first.
9. Discrete-choice kernels behind one interface (switch, store choice, moves) so smoothed
   variants can replace them; truncated horizons if differentiable.
10. Calibrate in layers: flows to counts, behaviour to survey shares, dynamics last.
11. Never scale outputs linearly from small runs; absolute seeds, shift-and-scale, weight columns.
12. Calibrate means at small N, never variances, tails, or spatial spread.
13. Rescale rates/capacities with the sample; tag kernels by interaction topology.
14. The N-ladder as a first-class experiment with seed ensembles and curve collapse.
15. LLMs only as prior generators; re-inject heterogeneity from microdata.
