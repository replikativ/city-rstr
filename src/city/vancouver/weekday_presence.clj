(ns city.vancouver.weekday-presence
  (:require [city.vancouver.diary-clock :as clock]
            [city.vancouver.roster :as roster]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- read-release [dir id]
  (with-open [r (io/reader (io/file dir (str id ".json")))]
    (json/read r :key-fn keyword)))

(defn- schedule-slots [template]
  (loop [clock 240 parts (:parts template) slots []]
    (if-let [[start duration kind slot] (first parts)]
      (do (when-not (and (= start clock) (pos? duration))
            (throw (ex-info "Vancouver template has a gap or overlap" {:minute clock})))
          (recur (+ start duration) (next parts)
                 (conj slots [(- (+ start duration) 240) (when (= kind "stop") slot)])))
      (do (when-not (= clock 1680)
            (throw (ex-info "Vancouver template does not span the weekday" {:end clock})))
          slots))))

(defn- lon-lat [[x y]]
  [(- (/ x 72600.0) 123.1) (- 49.26 (/ y 111195.0))])

(defn- incoming-positions! [root inputs joint transit coords emit]
  (let [dir (or (:incoming-transit inputs) (io/file root "incoming-transit" transit))
        report (read-release dir "report")
        cohort (or (:commuters inputs) (io/file root "commuters" (:workerRelease report)))
        homes (into {} (map (fn [[x y _ label]] [(last (.split ^String label " ")) (lon-lat [x y])])
                            (read-release dir "homes")))
        fit (when-let [version (get-in report [:homeFit :version])]
              (or (:home-fit inputs) (io/file root "incoming-home-fit" version)))]
    (when-not (= joint (:joint report)) (throw (ex-info "Incoming cohort release mismatch" {})))
    (doseq [group (sort (keys (:groups (read-release cohort "commuters"))))
            :let [shard (read-release cohort (name group))
                  moves (when fit (into {} (map (fn [[i _ h]] [i h])
                                                (read-release fit (name group)))))]
            [i [h j _ _ _ leave duration span attending]] (map-indexed vector (:people shard))
            :when (= attending 1)]
      (let [home (homes (nth (:homes shard) (get moves i h)))
            work (nth coords j)
            arrived (mod (- (+ leave duration) 240) 1440)
            returned (mod (- (+ leave duration span duration) 240) 1440)]
        (when-not home (throw (ex-info "Unresolved incoming home" {:group group :worker i})))
        (emit (if (< arrived returned)
                [[0 (first home) (second home)] (into [arrived] work) (into [returned] home)]
                [(into [0] work) (into [returned] home) (into [arrived] work)]))))))

(defn- periodic-stops [events]
  (let [ordered (into (sorted-map) (map (fn [[minute v]] [(mod (- minute 240) 1440) v])) events)]
    (assoc ordered 0 (get ordered 0 (val (last ordered))))))

(defn- regional-workers! [dir atlas covered places coords travel unknown submit! emit ordinal]
  (let [report (read-release dir "commuters")
        outside (inc unknown)]
    (when-not (= atlas (:atlas report)) (throw (ex-info "External worker atlas mismatch" {})))
    (doseq [group (sort (keys (:groups report)))
            :let [{:keys [people homes homePoints]} (read-release dir (name group))
                  _ (when (some covered homes) (throw (ex-info "External worker home overlaps roster" {:group group})))]]
      (submit!
       (frequencies
        (for [[h j _ _ _ leave duration span attending template] people :when (= 1 attending)
              :let [leave (+ leave (clock/minute-offset (vswap! ordinal inc)))
                    arrive (+ leave duration) depart (+ arrive span) back (+ depart duration)
                    ;; Gaps between paid-work episodes have no published destination.
                    work (for [[a b] (nth (:workSpans report) template)
                               event [[(+ arrive a) (nth places j)] [(+ arrive b) unknown]]] event)
                    stops (periodic-stops (concat [[leave travel] [arrive unknown]] work [[depart travel] [back outside]]))]]
          (do
            (when emit
              (let [home (lon-lat (nth homePoints h))]
                (emit (mapv (fn [[minute point]] (into [minute] point))
                            (periodic-stops [[arrive (nth coords j)] [back home]])))))
            (mapv (fn [[[_ area] end]] [end area])
                  (map vector stops (concat (next (keys stops)) [1440]))))))))))

(defn prepare [{:keys [root day atlas seed trip-rate position-fn jointRun incomingTransit inbound regionalWorkers producer-inputs] :or {root "public/data/vancouver"}}]
  (when-not (and (string? day) (string? atlas))
    (throw (ex-info "Supply a published Vancouver day and atlas" {:day day :atlas atlas})))
  (when (or seed trip-rate)
    (throw (ex-info "Vancouver uses the seed and diary fit of the selected release" {:day day})))
  (let [dd (or (:day producer-inputs) (io/file root "cityday" day))
        ad (or (:roster producer-inputs) (io/file root "atlas" atlas))
        {:keys [areas templates population das occupancy]} (read-release dd "day")
        census-areas (with-open [r (io/reader (io/file ad "atlas.json"))] (get (json/read r) "das"))
        population-of #(get-in census-areas [% "population"])
        offsets (roster/area-offsets das population-of)
        place-rows (read-release dd "places")
        places (mapv #(nth % 2) place-rows)
        coords (when position-fn (mapv lon-lat place-rows))
        slots (mapv schedule-slots templates)
        travel (count areas)
        unknown (inc travel)]
    {:city :vancouver :schedule-basis (if regionalWorkers :regional-diary-within-bin-v1 :published-resident-diary) :day day :atlas atlas :day-start 240 :reference (when-not regionalWorkers occupancy) :population (+ population (if regionalWorkers inbound 0))
     :areas (cond-> (conj areas :travelling :unresolved) regionalWorkers (conj :outside))
     :batches!
     (fn [submit!]
       (doseq [[da offset] (map vector das offsets)]
         (submit!
          (frequencies
           (map (fn [[i person home plan]]
                  (let [agent (+ offset i)
                        shift (if regionalWorkers (clock/minute-offset agent) 0)]
                    (when position-fn
                      (let [template (nth templates (nth person 7))]
                        (position-fn
                         (into [(into [0] (nth coords home))]
                               (keep (fn [[start _ kind slot]]
                                       (when (and (= kind "stop") (<= 0 (nth plan slot)))
                                         (into [(clock/day-boundary (- start 240) shift)] (nth coords (nth plan slot)))))) (:parts template)))))
                    (mapv (fn [[end slot]]
                            [(clock/day-boundary end shift)
                             (if (nil? slot) travel
                               (let [place (nth plan slot)]
                                 (if (= -1 place) unknown (nth places place))))])
                          (nth slots (nth person 7)))))
                (roster/residents ad dd da {:population (population-of da) :require-homes? (some? position-fn)})))))
       (when regionalWorkers
         (regional-workers! (or (:incoming-workers producer-inputs) (io/file root "incoming-workers" regionalWorkers))
                            atlas (set das) places coords travel unknown submit! position-fn
                            (volatile! (dec population))))
       (when (and (nil? regionalWorkers) position-fn (pos? (or inbound 0)))
         (incoming-positions! root producer-inputs jointRun incomingTransit coords position-fn)))}))
