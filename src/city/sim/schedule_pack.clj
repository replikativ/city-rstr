(ns city.sim.schedule-pack
  "Versioned, portable prepared resident schedules. Integers are big-endian."
  (:require [clojure.edn :as edn]
            [clojure.java.io :as io])
  (:import [java.io BufferedInputStream BufferedOutputStream DataInputStream DataOutputStream]
           [java.util.zip GZIPInputStream GZIPOutputStream]))

(defn write-pack! [file prepared]
  (with-open [out (DataOutputStream. (BufferedOutputStream. (GZIPOutputStream. (io/output-stream file))))]
    (.writeUTF out "city-rstr/weighted-schedules/1")
    (.writeUTF out (pr-str (dissoc prepared :batches :reference)))
    (.writeInt out (count (:batches prepared)))
    (doseq [{:keys [weights offsets starts ends]} (:batches prepared)]
      (.writeInt out (alength ^ints weights))
      (dotimes [i (alength ^ints weights)]
        (.writeInt out (aget ^ints weights i))
        (.writeInt out (- (aget ^ints offsets (inc i)) (aget ^ints offsets i)))
        (doseq [j (range (aget ^ints offsets i) (aget ^ints offsets (inc i)))]
          (.writeInt out (aget ^ints ends j)))))))

(defn read-pack
  "Reconstitute packed columns from interval ends and validate the day partition."
  [file]
  (with-open [in (DataInputStream. (BufferedInputStream. (GZIPInputStream. (io/input-stream file))))]
    (when-not (= "city-rstr/weighted-schedules/1" (.readUTF in))
      (throw (ex-info "Unknown schedule format" {})))
    (let [{:keys [population areas] :as meta} (edn/read-string (.readUTF in))
          zones (count areas) n (.readInt in) total (volatile! 0)]
      (when-not (and (pos? zones) (nat-int? population) (<= 0 n population))
        (throw (ex-info "Invalid schedule metadata" {})))
      (let [batches
            (mapv (fn [_]
                    (let [size (.readInt in)]
                      (when-not (<= 1 size (- population @total))
                        (throw (ex-info "Invalid schedule batch" {:size size})))
                      (let [weights (int-array size) offsets (int-array (inc size))
                            paths (object-array size) longest (volatile! 0)]
                        (dotimes [i size]
                          (let [w (.readInt in) parts (.readInt in)]
                            (when-not (and (<= 1 w (- population @total)) (<= 1 parts 1440))
                              (throw (ex-info "Invalid weighted schedule" {:weight w :parts parts})))
                            (vswap! total + w) (vswap! longest max parts)
                            (aset weights i w) (aset offsets (inc i) (+ (aget offsets i) parts))
                            (let [ends (int-array parts)]
                              (loop [j 0 prev 0]
                                (if (< j parts)
                                  (let [v (.readInt in) t (quot v zones)]
                                    (when-not (< prev t 1441) (throw (ex-info "Invalid interval end" {:end t})))
                                    (aset ends j v) (recur (inc j) t))
                                  (when-not (= 1440 prev) (throw (ex-info "Incomplete day" {})))))
                              (aset paths i ends))))
                        (let [ends (int-array (aget offsets size)) starts (int-array (alength ends))]
                          (dotimes [i size]
                            (let [^ints path (aget paths i) k (aget offsets i)]
                              (System/arraycopy path 0 ends k (alength path))
                              (dotimes [j (alength path)]
                                (aset starts (+ j k) (+ (rem (aget path j) zones)
                                                       (if (zero? j) 0 (* zones (quot (aget path (dec j)) zones))))))))
                          {:weights weights :offsets offsets :ids (int-array (range size))
                           :max-parts @longest :starts starts :ends ends})))) (range n))]
        (when-not (and (= @total population) (= -1 (.read in))) (throw (ex-info "Schedule pack does not balance" {})))
        (assoc meta :batches batches)))))
