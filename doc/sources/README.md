# Data sources

Surveys of public data for grounding city simulations, compiled from
2026-09-10 on while choosing sources for Stuttgart.  They are research notes:
the sources the model actually uses, with licences and access, are listed in
`../../DATA.md`.

- [demographics-synthetic-population.md](demographics-synthetic-population.md): census marginals, microdata, grids, commuting, existing synthetic populations
- [activity-time-use.md](activity-time-use.md): time-use surveys and activity diaries
- [trip-generation.md](trip-generation.md): trip rates and purposes
- [german-parameters.md](german-parameters.md): German model parameters from published estimates
- [economy.md](economy.md): economic data for the money layer
- [imagery.md](imagery.md): street-level, aerial, lidar, 3D, place photos
- [routing-algorithms.md](routing-algorithms.md): routing algorithms for a city-scale simulation

## Venue size: the variable the destination model actually needs (2026-09-12)

The destination kernel's size term is the whole effect (seventh pass), and it is
currently either a declared licence headcount (Vancouver, a measurement) or a
co-located venue count (the street-density proxy). Neither is a *size*. What is
wanted is floor area, and the survey below establishes that it is obtainable in
all three candidate cities, by different routes and at different quality.

**New York has it measured, per lot, with a use split.** PLUTO 26v2 carries
`retailarea`, `officearea`, `comarea`, `resarea`, `garagearea` and more for
858,284 tax lots: **64,230 lots with retail area, 294,318,846 sq ft** in total.
Free, no registration, 68 MB zipped, and it joins to census blocks. Manhattan's
477 M sq ft of office independently matches published inventory estimates, so
these are measurements rather than filler. The systematic hole: the use split is
**not available for one-, two- and three-family structures**, so neighbourhood
retail in rowhouse fabric reads as zero.

**Stuttgart and Vancouver have building footprints, from a pull like the one we
already do for streets.** Verified on a 1 km² square around Königstraße via
Overpass `out geom`:

| | value |
|---|---|
| buildings returned | 463 |
| with `building:levels` | 143 (31 %) |
| footprint median | 180 m² |
| footprint 90th percentile | 1,382 m² |
| footprint maximum | 7,676 m² |

That 43× spread between a typical building and the largest is the
discrimination the kernel needs; the density proxy spans about 10× and the
synthesized headcount spans nonsense. The pull is 561 KB for 1 km², so a whole
city is on the order of 100 MB, comparable to the 74 MB highway pull.

**Use the footprint, not footprint × levels**, where there is no use split. A
shop occupies the ground floor; multiplying by storeys counts the flats above
it, and on a high street that is most of the building. Levels are present on
only 31 % of buildings anyway.

Footprint and the density proxy measure different things and probably both
belong: footprint is the size of a *unit*, density is the agglomeration of a
*block*. A high street is many large units together.

**The buildings already in the store are useless for this**: 259,222 of them
(122,352 Stuttgart, 136,870 Vancouver), but they were pulled with `out center`
so they carry a centroid and no polygon, and only 46,323 carry levels. The
footprint pull is new work, not a re-read.

**Nobody publishes place-level visit counts.** Not New York, not either current
city, not for free anywhere. What New York does publish is subway entries by
hour for 428 station complexes, ~100 M rows, which pins the diurnal and spatial
profile of activity but never the draw of a particular shop. Plan the size term
as a *model* input validated against street counts, not as something that can
be observed per venue.
