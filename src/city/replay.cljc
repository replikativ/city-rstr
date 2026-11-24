(ns city.replay
  "Published weekday selection and portable replay links.")

(defn order-runs [runs current]
  (sort-by (juxt #(if (contains? current (:release %)) 0 1)
                 #(if (:jointRun %) 0 1)
                 :coverage :release)
           runs))

(defn preferred-run [runs city coverage]
  (first (order-runs (filter #(and (= city (:city %)) (= coverage (:coverage %))) runs)
                     (into #{} (map :release) runs))))

(defn weekday-query [{:keys [city release]}]
  (case city
    "stuttgart" (if release {"city" city "release" release} {"mode" "city"})
    "vancouver" (cond-> {"city" city}
                  release (assoc "release" release))
    {}))

(defn change-city
  "Open the target city's published weekday at the displayed local time."
  [runs city minute]
  (when-let [run (or (when (= city "vancouver") (preferred-run runs city "region"))
                     (preferred-run runs city "city"))]
    (let [minute (some-> minute (mod 1440))]
      (if (= city "stuttgart")
        {:path "lab.html"
         :query (cond-> (weekday-query run)
                  minute (assoc "hour" (str (/ minute 60.0))))}
        {:path "explorer.html"
         :query (cond-> (weekday-query run)
                  minute (assoc "minute" (str (long minute))))}))))
