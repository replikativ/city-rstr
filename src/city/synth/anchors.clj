(ns city.synth.anchors
  "Match **named real employers with measured headcounts** onto the Stuttgart
   firm register, so that employment at the top end is observed rather than
   allocated.

   **The defect this exists to fix.** `city.synth.stuttgart-firms` rakes each
   (Stadtbezirk × WZ-section) cell so its firms' drawn sizes sum to that cell's
   employment target. The targets are right; the carriers are not. Overture has
   no object at all for the Untertürkheim works, so the cell's 17,668
   manufacturing jobs land on whatever is there — 16,741 of them on three
   wineries on the Rotenberg hillside. City-wide, the name `Mercedes` carries
   641 jobs across 34 POIs and `Bosch` 600 across 37, against ~15,000 at Bosch
   Feuerbach alone.

   Overture is not missing the *names*; it is missing the *objects* and files
   what it has under the wrong category — \"Dr. Ing. h.c. F. Porsche AG\" at
   Porscheplatz 1 is tagged `library`, the MAHLE Werk 2 gatehouse is
   `contractor`. So category-based matching is hopeless and geometry is the
   reliable evidence.

   ## Three tiers, strongest first

   1. **Containment.** A register firm whose point falls inside an anchor's OSM
      site polygon belongs to that site. No name comparison at all, which is
      exactly why it survives the mis-tagging.
   2. **Name and proximity.** For employers with a coordinate but no polygon,
      `city.resolve/name-sim` (the larger of token Jaccard and Jaro-Winkler on
      normalised names) within a distance cap.
   3. **Address.** Employers with a street and postcode but no coordinate — the
      362 IHK firms — need geocoding before tier 2 can see them. Not done here.

   ## What a match means downstream

   A matched firm's employment becomes **observed**: it takes the published
   headcount and is flagged `:emp-observed 1`, which `day/venue-attract`
   already requires before it will trust a headcount over floor area.

   And the matched employment must be **subtracted from the cell target before
   the residual is raked**. Adding Mercedes without subtracting it would leave
   the wineries exactly as they are and merely add 23,000 jobs beside them.

   ## Scope is the hard part, and it is not a modelling choice

   Published headcounts are reported for whatever unit the company finds
   convenient, and mixing those units silently is the easiest way to be wrong
   by a factor. Every anchor row therefore carries a `scope`, and only `site`
   and `standortverbund` rows may be placed spatially; `region`, `germany` and
   `worldwide` rows exist for reconciliation and must never be allocated.

   **Untertürkheim is the instructive case.** The works is published at
   \">23,000\", which exceeds the Untertürkheim cell's entire 17,668, so a naive
   subtraction goes negative. That is not a contradiction in the data — the
   figure is a Standortverbund spanning Werkteile in three Stuttgart
   Stadtbezirke (Untertürkheim, Bad Cannstatt for engines, Hedelfingen for
   transmissions and battery systems) **and two in Esslingen** (Sirnau, Brühl).
   Those three Stuttgart districts hold 17,668 + 4,410 + 3,430 = **25,508**
   section-C jobs between them, which is consistent with the published figure
   once Esslingen is removed.

   So a Standortverbund is not forced into one cell. It is capped at each
   district's own target and distributed across the districts it actually spans,
   and the remainder is attributed outside the city rather than invented inside
   it. `cap-to-cells` does that, and it needs no guess about the 23,000 versus
   the ~12,500 its own source's infobox claims — both fit under 25,508."
  (:require [clojure.data.json :as json]
            [clojure.string :as str]
            [clojure.java.io :as io]
            [city.resolve :as r]
            [city.sim.world :as w]))

(def anchors-path "data/derived/stuttgart_anchors.json")
(def polygons-path "data/derived/stuttgart_anchor_polygons.geojson")

