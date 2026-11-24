(ns city.vancouver.survey-zones-test
  (:require [clojure.test :refer [deftest is]]
            [city.vancouver.survey-zones :as zones]))

(deftest adult-residents-and-external-work
  (is (= [0 0 2 5 5 0] (map zones/adult-fifths [0 2 3 4 13 88])))
  (is (= 9 (zones/trip-cell true nil)))
  (is (= [10 10 0 8 10 10] (map #(zones/trip-cell false %) [-2 -1 0 8 9 nil]))))

(deftest nonwork-purpose-follows-the-endpoints
  (doseq [[a b category] [["home" "store" :other] ["restaurant" "home" :other]
                          ["other-home" "store" :nonhome] ["job" "school" :nonhome]
                          ["home" "school" nil] ["job" "home" nil] ["home" "home" nil]
                          ["store" "unknown" nil] [nil "store" nil]]]
    (is (= category (zones/other-purpose a b) (zones/other-purpose b a)))))
