(ns city.web-test
  (:require [clojure.test :refer [deftest is testing]]
            [city.store :as store]
            [city.web :as web]
            [datahike.api :as d]))

(def ^:private cell-schema
  [{:db/ident :area/city :db/valueType :db.type/keyword
    :db/cardinality :db.cardinality/one}
   {:db/ident :area/level :db/valueType :db.type/keyword
    :db/cardinality :db.cardinality/one}
   {:db/ident :area/code :db/valueType :db.type/string
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/kind :db/valueType :db.type/keyword
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/name :db/valueType :db.type/string
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/geometry :db/valueType :db.type/string
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/area :db/valueType :db.type/ref
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/lon :db/valueType :db.type/double
    :db/cardinality :db.cardinality/one}
   {:db/ident :entity/lat :db/valueType :db.type/double
    :db/cardinality :db.cardinality/one}
   {:db/ident :cell/population :db/valueType :db.type/long
    :db/cardinality :db.cardinality/one}
   {:db/ident :cell/rent :db/valueType :db.type/double
    :db/cardinality :db.cardinality/one}])

(def ^:private two-city-cells
  [{:db/id -1 :area/city :stuttgart :entity/name "Stuttgart A"}
   {:db/id -2 :area/city :vancouver :entity/name "Vancouver A"}
   {:entity/kind :cell :entity/area -1
    :entity/lon 9.15 :entity/lat 48.78
    :cell/population 17 :cell/rent 12.5}
   {:entity/kind :cell :entity/area -2
    :entity/lon -123.1 :entity/lat 49.26
    :cell/population 29 :cell/rent 18.0}])

(defn- without-eid [feature-collection]
  (mapv #(dissoc (:properties %) :eid :area-eid) (:features feature-collection)))

(deftest cells-belong-to-the-requested-city
  (let [config {:store {:backend :memory :id (random-uuid)}
                :schema-flexibility :write
                :attribute-refs? false
                :max-string-length 0}]
    (d/create-database config)
    (let [conn (d/connect config)]
      (try
        (d/transact conn cell-schema)
        (d/transact conn two-city-cells)
        (with-redefs [store/db #(d/db conn)]
          (testing "Stuttgart is the default and excludes Vancouver cells"
            (let [result (web/cells {})]
              (is (= [[9.15 48.78]]
                     (mapv #(get-in % [:geometry :coordinates])
                           (:features result))))
              (is (= [{:population 17 :rent 12.5 :area-name "Stuttgart A"}]
                     (without-eid result)))))
          (testing "an explicit city selects only cells joined to that city"
            (let [result (web/cells {:city "vancouver"})]
              (is (= [[-123.1 49.26]]
                     (mapv #(get-in % [:geometry :coordinates])
                           (:features result))))
              (is (= [{:population 29 :rent 18.0 :area-name "Vancouver A"}]
                     (without-eid result))))))
        (finally
          (d/release conn)
          (d/delete-database config))))))

(deftest areas-aggregate-children-in-bulk
  (let [config {:store {:backend :memory :id (random-uuid)}
                :schema-flexibility :write
                :attribute-refs? false
                :max-string-length 0}
        polygon "{\"type\":\"Polygon\",\"coordinates\":[[[9.0,48.0],[9.1,48.0],[9.1,48.1],[9.0,48.0]]]}"
        data [{:db/id -1 :area/city :stuttgart :area/level :stadtteil
               :area/code "S-A" :entity/name "Stuttgart A" :entity/geometry polygon}
              {:db/id -2 :area/city :stuttgart :area/level :stadtteil
               :area/code "S-EMPTY" :entity/name "Stuttgart Empty" :entity/geometry polygon}
              {:db/id -3 :area/city :vancouver :area/level :stadtteil
               :area/code "V-X" :entity/name "Other City" :entity/geometry polygon}
              {:entity/kind :cell :entity/area -1 :cell/population 11}
              {:entity/kind :cell :entity/area -1 :cell/population 11}
              {:entity/kind :storefront :entity/area -1}
              {:entity/kind :place :entity/area -1}
              {:entity/kind :cell :entity/area -3 :cell/population 99}]]
    (d/create-database config)
    (let [conn (d/connect config)]
      (try
        (d/transact conn cell-schema)
        (d/transact conn data)
        (with-redefs [store/db #(d/db conn)]
          (let [features (:features (web/areas {:city "stuttgart" :level "stadtteil"}))
                by-name (into {} (map (juxt #(get-in % [:properties :name]) :properties) features))]
            (testing "only requested-city areas are returned"
              (is (= #{"Stuttgart A" "Stuttgart Empty"} (set (keys by-name)))))
            (testing "counts are grouped by area and kind"
              (is (= {"cell" 2 "storefront" 1 "place" 1}
                     (:counts (by-name "Stuttgart A")))))
            (testing "equal population values remain distinct cell contributions"
              (is (= 22 (:population (by-name "Stuttgart A")))))
            (testing "an area without children retains the old empty values"
              (is (= {} (:counts (by-name "Stuttgart Empty"))))
              (is (nil? (:population (by-name "Stuttgart Empty")))))))
        (finally
          (d/release conn)
          (d/delete-database config))))))
