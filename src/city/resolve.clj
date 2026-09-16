(ns city.resolve
  "Name similarity for matching records of the same business across sources.
   `name-sim` is the larger of token Jaccard and Jaro-Winkler on normalised
   names; `city.synth.anchors` uses it to match named employers to firms in
   the synthetic register when no site polygon contains them."
  (:require [clojure.set :as set]
            [clojure.string :as str]))

;; ---- normalization ----------------------------------------------------------

(def ^:private name-stop
  #{"inc" "ltd" "the" "and" "of" "co" "corp" "llp" "limited" "company" "incorporated" "holdings" "enterprises"})

(defn norm-name [s]
  (->> (str/split (str/lower-case (or s "")) #"[^a-z0-9]+")
       (remove #(or (str/blank? %) (name-stop %)))
       (str/join " ")))

;; ---- string metrics ---------------------------------------------------------

(defn jaccard [a b]
  (let [a (set (str/split a #" ")) b (set (str/split b #" "))
        u (count (set/union a b))]
    (if (zero? u) 0.0 (/ (double (count (set/intersection a b))) u))))

(defn jaro [^String s ^String t]
  (let [ls (count s) lt (count t)]
    (if (or (zero? ls) (zero? lt))
      0.0
      (let [window (max 0 (dec (quot (max ls lt) 2)))
            sm (boolean-array ls) tm (boolean-array lt)
            matches (loop [i 0 m 0]
                      (if (= i ls) m
                          (let [lo (max 0 (- i window)) hi (min lt (+ i window 1))
                                j (loop [j lo] (cond (>= j hi) nil
                                                     (and (not (aget tm j)) (= (.charAt s i) (.charAt t j))) j
                                                     :else (recur (inc j))))]
                            (if j (do (aset sm i true) (aset tm j true) (recur (inc i) (inc m)))
                                (recur (inc i) m)))))]
        (if (zero? matches)
          0.0
          (let [s-chars (for [i (range ls) :when (aget sm i)] (.charAt s i))
                t-chars (for [j (range lt) :when (aget tm j)] (.charAt t j))
                transpositions (/ (count (filter false? (map = s-chars t-chars))) 2.0)
                m (double matches)]
            (/ (+ (/ m ls) (/ m lt) (/ (- m transpositions) m)) 3.0)))))))

(defn jaro-winkler [s t]
  (let [j (jaro s t)
        prefix (count (take-while true? (map = s t)))
        l (min 4 prefix)]
    (+ j (* l 0.1 (- 1.0 j)))))

(defn name-sim
  "max of token Jaccard and Jaro-Winkler on normalized names; also compares
   the space-free forms so 'heart breaker' ~ 'heartbreaker'."
  [a b]
  (let [na (norm-name a) nb (norm-name b)]
    (if (or (str/blank? na) (str/blank? nb))
      0.0
      (let [jw (max (jaro-winkler na nb)
                    (jaro-winkler (str/replace na " " "") (str/replace nb " " "")))]
        ;; Jaro-Winkler is only informative when high; below 0.85 it says
        ;; little about unrelated business names, so token overlap decides.
        (max (jaccard na nb) (if (>= jw 0.85) jw 0.0))))))
