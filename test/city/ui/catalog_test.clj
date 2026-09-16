(ns city.ui.catalog-test
  (:require [clojure.test :refer [deftest is testing]]
            [city.ui.catalog :as catalog]))

(def stuttgart
  {:city :stuttgart :level "stadtteil" :area 123 :year 2025
   :bbox "9.1,48.7,9.2,48.8" :kinds #{:place :licence :storefront}
   :stride 20 :entity 456})

(deftest store-request-catalogue
  (let [requests (catalog/requests stuttgart)]
    (is (= {:base :store :path "/api/areas"
            :params {:city "stuttgart" :level "stadtteil"}}
           (:areas requests)))
    (is (= {:base :store :path "/api/cells"
            :params {:city "stuttgart"}}
           (:cells requests)))
    (is (= [{:base :store :path "/api/points" :kind :licence
             :params {:kind "licence" :area "123" :year 2025}}
            {:base :store :path "/api/points" :kind :place
             :params {:kind "place" :area "123"}}
            {:base :store :path "/api/points" :kind :storefront
             :params {:kind "storefront" :area "123" :year 2025}}]
           (:points requests)))
    (is (= {:base :store :path "/api/summary" :params {:area "123"}}
           (:summary requests)))
    (is (= {:base :store :path "/api/firms"
            :params {:area "123" :year 2025}}
           (:resolved requests)))
    (is (= {:base :store :path "/api/entity/456" :params {}}
           (:entity requests)))))

(deftest simulation-request-catalogue
  (let [requests (catalog/requests stuttgart)
        viewport {:area "stuttgart" :bbox "9.1,48.7,9.2,48.8"}]
    (is (= {:base :sim :path "/sim/layers" :params {}} (:runs requests)))
    (doseq [[key path] [[:meta "/sim/meta"]
                        [:aggregates "/sim/areas"]
                        [:econ "/sim/econ"]]]
      (is (= {:base :sim :path path :params {:area "stuttgart"}}
             (get requests key))))
    (doseq [[key path] [[:visits "/sim/visits"]
                        [:stops "/sim/stops"]]]
      (is (= {:base :sim :path path :params viewport}
             (get requests key))))
    (is (= {:base :sim :path "/sim/trips"
            :params (assoc viewport :stride 20)}
           (:trips requests)))))

(deftest context-controls-availability-and-run
  (testing "Vancouver has no cell request and whole-city requests use `city`"
    (let [requests (catalog/requests
                    {:city :vancouver :level "local-area" :area nil
                     :kinds #{:poi} :year 2024 :stride 10})]
      (is (nil? (:cells requests)))
      (is (nil? (:points requests)))
      (is (nil? (:summary requests)))
      (is (= {:area "city"} (get-in requests [:meta :params])))))
  (testing "a caller-resolved published run key wins"
    (let [requests (catalog/requests (assoc stuttgart :run-key 987))]
      (is (= "987" (get-in requests [:visits :params :area])))))
  (testing "numeric string ids are accepted; whole-city store ids are not"
    (is (= "42" (get-in (catalog/requests (assoc stuttgart :area "42"))
                         [:summary :params :area])))
    (let [requests (catalog/requests (assoc stuttgart :area "stuttgart"))]
      (is (nil? (:summary requests)))
      (is (nil? (:points requests))))))

(deftest static-export-files
  (let [reqs (catalog/requests {:city :stuttgart :level "stadtteil" :run-key "stuttgart"
                                :bbox "9,48,9.3,48.9" :stride 20 :scenario "close-milaneo"
                                :area "71151" :kinds #{:storefront}})]
    (testing "every simulation layer the explorer reads has a file, whatever the viewport"
      (is (= "trips.json" (catalog/static-path (:trips reqs))))
      (is (= "revenue.json" (catalog/static-path (:revenue reqs))))
      (is (= "scenario-close-milaneo.json" (catalog/static-path (:scenario reqs))))
      (is (= "scenarios.json" (catalog/static-path (:scenarios reqs))))
      (is (= "areas-stadtteil.json" (catalog/static-path (:areas reqs))))
      (is (= "areas-stadtbezirk.json" (catalog/static-path (:districts reqs))))
      (is (= "cells.json" (catalog/static-path (:cells reqs)))))
    (testing "observed records and summaries are not in the export"
      (is (nil? (catalog/static-path (:summary reqs))))
      (is (every? nil? (map catalog/static-path (:points reqs)))))))

