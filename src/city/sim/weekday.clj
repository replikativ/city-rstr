(ns city.sim.weekday
  "Pack resident schedules into numeric intervals and evaluate requested products.
   Each path partitions the day into [exclusive-end-minute area-index] pairs."
  (:require [city.sim.occupancy :as occ]))

(defn- pack-path! [^ints starts ^ints ends offset zones path]
  (loop [k offset from 0 parts (seq path)]
    (if-let [[end area] (first parts)]
      (do
        (when-not (and (integer? end) (< from end 1441)
                       (integer? area) (<= 0 area (dec zones)))
          (throw (ex-info "Invalid day interval" {:from from :end end :area area})))
        (aset starts k (+ (* from zones) area))
        (aset ends k (+ (* end zones) area))
        (recur (inc k) end (next parts)))
      (when-not (= from 1440)
        (throw (ex-info "Incomplete schedule" {:end from}))))))

(defn- pack-batch [zones groups]
  (when (seq groups)
    (let [paths (keys groups)
          offsets (int-array (reductions + 0 (map count paths)))
          size (aget offsets (count paths))
          starts (int-array size)
          ends (int-array size)]
      (doseq [[i path] (map-indexed vector paths)]
        (pack-path! starts ends (aget offsets i) zones path))
      {:ids (int-array (range (count paths)))
       :weights (int-array (map #(get groups %) paths))
       :offsets offsets :starts starts :ends ends
       :max-parts (apply max (map count paths))})))

(defn prepare-batches
  "Consume the producer once. Only numeric schedule arrays cross into execution."
  [{:keys [areas population batches!] :as producer}]
  (when-not (and (seq areas) (nat-int? population))
    (throw (ex-info "Invalid weekday geography or population" {:population population})))
  (let [batches (java.util.ArrayList.)
        ;; Source partitions are often small census areas. Combine equal paths
        ;; across them and bound the live hash table before packing arrays.
        pending (java.util.HashMap.)
        flush! (fn []
                 (when-not (.isEmpty pending)
                   (.add batches (pack-batch (count areas) pending))
                   (.clear pending)))]
    (batches! (fn [groups]
                (doseq [[path weight] groups]
                  (when-not (pos-int? weight)
                    (throw (ex-info "Schedule weights must be positive integers" {})))
                  (.put pending path (+ weight (.getOrDefault pending path 0)))
                  (when (>= (.size pending) 8192) (flush!)))))
    (flush!)
    (when-not (= population (reduce + 0 (map #(reduce + 0 (:weights %)) batches)))
      (throw (ex-info "Schedule weights disagree with population" {:population population})))
    (assoc (select-keys producer [:city :atlas :day :release :seed :trip-rate :schedule-basis
                                  :day-start :areas :population :reference])
           :batches (vec batches))))

(defn- accumulate! [^ints changes {:keys [ids starts max-parts] :as batch} backend]
  (let [inputs (assoc (dissoc batch :max-parts)
                      :shifts (int-array (alength ^ints starts))
                      :ranks (int-array (alength ^ints ids)) :settings (int-array 2)
                      :changes (int-array (alength changes)))
        ^ints result (first (occ/evaluate inputs [0] max-parts backend))]
    (dotimes [i (alength changes)]
      (aset changes i (+ (aget changes i) (aget result i))))))

(defn- presence-counts [{:keys [areas population batches reference] :as prepared} backend]
  (let [zones (count areas)
        changes (int-array (* 1441 zones))]
    (doseq [batch batches] (accumulate! changes batch backend))
    (let [counts (mapv (fn [minute]
                         (mapv (fn [area]
                                 (let [i (+ (* minute zones) area)
                                       n (+ (aget changes i) (if (zero? minute) 0 (aget changes (- i zones))))]
                                   (aset changes i n)
                                   n)) (range zones))) (range 1441))]
      (when-not (and (every? #(and (= population (reduce + %)) (every? nat-int? %)) (pop counts))
                     (every? zero? (peek counts)))
        (throw (ex-info "Weekday population does not balance" {:population population})))
      (when (and reference (not= reference (pop counts)))
        (throw (ex-info "Presence differs from the source weekday" (select-keys prepared [:city :day :atlas]))))
      (pop counts))))

(defn- add-count! [^ints counts index weight]
  (aset counts index (+ (aget counts index) weight)))

(defn- trip-ends
  "Hourly arrivals and departures at areas adjacent to a travel interval.
   Hours are offsets from day-start. An unfinished leg contributes its known end."
  [{:keys [areas batches]}]
  (let [zones (count areas)
        travel (.indexOf ^java.util.List areas :travelling)
        arrivals (int-array (* 24 zones))
        departures (int-array (* 24 zones))
        hours (fn [counts] (mapv vec (partition zones counts)))]
    (when (neg? travel)
      (throw (ex-info "Trip counting requires a travelling area" {:areas areas})))
    (doseq [{:keys [^ints starts ^ints offsets ^ints weights]} batches]
      (dotimes [path (alength weights)]
        (doseq [i (range (inc (aget offsets path)) (aget offsets (inc path)))]
          (let [start (aget starts i)
                from (rem (aget starts (dec i)) zones)
                to (rem start zones)
                hour (quot (quot start zones) 60)
                base (* hour zones)
                weight (aget weights path)]
            (cond
              (= from to) nil
              (= to travel) (add-count! departures (+ base from) weight)
              (= from travel) (add-count! arrivals (+ base to) weight))))))
    {:arrivals (hours arrivals) :departures (hours departures)}))

(defn- od-flows
  "Pair consecutive travel intervals with their known preceding and following stops.
   Rows contain [departure-hour arrival-hour origin destination people]."
  [{:keys [areas batches]}]
  (let [zones (count areas) travel (.indexOf ^java.util.List areas :travelling)
        flows (java.util.HashMap.)]
    (when (neg? travel) (throw (ex-info "OD counting requires a travelling area" {})))
    (doseq [{:keys [^ints starts ^ints offsets ^ints weights]} batches]
      (dotimes [path (alength weights)]
        (let [begin (aget offsets path) end (aget offsets (inc path))]
          (loop [i (inc begin) departure nil origin nil]
            (when (< i end)
              (let [from (rem (aget starts (dec i)) zones)
                    at (aget starts i) to (rem at zones) hour (quot at (* 60 zones))]
                (cond
                  (and (= to travel) (not= from travel))
                  (recur (inc i) hour from)

                  (and (= from travel) (not= to travel) (some? origin))
                  (let [key [departure hour origin to]]
                    (.put flows key (+ (.getOrDefault flows key 0) (aget weights path)))
                    (recur (inc i) nil nil))

                  :else (recur (inc i) departure origin))))))))
    (mapv (fn [[key n]] (conj key n)) (sort-by key flows))))

(defn execute
  "Evaluate the requested products against detached arrays. No producer is retained."
  ([prepared backend] (execute prepared backend #{:presence}))
  ([prepared backend products]
   (when-not (and (set? products) (seq products) (every? #{:presence :trip-ends :od-flows} products))
     (throw (ex-info "Unknown or empty weekday products" {:products products})))
   (cond-> (dissoc prepared :batches :reference)
     (products :presence) (assoc :presence (presence-counts prepared backend))
     (products :trip-ends) (assoc :trip-ends (trip-ends prepared))
     (products :od-flows) (assoc :od-flows (od-flows prepared)))))
