(ns city.geo.core
  "Minimal planar geometry over GeoJSON-shaped data. Enough to assign points
   to areas; a compiled geo-rstr can replace this if it becomes hot."
  (:require [clojure.data.json :as json]))

(defn- ring-contains? [ring [x y]]
  ;; even-odd ray casting; ring = [[lon lat] ...]
  (let [n (count ring)]
    (loop [i 0, j (dec n), inside false]
      (if (= i n)
        inside
        (let [[xi yi] (nth ring i) [xj yj] (nth ring j)
              crosses (and (not= (> yi y) (> yj y))
                           (< x (+ xi (/ (* (- xj xi) (- y yi)) (- yj yi)))))]
          (recur (inc i) i (if crosses (not inside) inside)))))))

(defn polygon-contains?
  "coords = GeoJSON Polygon coordinates: [outer hole1 hole2 ...]"
  [coords pt]
  (and (ring-contains? (first coords) pt)
       (not-any? #(ring-contains? % pt) (rest coords))))

(defn geometry-contains? [{:keys [type coordinates]} pt]
  (case type
    "Polygon" (polygon-contains? coordinates pt)
    "MultiPolygon" (boolean (some #(polygon-contains? % pt) coordinates))
    false))

(defn bbox-of [{:keys [type coordinates]}]
  (let [pts (case type
              "Polygon" (apply concat coordinates)
              "MultiPolygon" (mapcat #(apply concat %) coordinates)
              "Point" [coordinates])]
    {:west (apply min (map first pts)) :east (apply max (map first pts))
     :south (apply min (map second pts)) :north (apply max (map second pts))}))

(defn locate
  "Given [{:name .. :geometry ..}] areas, return the name containing [lon lat]."
  [areas pt]
  (some (fn [{:keys [name geometry bbox]}]
          (when (and (or (nil? bbox)
                         (and (<= (:west bbox) (first pt) (:east bbox))
                              (<= (:south bbox) (second pt) (:north bbox))))
                     (geometry-contains? geometry pt))
            name))
        areas))

(defn with-bbox [area] (assoc area :bbox (bbox-of (:geometry area))))

(defn geojson-str [geometry] (json/write-str geometry))
(defn parse-geojson [s] (json/read-str s :key-fn keyword))
