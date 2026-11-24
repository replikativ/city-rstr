(ns city.vancouver.dispatch-test
  (:require [city.vancouver.dispatch :refer [simulate]]
            [clojure.test :refer [deftest is]]))

(defn network [routes]
  (fn [from to budget]
    (let [seconds (if (= from to) 0 (get routes [from to]))]
      (when (and (some? seconds) (<= seconds budget)) seconds))))

(defn request [id hail due pickup destination access loaded egress]
  {:id id :hail hail :due due :pickup pickup :destination destination
   :access access :loaded loaded :egress egress})

(deftest successive-rides-use-one-vehicle-without-overlap
  (let [routes (network {[0 1] 4 [2 3] 2})
        a (request 0 0 19 1 2 3 10 1)
        b (request 1 2 30 3 4 3 5 2)
        c (request 2 18 25 3 5 4 5 1)
        d (request 3 21 45 5 0 0 4 0)]
    (is (= [{:id 0 :vehicle 0 :from 0 :depart 0 :curb 4 :board 4 :drop 14 :arrive 15}
            {:id 1 :vehicle 0 :from 2 :depart 14 :curb 16 :board 16 :drop 21 :arrive 23}
            {:id 2 :miss "diary"} {:id 3 :miss "dispatch"}]
           (simulate [d b c a] [0] 20 (constantly 0) routes)))))

(deftest curb-wait-and-patience-accounting
  (let [r (request 0 10 50 3 4 7 12 2)
        travel (network {[1 3] 5 [2 3] 1})]
    (is (= {:vehicle 1 :from 2 :depart 10 :curb 11 :board 17 :drop 29 :arrive 31 :id 0}
           (first (simulate [r] [1 2] 20 (constantly 0) travel))))
    (is (= [{:id 0 :miss "diary"}] (simulate [r] [1 2] 6 (constantly 0) travel)))))
