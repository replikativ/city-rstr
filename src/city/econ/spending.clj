(ns city.econ.spending
  "Retail spending: each resident's purchasing power (`city.econ.household`)
   times one retail share is their retail potential, and pushed through the
   destination kernel it becomes turnover by district. The city total is then
   predicted, and the published figure is a target rather than an input.

   ## The retail share, and why one scalar

   Two independent measurements of purchasing power exist per district: IFH's
   total Kaufkraft (Jahrbuch 6.5.2) and the retail study's
   *einzelhandelsrelevantes* Kaufkraftpotenzial (EZK 2024). Their ratio is the
   share of purchasing power that reaches retail, and across the 23 districts it
   runs **0.194 to 0.296, mean 0.240**, so the share genuinely varies.

   It varies the way Engel's law says it should: affluent Degerloch sits at
   0.204 and Bad Cannstatt at 0.263. A share that fell with income would fit
   better, and would also be fitted: two more parameters against 23
   observations, tuned on the very quantity being predicted. So the model uses
   **one measured scalar** and reports the residual, which then carries the
   Engel signal as a finding rather than hiding it inside a fitted curve. An
   income-dependent share would have to be scored against something other than
   the series it was fitted to.

   ## What is predicted and what is not

   - Household purchasing power is raked to IFH district totals, so it is
     measured, not predicted.
   - **Retail potential per district is predicted**: the synthetic population
     times one scalar, against the EZK's own district Kaufkraft.
   - **Turnover per district is predicted**: that potential pushed through the
     destination kernel, against the EZK's own district Umsatz."
  (:require [city.econ.household :as hh]
            [city.synth.retail :as retail]))

(defn measured-retail-share
  "The city-wide share of purchasing power that is retail-relevant: EZK retail
   Kaufkraft over IFH total Kaufkraft, both summed over the 23 Stadtbezirke.
   A measurement, not a parameter — but a single number standing for something
   that varies, which is the first thing to revisit."
  [& {:keys [kk targets] :or {kk (hh/kaufkraft) targets (retail/targets)}}]
  (let [tot (reduce + (keep #(:total-eur (val %)) kk))
        ret (reduce + (keep #(:kaufkraft-eur (val %)) targets))]
    (when (and (pos? (double tot)) (pos? (double ret))) (/ (double ret) (double tot)))))

(defn retail-potential
  "Per-person retail spending capacity, in euros per year: purchasing power
   times the share. Residents only — an in-commuter's retail spending belongs to
   the city they live in, and the EZK's Kaufkraft counts residents."
  [world & {:keys [share] :or {share (measured-retail-share)}}]
  (let [ps (:persons world) n (:n ps) ^doubles pp (:pp ps)]
    (when pp
      (let [out (double-array n)]
        (dotimes [i n] (aset out i (* (aget pp i) (double share))))
        out))))

(defn turnover-by-district
  "Predicted retail turnover per district, in euros per year.

   Every resident's retail potential is pushed through their home cell's own
   choice CDF, so a euro lands in the district of the venue actually chosen.
   This is `validate/retail-demand-share` weighted by money rather than by
   headcount — the same table, the same probabilities, a different numerator —
   which is why the two scores cannot disagree about the destination model and
   can only disagree about the money."
  [world tables & {:keys [table district-of spend] :or {district-of identity}}]
  (let [{:keys [^ints offsets ^ints venues ^doubles cdf]} (or table (:retail tables))
        grid (:grid tables)
        ps (:persons world) n (:n ps)
        ^ints hc (:home-cell tables)
        ^ints ext (or (:external ps) (int-array n))
        fs (:firms world) ^objects fla (:la fs)
        ^doubles sp (or spend (retail-potential world))]
    (when sp
      (let [cell-eur (double-array (:n grid))]
        (dotimes [i n]
          (when (and (zero? (aget ext i)) (>= (aget hc i) 0))
            (aset cell-eur (aget hc i) (+ (aget cell-eur (aget hc i)) (aget sp i)))))
        (let [out (java.util.HashMap.)]
          (dotimes [c (:n grid)]
            (let [e (aget cell-eur c)]
              (when (pos? e)
                (let [a (aget offsets c) b (aget offsets (inc c))]
                  (loop [k a prev 0.0]
                    (when (< k b)
                      (let [cur (aget cdf k) m (- cur prev)
                            d (district-of (aget fla (aget venues k)))]
                        (.put out d (+ (double (or (.get out d) 0.0)) (* e m)))
                        (recur (inc k) cur))))))))
          (into {} out))))))
