(ns city.opening-hours
  "Recurring shop hours on a local-minute simulation clock.")

(def ^:private presets {"full" "08:00-20:00" "short" "10:00-18:00"})

(defn- minutes [hh mm]
  (+ (* 60 (parse-long hh)) (parse-long mm)))

(defn schedule [value]
  (if (= value "24h")
    {:key value :label "24 hours" :start 0 :span 1440}
    (let [spec (get presets value value)]
      (when-let [[_ h m end-h end-m]
                 (and (string? spec)
                      (re-matches #"([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-3]):([0-5][0-9])" spec))]
        (let [start (minutes h m)
              span (mod (- (minutes end-h end-m) start) 1440)
              opens (str h ":" m) closes (str end-h ":" end-m)]
          (when (pos? span)
            {:key (or (some (fn [[k v]] (when (= spec v) k)) presets) spec)
             :label (str opens "–" closes) :opens opens :closes closes :start start :span span}))))))

(defn admits? [{:keys [start span]} arrival dwell]
  (and (pos? dwell)
       (or (= span 1440)
           (<= (+ (mod (- arrival start) 1440) dwell) span))))

(defn activation-minute? [minute]
  (and (integer? minute) (<= 240 minute 1679)))

(defn admits-after-activation? [hours activation arrival dwell inward]
  (and (activation-minute? activation)
       (number? inward) (pos? inward)
       (>= (- arrival inward) activation)
       (admits? hours arrival dwell)))

(defn best-shift
  "Count complete visits for each quarter-hour start of a fixed length shift.
   Prefer the start closest on the clock to 09:00 when visit totals tie."
  [stops span]
  (let [candidates (for [start (range 0 1440 15)
                         :let [hours {:start start :span span}
                               n (count (filter (fn [[s d]] (admits? hours s d)) stops))
                               from-nine (abs (- start 540))]]
                     {:start start :count n :distance (min from-nine (- 1440 from-nine))})
        best (first (sort-by (juxt (comp - :count) :distance :start) candidates))]
    (assoc (dissoc best :distance) :ties (count (filter #(= (:count best) (:count %)) candidates)))))
