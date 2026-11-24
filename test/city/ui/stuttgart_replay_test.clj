(ns city.ui.stuttgart-replay-test
  (:require [city.ui.stuttgart-replay :as replay]
            [clojure.test :refer [deftest is]]))

(deftest closure-examples-come-from-the-baseline-sample
  (let [shop {:pid 6 :purpose "store" :path [[9.1 48.7] [9.18195 48.79122]] :timestamps [510 530]}
        second-shop (assoc shop :pid 1 :timestamps [610 630])
        closed [{:lon 9.181953 :lat 48.791219}]
        sample [second-shop (assoc shop :purpose "work") shop
                (assoc-in shop [:path 1] [9.191 48.79])]
        legs (replay/closed-shopping-legs sample closed)]
    (is (= [shop second-shop] legs))
    (is (= shop (replay/shopping-example legs 505)))
    (is (= second-shop (replay/shopping-example legs 530)))
    (is (= shop (replay/shopping-example legs 640)))))
