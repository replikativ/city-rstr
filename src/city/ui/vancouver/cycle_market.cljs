(ns city.ui.vancouver.cycle-market
  "Join shopping occasions from each eligible mode, preserving resident and stop identities."
  (:require [goog.object :as obj]))

(defn- index-rows [occasions rows include?]
  (let [indices (js/Int32Array. (alength rows))]
    (.fill indices -1)
    (.forEach rows (fn [row j]
                     (when (include? row)
                       (aset indices j (alength occasions))
                       (.push occasions row))))
    indices))

(defn- append-bikes! [rows indices candidates]
  (doseq [[j minutes] candidates :let [i (aget indices j)] :when (>= i 0)]
    (.push rows #js [i minutes])))

(defn combine [catalog mode]
  (let [b (aget catalog "bicycle") walk (aget catalog "occasions") local (aget catalog "localWalk")
        take? (fn [group] (or (= group "diary") (= mode "ride") (and (= mode "access") (= group "access"))))
        occasions (.slice walk)
        indices (index-rows occasions (aget b "occasions") #(take? (aget % 17)))
        nbikes (- (alength occasions) (alength walk))
        walkers (when local
                  (index-rows occasions (aget local "occasions")
                              (fn [r] (let [overlap (aget r 18)]
                                        (case mode "ride" (zero? overlap) "access" (< overlap 2) true)))))
        sites (.map (aget catalog "sites")
                    (fn [site i]
                      (let [regular (.slice (aget site "changes")) late (.slice (aget site "afterHours"))]
                        (append-bikes! regular indices (aget (aget b "changes") i))
                        (append-bikes! late indices (aget (aget b "afterHours") i))
                        (when local
                          (doseq [[j metres] (obj/getValueByKeys local "sites" (aget site "id") "visits")
                                  :let [k (aget walkers j)] :when (>= k 0)]
                            (let [r (aget occasions k) s (aget r 3)
                                  within? (and (>= s 480) (<= (+ s (aget r 4)) 1200))]
                              (.push (if within? regular late) #js [k (/ (* 2 metres) (aget local "speed"))]))))
                        (js/Object.assign #js {} site #js {:changes regular :afterHours late}))))
        qualifying (reduce + 0 (for [group (js/Object.keys (aget b "cohorts")) :when (take? group)]
                                 (obj/getValueByKeys b "cohorts" group "qualifying")))]
    (js/Object.assign #js {} catalog #js {:occasions occasions :sites sites :bikeQualifying qualifying
                                         :bikeOccasions nbikes})))
