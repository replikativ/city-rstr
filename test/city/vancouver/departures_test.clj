(ns city.vancouver.departures-test
  (:require [city.vancouver.departures :as departures]
            [clojure.test :refer [deftest is]]))

(deftest census-profile-boundaries
  (is (= [5 0 1 2 3 4 4 5 5 5]
         (mapv departures/profile-band [299 300 360 420 480 540 719 720 960 1679]))))

(deftest first-work-journey
  (let [template {"slots" ["home" "store" "job" "home" "job"]
                  "parts" [[240 60 "stop" 0 0] [300 10 "walk" 0 1] [310 10 "stop" 1 1]
                           [320 10 "walk" 1 2] [330 30 "stop" 2 2] [360 10 "walk" 2 3]
                           [370 30 "stop" 3 3] [400 10 "bike" 3 4] [410 30 "stop" 4 4]]}
        job (fn [t] [t 30 "paid-work" "work-or-school"])
        tour (fn [t eps] (departures/first-tour t {"episodes" eps}))]
    (is (= {:kind :via :minute 300} (tour template [(job 330) (job 410)])))
    (is (= {:kind :direct :minute 400} (tour template [(job 410)])))
    (is (= {:kind :untraced} (tour (update template "parts" subvec 1) [(job 330) (job 410)])))
    (is (= {:kind :untraced} (tour (update template "parts" #(vec (concat (take 3 %) (drop 4 %)))) [(job 330)])))
    (is (= {:kind :noJobStop} (tour template [[240 30 "paid-work" "home"]])))))
