(ns city.synth.sampling
  (:import [java.util ArrayList Collection Collections Random]))

(defn shuffled [^Random rng items]
  (let [permutation (ArrayList. ^Collection (vec items))]
    (Collections/shuffle permutation rng)
    (vec permutation)))

(defn effective-count [weights]
  (let [total (double (reduce + weights))]
    (if (pos? total) (/ (* total total) (reduce + (map #(* % %) weights))) 0.0)))
