(ns city.sim.world
  "The category vocabulary that decides which firms are retail and food
   venues, and the great-circle metric every distance in the model uses.")

(def food-types #{"Restaurant" "Limited Service Food Establishment" "Liquor Establishment" "Retail Dealer - Food"
                  "Food Processing" "Liquor Retail Store"})

(def retail-place-re #"(?i)store|shop|grocery|supermarket|pharmacy|market|boutique|retail|bakery|liquor|dispensary|florist|bookstore|electronics|clothing|furniture|hardware")

(def retail-storefront #{"Convenience Goods" "Comparison Goods"})

(def retail-licence-re #"(?i)retail|grocery|liquor retail|pharmac")

(def food-place-re #"(?i)restaurant|cafe|coffee|bar|pub|bakery|pizza|sushi|food|deli|bistro|diner|brew|tea")

(defn haversine-m ^double [^double lon1 ^double lat1 ^double lon2 ^double lat2]
  (let [r 6371000.0 dlat (Math/toRadians (- lat2 lat1)) dlon (Math/toRadians (- lon2 lon1))
        a (+ (Math/pow (Math/sin (/ dlat 2)) 2) (* (Math/cos (Math/toRadians lat1)) (Math/cos (Math/toRadians lat2)) (Math/pow (Math/sin (/ dlon 2)) 2)))]
    (* 2 r (Math/asin (Math/sqrt a)))))
