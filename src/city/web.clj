(ns city.web
  "The evidence API (port 8090): read-only HTTP over the Datahike store for
   the explorer, plus static files from `public/`. Areas and cells are also
   called in process by `city.demo.stuttgart` for the static export. The
   endpoints are listed in `doc/api.md`; `/api/entity/<eid>` returns a record
   with the receipts of the sources it came from."
  (:require [org.httpkit.server :as http]
            [city.store :as store]
            [city.geo.core :as geo]
            [datahike.api :as d]
            [clojure.data.json :as json]
            [clojure.set]
            [clojure.string :as str]
            [clojure.java.io :as io]))

(defonce server (atom nil))

(defn- params [{:keys [query-string]}]
  (into {} (for [kv (str/split (or query-string "") #"&") :when (seq kv)
                 :let [[k v] (str/split kv #"=" 2)]]
             [(keyword k) (java.net.URLDecoder/decode (or v "") "UTF-8")])))

(defn- json-resp [data]
  {:status 200 :headers {"content-type" "application/json" "access-control-allow-origin" "*"}
   :body (json/write-str data)})

(defn- feature [geometry props] {:type "Feature" :geometry geometry :properties props})
(defn- fc [features] {:type "FeatureCollection" :features (vec features)})

(defn areas [{:keys [city level]}]
  (let [db (store/db)
        city (keyword (or city "stuttgart")) level (keyword (or level "stadtteil"))
        rows (d/q '[:find ?e ?n ?g ?code
                    :in $ ?city ?level
                    :where [?e :area/city ?city] [?e :area/level ?level]
                           [?e :entity/name ?n] [?e :entity/geometry ?g]
                           [(get-else $ ?e :area/code "") ?code]] db city level)
        area-ids (mapv first rows)
        counts (if (seq area-ids)
                 (reduce (fn [m [area kind n]] (assoc-in m [area (name kind)] n))
                         {}
                         (d/q '[:find ?area ?kind (count ?entity)
                                :in $ [?area ...]
                                :where [?entity :entity/area ?area]
                                       [?entity :entity/kind ?kind]]
                              db area-ids))
                 {})
        ;; :with ?cell preserves one contribution per cell when multiple cells
        ;; have the same population value; otherwise Datalog's set semantics
        ;; collapse equal ?population bindings before summing.
        populations (if (and (= city :stuttgart) (seq area-ids))
                      (into {}
                            (d/q '[:find ?area (sum ?population)
                                   :with ?cell
                                   :in $ [?area ...]
                                   :where [?cell :entity/area ?area]
                                          [?cell :cell/population ?population]]
                                 db area-ids))
                      {})]
    (fc (for [[e n g code] rows]
          (feature (geo/parse-geojson g)
                   (cond-> {:eid e :name n :code code :counts (get counts e {})}
                     (= city :stuttgart) (assoc :population (get populations e))))))))

(def point-props
  {:licence [:licence/type :licence/employees :licence/status :licence/year]
   :storefront [:storefront/category :storefront/year :storefront/store-id]
   :poi [:osm/shop :osm/amenity :osm/office]
   :place [:place/category :place/confidence :place/brand]
   :building [:osm/building :osm/levels]
   :parcel []
   :cell [:cell/population :cell/rent]})

(defn points [{:keys [kind area year]}]
  (let [db (store/db)
        kind (keyword kind)
        base '[:find ?e ?lon ?lat :in $ ?k ?a :where [?e :entity/kind ?k] [?e :entity/area ?a] [?e :entity/lon ?lon] [?e :entity/lat ?lat]]
        rows (d/q base db kind (Long/parseLong area))
        year (some-> year Long/parseLong)
        yattr (case kind :storefront :storefront/year :licence :licence/year nil)]
    (fc (for [[e lon lat] rows
              :let [ent (d/entity db e)]
              :when (or (nil? year) (nil? yattr) (= year (get ent yattr)))
              :when (or (not= kind :licence) (= "Issued" (:licence/status ent)))]
          (feature {:type "Point" :coordinates [lon lat]}
                   (into {:eid e :kind (name kind) :name (:entity/name ent) :address (:entity/address ent)
                          :links (+ (count (:entity/same-as ent))
                                    (count (d/q '[:find [?x ...] :in $ ?e :where [?x :entity/same-as ?e]] db e)))}
                         (for [a (point-props kind) :let [v (get ent a)] :when (some? v)] [(name a) v])))))))

(defn cells [{:keys [city]}]
  (let [db (store/db)
        city (keyword (or city "stuttgart"))
        rows (d/q '[:find ?e ?lon ?lat ?p
                    :in $ ?city
                    :where [?e :entity/kind :cell]
                           [?e :entity/area ?area]
                           [?area :area/city ?city]
                           [?e :entity/lon ?lon]
                           [?e :entity/lat ?lat]
                           [?e :cell/population ?p]] db city)]
    (fc (for [[e lon lat p] rows]
          (let [ent (d/entity db e)]
            (feature {:type "Point" :coordinates [lon lat]}
                     {:eid e :population p :rent (:cell/rent ent)
                      :area-eid (:db/id (:entity/area ent))
                      :area-name (:entity/name (:entity/area ent))}))))))

(defn- json-val
  "Datahike entities (refs) render as their :db/id; instants as ISO-8601."
  [v]
  (cond
    (or (set? v) (sequential? v)) (mapv json-val v)
    (instance? java.util.Date v) (str (.toInstant ^java.util.Date v))
    (or (nil? v) (string? v) (number? v) (keyword? v) (boolean? v)) v
    (instance? clojure.lang.ILookup v) (or (:db/id v) (str v))
    :else v))

(defn- receipt
  "The acquisition receipt behind one record, through :entity/acq. Provenance is
   not decoration: the model may only use claims dated before the outcome window
   (the temporal-leakage trap in doc/simulator.md), so every card carries the
   dataset it came from and when that dataset was fetched."
  [db ent]
  (when-let [a (:entity/acq ent)]
    (let [a (if (number? a) (d/entity db a) a)
          src (:acq/source a)]
      (cond-> {}
        (:acq/dataset a)    (assoc "acq/dataset" (:acq/dataset a))
        (:acq/url a)        (assoc "acq/url" (:acq/url a))
        (:acq/fetched-at a) (assoc "acq/fetched-at" (str (.toInstant ^java.util.Date (:acq/fetched-at a))))
        (:source/id src)    (assoc "acq/source" (str (symbol (:source/id src))))
        (:source/name src)  (assoc "acq/source-name" (:source/name src))))))

(defn entity [eid]
  (let [db (store/db)
        e (d/entity db (Long/parseLong eid))
        ->m (fn [ent] (into {} (for [[k v] ent :when (not= k :entity/geometry)]
                                [(str (namespace k) "/" (name k)) (json-val v)])))
        links (concat (:entity/same-as e)
                      (map #(d/entity db (:db/id %)) (d/q '[:find [?x ...] :in $ ?e :where [?x :entity/same-as ?e]] db (:db/id e))))]
    {:entity (assoc (->m e) "db/id" (:db/id e) "acq" (receipt db e))
     :links (for [l links :let [l (if (number? l) (d/entity db l) l)]]
              (assoc (->m l) "db/id" (:db/id l) "acq" (receipt db l)))}))

(defn summary [{:keys [area]}]
  (let [db (store/db) a (Long/parseLong area)]
    {:kinds (into {} (map (fn [[k c]] [(name k) c])) (d/q '[:find ?k (count ?x) :in $ ?a :where [?x :entity/area ?a] [?x :entity/kind ?k]] db a))
     :storefront-categories (into {} (map (fn [[k c]] [k c])) (d/q '[:find ?c (count ?e) :in $ ?a :where [?e :entity/area ?a] [?e :storefront/year 2024] [?e :storefront/category ?c]] db a))
     :licence-types (->> (d/q '[:find ?t (count ?e) (sum ?emp) :in $ ?a
                                :where [?e :entity/area ?a] [?e :licence/year 2025] [?e :licence/status "Issued"] [?e :licence/type ?t]
                                       [(get-else $ ?e :licence/employees 0.0) ?emp]] db a)
                         (sort-by second >) (take 20) (map (fn [[t n emp]] {:type t :count n :employees emp})))
     :place-categories (->> (d/q '[:find ?c (count ?e) :in $ ?a :where [?e :entity/area ?a] [?e :place/category ?c]] db a) (sort-by second >) (take 20))
     :lots-by-zoning (->> (d/q '[:find ?z (count ?e) (sum ?lv) (sum ?iv) :in $ ?a
                                 :where [?e :lot/parcel ?p] [?p :entity/area ?a] [?e :parcel/zoning-class ?z] [?e :parcel/land-value ?lv] [?e :parcel/improvement-value ?iv]] db a)
                          (map (fn [[z n lv iv]] {:zoning z :lots n :land-value lv :improvement-value iv})))}))

(defn firms
  "Resolved business clusters in an area: connected components over
   :entity/same-as among storefronts, licences, places and pois, one firm per
   component with merged attributes. Rental licences excluded."
  [{:keys [area year]}]
  (let [db (store/db) a (Long/parseLong area) year (Long/parseLong (or year "2025"))
        kinds #{:storefront :licence :place :poi}
        ents (d/q '[:find ?e ?k :in $ ?a [?k ...] :where [?e :entity/area ?a] [?e :entity/kind ?k]] db a kinds)
        keep? (fn [e k] (let [ent (d/entity db e)]
                          (case k
                            :storefront (and (= year (:storefront/year ent)) (not (str/starts-with? (or (:entity/name ent) "") "Vacant")))
                            :licence (and (= year (:licence/year ent)) (= "Issued" (:licence/status ent))
                                          (not (#{"Long-term Rental" "Short-term Rental Operator"} (:licence/type ent))))
                            true)))
        nodes (set (for [[e k] ents :when (keep? e k)] e))
        edges (filter (fn [[_ y]] (nodes y)) (d/q '[:find ?x ?y :in $ [?x ...] :where [?x :entity/same-as ?y]] db nodes))
        adj (reduce (fn [m [x y]] (-> m (update x (fnil conj #{}) y) (update y (fnil conj #{}) x))) {} edges)
        comps (loop [todo nodes seen #{} out []]
                (if (empty? todo) out
                    (let [start (first todo)
                          comp (loop [stack [start] c #{}]
                                 (if (empty? stack) c
                                     (let [x (peek stack) stack (pop stack)]
                                       (if (c x) (recur stack c)
                                           (recur (into stack (remove c (adj x))) (conj c x))))))]
                      (recur (clojure.set/difference todo comp) (into seen comp) (conj out comp)))))
        merged (for [c comps
                     :let [es (map #(d/entity db %) c)
                           by-kind (group-by :entity/kind es)
                           lic (first (sort-by #(- (or (:licence/employees %) 0)) (:licence by-kind)))
                           sf (first (:storefront by-kind)) pl (first (:place by-kind))
                           pos (first (filter #(and (:entity/lon %) (:entity/lat %)) [sf lic pl (first (:poi by-kind))]))]
                     :when pos]
                 {:eids (vec c)
                  :name (or (:entity/name sf) (:entity/name lic) (:entity/name pl))
                  :lon (:entity/lon pos) :lat (:entity/lat pos)
                  :licence-type (:licence/type lic) :employees (:licence/employees lic)
                  :storefront-category (:storefront/category sf)
                  :place-category (:place/category pl)
                  :website (first (:place/website pl))
                  :kinds (mapv name (keys by-kind))})]
    {:firms (vec merged) :count (count merged) :nodes (count nodes)}))

(defn- static [path]
  (let [p (if (= path "/") "/index.html" path)
        f (io/file (str "public" p))]
    (when (.isFile f)
      {:status 200 :headers {"content-type" (cond (str/ends-with? p ".html") "text/html" (str/ends-with? p ".js") "application/javascript" (str/ends-with? p ".css") "text/css" :else "application/octet-stream")}
       :body f})))

(defn handler [{:keys [uri] :as req}]
  (try
    (let [q (params req)]
      (cond
        (= uri "/api/areas") (json-resp (areas q))
        (= uri "/api/points") (json-resp (points q))
        (= uri "/api/cells") (json-resp (cells q))
        (= uri "/api/summary") (json-resp (summary q))
        (= uri "/api/firms") (json-resp (firms q))
        (str/starts-with? uri "/api/entity/") (json-resp (entity (subs uri 12)))
        :else (or (static uri) {:status 404 :body "not found"})))
    (catch Exception e
      {:status 500 :headers {"content-type" "text/plain"} :body (str (.getMessage e) "\n" (with-out-str (.printStackTrace e)))})))

(defn start! [& {:keys [port ip] :or {port 8090 ip "127.0.0.1"}}]
  (when @server (@server))
  (reset! server (http/run-server #'handler {:port port :ip ip}))
  (str "http://localhost:" port))

(defn stop! [] (when @server (@server) (reset! server nil)))
