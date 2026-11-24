(ns city.vancouver.shopping
  "Primary shopping episodes in a resident's diary. Counts are per person-day.")

(def categories
  [:goods-at-store :goods-elsewhere-or-unknown :in-person-services
   :online :purchase-research :unspecified])

(defn category [{:keys [act loc shopping-detail]}]
  (when (= :shopping act)
    (case shopping-detail
      :in-person-goods (if (= loc :store) :goods-at-store :goods-elsewhere-or-unknown)
      (:in-person-services :online :purchase-research) shopping-detail
      :unspecified)))

(defn candidate-episodes
  "Recorded in-person goods episodes at a grocery, other store or mall.
   Retain their original times and durations for the prospective shop comparison."
  [chain]
  (filterv #(= :goods-at-store (category %)) chain))

(defn add-episode [totals weight episode]
  (if-let [kind (category episode)]
    (-> totals
        (update [kind :episodes] (fnil + 0.0) weight)
        (update [kind :minutes] (fnil + 0.0) (* weight (:dur episode))))
    totals))

(defn per-day [rates]
  (into {} (for [kind categories]
             [kind {:episodes (get rates [kind :episodes] 0.0)
                    :minutes (get rates [kind :minutes] 0.0)}])))
