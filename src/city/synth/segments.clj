(ns city.synth.segments
  "Retail demand segments: the split that lets one city have both a dominant
   centre and short shopping trips.

   One destination kernel cannot reproduce Stuttgart. The retail concept puts
   42 % of the city's turnover in Mitte, and the mobility survey puts the mean
   shopping trip at 3.6 km door to door. A single Huff kernel asked to explain
   both must either send residents far enough to fill the centre, which breaks
   the trip length, or keep them local, which empties the centre. Measured on a
   single-class posterior: every θ the turnover likes implies 4.4 km trips, and
   every θ near the observed distance misplaces twice as much of the retail
   euro.

   The resolution is published, and it is not a new mechanism. The EZK splits
   every district into three demand classes, and they behave nothing alike:

   | class | turnover M € | resident potential M € | city Z | Mitte Z |
   |---|---|---|---|---|
   | `:short` kurzfristiger Bedarf | 2,168.7 | 2,443.1 | 0.89 | 4.49 |
   | `:medium` mittelfristiger Bedarf | 1,331.7 | 732.5 | 1.82 | 36.72 |
   | `:long` langfristiger Bedarf | 979.8 | 1,356.8 | 0.72 | 8.17 |

   Food is local and is most of the *trips*; clothing is a rare trip to the
   centre and is 38 % of Mitte's turnover. Give each class its own kernel and
   its own share of the money, and both observations can hold at once: 69
   turnover observations against 9 parameters, where there are now 23 against 3.

   **Money and trips split differently, and that is the point.** A household
   makes many small food trips and few large clothing trips. The money split
   comes from `potential-shares` below, measured per district. The trip split
   is a separate quantity that must come from the mobility survey's purposes,
   and it is deliberately *not* in this namespace: it belongs to the diary
   process, not to the venue set.

   ## The class of a Warengruppe is derived, not assumed

   The source publishes the three rollups and eighteen individual groups but
   states no membership. `warengruppe->segment` was recovered by summing: with
   the mapping below the individual groups reproduce each published rollup to
   0.2 % of turnover and 0.2 % of floor area over the 23 districts. Two groups
   are counter-intuitive and were found this way rather than guessed —
   `Uhren/Schmuck` and `Medizinische und orthopädische Artikel` are
   *langfristig*, not mittelfristig. Putting them where intuition suggests left
   both classes wrong by 187 M €, which is exactly their combined turnover.

   `Sonstiges` belongs to no class: 4.6 M € of turnover against 50.0 M € of
   potential citywide. It is dropped, and `targets` says so.

   ## What the classifier reaches

   Measured 2026-09-15 over the 5,268 places inside the Stuttgart bounding box
   that `city.sim.world/retail-place-re` flags as retail:

   | outcome | places | |
   |---|---|---|
   | one class | 4,170 | 79.2 % |
   | `:mixed` | 546 | 10.4 % |
   | `:not-retail` | 482 | 9.1 % |
   | unknown | 70 | 1.3 % |

   98.7 % therefore get a determinate treatment, and the last 1.3 % is a long
   tail of one- and two-place categories that `split-weights` resolves against
   the district mix rather than dropping. The `:not-retail` figure is not
   noise: it is the count of places the existing retail flag wrongly admits,
   and the destination kernel can currently send a shopper to every one of
   them."
  (:require [clojure.string :as str]
            [city.synth.retail :as retail]))

(def segments
  "The three classes, in the order the source lists them: soonest-needed first."
  [:short :medium :long])

(def rollup-names
  {:short "Überwiegend kurzfristiger Bedarf"
   :medium "Überwiegend mittelfristiger Bedarf"
   :long "Überwiegend langfristiger Bedarf"})

