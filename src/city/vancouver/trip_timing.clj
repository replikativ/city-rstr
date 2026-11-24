(ns city.vancouver.trip-timing
  "Count resident trip departures by minute and purpose on a combined weekday."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [city.vancouver.survey-zones :refer [adult-fifths]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- count-trip! [counts purpose minute weight]
  (let [^longs minutes (counts purpose)
        i (- minute 240)]
    (aset-long minutes i (+ (aget minutes i) weight))))

(defn- gap-purpose [gaps start duration from to]
  (let [matches (for [[boundary a b purpose] gaps
                      :when (and (= a from) (= b to) (<= start boundary (+ start duration)))]
                  purpose)]
    (when-not (= 1 (count matches))
      (throw (ex-info "Expected one diary boundary for an inferred walk"
                      {:start start :duration duration :from from :to to})))
    (first matches)))

(defn- group-residents [rows]
  (group-by (fn [[d i]] [d i]) rows))

(defn -main [atlas-dir day-dir input output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        {:strs [diaries gaps shortWalks shoppingWalks purposes shopping returnHome]} (read-json input)
        count-array #(vec (repeatedly (count purposes) (fn [] (long-array 1440))))
        recorded (count-array) inferred (count-array) fitted (count-array)
        ordinal (zipmap (day "das") (range))
        short (group-residents shortWalks)
        tours (group-residents shoppingWalks)
        adults (volatile! 0)]
    (visit-residents!
     atlas-dir day-dir atlas (day "das")
     (fn [da i person _ _]
       (let [weight (adult-fifths (first person))
             template (peek person)
             key [(ordinal da) i]]
         (when (pos? weight)
           (vswap! adults + weight)
           (doseq [[minute purpose] (diaries template)]
             (count-trip! recorded purpose minute weight))
           (doseq [[_ _ start duration from to] (short key)]
             (count-trip! inferred (gap-purpose (gaps template) start duration from to) start weight))
           (doseq [[_ _ start there dwell] (tours key)]
             (count-trip! fitted shopping start weight)
             (count-trip! fitted returnHome (+ start there dwell) weight))))))
    (with-open [stream (io/writer output)]
      (json/write {:adults @adults :recorded (mapv vec recorded)
                   :inferred (mapv vec inferred) :fitted (mapv vec fitted)} stream))))
