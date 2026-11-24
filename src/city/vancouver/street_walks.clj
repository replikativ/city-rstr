(ns city.vancouver.street-walks
  "Bucket single-mode walking, cycling and driving bouts and potential workplace-mode changes by replay hour."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.outbound :as outbound]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.io BufferedOutputStream DataOutputStream]))

(defn indexed-parts [{:strs [slots parts] :as template} {:strs [episodes] :as diary} census?]
  (let [paid (when census? (outbound/paid-slots template diary))]
    (mapcat identity
            (keep-indexed
             (fn [k [start duration mode a b :as part]]
               (when (and (not= mode "stop") (<= 0 a) (<= 0 b))
                 (let [end (+ start duration)
                       pure? (and (#{"walk" "bike" "car-driver"} mode)
                                  (every? #(= mode (nth % 3))
                                          (filter #(<= start (first %) (dec end)) episodes)))
                       kind (when pure? (if (= mode "car-driver") :car (keyword mode)))
                       commute? (and census? (not (#{:walk :bike} kind))
                                     (outbound/direct-commute? slots paid part))
                       hours (range (quot start 60) (inc (quot (dec end) 60)))]
                   (cond-> []
                     kind (conj [kind k a b hours])
                     commute? (conj [:commute k a b hours])))))
             parts))))

(defn- emit! [^DataOutputStream stream d i tpl k a b]
  ;; Network byte order, four unsigned 16-bit identifiers and two signed 32-bit place IDs.
  (.writeShort stream d) (.writeShort stream i) (.writeShort stream tpl) (.writeShort stream k)
  (.writeInt stream a) (.writeInt stream b))

(defn -main [atlas-dir day-dir output clock-file census]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        clock (when-not (= "-" clock-file) (read-json clock-file))
        census? (= "census" census)
        templates (get clock "templates")
        parts (mapv #(vec (indexed-parts %1 %2 census?))
                    (into (day "templates") (map #(get % "day") templates))
                    (into (atlas "templates") (map #(get % "diary") templates)))
        hours (range 4 28)
        streams (into {} (for [kind (if census? [:walk :bike :car :commute] [:walk :bike :car]) h hours]
                           [[kind h] (DataOutputStream. (BufferedOutputStream.
                                                         (io/output-stream (io/file output (str (name kind) "-" h ".bin")))))]))
        totals (volatile! {:residents 0 :walk 0 :bike 0 :car 0 :commute 0})]
    (try
      (when (and clock (not= [(clock "atlas") (clock "day")]
                             (mapv #(.getName (io/file %)) [atlas-dir day-dir])))
        (throw (ex-info "Street index and clock have different parents" {})))
      (doseq [[d da] (map-indexed vector (day "das"))]
        (let [people ((read-json (io/file atlas-dir (str da ".json"))) "people")
              plans ((read-json (io/file day-dir (str da ".json"))) "plans")
              changes (into {} (map (juxt first rest)) (get-in clock ["changes" da]))]
          (when-not (= (count plans) (count people) (get-in atlas ["das" da "population"]))
            (throw (ex-info "Street index and roster differ" {:da da})))
          (vswap! totals update :residents + (count people))
          (doseq [[i p] (map-indexed vector people)]
            (let [tpl (nth p 7) [old replacement] (get changes i)
                  _ (when (and old (not= tpl old)) (throw (ex-info "Clock and roster differ" {:da da :i i})))
                  effective (or replacement tpl) plan (plans i)]
              (doseq [[kind k a b buckets] (parts effective)]
                (when (> (max d i effective k) 65535) (throw (ex-info "Street record exceeds 16-bit ID" {:da da :i i})))
                (vswap! totals update kind inc)
                (doseq [h buckets] (emit! (streams [kind h]) d i effective k (plan a) (plan b))))))))
      (when-not (= (:residents @totals) (day "population")) (throw (ex-info "Incomplete street index" @totals)))
      (with-open [w (io/writer (io/file output "walks.json"))]
        (json/write (assoc @totals :atlas (.getName (io/file atlas-dir)) :day (.getName (io/file day-dir))
                           :clock (when clock (.getName (.getParentFile (io/file clock-file))))
                           :census census?) w))
      (finally (doseq [^DataOutputStream s (vals streams)] (.close s))))))
