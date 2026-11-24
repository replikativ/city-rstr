(ns city.vancouver.roster
  "Resident rows are keyed by dissemination area and index within its published roster.
   The global replay ID adds the population of every preceding area in day order."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn area-offsets [das population-of]
  (pop (reduce (fn [starts da]
                 (let [n (population-of da)]
                   (when-not (nat-int? n)
                     (throw (ex-info "Missing or invalid area population" {:da da :population n})))
                   (conj starts (+ (peek starts) n))))
               [0] das)))

(defn- shard [dir da]
  (with-open [r (io/reader (io/file dir (str da ".json")))]
    (json/read r)))

(defn residents
  "Return [local-index person home plan] rows from one area. Private-household
   studies take the leading private-count rows. The weekday takes the full roster.
   Early presence-only exports can lack home coordinates."
  [atlas-dir day-dir da {:keys [population private-count require-homes?]}]
  (let [{:strs [people]} (shard atlas-dir da)
        {:strs [home plans]} (shard day-dir da)
        n (count people)]
    (when-not (and (vector? people) (vector? plans) (= n (count plans))
                   (or (nil? population) (= population n))
                   (or (and (nil? home) (not require-homes?))
                       (and (vector? home) (= n (count home))))
                   (or (nil? private-count) (and (nat-int? private-count) (<= private-count n))))
      (throw (ex-info "Resident and location rosters differ" {:da da :population n :private private-count})))
    (map (fn [i] [i (people i) (get home i) (plans i)])
         (range (or private-count n)))))

(defn visit-private!
  "Visit private-household rows in the selected areas, retaining their original local IDs."
  [atlas-dir day-dir atlas das visit!]
  (doseq [da das]
    (let [{:strs [private population]} (get-in atlas ["das" da])]
      (when-not (nat-int? private)
        (throw (ex-info "Missing private-household count" {:da da})))
      (doseq [[i person home plan] (residents atlas-dir day-dir da
                                             {:population population :private-count private :require-homes? true})]
        (visit! da i person home plan)))))
