(ns city.ui.stuttgart-replay
  "Read shopping examples from the published baseline trajectories.")

(defn- point-key [point]
  (mapv #(#?(:clj Math/round :cljs js/Math.round) (* 1e5 %)) point))

(defn closed-shopping-legs [trips closed]
  (when (seq closed)
    (let [closed-places (into #{} (map (fn [{:keys [lon lat]}] (point-key [lon lat]))) closed)]
      (->> trips
           (filter #(and (= "store" (:purpose %)) (seq (:path %))
                         (= (count (:path %)) (count (:timestamps %)))
                         (< (first (:timestamps %)) (peek (:timestamps %)))
                         (closed-places (point-key (peek (:path %))))))
           (sort-by (juxt (comp first :timestamps) :pid))
           vec))))

(defn shopping-example [legs minute]
  (or (first (filter #(< minute (peek (:timestamps %))) legs))
      (first legs)))
