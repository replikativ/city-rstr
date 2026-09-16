(ns city.econ.report
  "Run every registered economic scorer against a world and flatten the results
   into rows the explorer's scorecard draws (`/sim/econ`).

   The registry (`city.econ.quantities`) already says what each quantity is,
   where it came from and how to check it. This turns that into one table, so a
   panel never has to know which scorer produced which number: adding a
   quantity to the registry is enough to make it appear."
  (:require [city.econ.quantities :as q]))

(defn- rows-of [id res]
  (for [r (:rows res)]
    {:quantity (str (symbol id))
     :district (:district r)
     :observed (or (:observed-mio r) (:observed-eur r))
     :predicted (or (:predicted-mio r) (:implied-eur r))
     :ratio (:ratio r)}))

(defn scores
  "`{:rows [...] :summary [...]}` for every quantity whose scorer resolves and
   runs. A scorer that throws is reported rather than swallowed — a silently
   missing quantity is exactly the failure this design exists to prevent."
  [world tables & {:keys [args] :or {args {}}}]
  (let [out (for [[id spec] (sort q/quantities)
                  :let [f (some-> (:scorer spec) requiring-resolve)]]
              (if-not f
                {:id id :error "no scorer"}
                (try
                  (let [res (apply f world (concat (when (:needs-tables spec) [tables])
                                                   (mapcat identity (seq args))))]
                    {:id id :res res})
                  (catch Exception e {:id id :error (.getMessage e)}))))]
    {:summary (vec (for [{:keys [id res error]} out]
                     (merge {:quantity (str (symbol id))
                             :status (name (or (q/status-of id) :unknown))
                             :unit (name (or (:unit (q/quantities id)) :unknown))}
                            (if error
                              {:error error}
                              (select-keys res [:n :city-observed-mio :city-predicted-mio
                                                :city-ratio :mean-abs-log-ratio
                                                :mean-abs-log-ratio-base-corrected])))))
     :rows (vec (mapcat (fn [{:keys [id res]}] (when res (rows-of id res))) out))}))