(def warengruppe->segment
  "Which class each published Warengruppe rolls up into. Verified against the
   source's own rollup rows; see the namespace docstring."
  {"Nahrungs- und Genussmittel" :short
   "Gesundheit und Körperpflege" :short
   "Blumen (Indoor)/Zoo" :short
   "PBS/Zeitungen/Zeitschriften/Bücher" :short
   "Bekleidung" :medium
   "Schuhe/Lederwaren" :medium
   "Sport und Freizeit" :medium
   "Spielwaren/Hobbyartikel" :medium
   "GPK/Haushaltswaren" :medium
   "Möbel" :long
   "Wohneinrichtung" :long
   "Elektro/Leuchten" :long
   "Elektronik/Multimedia" :long
   "Baumarktsortimente" :long
   "Gartenmarktsortimente" :long
   "Uhren/Schmuck" :long
   "Medizinische und orthopädische Artikel" :long})

;; ---- the firm's class, from its category ------------------------------------------------

(def not-retail
  "Categories the retail flag catches that the retail census does not count.

   `city.sim.world/retail-place-re` matches on `market`, which also matches
   **marketing**: 132 marketing agencies, internet marketing services and
   marketing consultants inside the Stuttgart bounding box are currently
   flagged as shops the destination kernel can send someone to. It also matches
   on `shop`, which catches gastronomy — coffee shops, ice cream shops,
   sandwich shops — that belongs to the `:food` class and is already counted
   there. Motor trade is excluded because the census's Warengruppen do not
   include it."
  #{"marketing_agency" "internet_marketing_service" "marketing_consultant"
    "telemarketing_services" "market_research_consultant" "marketing"
    "coffee_shop" "ice_cream_shop" "sandwich_shop" "juice_and_smoothie_shop"
    "auto_parts_and_supply_store" "auto_body_shop" "tire_shop" "car_wash"
    "motorcycle_dealer" "car_dealer" "wholesale_store"
    ;; trade counters and workshops, not shops a household chooses between
    "machine_shop" "computer_hardware_company" "print_shop" "body_shop"
    "repair_shop" "welding_shop"})

(def mixed-assortment
  "Categories that genuinely sell across all three classes. A department store
   is not a `:long` shop that happens to stock food; it is a shop whose floor
   area belongs to every class at once, which is why the concept measures floor
   area by Warengruppe and not by shop. These are the 13 % of Stuttgart's
   retail places that no single class fits, and `shopping` — Overture's generic
   fallback — is most of them.

   `split-weights` divides such a venue across the three classes by its
   district's own measured potential mix rather than picking one. Assigning
   them to a single class, or dropping them, would move real floor area into
   the wrong raking total."
  #{"shopping" "shopping_center" "department_store" "discount_store"
    "variety_store" "general_store" "pop_up_shop" "flea_market"
    "outlet_store" "duty_free_store"})

