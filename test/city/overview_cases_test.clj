(ns city.overview-cases-test
  (:require [city.overview-cases :as cases]
            [clojure.data.json :as json]
            [clojure.test :refer [deftest is testing]]))

(deftest ^:data retail-comparisons
  (doseq [run (json/read-str (slurp "public/data/runs/current.json") :key-fn keyword)]
    (testing (:label run)
      (let [retail (filter :venues (cases/scenarios "public/data" run))
            baseline (last retail)
            shops (:venues baseline)]
        (if (and (= "region" (:coverage run)) (nil? (:regionalWorkers run)))
          (is (empty? retail))
          (do
            (is (seq shops))
            (is (= (count shops) (count (set (map first shops)))))
            (doseq [scenario (butlast retail)]
              (is (= (map #(take 4 %) shops) (map #(take 4 %) (:venues scenario))))
              (if (= "vancouver" (:city run))
                (let [rows (:venues scenario)
                      gained (reduce + (map last (filter #(pos? (last %)) rows)))
                      lost (- (reduce + (map last (filter #(neg? (last %)) rows))))]
                  (let [events (:visitEvents scenario)
                        minutes (map first events)
                        losses (frequencies (keep second events))]
                    (is (= gained (count events)))
                    (is (= minutes (sort minutes)))
                    (is (every? #(<= 0 % 1439) minutes))
                    (is (every? (fn [[id _ _ _ delta]]
                                  (= delta (if (= id (:openingSite scenario)) gained (- (get losses id 0))))) rows)))
                  (is (= gained (reduce + (first (:values scenario)))))
                  (is (every? (fn [[id _ _ _ delta]]
                                (let [hours (get (:hourlyVisits scenario) id)]
                                  (and (= 24 (count hours)) (= delta (reduce + hours))))) rows))
                  (is (every? (fn [hour]
                                (let [changes (map #(nth % hour) (vals (:hourlyVisits scenario)))]
                                  (<= 0 (reduce + changes))))
                              (range 24)))
                  (is (every? (fn [[_ _ _ before delta]] (<= 0 (+ before delta))) rows))
                  (is (.contains (:summary scenario) (str lost " diverted")))
                  (is (.contains (:summary scenario) (str (- gained lost) " newly feasible"))))
                (do
                  (is (some (fn [[_ _ _ base delta]] (and (number? base) (number? delta))) (:venues scenario)))
                  (is (some (fn [[_ _ _ base delta]] (and (number? base) (nil? delta))) (:venues scenario))))))))))))
