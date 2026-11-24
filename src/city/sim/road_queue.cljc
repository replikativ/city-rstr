(ns city.sim.road-queue
  "Minute-level discharge at an explicitly capacity-limited road screen.")

(defn discharge
  "Return [arrivals, crossings, waiting at end of minute, offered capacity].
   Capacities are in vehicles per hour. Keep fractional capacity across
   minute boundaries without banking idle slots."
  [arrivals vehicles-per-hour]
  (assert (= (count arrivals) (count vehicles-per-hour)))
  (first
    (reduce (fn [[rows waiting fraction] [enter rate]]
              (let [offered (+ fraction rate)
                    slots (quot offered 60)
                    demand (+ waiting enter)
                    served (min demand slots)
                    remaining (- demand served)]
                [(conj rows [enter served remaining slots]) remaining (rem offered 60)]))
            [[] 0 0]
            (map vector arrivals vehicles-per-hour))))

(defn lanes [site policy direction minute]
  (case site
    "LionsGateBridge"
    (let [centre (case policy
                   "weekday" (if (<= 360 minute 569) 0 1)
                   "south" 0
                   "north" 1)]
      (if (= direction centre) 2 1))

    "Ironworkers"
    (if (and (= "closure" policy) (zero? direction) (<= 420 minute 539)) 2 3)))

(defn replay [site policy direction start capacities arrivals]
  (discharge arrivals
             (map #(get capacities (lanes site policy direction %))
                  (range start (+ start (count arrivals))))))

#?(:cljs
   (defn queue-js [site policy direction start capacities arrivals]
     (let [capacity-map (into {} (map (fn [[k v]] [(js/Number k) v])) (js->clj capacities))]
       (clj->js (replay site policy direction start capacity-map (js->clj arrivals))))))
