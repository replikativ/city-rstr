(ns city.synth.retail-test
  "Measured floor area as the store kernel's size term: footprints for shape,
   the census for level, and the retail concept's detail tables read into
   district rows. No data needed; every input is passed in."
  (:require [clojure.test :refer [deftest is testing]]
            [city.synth.retail :as retail]
            [city.synth.segments :as seg]))

(deftest footprints-are-raked-to-the-census-floor-area
  ;; firm 3 has no building (takes district A's median, 300) and is not
  ;; retail (so it does not enter A's sum, but is scaled with A)
  (let [firms {:n 4 :eid (long-array [1 2 3 4]) :la (into-array String ["A" "A" "A" "B"])
               :retail (int-array [1 1 0 1])}
        r (retail/attract firms :sizes {1 100.0 2 300.0 4 50.0} :census {"A" 800.0 "B" 100.0} :st->bez {})]
    (is (= [200.0 600.0 600.0 100.0] (vec (:attract r))))
    (is (= 3 (:matched r)))
    (is (= 2 (:districts-raked r)))))

(deftest a-firm-with-no-footprint-takes-the-city-median-when-its-district-has-none
  (let [firms {:n 3 :eid (long-array [1 2 3]) :la (into-array String ["A" "A" "B"])}
        f (:filled (retail/filled-footprints firms {1 10.0 2 30.0} (retail/district-fn firms {})))]
    (is (= [10.0 30.0 30.0] (vec f)))))

(def detail-doc
  {:entries [{:scope "stadtbezirk" :name "Stuttgart-Mitte"
              :total {:umsatz_mio_eur 1900.0 :kaufkraft_mio_eur 180.0 :zentralitaet 10.54
                      :verkaufsflaeche_m2 300000 :betriebe 1000}
              :by_warengruppe [{:warengruppe "Überwiegend kurzfristiger Bedarf" :umsatz_mio_eur 500.0
                                :kaufkraft_mio_eur 90.0 :verkaufsflaeche_m2 80000 :betriebe 400 :zentralitaet 5.5}
                               {:warengruppe "Überwiegend mittelfristiger Bedarf" :umsatz_mio_eur 700.0
                                :kaufkraft_mio_eur 30.0 :verkaufsflaeche_m2 120000 :betriebe 300 :zentralitaet 23.3}
                               {:warengruppe "Überwiegend langfristiger Bedarf" :umsatz_mio_eur 400.0
                                :kaufkraft_mio_eur 60.0 :verkaufsflaeche_m2 100000 :betriebe 300 :zentralitaet 6.7}
                               {:warengruppe "Bekleidung" :umsatz_mio_eur 450.0}]}
             {:scope "zentrum" :name "City"}]})

(deftest the-detail-tables-read-into-district-rows
  (with-redefs [retail/read-detail (fn [_] detail-doc)]
    (testing "district totals"
      (is (= {"Mitte" {:umsatz-eur 1.9e9 :kaufkraft-eur 1.8e8 :zentralitaet 10.54
                       :verkaufsflaeche-m2 300000 :betriebe 1000}}
             (retail/targets "any"))))
    (testing "the three class rollups, individual groups ignored"
      (let [tg (seg/targets "any")]
        (is (= ["Mitte"] (keys tg)))
        (is (= #{:short :medium :long} (set (keys (tg "Mitte")))))
        (is (= 7.0e8 (get-in tg ["Mitte" :medium :umsatz-eur])))
        (is (= 100000 (get-in tg ["Mitte" :long :verkaufsflaeche-m2])))))))
