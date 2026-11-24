(ns city.vancouver.departure-clock-test
  (:require [city.vancouver.departure-clock :refer [variants]]
            [clojure.test :refer [deftest is]]))

(deftest preserves-a-shift-end-and-travel-budget-at-an-hour-boundary
  (let [parts [[240 780 "stop" 0 0] [1020 30 "car-passenger" 0 1] [1050 630 "stop" 1 1]]
        episodes [[240 780 "paid-work" "work-or-school"] [1020 30 "travel" "car-passenger"]
                  [1050 15 "eating" "home"] [1065 615 "sleep" "home"]]
        options (variants {"parts" parts} {"episodes" episodes} 7)
        last-option (peek options)
        result (get-in last-option [:diary "episodes"])]
    (is (= [[240 780 "paid-work" "work-or-school"] [1020 7 "waiting" "work-or-school"]
            [1027 30 "travel" "car-passenger"] [1057 8 "eating" "home"] [1065 615 "sleep" "home"]]
           result))
    (is (= [[240 787 "stop" 0 0] [1027 30 "car-passenger" 0 1] [1057 623 "stop" 1 1]]
           (get-in last-option [:day "parts"])))
    (is (nil? (first options)))))

(deftest shared-stop-has-enough-slack-for-its-two-neighbouring-trips
  (let [parts [[240 300 "stop" 0 0] [540 15 "walk" 0 1] [555 10 "stop" 1 1]
               [565 15 "walk" 1 2] [580 1100 "stop" 2 2]]
        episodes [[240 300 "sleep" "home"] [540 15 "travel" "walk"] [555 10 "eating" "restaurant"]
                  [565 15 "travel" "walk"] [580 1100 "paid-work" "work-or-school"]]]
    (doseq [option (remove nil? (variants {"parts" parts} {"episodes" episodes} 7))]
      (let [ep (get-in option [:diary "episodes"])]
        (is (>= (second (first (filter #(= "eating" (nth % 2)) ep))) 5))
        (is (= (map #(+ (first %) (second %)) ep) (concat (map first (rest ep)) [1680])))))))
