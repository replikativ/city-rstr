(ns city.vancouver.worksites-test
  (:require [city.vancouver.worksites :as sites]
            [clojure.test :refer [deftest is]]))

(deftest exchange-applies-to-the-whole-work-spell
  (let [parts [[240 200 "stop" 0 0] [440 20 "walk" 0 1] [460 480 "stop" 1 1]
               [940 15 "walk" 1 2] [955 725 "stop" 2 2]]
        pattern (fn [parts starts] (sites/commute-pattern {"slots" ["home" "job" "home"] "parts" parts} starts))]
    (is (= {:exchange true :jobSlot 1 :legs [[0 1 20 440] [2 1 15 940]]} (pattern parts [440 940])))
    (is (false? (:exchange (pattern parts [440]))))
    (is (false? (:exchange (pattern (subvec parts 2) [940]))))))

(deftest costs-preserve-existing-feasible-legs-and-prefer-existing-sites
  (let [ws [{:legs [[1 3 5 400] [1 3 10 900]]} {:legs [[2 4 5 400] [2 4 10 900]]}]
        model {:metres {[1 3] 800 [1 4] 300 [2 4] 250 [2 3] 500} :speed 75}]
    (is (= {:siteSlots [0 1] :costs [[6 1] [nil 0]]} (sites/cost-matrix model ws)))
    (is (= [[6 1] [1 0]] (:costs (sites/cost-matrix (assoc-in model [:metres [2 3]] 200) ws))))))
