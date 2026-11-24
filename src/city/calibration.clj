(ns city.calibration
  "Compare model outputs with reference margins in their own units.")

(defn score
  "Score one ordered margin. Reference metadata includes unit, geography,
   population, period, source and whether it was used in fitting."
  [{:keys [id reference] :as target} predicted]
  (when-not (and (sequential? predicted) (seq reference) (= (count reference) (count predicted))
                 (every? #(and (number? %) (Double/isFinite (double %))) (concat reference predicted)))
    (throw (ex-info "Prediction and reference cells must be finite and aligned" {:target id})))
  (let [residuals (mapv - predicted reference)]
    (assoc target
           :predicted (vec predicted)
           :residuals residuals
           :mae (/ (double (transduce (map abs) + residuals)) (count residuals)))))