(def category-rules
  "Overture place category → demand class, most specific first. The vocabulary
   is the one the Stuttgart pulls actually use, ordered by how many places carry
   it, so the common cases are covered by name rather than by a catch-all.

   A category that reaches none of these is `nil`, and the caller decides: an
   unclassified shop must be assigned by its district's measured mix, never
   dropped, or the raking silently moves its floor area onto its neighbours."
  [[#"(?i)grocer|supermarket|convenience_store|bakery|butcher|health_food|farmers_market|liquor|beverage_store|candy|delicatessen|fish_market|greengrocer|dairy|coffee_roast|tea_store|wine" :short]
   [#"(?i)pharmac|drugstore|perfume|cosmetic|e_cigarette|tobacco|hair_supply|beauty_supply|herbs?_and_spices?|vitamins" :short]
   ;; `pet_` is guarded: `carpet_store` contains `pet_store`, and without the
   ;; lookbehind a carpet showroom is classified as a pet shop and raked into
   ;; the wrong district total. Found by the vocabulary test, not by reading.
   [#"(?i)florist|flowers|(?<![a-z])pet_(store|suppl)|garden_cent" :short]
   [#"(?i)newspaper_and_magazines|newsstand|bookstore|stationery|office_supply|comic" :short]
   [#"(?i)clothing|boutique|bridal|lingerie|t_shirt|fashion_accessor|thrift_store|used_clothing|hat_shop|uniform" :medium]
   [#"(?i)shoe_store|shoes|luggage|leather_goods|handbag" :medium]
   [#"(?i)sporting_goods|bicycle_shop|sports_wear|outdoor_gear|ski_shop|dive_shop|golf_equipment" :medium]
   [#"(?i)toy_store|hobby_shop|game_store|craft_(store|shop)|party_supply|ski_and_snowboard" :medium]
   [#"(?i)home_goods|kitchen_supply|houseware|tableware|glassware|pottery|gift_shop|souvenir" :medium]
   [#"(?i)furniture|mattress|carpet|rug_store|interior_design_store|curtain|framing_store|antique|fabric_store|upholster" :long]
   [#"(?i)electronics|computer_store|mobile_phone|appliance|audio_visual|music_and_dvd|musical_instrument|camera_store|photography_store|video_game_store" :long]
   [#"(?i)lighting_store|lamp" :long]
   [#"(?i)building_supply|home_improvement|hardware_store|paint_store|tile_store|plumbing_supply|lumber|flooring_store|electrical_supply" :long]
   [#"(?i)nursery_and_gardening|garden_supply|landscaping_supply" :long]
   [#"(?i)jewelry|jeweller|watch_store|clock" :long]
   [#"(?i)medical_supply|orthopedic|hearing_aid|optician|eyewear|optical" :long]])

(defn segment-of
  "Demand class for an Overture place category: one of `:short`, `:medium`,
   `:long`, `:mixed` for a multi-assortment venue, `:not-retail` for one the
   census excludes, or nil when the category is unknown to the rules.

   nil is a real answer and must not be silently treated as a class. See
   `split-weights`, which resolves both nil and `:mixed` against the district's
   measured mix."
  [category]
  (let [c (str/lower-case (str (or category "")))]
    (cond
      (str/blank? c) nil
      (not-retail c) :not-retail
      (mixed-assortment c) :mixed
      :else (some (fn [[re s]] (when (re-find re c) s)) category-rules))))

(defn split-weights
  "{segment → weight} summing to 1 for one firm, given its category and its
   district's `potential-shares` row. A firm with a class gets all its weight
   there. A `:mixed` venue, or one whose category the rules do not know, is
   divided by the district's measured mix — the only split the data supports —
   so its floor area still lands in the district's raking totals in the right
   proportions. `:not-retail` returns nil: that firm should not carry retail
   floor area at all."
  [category shares]
  (let [s (segment-of category)]
    (cond
      (= :not-retail s) nil
      (contains? (set segments) s) {s 1.0}
      :else shares)))

;; ---- what the census says each district's classes are worth ---------------------------

(defn targets
  "{Stadtbezirk → {:short {...} :medium {...} :long {...}}} from the rollup rows
   of the 2024 concept, with `:umsatz-eur`, `:kaufkraft-eur`,
   `:verkaufsflaeche-m2`, `:betriebe` and `:zentralitaet` each.

   These are the observations a segmented model is scored against, and the
   raking targets its attractiveness is scaled to. Every one of the 23 districts
   carries all three rows. The three sum to 99.9 % of the district's own
   turnover and floor-area totals; the residue is `Sonstiges`."
  ([] (targets retail/detail-path))
  ([path]
   (some->> (retail/read-detail path) retail/district-entries
            (keep (fn [[d e]]
                    (let [by-name (into {} (for [[k v] rollup-names] [v k]))
                          rows (into {} (for [w (:by_warengruppe e)
                                              :let [s (by-name (:warengruppe w))]
                                              :when s]
                                          [s {:umsatz-eur (retail/mio-eur (:umsatz_mio_eur w))
                                              :kaufkraft-eur (retail/mio-eur (:kaufkraft_mio_eur w))
                                              :verkaufsflaeche-m2 (:verkaufsflaeche_m2 w)
                                              :betriebe (:betriebe w)
                                              :zentralitaet (:zentralitaet w)}]))]
                      (when (= 3 (count rows)) [d rows]))))
            (into {}))))

(defn potential-shares
  "{district → {segment → share}}: how a district's retail euro divides across
   the three classes, measured. This is κ in the model description — the split
   of *money*, which is not the split of *trips*."
  ([] (potential-shares (targets)))
  ([tg]
   (into {} (for [[d rows] tg
                  :let [tot (reduce + (keep #(:kaufkraft-eur (val %)) rows))]
                  :when (pos? (double (or tot 0)))]
              [d (into {} (for [[s r] rows] [s (/ (double (:kaufkraft-eur r)) (double tot))]))]))))

;; ---- per-segment attractiveness --------------------------------------------------------

(defn attract-by-segment
  "{segment → double[n-firms]}: each firm's attractiveness *within* a demand
   class, raked so that every district's firms sum to the Verkaufsfläche the
   concept publishes for that class.

   The same two-layer construction as `city.synth.retail/attract`, footprint
   (`retail/filled-footprints`) for shape and census for level, with one
   addition: a firm contributes its footprint to a class in proportion to
   `split-weights`, so a department store carries floor area in all three
   classes, a shoe shop in one, and a marketing agency in none.

   **Zero means not in the choice set**, and `city.sim.candidates/reduce-dense`
   reads it that way. It cannot be read that way by `table-dense`, which treats
   α = 0 as every candidate weighing 1; the segmented model must use the fused
   reducer for that reason.

   Returns nil when the inputs are missing, like `retail/attract`. Also returns
   `:coverage`, the share of flagged firms that reached a class by name rather
   than through the district mix — the number that says whether the classifier
   is still keeping up with the source vocabulary."
  [firms & {:keys [sizes st->bez tg shares flag]
            :or {sizes (retail/firm-sizes) st->bez (retail/district-of)}}]
  (let [tg (or tg (targets))
        shares (or shares (potential-shares tg))]
    (when (and sizes st->bez (seq tg))
      (let [n (:n firms)
            ^objects cat (:category firms)
            ^ints flag (or flag (:retail firms))
            dist (retail/district-fn firms st->bez)
            ^doubles filled (:filled (retail/filled-footprints firms sizes dist))
            ;; a firm's weight vector over the classes, and how it got one
            named (long-array 2)                              ; by-name, total
            weights (object-array n)
            _ (dotimes [j n]
                (when (= 1 (aget flag j))
                  (let [d (dist j) c (when cat (aget cat j))
                        s (segment-of c)
                        w (split-weights c (get shares d))]
                    (aset weights j w)
                    (aset named 1 (inc (aget named 1)))
                    (when (contains? (set segments) s) (aset named 0 (inc (aget named 0)))))))
            per (into {} (for [s segments] [s (double-array n)]))
            sums (reduce (fn [m j]
                           (if-let [w (aget weights j)]
                             (reduce (fn [m2 s]
                                       (let [x (* (aget filled j) (double (get w s 0.0)))]
                                         (when (pos? x) (aset ^doubles (per s) j x))
                                         (if (pos? x) (update m2 [(dist j) s] (fnil + 0.0) x) m2)))
                                     m segments)
                             m))
                         {} (range n))]
        (doseq [s segments
                :let [^doubles a (per s)]]
          (dotimes [j n]
            (let [x (aget a j)]
              (when (pos? x)
                (let [d (dist j)
                      sum (double (get sums [d s] 0.0))
                      t (double (or (get-in tg [d s :verkaufsflaeche-m2]) 0.0))]
                  (aset a j (if (and (pos? sum) (pos? t)) (* x (/ t sum)) x)))))))
        (assoc per
               :coverage (when (pos? (aget named 1)) (/ (double (aget named 0)) (aget named 1)))
               :flagged (aget named 1)
               :districts-raked (count (distinct (map first (keys sums)))))))))
