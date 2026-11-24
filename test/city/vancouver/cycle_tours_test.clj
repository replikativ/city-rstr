(ns city.vancouver.cycle-tours-test
  (:require [clojure.test :refer [deftest is]]
            [city.vancouver.cycle-tours :refer [tours]]))

(def template {"slots" ["home" "store" "restaurant" "home"]
               "parts" [[240 40 "stop" 0 0] [280 10 "car-driver" 0 1] [290 20 "stop" 1 1]
                        [310 8 "car-driver" 1 2] [318 22 "stop" 2 2] [340 10 "car-driver" 2 3]
                        [350 1330 "stop" 3 3]]})
(def diary {"episodes" [[240 40 "media" "home"] [280 10 "travel" "car-driver"]
                        [290 20 "shopping" "store"] [310 8 "travel" "car-driver"]
                        [318 22 "eating" "restaurant"] [340 10 "travel" "car-driver"] [350 1330 "sleep" "home"]]})
(def purposes {280 "Shopping" 310 "Dining" 340 "Return home"})

(deftest whole-home-tours-with-recorded-travel
  (is (= [{:purpose "Shopping" :legs [1 3 5]}] (tours template diary purposes)))
  (is (empty? (tours (update template "parts" pop) diary purposes)))
  (is (empty? (tours (update template "parts" #(vec (concat (take 3 %) (drop 4 %)))) diary purposes)))
  (is (empty? (tours template (assoc-in diary ["episodes" 1 3] "walk") purposes)))
  (is (empty? (tours template (assoc-in diary ["episodes" 4 2] "childcare") purposes)))
  (is (empty? (tours template diary (assoc purposes 310 "Other or unclear")))))
