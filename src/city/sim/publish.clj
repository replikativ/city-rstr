(ns city.sim.publish
  "Helpers that turn a simulated day into what the simulation server holds:
   the diary pool reweighted to a city's trip rate, legs in their wire format,
   and measures computed from a published run's cached legs. The Stuttgart
   pipeline that uses them is `city.demo.stuttgart`."
  (:require [city.sim.serve :as serve]
            [city.synth.timeuse :as tu]
            [city.synth.tripgen :as tg]))

(defonce ^{:doc "Statistics Canada Time Use Survey 2022 weekday urban diaries by
  person type, all provinces: 7,017 diaries over 59 types. A single-province
  filter left about 21 diaries per type, and 56 % of simulated mobile days
  came out as one trip out and back. The trip *rate* is a property of the
  instrument and is reweighted per city; the chain variety comes from the pool."}
  pool (delay (tu/chains-by-type (tu/load-diaries :provinces nil))))

(defn diaries-for
  "The diary pool reweighted to a city's published trip rate
   (`city.synth.tripgen`), using that world's own person-type mix. Prints the
   calibration, including the mobile share, which is a *prediction*: only the
   mean is fitted."
  [world city & {:keys [level]}]
  (let [mix (tg/person-type-mix (:persons world))
        {:keys [by-type report]} (tg/calibrate @pool city :type-mix mix :level level)]
    (println "tripgen" city (pr-str (dissoc report :per-type)))
    by-type))

(defn- r5 ^double [^double x] (/ (Math/round (* x 100000.0)) 100000.0))

(defn flat-leg
  "One trace leg as the record `/sim/trips` serves. `:access` is absent: the
   purpose carries it."
  [person {:keys [purpose path timestamps mode]}]
  {:pid person :purpose purpose :mode mode
   :path (mapv (fn [[lon lat]] [(r5 lon) (r5 lat)]) path)
   :timestamps timestamps})

(defn with-access
  "A lazy view of flat legs carrying the `:access` flag that
   `cityworld/area-aggregates` needs, reconstructed from the purpose. Lazy so
   that the flag never costs a second copy of the legs."
  [legs]
  (map #(assoc % :access (= "access" (:purpose %))) legs))

(def city-override-keys
  "The run parameters the city pipeline executes."
  #{:lambda-m :venue-kernel :venue-alpha :venue-beta :venue-d0-m
    :venue-lambda-m :k-venues :venue-attract-radius-m
    :p-keep-diary-mode :route-variants})

(defn traces-from-cache
  "The published run's cached legs, reshaped into per-person traces, so a
   counted target (`city.sim.validate`) can be re-measured without re-routing
   a day. The `:access` flag is reconstructed from the purpose: a walk count
   includes a transit trip's access and egress walk."
  [key]
  (let [out (or (get @serve/outputs (str key)) (throw (ex-info "no run" {:key key})))
        stride (long (or (first (keys (:trips out))) 10))]
    {:stride stride
     :traces (vec (for [[pid ls] (group-by :pid (get-in out [:trips stride]))]
                    {:person pid
                     :legs (mapv #(assoc % :access (= "access" (:purpose %))) ls)}))}))

(defn trip-rate
  "The published run's trip generation, counted the way a travel survey counts
   it (see `city.sim.validate/trip-rate`), from the cached legs.
   `:trips-per-person` is `:mobile-share` × `:trips-per-mobile-person`: a
   shortfall is either too few people leaving home or too short a day."
  [key]
  (let [out (or (get @serve/outputs (str key)) (throw (ex-info "no run" {:key key})))
        {:keys [world]} out
        stride (long (or (first (keys (:trips out))) 10))
        legs (get-in out [:trips stride])
        tables (:daily-tables world)
        ps (:persons world) n (:n ps)
        ^ints ptype (:ptype tables) ^ints hc (:home-cell tables) ^ints work (:work ps)
        ^ints ext (or (:external ps) (int-array n))
        elig? (fn [i] (and (>= (aget ptype i) 0) (or (>= (aget hc i) 0) (>= (aget work i) 0))))
        el (filterv elig? (range n))
        traced (/ (double (count el)) stride)
        real (remove #(= "access" (:purpose %)) legs)
        movers (set (map :pid real))
        r3 (fn [^double x] (/ (Math/round (* 1000.0 x)) 1000.0))
        part (fn [pred] (let [ls (filter #(pred (:pid %)) real)
                              d (/ (double (count (filter pred el))) stride)]
                          (when (pos? d) {:n (long (* d stride)) :trips-per-person (r3 (/ (count ls) d))})))]
    {:run (str key) :stride stride
     :eligible (count el) :traced (long traced)
     :trips (count real) :access-legs (- (count legs) (count real))
     :movers (count movers)
     :mobile-share (r3 (/ (count movers) traced))
     :trips-per-person (r3 (/ (count real) traced))
     :trips-per-mobile-person (r3 (/ (count real) (max 1 (count movers))))
     :residents (part #(zero? (aget ext %)))
     :in-commuters (part #(= 1 (aget ext %)))
     :by-purpose (into (sorted-map) (frequencies (map :purpose real)))}))
