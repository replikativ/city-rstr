(ns city.sim.run
  "The run's parameter table: every tunable of the day with its documentation
   and, where it is a calibration target, its prior range. A run's config is
   `(config overrides)`, and `city.sim.day/venue-kernels` turns its store and
   restaurant entries into kernel specs. The published run records the config
   it used."
  (:require [city.sim.day :as d2]
            [city.sim.network :as net]))

(def ^:private store (:retail d2/default-venue-kernels))

(def defaults
  {:lambda-m        {:value 6000.0 :doc "workplace choice distance decay (m), as `city.sim.cityworld/assign-workplaces-grid!` uses it" :prior [:log-uniform 1000 8000]}
   :k-venues        {:value (:k store) :doc "top-K restaurant venues per cell in the gravity table (the store table is the exact dense kernel and ignores K). K truncates the choice set: at K = 16 a city centre is crowded out of a suburban cell's CDF by the sixteen venues on the corner before the kernel is consulted." :prior [:choice 16 32 64]}
   :venue-kernel    {:value (:kernel store) :doc "form of the store/restaurant distance decay: :power = (1 + d/d0)^-beta (Huff / Schläpfer visitation law, scale-free, so a large centre can win at any distance), :exp = exp(-d/lambda), which cannot" :prior [:choice :power :exp]}
   :venue-alpha     {:value (:alpha store) :doc "attractiveness exponent alpha in w = attract^alpha · f(d) for store/restaurant choice; 0 = no size term (every venue in reach is equal), 1 = proportional to size (Huff). `attract` is the raked retail floor area (`city.synth.retail/attract`)." :prior [:uniform 0.0 1.5]}
   :venue-beta      {:value (:beta store) :doc "power-kernel decay exponent beta of the traced day's store and restaurant choice. Schläpfer et al. 2021 find visitation density ∝ (r·f)^-2 across cities; 1.6 was calibrated by hand on 2026-09-12 against the measured retail turnover per Stadtbezirk of the 2024 Einzelhandels- und Zentrenkonzept. Beta is the lever that matters and alpha is not: raising alpha concentrates spending into large venues everywhere, while lowering beta lets a large distant centre stay in reach. At 1.6 the share of the city's retail euro in the wrong district fell from 16.6 % to 13.0 % and Mitte reached 0.88 of its observed turnover; lower values help the centre further but degrade the periphery (mean absolute log ratio 0.42 at 2.0, 0.62 at 1.2). The economic day and the likelihood do not use this value: they use one inferred kernel per demand class." :prior [:uniform 1.0 3.5]}
   :venue-d0-m      {:value (:d0-m store) :doc "power-kernel scale d0 (m): inside it the kernel is flat, outside it scale-free" :prior [:log-uniform 200 2000]}
   :venue-lambda-m  {:value (:lambda-m store) :doc "store/restaurant choice distance decay (m), used only when :venue-kernel is :exp" :prior [:log-uniform 150 4000]}
   :venue-attract-radius-m {:value d2/default-attract-radius-m :doc "radius of the street-density fallback attractiveness (m): one block face" :prior [:log-uniform 50 400]}
   :p-keep-diary-mode {:value d2/default-p-keep-diary-mode
                       :doc "probability a person-day keeps the diary's own travel modes; otherwise every leg of that day takes the person's census commute-mode profile (mode substitution, `day/make-leg`)"
                       :prior [:uniform 0.0 1.0]}
   :profile-walk-max-m {:value net/profile-walk-max-m
                        :doc "a census *walk* person walks a leg up to this far (crow flight) and rides transit beyond it"
                        :prior [:log-uniform 1000 5000]}
   :route-variants  {:value net/walk-route-variants :doc "near-shortest walk routes a leg draws between (1 = strict shortest path)"}
   :route-jitter    {:value net/walk-route-jitter :doc "per-edge length penalty bound of a non-zero walk route variant" :prior [:uniform 0.0 0.6]}
   :seed            {:value 1 :doc "base seed"}})

(defn config
  "Merge overrides ({key value}) into defaults → flat {key value}."
  [overrides]
  (merge (update-vals defaults :value) overrides))
