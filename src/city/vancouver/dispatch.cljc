(ns city.vancouver.dispatch
  "Dispatch a fixed fleet to chronological requests on a directed network.
   Durations and clock values are integer seconds past the replay's midnight.")

(defn- offers [fleet request lower-bound]
  (let [{:keys [hail pickup]} request]
    (->> fleet
         (map-indexed
          (fn [id {:keys [place free]}]
            (let [depart (max hail free)]
              [(+ depart (lower-bound place pickup)) id depart place])))
         sort)))

(defn- dispatch-one [fleet request patience lower-bound travel-seconds]
  (let [{:keys [hail due access pickup loaded egress]} request
        ready (+ hail access)
        latest (min (+ hail patience) (- due loaded egress))]
    (if (< latest ready)
      {:miss "diary"}
      (loop [[[bound vehicle depart from] & rest] (offers fleet request lower-bound)
             best nil
             cutoff latest]
        (if (or (nil? bound) (> bound cutoff))
          (or best {:miss "dispatch"})
          (if-let [moving (travel-seconds from pickup (- cutoff depart))]
            (let [at-curb (+ depart moving)
                  board (max ready at-curb)
                  drop (+ board loaded)
                  offer {:vehicle vehicle :from from :depart depart :curb at-curb
                         :board board :drop drop :arrive (+ drop egress)}]
              (if (and (<= board cutoff)
                       (or (nil? best)
                           (< board (:board best))
                           (and (= board (:board best))
                                (< moving (- (:curb best) (:depart best))))))
                (recur rest offer board)
                (recur rest best cutoff)))
            (recur rest best cutoff)))))))

(defn simulate
  "Requests supply :id, :hail, :due, :pickup, :destination, :access, :loaded
   and :egress. Lower bound and travel must agree on endpoint and time units.
   The time oracle returns nil when the traffic arc cannot meet the budget."
  [requests staged patience lower-bound travel-seconds]
  (loop [[request & rest] (sort-by (juxt :hail :id) requests)
         fleet (mapv (fn [place] {:place place :free 0}) staged)
         result (transient [])]
    (if-not request
      (persistent! result)
      (let [{:keys [vehicle drop] :as dispatch} (dispatch-one fleet request patience lower-bound travel-seconds)]
        (recur rest
               (if (some? vehicle)
                 (assoc fleet vehicle {:place (:destination request) :free drop})
                 fleet)
               (conj! result (assoc dispatch :id (:id request))))))))

#?(:cljs
   (defn simulate-js [requests staged patience lower-bound travel-seconds]
     (clj->js (simulate (js->clj requests :keywordize-keys true) (vec (array-seq staged))
                        patience lower-bound travel-seconds))))
