(ns city.intake.overpass
  "OpenStreetMap via the Overpass API. ODbL — attribution required."
  (:require [city.intake.core :as acq]
            [clojure.data.json :as json]
            [clojure.string :as str]))

(def endpoint "https://overpass.kumi.systems/api/interpreter")

(defn bbox-str [{:keys [south west north east]}]
  (str "(" south "," west "," north "," east ")"))

(defn pois-and-buildings-query
  "Nodes+ways tagged shop/amenity/office/craft/leisure/tourism, and building ways,
   inside bbox, with geometry centers."
  [bbox]
  (let [b (bbox-str bbox)]
    (str "[out:json][timeout:180];("
         (str/join (for [k ["shop" "amenity" "office" "craft" "leisure" "tourism" "healthcare" "public_transport"]]
                     (str "nwr[\"" k "\"]" b ";")))
         "way[\"building\"]" b ";"
         ");out tags center;")))

(defn acquire-bbox! [bbox & {:keys [note]}]
  (acq/acquire! {:source :osm-overpass :dataset "pois-and-buildings"
                 :url endpoint :ext "json"
                 :body (str "data=" (java.net.URLEncoder/encode (pois-and-buildings-query bbox) "UTF-8"))
                 :note (merge {:bbox bbox} note)}))
