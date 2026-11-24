(ns city.vancouver.cycle-tour-clock-test
  (:require [city.vancouver.cycle-tour-clock :as clock]
            [clojure.test :refer [deftest is]]))

(deftest projection-groups-whole-residents-and-keeps-intervals-half-open
  (let [out (fn [i z access start] [0 i 1 z "Shopping" [[start 2 0 1] [(+ start 4) 2 1 0]] access])
        rows [(out 0 "east" true 240) (out 1 "east" true 240)
              (out 2 "west" false 240) (out 2 "west" false 1674)]
        {:keys [agents groups access ride]} (clock/project ["west" "east"] rows "jvm")]
    (is (= [3 2] [agents groups]))
    (is (= [[0 2] [0 2] [0 0] [0 0] [0 2] [0 2]] (subvec access 0 6)))
    (is (= [1 2] (first ride)))
    (is (= [1 0] (peek ride)))
    (is (= [0 0] (peek access)))
    (is (thrown? clojure.lang.ExceptionInfo (clock/project ["west"] [(out 1 "west" true 240) (out 1 "west" true 241)] "jvm")))))
