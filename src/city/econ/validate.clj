(ns city.econ.validate
  "Scorers for the economic quantities in `city.econ.quantities`.

   **The scored claim must not be the one that was fitted.** Purchasing power is
   raked to each district's published total, so district totals agree exactly and
   testing them would test nothing. What is *not* raked is our population: the
   rake divides a published district total by the residents **we** synthesized.
   So the implied purchasing power per inhabitant is a real prediction, and
   comparing it with the published per-inhabitant figure measures the error in
   our population distribution against a source the synthesis never saw.

   That is the same trick the retail census already gave us — its implied
   populations agreed with the synthesis to 4.7 % per district — applied to a
   second, independent measurement."
  (:require [city.econ.household :as hh]
            [city.econ.spending :as sp]
            [city.synth.retail :as retail]))

(defn purchasing-power-by-district
  "Implied Kaufkraft per inhabitant against the published figure, per district.

   A district where we synthesized too many residents shows a *low* implied
   value (the same euros spread over more people) and vice versa, so the ratio
   is a direct read on the population distribution — `:ratio` below 1 means we
   put too many people there."
  [world & {:keys [kk by-district] :or {kk (hh/kaufkraft) by-district identity}}]
  (let [ps (:persons world) n (:n ps)
        ^ints ext (or (:external ps) (int-array n))
        ^objects la (:la ps)
        ^doubles pp (:pp ps)]
    (when pp
      (let [agg (reduce (fn [m i]
                          (if (zero? (aget ext i))
                            (let [d (by-district (aget la i))]
                              (-> m (update-in [d :n] (fnil inc 0))
                                    (update-in [d :eur] (fnil + 0.0) (aget pp i))))
                            m))
                        {} (range n))
            r3 (fn [^double x] (/ (Math/round (* 1000.0 x)) 1000.0))
            rows (vec (for [[d {:keys [n eur]}] (sort agg)
                            :let [obs (get-in kk [d :per-inhabitant])
                                  sim (when (pos? (long n)) (/ eur (double n)))]
                            :when obs]
                        {:district d :residents n
                         :observed-eur (Math/round (double obs))
                         :implied-eur (when sim (Math/round (double sim)))
                         :ratio (when sim (r3 (/ sim (double obs))))}))
            ok (filterv :ratio rows)
            ;; Every ratio comes out above 1 because IFH's population base is
            ;; not ours: dividing the published city total by its
            ;; per-inhabitant figure implies 632,867 residents against our
            ;; 610,444, 3.7 % apart. That is a *base* difference, not a
            ;; distribution error, and reporting only the raw ratio would
            ;; charge the synthesis for it. Both are given; the base-corrected
            ;; figure is the one that measures what we control.
            city-ratio (when (seq ok)
                         (/ (reduce + (map #(double (:ratio %)) ok)) (count ok)))]
        {:rows rows :n (count ok)
         :implied-population-base
         (let [c (hh/city-kaufkraft)]
           (when c (Math/round (/ (:total-eur c) (:per-inhabitant c)))))
         :our-residents (count (filter #(zero? (aget ext %)) (range n)))
         :mean-abs-log-ratio
         (when (seq ok)
           (r3 (/ (reduce + (map #(Math/abs (Math/log (double (:ratio %)))) ok)) (count ok))))
         :mean-abs-log-ratio-base-corrected
         (when (and (seq ok) city-ratio (pos? (double city-ratio)))
           (r3 (/ (reduce + (map #(Math/abs (Math/log (/ (double (:ratio %)) (double city-ratio)))) ok))
                  (count ok))))
         :worst (->> ok (sort-by #(- (Math/abs (Math/log (double (:ratio %)))))) first)}))))


(defn- score-rows
  "Common shape: {district → predicted} against {district → observed}."
  [pred obs-of targets]
  (let [r2 (fn [^double x] (/ (Math/round (* 100.0 x)) 100.0))
        rows (vec (for [[d t] (sort targets)
                        :let [o (obs-of t) s (get pred d)]
                        :when (and o s (pos? (double o)))]
                    {:district d :observed-mio (r2 (/ (double o) 1.0e6))
                     :predicted-mio (r2 (/ (double s) 1.0e6))
                     :ratio (r2 (/ (double s) (double o)))}))
        rs (mapv :ratio rows)
        tot-o (reduce + (map :observed-mio rows)) tot-p (reduce + (map :predicted-mio rows))]
    {:rows rows :n (count rows)
     :city-observed-mio (r2 tot-o) :city-predicted-mio (r2 tot-p)
     :city-ratio (when (pos? tot-o) (/ (Math/round (* 1000.0 (/ tot-p tot-o))) 1000.0))
     :mean-abs-log-ratio
     (when (seq rs)
       (/ (Math/round (* 1000.0 (/ (reduce + (map #(Math/abs (Math/log (double %))) rs)) (count rs)))) 1000.0))
     :centre (first (filter #(= "Mitte" (:district %)) rows))}))

(defn retail-potential-by-district
  "Predicted retail spending capacity against the EZK's own einzelhandels-
   relevantes Kaufkraftpotenzial.

   The city total cannot miss — the share is the city-wide ratio of the two
   published sums — so the scored claim is the **distribution**, and its residual
   is the Engel signal the single scalar deliberately does not absorb: the share
   of purchasing power reaching retail runs 0.194 in affluent Degerloch to 0.296
   in Bad Cannstatt, and a flat share must therefore over-predict the rich
   districts and under-predict the poor ones."
  [world & {:keys [spend by-district targets] :or {by-district identity targets (retail/targets)}}]
  (let [ps (:persons world) n (:n ps) ^objects la (:la ps) ^ints ext (or (:external ps) (int-array n))
        ^doubles sp* (or spend (sp/retail-potential world))]
    (when sp*
      (let [pred (reduce (fn [m i] (if (zero? (aget ext i))
                                     (update m (by-district (aget la i)) (fnil + 0.0) (aget sp* i))
                                     m))
                         {} (range n))]
        (score-rows pred :kaufkraft-eur targets)))))

(defn retail-turnover
  "Predicted retail turnover against the published census — the derivation that
   `validate/retail-revenue` only attributes.

   `retail-revenue` takes the census's 4,484.4 M EUR and asks where it goes.
   This asks **how much there is**: household purchasing power times a measured
   share, spent through the destination kernel. The city total is therefore a
   prediction and `:city-ratio` is the headline.

   Expect it above 1, and know why: every euro of resident potential is spent at
   a Stuttgart venue because the model has no out-of-city shopping, while the
   census's own city-wide centrality is 0.964 — Stuttgart is a slight net
   exporter of retail spending. A perfect destination model with no leakage
   should therefore land near 1/0.964 = 1.037. Two omissions partly offset:
   in-commuter spending is also absent, and would push the other way."
  [world tables & {:keys [table spend by-district targets]
                   :or {by-district identity targets (retail/targets)}}]
  (when-let [pred (sp/turnover-by-district world tables :table table :district-of by-district :spend spend)]
    (score-rows pred :umsatz-eur targets)))
