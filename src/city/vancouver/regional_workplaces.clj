(ns city.vancouver.regional-workplaces
  "Extract paired regional commute assignments and the constraints on changing them."
  (:require [city.commute :as commute]
            [city.vancouver.tract-workplaces :as tract]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def municipalities ["Vancouver" "City of North Vancouver" "District of North Vancouver" "West Vancouver"])

(defn- read-json [dir file]
  (with-open [r (io/reader (io/file dir file))] (json/read r)))

(defn- work-template [{:strs [slots] :as template} diary]
  (let [paid (commute/paid-slots template diary)
        arrivals (commute/home-work-arrivals template paid)
        constraints (tract/trip-constraints template paid (set (map first arrivals)))]
    {:arrivals (mapv peek arrivals)
     :paid (vec (sort paid))
     :fixed (or (:untimed constraints) (< (count paid) (count (filter #{"job"} slots))))
     :trips (:timed-trips constraints)}))

(defn- worker [plans people home-group place-groups templates d i detailed?]
  (let [[age _ labour _ _ occupation _ t] (people i)
        plan (plans i)
        {:keys [arrivals paid fixed trips]} (templates t)]
    (when (and (= 1 labour) (or (not detailed?) (<= 3 age 13)))
      (when-let [job (some (fn [slot] (let [site (get plan slot -1)] (when (<= 0 site) site))) arrivals)]
        (let [work-group (place-groups job)]
          (when (or detailed? (<= 0 work-group))
            (cond-> [d i home-group work-group job paid
                     (when (and (not fixed) (seq trips) (every? #(= job (get plan %)) paid))
                       (mapv (fn [[slot duration mode _ start from-work?]]
                               (cond-> [(get plan slot -1) duration mode]
                                 detailed? (conj start from-work?))) trips))]
              detailed? (conj occupation))))))))

(defn -main [atlas-dir day-dir output & [detail]]
  (let [atlas (read-json atlas-dir "atlas.json")
        day (read-json day-dir "day.json")
        code (zipmap municipalities (range))
        scope #(if (= % "UBC Vancouver campus") -1 (get code % 0))
        area-groups (mapv scope (day "areas"))
        place-groups (mapv (fn [[_ _ area]] (get area-groups area -1)) (read-json day-dir "places.json"))
        home-groups (into {} (for [[area stats] (atlas "areas"), da (stats "das")] [da (scope area)]))
        templates (mapv work-template (day "templates") (atlas "templates"))
        das (day "das")
        detailed? (= detail "swaps")
        workers (into []
                      (mapcat (fn [[d da]]
                                (let [home-group (home-groups da)
                                      file (str da ".json")
                                      people ((read-json atlas-dir file) "people")
                                      plans ((read-json day-dir file) "plans")]
                                  (when-not (= (count people) (count plans))
                                    (throw (ex-info "Incomplete workplace replay" {:area da})))
                                  (when (<= 0 home-group)
                                    (keep #(worker plans people home-group place-groups templates d % detailed?)
                                          (range (if detailed? (get-in atlas ["das" da "private"]) (count people))))))))
                      (map-indexed vector das))]
    (with-open [w (io/writer output)]
      (json/write {:municipalities municipalities :placeGroups place-groups :workers workers} w))))
