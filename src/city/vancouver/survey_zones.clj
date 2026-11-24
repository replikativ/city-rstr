(ns city.vancouver.survey-zones
  "Compare resident trips by purpose with held-out City survey zone shares."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- read-json [file]
  (with-open [r (io/reader file)] (json/read r)))

(defn- read-at [dir file] (read-json (io/file dir file)))

(defn adult-fifths [age]
  (cond (<= 4 age 13) 5 (= age 3) 2 :else 0))

(defn trip-cell
  "Columns 0–8 are internal city destinations, 9 is external and 10 is unresolved."
  [outside? work-zone]
  (cond outside? 9 (and (some? work-zone) (<= 0 work-zone 8)) work-zone :else 10))

(defn- add! [^longs arr i n]
  (aset-long arr i (+ n (aget arr i))))

(defn- serialize [matrix]
  (mapv #(mapv (fn [value] (/ value 5.0)) %) (partition 11 matrix)))

(defn other-purpose [a b]
  (when (and a b (not= "unknown" a) (not= "unknown" b))
    (cond
      (and (not= a "home") (not= b "home")) :nonhome
      (= a b) nil
      (#{"school" "job"} (if (= a "home") b a)) nil
      :else :other)))

(defn- count-other! [totals w o zones borders h plan external-slots a b]
  (let [u (plan a) v (plan b)
        za (trip-cell (external-slots a) (get zones u))
        zb (trip-cell (external-slots b) (get zones v))
        offset (* o 5)]
    (if (and (< za 10) (< zb 10))
      (let [within? (and (< o 9) (= o za zb))
            interior? (and (< o 9) (not (get borders h))
                           (or (= za 9) (not (get borders u))) (or (= zb 9) (not (get borders v))))]
        (add! totals offset w)
        (when within? (add! totals (inc offset) w))
        (when interior?
          (add! totals (+ offset 2) w)
          (when within? (add! totals (+ offset 3) w))))
      (add! totals (+ offset 4) w))))

(defn -main [atlas-dir day-dir outbound-dir sites-dir input output]
  (let [day (read-at day-dir "day.json") atlas (read-at atlas-dir "atlas.json")
        report (read-at outbound-dir "report.json") sites (read-at sites-dir "worksites.json")
        outside (read-at outbound-dir "assignments.json") geo (read-json input)
        zones (geo "zone") borders (geo "border") templates (day "templates")
        changes (reduce (fn [by-person [d i slot _ to]] (assoc-in by-person [[d i] slot] to)) {} (sites "changes"))
        legs (mapv (fn [t starts]
                     (let [direct (set starts) slots (t "slots")]
                       (vec (for [[s _ _ a b] (t "parts") :when (direct s)]
                              (if (= "home" (slots a)) [a b] [b a]))))) templates (report "directStarts"))
        other-legs (mapv (fn [{:strs [slots parts]}]
                           (vec (for [[_ _ mode a b] parts :when (not= mode "stop")
                                      :let [kind (other-purpose (get slots a) (get slots b))] :when kind]
                                  [kind a b]))) templates)
        paid (mapv set (report "slots"))
        other-counts {:other (long-array 50) :nonhome (long-array 50)}
        ;; The last origin row keeps unmapped homes visible in the city denominator.
        census (long-array 10) original (long-array 110) matched (long-array 110) interior (long-array 110)
        skipped (long-array 1)]
    (when-not (and (= (report "day") (sites "day") (.getName (io/file day-dir)))
                   (= (report "atlas") (sites "atlas") (.getName (io/file atlas-dir)))
                   (= (sites "outbound") (.getName (io/file outbound-dir))))
      (throw (ex-info "Survey geography and resident releases differ" {})))
    (doseq [[d da] (map-indexed vector (day "das"))]
      (let [file (str da ".json") people (get (read-at atlas-dir file) "people")
            {:strs [plans home]} (read-at day-dir file)
            external (into #{} (map first) (outside d)) private (get-in atlas ["das" da "private"])]
        (dotimes [i private]
          (let [person (people i) pattern (legs (peek person)) age (first person)
                w (adult-fifths age) h (home i) home-zone (get zones h -1)
                o (if (neg? home-zone) 9 home-zone)]
            (when (= age 88) (add! skipped 0 (count pattern)))
            (when (pos? w)
              (add! census o w)
              (let [plan (plans i) ext? (contains? external i)
                    adjusted (reduce-kv assoc plan (changes [d i]))]
                (let [ext-slots (if ext? (paid (peek person)) #{})]
                  (doseq [[kind a b] (other-legs (peek person))]
                    (count-other! (other-counts kind) w o zones borders h adjusted ext-slots a b)))
                (doseq [[hs js] pattern]
                  (let [j (plan js) site (adjusted js)
                        located? (= h (plan hs))
                        cell (if located? (trip-cell ext? (get zones j)) 10)
                        fitted (if located? (trip-cell ext? (get zones site)) 10)]
                    (add! original (+ (* 11 o) cell) w)
                    (add! matched (+ (* 11 o) fitted) w)
                    (when (and (< o 9) (< fitted 10) (not (get borders h))
                               (or ext? (not (get borders site))))
                      (add! interior (+ (* 11 o) fitted) w))))))))))
    (with-open [w (io/writer output)]
      (json/write (merge (select-keys geo ["zones" "metres" "source" "item" "digest"])
                         {:atlas (sites "atlas") :day (sites "day") :outbound (sites "outbound")
                          :worksites (or (sites "worksites") (.getName (io/file sites-dir))) :unknownAgeLegs (aget skipped 0)
                          :otherPurposes (update-vals other-counts #(mapv (fn [row] (mapv (fn [n] (/ n 5.0)) row)) (partition 5 %)))
                          :population (mapv #(/ % 5.0) census) :original (serialize original)
                          :matched (serialize matched) :interior (serialize interior)}) w))))
