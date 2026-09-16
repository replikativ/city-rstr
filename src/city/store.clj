(ns city.store
  "The world's structured state: Datahike with history, on disk under data/db.

   Schema principles
   - every derived entity points at the receipt it came from (:entity/acq)
   - every entity carries a stable external id (:entity/ext-id) so re-loads upsert
   - geometry is stored as GeoJSON text; hot geometry lives in raster columns
   - per-source claims stay separate; resolution (:entity/same-as) is additive"
  (:require [datahike.api :as d]))

(def ^:dynamic *db-path* "data/db")

(def store-id #uuid "7c1a2e3e-9b1c-4d6a-8f0e-c17900000001")

(defn config [] {:store {:backend :file :path *db-path* :id store-id}
                 :keep-history? true
                 :max-string-length 0
                 :schema-flexibility :write
                 :attribute-refs? false
                 :name "city"})

(defn- attr
  ([ident type] (attr ident type :db.cardinality/one nil))
  ([ident type card] (attr ident type card nil))
  ([ident type card extra]
   (merge {:db/ident ident :db/valueType type :db/cardinality card} extra)))

(def unique-id {:db/unique :db.unique/identity})
(def indexed {:db/index true})

(def schema
  (concat
   ;; ---- provenance -------------------------------------------------------
   [(attr :source/id :db.type/keyword :db.cardinality/one unique-id)
    (attr :source/name :db.type/string)
    (attr :source/url :db.type/string)
    (attr :source/license :db.type/string)
    (attr :acq/id :db.type/uuid :db.cardinality/one unique-id)
    (attr :acq/source :db.type/ref)
    (attr :acq/dataset :db.type/string)
    (attr :acq/url :db.type/string)
    (attr :acq/sha256 :db.type/string)
    (attr :acq/bytes :db.type/long)
    (attr :acq/fetched-at :db.type/instant)
    (attr :acq/path :db.type/string)
    (attr :acq/note :db.type/string)]
   ;; ---- generic entity ----------------------------------------------------
   [(attr :entity/ext-id :db.type/string :db.cardinality/one unique-id)
    (attr :entity/kind :db.type/keyword :db.cardinality/one indexed)
    (attr :entity/acq :db.type/ref)
    (attr :entity/name :db.type/string)
    (attr :entity/lat :db.type/double)
    (attr :entity/lon :db.type/double)
    (attr :entity/area :db.type/ref)
    (attr :entity/geometry :db.type/string)
    (attr :entity/address :db.type/string)
    (attr :entity/same-as :db.type/ref :db.cardinality/many)]
   ;; ---- areas (local areas / Stadtbezirke / zoning) -----------------------
   [(attr :area/name :db.type/string :db.cardinality/one indexed)
    (attr :area/city :db.type/keyword)
    (attr :area/level :db.type/keyword)
    (attr :area/code :db.type/string :db.cardinality/one indexed)
    (attr :area/parent :db.type/ref)
    (attr :area/land-km2 :db.type/double)]
   ;; ---- business licences (from the Vancouver prototype; unused for Stuttgart)
   [(attr :licence/number :db.type/string :db.cardinality/one indexed)
    (attr :licence/rsn :db.type/string)
    (attr :licence/year :db.type/long)
    (attr :licence/status :db.type/string)
    (attr :licence/issued :db.type/instant)
    (attr :licence/expired :db.type/instant)
    (attr :licence/type :db.type/string :db.cardinality/one indexed)
    (attr :licence/subtype :db.type/string)
    (attr :licence/employees :db.type/double)
    (attr :licence/fee :db.type/double)
    (attr :licence/trade-name :db.type/string)
    (attr :licence/business-name :db.type/string)
    (attr :licence/postal :db.type/string)]
   ;; ---- storefront inventory (from the Vancouver prototype; unused for Stuttgart)
   [(attr :storefront/store-id :db.type/long :db.cardinality/one indexed)
    (attr :storefront/year :db.type/long)
    (attr :storefront/category :db.type/string)
    (attr :storefront/bia :db.type/string)]
   ;; ---- parcels / property tax --------------------------------------------
   ;; a :parcel is the land polygon (one per land coordinate); a :lot is one
   ;; assessed unit on it (strata lots share a parcel), carrying the values.
   [(attr :lot/parcel :db.type/ref)
    (attr :lot/folio :db.type/string :db.cardinality/one indexed)
    (attr :parcel/pid :db.type/string :db.cardinality/one indexed)
    (attr :parcel/folio :db.type/string)
    (attr :parcel/land-coordinate :db.type/string :db.cardinality/one indexed)
    (attr :parcel/legal-type :db.type/string)
    (attr :parcel/zoning-district :db.type/string)
    (attr :parcel/zoning-class :db.type/string)
    (attr :parcel/street :db.type/string)
    (attr :parcel/civic-from :db.type/string)
    (attr :parcel/civic-to :db.type/string)
    (attr :parcel/postal :db.type/string)
    (attr :parcel/land-value :db.type/long)
    (attr :parcel/improvement-value :db.type/long)
    (attr :parcel/prev-land-value :db.type/long)
    (attr :parcel/prev-improvement-value :db.type/long)
    (attr :parcel/year-built :db.type/long)
    (attr :parcel/tax-levy :db.type/double)
    (attr :parcel/assessment-year :db.type/long)
    (attr :parcel/neighbourhood-code :db.type/string)]
   ;; ---- census marginals (small-area statistics) ---------------------------
   ;; one entity per (area, variable, category): counts by sex where available
   [(attr :marginal/area :db.type/ref :db.cardinality/one indexed)
    (attr :marginal/source :db.type/keyword)          ;; :statcan-2021 | :zensus-2022 | :stuttgart-stat
    (attr :marginal/cid :db.type/long)                ;; StatCan characteristic id
    (attr :marginal/variable :db.type/string :db.cardinality/one indexed)
    (attr :marginal/category :db.type/string)
    (attr :marginal/total :db.type/double)
    (attr :marginal/men :db.type/double)
    (attr :marginal/women :db.type/double)
    (attr :marginal/rate :db.type/double)
    (attr :marginal/year :db.type/long)]
   ;; ---- grid cells (Zensus 100 m) -------------------------------------------
   [(attr :cell/gid :db.type/string :db.cardinality/one unique-id)
    (attr :cell/x :db.type/double) (attr :cell/y :db.type/double)
    (attr :cell/population :db.type/long)
    (attr :cell/age :db.type/string)          ;; edn map of age band -> count
    (attr :cell/household-size :db.type/string) ;; edn map
    (attr :cell/rent :db.type/double)          ;; mean Nettokaltmiete €/m²
    (attr :cell/building-year :db.type/string)] ;; edn map
   ;; ---- Overture places ----------------------------------------------------
   [(attr :place/id :db.type/string :db.cardinality/one indexed)
    (attr :place/category :db.type/string :db.cardinality/one indexed)
    (attr :place/alt-categories :db.type/string :db.cardinality/many)
    (attr :place/confidence :db.type/double)
    (attr :place/website :db.type/string :db.cardinality/many)
    (attr :place/social :db.type/string :db.cardinality/many)
    (attr :place/phone :db.type/string :db.cardinality/many)
    (attr :place/email :db.type/string :db.cardinality/many)
    (attr :place/brand :db.type/string)
    (attr :place/postcode :db.type/string)
    (attr :place/source-dataset :db.type/string)]
   ;; ---- OpenStreetMap -----------------------------------------------------
   [(attr :osm/id :db.type/long :db.cardinality/one indexed)
    (attr :osm/type :db.type/keyword)
    (attr :osm/tags :db.type/string)
    (attr :osm/shop :db.type/string)
    (attr :osm/amenity :db.type/string)
    (attr :osm/office :db.type/string)
    (attr :osm/building :db.type/string)
    (attr :osm/levels :db.type/long)
    (attr :osm/opening-hours :db.type/string)
    (attr :osm/brand :db.type/string)
    (attr :osm/website :db.type/string)]))

(defonce conn (atom nil))

(defn connect!
  "Create (if needed) and connect. Idempotent; transacts the schema."
  []
  (let [cfg (config)]
    (when-not (d/database-exists? cfg) (d/create-database cfg))
    (let [c (d/connect cfg)]
      (d/transact c schema)
      (reset! conn c)
      c)))

(defn db [] (d/db @conn))

(defn reset-db!
  "Delete the database on disk and reconnect with a fresh schema."
  []
  (when @conn (try (d/release @conn) (catch Exception _)))
  (let [cfg (config)]
    (when (d/database-exists? cfg) (d/delete-database cfg)))
  (connect!))

(defn ensure-source! [{:source/keys [id] :as source}]
  (d/transact @conn [source])
  [:source/id id])

(defn receipt-tx
  "Turn an intake receipt into a transactable entity."
  [{:acq/keys [id source dataset url sha256 bytes fetched-at path note]}]
  (cond-> {:acq/id id
           :acq/source [:source/id source]
           :acq/url url :acq/sha256 sha256 :acq/bytes bytes
           :acq/fetched-at fetched-at
           :acq/path path}
    dataset (assoc :acq/dataset dataset)
    note (assoc :acq/note (pr-str note))))

(defn record-receipt! [receipt]
  (d/transact @conn [(receipt-tx receipt)])
  [:acq/id (:acq/id receipt)])

(defn transact-batched!
  "Transact `entities` in batches; returns {:count n :ms elapsed}."
  [entities & {:keys [batch] :or {batch 1000}}]
  (let [t0 (System/nanoTime)
        n (reduce (fn [acc chunk] (d/transact @conn (vec chunk)) (+ acc (count chunk)))
                  0 (partition-all batch entities))]
    {:count n :ms (/ (- (System/nanoTime) t0) 1e6)}))

(defn count-kind [kind]
  (d/q '[:find (count ?e) . :in $ ?k :where [?e :entity/kind ?k]] (db) kind))

(defn kinds []
  (->> (d/q '[:find ?k (count ?e) :where [?e :entity/kind ?k]] (db)) (into (sorted-map))))
