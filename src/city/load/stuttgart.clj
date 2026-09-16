(ns city.load.stuttgart
  "Stuttgart places: Overture (bbox extract) and OSM per Stadtbezirk (Overpass
   JSON, or ohsome GeoJSON for the districts Overpass refused). Entities are
   assigned to Stadtteile by point-in-polygon."
  (:require [city.intake.core :as acq]
            [city.intake.overture :as overture]
            [city.geo.core :as geo]
            [city.store :as store]
            [datahike.api :as d]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str])
  (:import [java.io File]))

(defn- strip-nil [m] (into {} (remove (comp nil? val)) m))
(defn- long* [v] (when v (try (long (Double/parseDouble (str v))) (catch Exception _ nil))))

(defn stadtteile []
  (->> (d/q '[:find ?e ?n ?g :where [?e :area/city :stuttgart] [?e :area/level :stadtteil] [?e :entity/name ?n] [?e :entity/geometry ?g]] (store/db))
       ;; `geo/locate` returns :name — make it the entity id so :entity/area gets a ref, not a string
       (map (fn [[e n g]] (geo/with-bbox {:eid e :name e :label n :geometry (geo/parse-geojson g)})))))

(defn load-overture! []
  (store/ensure-source! overture/source)
  (let [path "data/raw/overture-places/stuttgart_bbox.jsonl"
        r (acq/adopt! {:source :overture-places :dataset "places (Stuttgart bbox)" :path path
                       :url (str "s3://overturemaps-us-west-2/release/" overture/release "/theme=places/type=place/")})
        acq-ref (store/record-receipt! r)
        areas (stadtteile)
        ents (for [{:keys [id name category alt_categories confidence websites socials phones emails brand address postcode lon lat source_dataset]}
                   (overture/read-places r)
                   :let [a (when (and lon lat) (geo/locate areas [lon lat]))]
                   :when a]
               (strip-nil
                {:entity/ext-id (str "overture:" id) :entity/kind :place :entity/acq acq-ref
                 :entity/name name :entity/lat lat :entity/lon lon :entity/address address :entity/area a
                 :place/id id :place/category category
                 :place/alt-categories (when (seq alt_categories) (vec alt_categories))
                 :place/confidence (when confidence (double confidence))
                 :place/website (when (seq websites) (vec websites)) :place/social (when (seq socials) (vec socials))
                 :place/phone (when (seq phones) (vec phones)) :place/email (when (seq emails) (vec emails))
                 :place/brand brand :place/postcode postcode :place/source-dataset source_dataset}))]
    (store/transact-batched! ents :batch 2000)))

(defn- osm-elements
  "Normalize Overpass JSON or ohsome GeoJSON into {:type :id :tags :lon :lat}."
  [^File f]
  (let [data (with-open [r (io/reader f)] (json/read r :key-fn keyword))]
    (if (:elements data)
      (for [{:keys [type id tags lat lon center]} (:elements data)]
        {:type type :id id :tags tags :lat (or lat (:lat center)) :lon (or lon (:lon center))})
      (for [{:keys [geometry properties]} (:features data)
            :let [osm-id (or (get properties (keyword "@osmId")) (:osmId properties))
                  [t i] (when osm-id (str/split (str osm-id) #"/"))]
            :when (and t i (= "Point" (:type geometry)))]
        {:type t :id (Long/parseLong i)
         :tags (apply dissoc properties (map keyword ["@osmId" "@validFrom" "@validTo" "@version" "@changesetId"]))
         :lon (first (:coordinates geometry)) :lat (second (:coordinates geometry))}))))

(defn load-osm! []
  (store/ensure-source! {:source/id :osm-overpass :source/name "OpenStreetMap via Overpass/ohsome"
                         :source/url "https://overpass-api.de/api/interpreter" :source/license "ODbL 1.0 (c) OpenStreetMap contributors"})
  (let [areas (stadtteile)
        files (->> (.listFiles (io/file "data/raw/osm-overpass/stuttgart")) (filter #(re-find #"\.(json|geojson)$" (.getName ^File %))))]
    (doall
     (for [^File f files
           :when (or (with-open [in (io/reader f)] (= (int \{) (.read in)))
                     (do (println "skipping non-JSON file" (.getName f)) false))]
       (let [r (acq/adopt! {:source :osm-overpass :dataset (str "stuttgart/" (.getName f)) :path (.getPath f)
                            :url (if (str/ends-with? (.getName f) ".geojson") "https://api.ohsome.org/v1/elementsFullHistory/centroid" "https://overpass-api.de/api/interpreter")})
             acq-ref (store/record-receipt! r)
             ents (for [{:keys [type id tags lat lon]} (osm-elements f)
                        :let [a (when (and lat lon) (geo/locate areas [lon lat]))]
                        :when a]
                    (strip-nil
                     {:entity/ext-id (str "osm:" type ":" id)
                      :entity/kind (if (:building tags) :building :poi)
                      :entity/acq acq-ref
                      :entity/name (:name tags) :entity/lat lat :entity/lon lon :entity/area a
                      :entity/address (let [s (str/join " " (remove nil? [(:addr:street tags) (:addr:housenumber tags)]))] (when-not (str/blank? s) s))
                      :osm/id id :osm/type (keyword type) :osm/tags (pr-str tags)
                      :osm/shop (:shop tags) :osm/amenity (:amenity tags) :osm/office (:office tags)
                      :osm/building (:building tags) :osm/levels (long* (:building:levels tags))
                      :osm/opening-hours (:opening_hours tags) :osm/brand (:brand tags)
                      :osm/website (or (:website tags) (:contact:website tags))}))]
         [(.getName f) (store/transact-batched! ents :batch 2000)])))))

(defn repair-area-links!
  "Entities whose :entity/area points at a phantom entity (no :area/name)
   are re-located into Stadtteile by point-in-polygon; phantoms are retracted."
  []
  (let [db (store/db)
        areas (stadtteile)
        bad (d/q '[:find ?e ?lon ?lat ?a
                   :where [?e :entity/area ?a] [(missing? $ ?a :area/name)] [?e :entity/lon ?lon] [?e :entity/lat ?lat]] db)
        phantoms (set (map last bad))
        tx (for [[e lon lat _] bad :let [a (geo/locate areas [lon lat])] :when a] [:db/add e :entity/area a])
        r1 (store/transact-batched! tx :batch 2000)
        r2 (store/transact-batched! (for [p phantoms] [:db/retractEntity p]) :batch 2000)]
    {:bad (count bad) :relinked (:count r1) :phantoms-retracted (:count r2)}))
