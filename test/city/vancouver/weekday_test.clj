(ns city.vancouver.weekday-test
  (:require [clojure.test :refer [deftest is]]
            [city.vancouver.weekday :as weekday]
            [city.vancouver.shopping :as shopping]
            [city.synth.timeuse :as timeuse]
            [city.vancouver.household :as household])
  (:import [java.util Random]))

(defn- diary [weight minutes]
  {:weight weight :type [:worker :a25-34 :women]
   :chain [{:act :sleep :start 240 :dur 1170}
           {:act :childcare :start 1410 :dur minutes}
           {:act :other :start (+ 1410 minutes) :dur (- 270 minutes)}]})

(deftest weighted-complete-days
  (let [a (diary 3 60) b (diary 1 120)
        pools {:a25-34 {:fit [a b] :holdout [b]}
               :a75+ {:fit [(diary 2 90)] :holdout [b]}}
        domain {:areas 1 :age-counts {:a25-34 2 :a75+ 1}}
        result (get-in (weekday/weekday-baseline {"area" domain} pools)
                       [:areas "area" :minutes-per-resident-weekday])
        care (:childcare result)]
    (is (== 80 (:model care)))
    (is (== -40 (:error care)))
    (is (== 30 (nth (:model-by-clock-hour care) 23)))
    (is (every? #(== 60 %) (apply map + (map :model-by-clock-hour (vals result)))))
    (is (== 1440 (reduce + (map :holdout (vals result)))))
    (is (contains? #{(:chain a) (:chain b)} (weekday/draw-weekday pools :a25-34 (Random. 2))))))

(deftest respondent-split-and-coverage
  (let [ds (into {} (for [i (range 10)] [(str i) (diary 1 (+ 60 i))]))
        pools (weekday/split-diaries ds)
        {:keys [fit holdout]} (:a25-34 pools)]
    (is (= 2 (count holdout)))
    (is (= 8 (count fit)))
    (is (not-any? (set holdout) fit))
    (is (= pools (weekday/split-diaries (into (sorted-map) ds))))
    (is (thrown? clojure.lang.ExceptionInfo
                 (weekday/split-diaries (assoc-in ds ["0" :chain 1 :start] 1411))))))

(deftest household-roster-and-denominator
  (is (true? (timeuse/child-under-15 {:CHH0004C "9" :CHH0514C "1"})))
  (is (false? (timeuse/child-under-15 {:CHH0004C "0" :CHH0514C "0"})))
  (is (nil? (timeuse/child-under-15 {:CHH0004C "9" :CHH0514C "0"})))
  (let [mix (household/composition [[{:age 2 :weight 100} {:age 3 :weight 2} {:age 4 :weight 4}]
                                    [{:age 3 :weight 3}]
                                    [{:age 3 :weight 1} {:age 88 :weight 1}]])]
    (is (= {:with-child 6.0 :without-child 3.0 :unknown 1.0 :share-with-child (/ 6.0 9.0)}
           (:a15-24 mix)))))

(deftest household-conditioning
  (let [with-child (assoc (diary 1 120) :child-under-15? true)
        without-child (assoc (diary 1 60) :child-under-15? false)
        pools {:a25-34 {:fit [with-child without-child] :holdout [with-child without-child]}
               :a75+ {:fit [without-child] :holdout [with-child]}}
        area {"test" {:age-counts {:a25-34 1}}}
        metro {:a25-34 {:share-with-child 1.0} :a75+ {:share-with-child 0.5}}
        result (weekday/household-comparison area pools metro)
        care (get-in result [:projected-minutes-per-resident-weekday "test" :childcare])]
    ;; One effective matching donor gets 1/6 of the mass. The age-only mean is 90.
    (is (== 95 (:total care)))
    (is (== 95 (reduce + (:by-clock-hour care))))
    (is (zero? (get-in result [:fit-by-age :a75+ :with-child :share])))
    (is (= (:chain without-child) (weekday/draw-weekday pools :a75+ true (Random. 1))))
    (is (= (weekday/draw-weekday pools :a25-34 (Random. 1))
           (weekday/draw-weekday pools :a25-34 nil (Random. 1))))
    (is (< (get-in result [:urban-bc-holdout-rmse-minutes :childcare :household-rmse])
           (get-in result [:urban-bc-holdout-rmse-minutes :childcare :age-only-rmse])))
    (is (nil? (:projected-minutes-per-resident-weekday (weekday/household-comparison area pools nil))))))

(deftest shopping-codes-and-location
  (let [row {:ACTIVITY "0260" :LOCATION "3306" :STARTMIN "1425" :DURATION "35"}
        episode #(timeuse/diary-episode (assoc row :TUI_01 %))
        goods (episode "0261")
        elsewhere (assoc goods :loc :business)
        travel (timeuse/diary-episode (assoc row :ACTIVITY "0400" :TUI_01 "0409"))
        chain [elsewhere travel (episode "0262") (episode "0264") (episode "0269") goods]]
    (is (= [:goods-at-store :in-person-services :online :purchase-research :unspecified :unspecified]
           (mapv (comp shopping/category episode) ["0261" "0262" "0263" "0264" "0269" nil])))
    (is (= :goods-elsewhere-or-unknown (shopping/category elsewhere)))
    (is (= [goods] (shopping/candidate-episodes chain)))
    (is (= :unspecified (shopping/category {:act :shopping :loc :store})))
    (is (nil? (shopping/category travel)))
    (is (= [1425 35] ((juxt :start :dur) goods)))))

(deftest shopping-episodes-and-minutes
  (let [goods {:act :shopping :shopping-detail :in-person-goods :loc :store :start 1425 :dur 35}
        online (assoc goods :shopping-detail :online :start 800 :dur 15)
        a {:weight 3 :chain [online goods] :child-under-15? true}
        b {:weight 1 :chain [] :child-under-15? true}
        pools {:a25-34 {:fit [a b] :holdout [b]}}
        domain {"area" {:areas 1 :age-counts {:a25-34 8}}}
        area (get-in (weekday/weekday-baseline domain pools) [:areas "area"])
        metro {:a25-34 {:share-with-child 0.25}}
        h (get-in (weekday/household-comparison domain pools metro)
                  [:projected-shopping-per-resident-weekday "area"])
        {:keys [age-only holdout]} (:shopping-per-resident-weekday area)]
    (is (= {:episodes 0.75 :minutes 26.25} (:goods-at-store age-only)))
    (is (= age-only h))
    (is (zero? (get-in holdout [:goods-at-store :episodes])))
    (is (== (get-in area [:minutes-per-resident-weekday :shopping :model])
            (reduce + (map :minutes (vals age-only)))))))
