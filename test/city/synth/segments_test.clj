(ns city.synth.segments-test
  "The segment split's inputs, checked against the source they come from.
   The first test is the derivation itself: the Warengruppe → class mapping was
   recovered by summing, so it is re-derived here rather than trusted."
  (:require [clojure.test :refer [deftest is testing]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [city.synth.retail :as retail]
            [city.synth.segments :as seg]))

(defn- doc
  "The retail concept's detail tables. Tests tagged ^:data need them and fail
   when they are missing; CI excludes the tag (`clojure -M:test`), and
   `clojure -M:test-data` runs them against data/derived."
  []
  (if (.exists (io/file retail/detail-path))
    (json/read-str (slurp retail/detail-path) :key-fn keyword)
    (throw (ex-info "missing data for a ^:data test" {:path retail/detail-path}))))

(defn- districts [d] (filter #(= "stadtbezirk" (:scope %)) (:entries d)))

(deftest ^:data the-warengruppe-mapping-reproduces-the-published-rollups
  (let [d (doc)]
    (let [ds (districts d)
          sum (fn [pred field]
                (reduce + 0.0 (for [e ds w (:by_warengruppe e)
                                    :when (pred (:warengruppe w))]
                                (double (or (get w field) 0.0)))))
          rollup (fn [s field] (sum #(= % (seg/rollup-names s)) field))
          parts (fn [s field] (sum #(= s (seg/warengruppe->segment %)) field))]
      (doseq [s seg/segments
              [field tol] [[:umsatz_mio_eur 0.005] [:verkaufsflaeche_m2 0.005]]]
        (let [published (rollup s field) derived (parts s field)]
          (is (pos? published))
          (is (< (Math/abs (- derived published)) (* tol published))
              (str s " " field ": derived " derived " published " published))))
      (testing "and no group is claimed by two classes or silently dropped"
        (let [named (set (keys seg/warengruppe->segment))
              all (set (for [e ds w (:by_warengruppe e)] (:warengruppe w)))
              rollups (set (vals seg/rollup-names))]
          (is (empty? (remove #(or (named %) (rollups %) (= "Sonstiges" %)) all))
              "every published group is mapped, a rollup, or Sonstiges"))))))

(deftest ^:data targets-cover-every-district-and-reconcile
  (let [d (doc)]
    (let [tg (seg/targets)
          whole (retail/targets)]
      (is (= 23 (count tg)))
      (is (= (set (keys whole)) (set (keys tg))))
      (doseq [[district rows] tg]
        (is (= #{:short :medium :long} (set (keys rows))) district)
        (doseq [[s r] rows]
          (is (pos? (double (:umsatz-eur r))) [district s])
          (is (number? (:verkaufsflaeche-m2 r)) [district s])))
      (testing "the three classes reconcile to the district total"
        (doseq [[district rows] tg
                :let [part (reduce + (map (comp double :umsatz-eur val) rows))
                      total (double (:umsatz-eur (whole district)))]]
          (is (< (Math/abs (- part total)) (* 0.05 total))
              (str district ": classes " part " total " total))))
      (testing "citywide the classes are the shape the thirteenth pass measured"
        (let [mio (fn [s] (/ (reduce + (map #(double (:umsatz-eur (get % s))) (vals tg))) 1e6))]
          (is (< 2100 (mio :short) 2250))
          (is (< 1280 (mio :medium) 1380))
          (is (< 930 (mio :long) 1030)))))))

(deftest ^:data potential-shares-are-a-distribution
  (do (doc)
    (let [ps (seg/potential-shares)]
      (is (= 23 (count ps)))
      (doseq [[district rows] ps]
        (is (< (Math/abs (- 1.0 (reduce + (vals rows)))) 1e-9) district)
        (is (every? pos? (vals rows)) district))
      (testing "food is the largest share of the money everywhere"
        (doseq [[district rows] ps]
          (is (= :short (key (apply max-key val rows))) district))))))

(deftest the-classifier-covers-the-vocabulary-the-city-actually-uses
  ;; The most common retail categories inside the Stuttgart bounding box, with
  ;; the class each must receive. If Overture's vocabulary shifts, this is the
  ;; test that says so rather than the raking silently absorbing it.
  (let [expect {"grocery_store" :short "bakery" :short "pharmacy" :short
                "butcher_shop" :short "convenience_store" :short "liquor_store" :short
                "newspaper_and_magazines_store" :short "bookstore" :short
                "flowers_and_gifts_shop" :short "florist" :short "pet_store" :short
                "clothing_store" :medium "womens_clothing_store" :medium
                "mens_clothing_store" :medium "childrens_clothing_store" :medium
                "boutique" :medium "shoe_store" :medium "bicycle_shop" :medium
                "toy_store" :medium "home_goods_store" :medium
                "furniture_store" :long "building_supply_store" :long
                "home_improvement_store" :long "hardware_store" :long
                "electronics" :long "computer_store" :long "mobile_phone_store" :long
                "appliance_store" :long "jewelry_store" :long "carpet_store" :long
                "lighting_store" :long "mattress_store" :long "antique_store" :long}]
    (doseq [[category s] expect]
      (is (= s (seg/segment-of category)) category)))
  (testing "the retail flag's false positives are named, not classified"
    (doseq [c ["marketing_agency" "internet_marketing_service" "marketing_consultant"
               "coffee_shop" "ice_cream_shop" "auto_parts_and_supply_store"]]
      (is (= :not-retail (seg/segment-of c)) c)))
  (testing "a multi-assortment venue is :mixed, not forced into one class"
    (doseq [c ["shopping" "shopping_center" "department_store" "discount_store"]]
      (is (= :mixed (seg/segment-of c)) c)))
  (testing "an unknown category is nil, so the caller must decide"
    (is (nil? (seg/segment-of "pawn_shop")))
    (is (nil? (seg/segment-of nil))))
  (testing "carpet is not a pet shop"
    (is (= :long (seg/segment-of "carpet_store")))
    (is (= :short (seg/segment-of "pet_store")))))

(deftest split-weights-always-conserve-a-firm
  (let [shares {:short 0.55 :medium 0.16 :long 0.29}
        sum #(reduce + (vals %))]
    (testing "a classified firm puts all its weight in its class"
      (is (= {:short 1.0} (seg/split-weights "bakery" shares)))
      (is (= {:medium 1.0} (seg/split-weights "shoe_store" shares)))
      (is (= {:long 1.0} (seg/split-weights "furniture_store" shares))))
    (testing "a mixed or unknown firm takes the district's measured mix"
      (is (= shares (seg/split-weights "department_store" shares)))
      (is (= shares (seg/split-weights "pawn_shop" shares))))
    (testing "every weight vector sums to one"
      (doseq [c ["bakery" "shoe_store" "furniture_store" "department_store" "pawn_shop"]]
        (is (< (Math/abs (- 1.0 (sum (seg/split-weights c shares)))) 1e-12) c)))
    (testing "a non-retail firm carries no retail floor area at all"
      (is (nil? (seg/split-weights "marketing_agency" shares)))
      (is (nil? (seg/split-weights "coffee_shop" shares))))))

(deftest ^:data the-shares-a-real-district-produces-are-a-usable-mix
  (doc)
  (let [row (val (first (seg/potential-shares)))]
    (is (< (Math/abs (- 1.0 (reduce + (vals (seg/split-weights "shopping" row))))) 1e-9))))

(deftest attractiveness-is-raked-to-the-published-floor-area-of-each-class
  (let [;; two districts, six firms: one per class, a department store, a
        ;; marketing agency the retail flag wrongly admits, and an unknown.
        cats ["grocery_store" "shoe_store" "furniture_store"
              "department_store" "marketing_agency" "pawn_shop"]
        areas ["A" "A" "A" "B" "B" "B"]
        firms {:n 6
               :eid (long-array [1 2 3 4 5 6])
               :la (into-array String areas)
               :category (into-array String cats)
               :retail (int-array 6 1)}
        sizes {1 100.0 2 200.0 3 300.0 4 400.0 5 500.0 6 600.0}
        tg {"A" {:short {:verkaufsflaeche-m2 1000.0 :kaufkraft-eur 55.0}
                 :medium {:verkaufsflaeche-m2 2000.0 :kaufkraft-eur 16.0}
                 :long {:verkaufsflaeche-m2 3000.0 :kaufkraft-eur 29.0}}
            "B" {:short {:verkaufsflaeche-m2 700.0 :kaufkraft-eur 50.0}
                 :medium {:verkaufsflaeche-m2 800.0 :kaufkraft-eur 20.0}
                 :long {:verkaufsflaeche-m2 900.0 :kaufkraft-eur 30.0}}}
        r (seg/attract-by-segment firms :sizes sizes :st->bez {} :tg tg)]
    (is (some? r))
    (testing "each district and class sums to exactly its published floor area"
      (doseq [[d s target] [["A" :short 1000.0] ["A" :medium 2000.0] ["A" :long 3000.0]
                            ["B" :short 700.0] ["B" :medium 800.0] ["B" :long 900.0]]]
        (let [^doubles a (get r s)
              got (reduce + (for [j (range 6) :when (= d (nth areas j))] (aget a j)))]
          (is (< (Math/abs (- got target)) 1e-9) (str d " " s ": " got " vs " target)))))
    (testing "a single-class firm carries area in its class only"
      (is (pos? (aget ^doubles (get r :short) 0)))
      (is (zero? (aget ^doubles (get r :medium) 0)))
      (is (zero? (aget ^doubles (get r :long) 0))))
    (testing "a department store carries area in all three"
      (is (every? #(pos? (aget ^doubles (get r %) 3)) seg/segments)))
    (testing "a wrongly flagged non-retail firm carries none"
      (is (every? #(zero? (aget ^doubles (get r %) 4)) seg/segments)))
    (testing "an unknown category is spread, not dropped"
      (is (every? #(pos? (aget ^doubles (get r %) 5)) seg/segments)))
    (testing "coverage counts only the firms a rule named"
      (is (= 6 (:flagged r)))
      (is (< (Math/abs (- (/ 3.0 6.0) (:coverage r))) 1e-12)))))