(def placeable
  "Scopes that may be put on the map. A `region` figure covers municipalities we
   do not simulate; placing it would double-count the city."
  #{"site" "standortverbund"})

(defn anchors
  ([] (anchors anchors-path))
  ([path] (when (.exists (io/file path))
            (let [d (json/read-str (slurp path) :key-fn keyword)]
              (vec (if (map? d) (or (:anchors d) (:entries d)) d))))))

(defn polygons
  "{anchor_id → [ring …]}, each ring a vector of [lon lat]. MultiPolygon and
   Polygon are flattened to their outer rings; holes are ignored, since a plant
   site's courtyard is still the plant."
  ([] (polygons polygons-path))
  ([path]
   (when (.exists (io/file path))
     (let [fc (json/read-str (slurp path) :key-fn keyword)]
       (into {} (for [f (:features fc)
                      :let [g (:geometry f) t (:type g)
                            rings (case t
                                    "Polygon" [(first (:coordinates g))]
                                    "MultiPolygon" (mapv first (:coordinates g))
                                    nil)]
                      :when (seq rings)]
                  [(get-in f [:properties :anchor_id]) rings]))))))

(defn in-ring?
  "Ray casting. `ring` is [[lon lat] …]."
  [ring ^double lon ^double lat]
  (loop [i 0 j (dec (count ring)) inside false]
    (if (>= i (count ring))
      inside
      (let [[^double xi ^double yi] (nth ring i)
            [^double xj ^double yj] (nth ring j)
            cross (and (not= (> yi lat) (> yj lat))
                       (< lon (+ xi (/ (* (- xj xi) (- lat yi)) (- yj yi)))))]
        (recur (inc i) i (if cross (not inside) inside))))))

(defn in-any? [rings lon lat]
  (boolean (some #(in-ring? % lon lat) rings)))

(defn match
  "Match register firms to anchors. `firms` is a seq of maps with at least
   `:name`, `:lon`, `:lat`.

   Returns `{:matches [{:anchor_id :firm-index :how :score}] :by-anchor {…}}`,
   where `:how` is `:contained`, `:name-proximity` or `:name-in-district`.

   `:max-m` caps tier 2; `:min-sim` is the name-similarity floor. Both are
   deliberately strict — a wrong match moves thousands of jobs to the wrong
   place, which is the failure we are here to remove, so an unmatched anchor is
   much cheaper than a mismatched one."
  [firms & {:keys [anchor-rows polys max-m min-sim]
            :or {max-m 400.0 min-sim 0.80}}]
  (let [as (filterv #(placeable (:scope %)) (or anchor-rows (anchors)))
        ps (or polys (polygons))
        fv (vec firms)
        idx (map-indexed vector fv)
        contained (for [a as
                        :let [rings (get ps (:anchor_id a))]
                        :when rings
                        [i f] idx
                        :when (and (:lon f) (:lat f)
                                   (in-any? rings (double (:lon f)) (double (:lat f))))]
                    {:anchor_id (:anchor_id a) :firm-index i :how :contained :score 1.0
                     :firm-name (:name f)})
        taken (set (map :firm-index contained))
        by-name (for [a as
                      :when (not (get ps (:anchor_id a)))
                      :let [[clon clat] (:centroid a)
                            best (when (and clon clat)
                                   (->> idx
                                        (remove #(taken (first %)))
                                        (keep (fn [[i f]]
                                                (when (and (:lon f) (:lat f) (:name f))
                                                  (let [d (w/haversine-m clon clat (:lon f) (:lat f))
                                                        s (r/name-sim (:name a) (:name f))]
                                                    (when (and (<= d (double max-m)) (>= s (double min-sim)))
                                                      {:firm-index i :score s :dist-m d :firm-name (:name f)})))))
                                        (sort-by (comp - :score))
                                        first))]
                      :when best]
                  (assoc best :anchor_id (:anchor_id a) :how :name-proximity))
        ;; 2b. No polygon and no usable centroid. Porsche's Stammsitz is
        ;; published without a headcount *and* fails to geocode (Nominatim
        ;; returns only the Neuwirtshaus railway halt), yet the register plainly
        ;; holds the plant.
        ;;
        ;; Name *similarity* is the wrong instrument here and measurably so:
        ;; against "Porsche Stammsitz Zuffenhausen", `name-sim` scores "Porsche
        ;; Museum" 0.85 and the actual 12,154-employee "Porsche Zuffenhausen
        ;; Werk 2 Bau 1" only 0.29, because the works names carry many extra
        ;; tokens and Jaro-Winkler rewards the short string. Taking the best
        ;; match would have moved a plant's employment into a museum.
        ;;
        ;; A plant is a *set* of buildings, so match the way tier 1 does — take
        ;; everything that qualifies, not the single best — and qualify on
        ;; **token containment**: a candidate must carry every distinctive token
        ;; of the anchor's name. "Porsche Zuffenhausen Werk 4 Motorenwerk"
        ;; qualifies; "Porsche Museum" does not.
        stop #{"stammsitz" "werk" "standort" "zentrale" "konzernzentrale" "campus"
               "gruppe" "group" "ag" "gmbh" "se" "kg" "co" "und" "the"}
        toks (fn [nm] (into #{} (remove stop) (re-seq #"\p{L}{2,}" (str/lower-case (str nm)))))
        placed (set (map :firm-index (concat contained by-name)))
        by-district (for [a as
                          :when (and (not (get ps (:anchor_id a)))
                                     (not (some #(= (:anchor_id a) (:anchor_id %)) (concat contained by-name)))
                                     (:stadtbezirk a))
                          :let [want (toks (:name a))]
                          :when (seq want)
                          [i f] idx
                          :when (and (not (placed i))
                                     (:name f)
                                     (= (:stadtbezirk f) (:stadtbezirk a))
                                     (every? (toks (:name f)) want))]
                      {:anchor_id (:anchor_id a) :firm-index i :how :name-in-district
                       :score 1.0 :firm-name (:name f)})
        all (concat contained by-name by-district)]
    {:matches (vec all)
     :by-anchor (into {} (for [[k v] (group-by :anchor_id all)] [k (vec v)]))
     :unmatched (vec (for [a as :when (not-any? #(= (:anchor_id a) (:anchor_id %)) all)] (:anchor_id a)))}))

(defn cap-to-cells
  "Distribute an anchor's employment across the districts it actually spans,
   capped at each district's own measured cell target.

   `cell-target` is `{[bezirk section] → employees}` and `spans` names the
   districts this anchor covers, in priority order. Returns
   `{:placed {bezirk n} :outside n}`; `:outside` is the part that belongs to
   municipalities we do not simulate and is reported rather than absorbed.

   This is what makes a Standortverbund tractable without a scope guess: no
   district receives more than it is published to hold, and nothing is invented."
  [employees spans section cell-target]
  (loop [[b & more] (vec spans) left (double employees) placed {}]
    (if (or (nil? b) (<= left 0.0))
      {:placed placed :outside (max 0.0 left)}
      (let [cap (double (get cell-target [b section] 0.0))
            take (min left cap)]
        (recur more (- left take) (if (pos? take) (assoc placed b take) placed))))))

(def anchor-section
  "WZ section per anchor. Stated explicitly rather than inferred from the matched
   POIs, because those POIs are exactly the ones Overture mis-tagged — inferring
   the section from them would launder the error we are removing. Mercedes,
   Porsche, Bosch and MAHLE are C (Verarbeitendes Gewerbe); the SSB is H
   (Verkehr und Lagerei); the Klinikum is Q; the university is P."
  {"mercedes-untertuerkheim" "C" "mercedes-sindelfingen" "C" "porsche-zuffenhausen" "C"
   "porsche-weissach" "C" "bosch-feuerbach" "C" "bosch-schwieberdingen" "C"
   "bosch-gerlingen" "C" "bosch-renningen" "C" "bosch-abstatt" "C"
   "mahle-pragstrasse" "C" "daimler-truck-campus" "C" "stihl-waiblingen" "C"
   "eberspaecher-esslingen" "C" "ssb-moehringen" "H" "klinikum-stuttgart" "Q"
   "universitaet-stuttgart" "P"})

(defn cell-targets
  "{[bezirk section] → employees} as the register currently stands. This is the
   quantity the anchors are subtracted from."
  [firms]
  (reduce (fn [m f] (update m [(:stadtbezirk f) (:wz f)] (fnil + 0.0) (double (or (:employees f) 0))))
          {} firms))

(defn apply-anchors
  "Put measured employment on the register, and take it out of the cell targets.

   For each placeable anchor with matched POIs:

   1. Its published headcount is spread over the districts its matched POIs
      actually lie in, **capped at each district's own cell target**
      (`cap-to-cells`). A Standortverbund therefore lands where it really is
      rather than piling into one cell, and nothing exceeds what the district is
      published to hold. Whatever will not fit is reported as `:outside` — for
      Untertürkheim that is the Esslingen share, which belongs to a municipality
      we do not simulate.
   2. Within a district the share is split across that district's matched POIs
      in proportion to their current employment, falling back to an equal split
      when they all sit near zero — which, since the raking starved them, is the
      usual case.
   3. Those firms are flagged `:emp-observed 1`. `day/venue-attract` already
      refuses to use a headcount without that flag, so the measured figures take
      effect on destination choice and the synthesised ones still do not.

   Returns `{:firms … :residual-targets … :placed … :outside …}`. The residual
   targets are what the size draw should be raked to afterwards; raking to the
   original targets would leave the artefacts untouched and merely add the
   anchors beside them."
  [firms matches & {:keys [anchor-rows]}]
  (let [fv (vec firms)
        ar (into {} (for [a (or anchor-rows (anchors))] [(:anchor_id a) a]))
        targets (cell-targets fv)
        ;; Order matters and is not arbitrary. A `site` headcount names one
        ;; place; a `standortverbund` headcount is a total to be spread over
        ;; several. Placing the verbund first lets it swallow a cell that a
        ;; specific site is published to occupy — Mercedes' Bad Cannstatt
        ;; Werkteil consumed all 4,410 of that district's section C and left
        ;; MAHLE's 4,000-employee headquarters, which is *in* Bad Cannstatt,
        ;; with nothing. Sites first, largest first, verbunde last.
        by-anchor (->> (group-by :anchor_id matches)
                       (sort-by (fn [[aid _]]
                                  (let [a (ar aid)]
                                    [(if (= "site" (:scope a)) 0 1) (- (long (or (:employees a) 0)))]))))
        ;; district order: most matched POIs first, which is where the mass is
        result (reduce
                (fn [acc [aid ms]]
                  (let [a (ar aid) sec (anchor-section aid)]
                    (if-not (and a sec (placeable (:scope a)) (:employees a))
                      acc
                      (let [spans (->> ms (map #(:stadtbezirk (nth fv (:firm-index %))))
                                       (remove nil?) frequencies (sort-by (comp - val)) (mapv key))
                            {:keys [placed outside]} (cap-to-cells (:employees a) spans sec (:targets acc))
                            acc (update acc :outside (fnil + 0.0) outside)]
                        (reduce
                         (fn [acc [bez amount]]
                           ;; One establishment per (anchor, district), not one
                           ;; per building. Jahrbuch 5.2.6 counts
                           ;; *Niederlassungen*, and its own Info sheet says
                           ;; sites of one firm in one municipality and industry
                           ;; may be aggregated into a Masterniederlassung.
                           ;; Splitting Untertürkheim's 17,668 across its 26
                           ;; matched buildings would put 26 establishments over
                           ;; 250 employees into a section the city says holds
                           ;; 22 in total. The share goes to the building that
                           ;; already carries the most employment — the register's
                           ;; own guess at the principal site — and the rest fall
                           ;; to the one-person floor, still flagged as part of
                           ;; the site.
                           (let [mine (filterv #(= bez (:stadtbezirk (nth fv (:firm-index %)))) ms)
                                 ranked (vec (sort-by #(- (double (or (:employees (nth fv (:firm-index %))) 0))) mine))
                                 shares (into [1.0] (repeat (max 0 (dec (count ranked))) 0.0))
                                 mine ranked]
                             (-> (reduce (fn [acc [m sh]]
                                           (let [i (:firm-index m) e (max 1 (Math/round (* sh (double amount))))]
                                             (update acc :firms assoc i
                                                     (assoc (nth (:firms acc) i)
                                                            :employees e :emp-observed 1
                                                            ;; the section too, not just the headcount:
                                                            ;; Overture filed the Untertürkheim works
                                                            ;; under N and Bosch Feuerbach under F, so
                                                            ;; leaving :wz alone would put 11,871
                                                            ;; manufacturing jobs in "sonstige
                                                            ;; wirtschaftliche Dienstleistungen" and
                                                            ;; corrupt the very marginal the anchor was
                                                            ;; subtracted from
                                                            :wz sec
                                                            :anchor-id aid :anchor-scope (:scope a)))))
                                         acc (map vector mine shares))
                                 (update :targets update [bez sec] (fnil - 0.0) (double amount))
                                 (update :placed assoc [aid bez] amount))))
                         acc placed)))))
                {:firms fv :targets targets :placed {} :outside 0.0}
                by-anchor)]
    {:firms (:firms result)
     :residual-targets (:targets result)
     :placed (:placed result)
     :outside (:outside result)}))

(defn rerake
  "Rescale every **non-anchor** firm so each (Bezirk, section) cell sums to its
   residual target — what is left after the measured employers have been placed
   and subtracted.

   This is the step that actually removes the artefact. Placing Mercedes without
   re-raking would leave Weingut Warth on 9,006 employees and simply add 23,000
   beside it; subtracting without re-raking would leave the register's own total
   overstated by the same amount.

   An establishment employs at least the person running it, so the floor is 1
   rather than 0. Where a cell's residual is zero — Untertürkheim's section C is
   exactly consumed by the works — every remaining firm in it falls to that
   floor, which is the correct answer: the wineries on the Rotenberg hillside
   are small businesses, and the register said so before the raking overwrote
   them."
  [firms residual-targets]
  (let [fv (vec firms)
        anchor? (fn [f] (some? (:anchor-id f)))
        sums (reduce (fn [m [i f]]
                       (if (anchor? f) m
                           (update m [(:stadtbezirk f) (:wz f)] (fnil + 0.0) (double (or (:employees f) 0)))))
                     {} (map-indexed vector fv))]
    (mapv (fn [f]
            (if (or (anchor? f) (nil? (:wz f)))
              f
              (let [k [(:stadtbezirk f) (:wz f)]
                    s (double (get sums k 0.0))
                    t (max 0.0 (double (get residual-targets k 0.0)))
                    e (double (or (:employees f) 0))]
                (assoc f :employees (max 1 (long (Math/round (if (pos? s) (* e (/ t s)) e))))))))
          fv)))

(def size-joint-path "data/derived/stuttgart_size_class_joint.json")

(defn size-class-allowance
  "{WZ section → number of establishments with 250+ employees}, from Jahrbuch
   5.2.6 (`year` defaults to 2023). `nil` for a suppressed cell, which must be
   left alone rather than read as zero."
  ([] (size-class-allowance size-joint-path "2023"))
  ([path year]
   (when (.exists (io/file path))
     (let [doc (json/read-str (slurp path))]
       (into {} (for [[sec m] (get doc year)] [sec (get m "c250plus")]))))))

(defn- cap-once
  "Hold the register to the city's published count of large establishments.

   Jahrbuch 5.2.6 cross-tabulates WZ section by employee size class, and it is
   the constraint the register has never been subject to. Section **L**
   (Grundstücks- und Wohnungswesen) has **zero** establishments over 250
   employees in the whole city; **P** (Erziehung und Unterricht) has seven; **R**
   four and **S** five. Raking employment into a cell without that constraint is
   what produced a 3,762-employee kindergarten and a 3,486-employee carpet
   cleaner.

   Per section, firms are ranked by employment and everything past the published
   allowance is capped at 249. The jobs removed are redistributed **within the
   same (Bezirk, section) cell**, proportionally across firms that are still
   under the cap, so the cell total — which is a measured marginal — is
   preserved.

   Two exemptions, both deliberate:

   - **Measured firms are never capped.** An anchor carries a published
     headcount; if it disagrees with the size-class count then the count is the
     thing that is aggregated and approximate, not the plant.
   - **A suppressed cell is not a zero.** Where 5.2.6 withholds a value
     (Gastgewerbe's top classes, among others) the section is left untouched,
     because German disclosure rules suppress small non-zero cells and reading
     them as zero would delete real establishments."
  [firms & {:keys [allowance passes] :or {allowance (size-class-allowance) passes 4}}]
  (if-not allowance
    (vec firms)
    (let [fv (vec firms)
          big (fn [f] (>= (long (or (:employees f) 0)) 250))
          idx (map-indexed vector fv)
          ;; which firm indexes must come down
          to-cap (mapcat (fn [[sec allow]]
                           (when allow
                             (let [mine (->> idx
                                             (filter (fn [[_ f]] (and (= sec (:wz f)) (big f)
                                                                      (not (:emp-observed f)))))
                                             (sort-by (fn [[_ f]] (- (long (or (:employees f) 0))))))
                                   keep-n (max 0 (- (long allow)
                                                    (count (filter (fn [[_ f]] (and (= sec (:wz f)) (big f)
                                                                                    (:emp-observed f))) idx))))]
                               (map first (drop keep-n mine)))))
                         allowance)
          capped (set to-cap)
          freed (reduce (fn [m i] (let [f (nth fv i)]
                                    (update m [(:stadtbezirk f) (:wz f)] (fnil + 0.0)
                                            (- (double (or (:employees f) 0)) 249.0))))
                        {} capped)
          ;; room available per cell among firms still under the cap
          room (reduce (fn [m [i f]]
                         ;; a firm already held at the cap must not receive
                         ;; redistribution, or it climbs straight back over it
                         (if (or (capped i) (:size-capped f) (:emp-observed f) (nil? (:wz f)) (big f)) m
                             (update m [(:stadtbezirk f) (:wz f)] (fnil + 0.0)
                                     (double (or (:employees f) 0)))))
                       {} idx)]
      (mapv (fn [[i f]]
              (cond
                (capped i) (assoc f :employees 249 :size-capped true)
                (or (:size-capped f) (:emp-observed f) (nil? (:wz f)) (big f)) f
                :else (let [k [(:stadtbezirk f) (:wz f)]
                            add (double (get freed k 0.0))
                            base (double (get room k 0.0))
                            e (double (or (:employees f) 0))]
                        (if (and (pos? add) (pos? base))
                          (assoc f :employees (max 1 (long (Math/round (* e (+ 1.0 (/ add base)))))))
                          f))))
            idx))))

(defn cap-size-classes
  "`cap-once` to a fixed point. One pass is not enough: redistributing a capped
   firm's jobs across its cell can push a recipient over 250 and create a new
   violation, so the pass is repeated until the counts stop moving (4 is ample;
   the second pass typically settles it)."
  [firms & {:keys [allowance passes] :or {allowance (size-class-allowance) passes 4}}]
  (loop [fs (vec firms) n passes]
    (if (zero? n)
      fs
      (let [next (cap-once fs :allowance allowance)]
        (if (= (mapv :employees next) (mapv :employees fs)) fs (recur next (dec n)))))))

(def scope-required
  "Employer sources may only be placed on the map when their headcount is
   labelled with a scope we can interpret. This is not bureaucracy: the e-mobil
   BW Kompetenzatlas publishes a `companySize` that reads as an exact employee
   count and is in fact the **worldwide group** figure. Mercedes-Benz Group
   appears there as 175,000 against a published Untertürkheim site of 17,668,
   and MAHLE as 71,000 against a Bad Cannstatt headquarters of 4,000 — a 13×
   error, on a source whose coordinates and sector tags are otherwise excellent.

   So a source contributes employment only if every row carries one of these,
   and only `site` and `standortverbund` rows are ever placed. Everything else
   is reconciliation material."
  #{:site :standortverbund :municipality :region :germany :worldwide})

(defn placeable-rows
  "Filter an employer source to rows that may be placed, rejecting anything
   whose scope is missing or wider than a Standortverbund. Returns
   `{:rows … :rejected {reason count}}` so a source that contributes nothing
   says so loudly rather than silently."
  [rows]
  (let [scope-of (fn [r] (some-> (or (:scope r) (:employment-scope r)) name keyword))
        grouped (group-by (fn [r]
                            (let [s (scope-of r)]
                              (cond (nil? s) :no-scope
                                    (not (scope-required s)) :unknown-scope
                                    (placeable (name s)) :ok
                                    :else :too-wide)))
                          rows)]
    {:rows (vec (:ok grouped))
     :rejected (into {} (for [[k v] grouped :when (not= k :ok)] [k (count v)]))}))
