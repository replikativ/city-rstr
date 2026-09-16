(ns city.econ.quantities
  "Every economic quantity the model carries, declared with its unit, its
   grounding and the scorer that checks it.

   **Why a registry rather than prose.** `city.sim.run/defaults` documents the
   *parameters* the day uses; receipts (`:acq/*`) document the *files*
   ingested. Nothing connected the two, so a number in the world (a person's
   purchasing power, a district's turnover) carried no machine-readable answer
   to \"where did this come from and what says it is right\". The usual answer
   in agent-based modelling is the ODD protocol, a prose template nothing
   checks; this registry is the smallest thing that makes the question
   answerable by code.

   **The audit flag is `:status`:**

   - `:measured`: read from a source, per entity.
   - `:derived`: computed from measured inputs by a stated rule, and scored
     against a published aggregate it was *not* fitted to where possible.
   - `:assumed`: no grounding. Allowed, but it must be visible, and a
     quantity may not stay here quietly.

   A quantity with no `:target` and no `:scorer` is `:assumed` by construction,
   and `unscored` lists them. That list is the measure of how much of the
   economy is made up.

   **Each entry declares**

   | key | meaning |
   |---|---|
   | `:unit` | the unit, explicitly: a unit error is easier to make than a data error |
   | `:level` | `:person`, `:household`, `:firm`, `:district`, `:city` |
   | `:status` | as above |
   | `:source` | `{:dataset :path :field :value :year}`, the measured input |
   | `:target` | `{:dataset :path :value :year}`, what it is scored against |
   | `:scorer` | a fully-qualified symbol, resolved at call time so this namespace stays dependency-free |
   | `:note` | what the number does *not* claim |"
  (:require [clojure.java.io :as io]))

(def quantities
  {:household/purchasing-power
   {:unit :eur-per-inhabitant-year
    :level :person
    :status :derived
    :source {:dataset "jahrbuch-6-5-2-kaufkraft"
             :path "data/derived/stuttgart_jahrbuch_einkommen.json"
             :field :kaufkraft_je_einwohner_eur
             :year 2024
             :note "IFH purchasing power per inhabitant, per Stadtbezirk: 23 measured values from 25,369 (Stammheim) to 37,970 (Nord)"}
    :target {:dataset "jahrbuch-6-5-2-kaufkraft"
             :path "data/derived/stuttgart_jahrbuch_einkommen.json"
             :field :kaufkraft_absolut_1000_eur
             :note "the district totals, which the assignment is raked to and therefore cannot fail; the scored claim is the *within-district* shape against the city aggregate"}
    :city-check {:dataset "jahrbuch-6-5-1-einkommen"
                 :field :verfuegbares_einkommen_je_einwohner_eur
                 :value 31390 :year 2023
                 :note "disposable income per inhabitant from the VGR, a different concept from IFH Kaufkraft and a different year; agreement is a sanity band, not a target"}
    :scorer 'city.econ.validate/purchasing-power-by-district
    :note "Purchasing power is not income. It is what the retail study's own centrality denominator uses, which is why it is the quantity to carry: it makes the spending loop consistent with the target the destination model is already scored on. It says nothing about wages, taxes or transfers."}

   :household/retail-potential
   {:unit :eur-per-year :level :person :status :derived
    :source {:dataset "measured-retail-share"
             :path "data/derived/stuttgart_retail_detail.json"
             :note "EZK retail Kaufkraft over IFH total Kaufkraft, both summed over the 23 Stadtbezirke: 0.2377. One scalar standing for something that varies 0.194 (Degerloch) to 0.296 (Bad Cannstatt) — Engel's law — and the residual is reported rather than fitted away."}
    :target {:dataset "ezk-2024-kaufkraft"
             :path "data/derived/stuttgart_retail_detail.json"
             :field :kaufkraft_mio_eur :year 2021}
    :scorer 'city.econ.validate/retail-potential-by-district
    :note "The city total cannot miss, since the share is the ratio of the two published sums. The scored claim is the distribution: mean absolute log error 0.080, range 0.80-1.22."}

   :firm/retail-turnover
   {:unit :eur-per-year :level :district :status :derived
    ;; its scorer takes (world tables), unlike the household ones
    :needs-tables true
    :source {:dataset "household purchasing power x retail share, through the destination kernel"
             :path "data/derived/stuttgart_jahrbuch_einkommen.json"}
    :target {:dataset "ezk-2024-umsatz"
             :path "data/derived/stuttgart_retail_detail.json"
             :field :umsatz_mio_eur :value 4.4844E9 :year 2021}
    :scorer 'city.econ.validate/retail-turnover
    :note "The derivation that validate/retail-revenue only attributes. The city total is a prediction: 4,650.9 M EUR against a published 4,484.4 M, ratio 1.037, and the excess is the out-of-city leakage the model does not carry — the census's own city-wide centrality is 0.964. In-commuter spending is absent too and pushes the other way."}})

(defn status-of [id] (get-in quantities [id :status]))

(defn unscored
  "Quantities with no scorer — the ones we are asserting rather than checking."
  []
  (vec (for [[id q] quantities :when (nil? (:scorer q))] id)))

(defn sources-present?
  "Whether every declared source and target file is actually on disk. A registry
   that names a file nobody shipped is worse than no registry."
  []
  (into {} (for [[id q] quantities
                 :let [ps (keep :path [(:source q) (:target q)])]]
             [id (every? #(.exists (io/file %)) ps)])))

(defn report
  "The audit line: every quantity, its status, whether its sources exist and
   whether it is scored, readable without opening the code."
  []
  (vec (for [[id q] (sort quantities)]
         {:id id :unit (:unit q) :level (:level q) :status (:status q)
          :scored (some? (:scorer q))
          :sources-on-disk (get (sources-present?) id)})))
