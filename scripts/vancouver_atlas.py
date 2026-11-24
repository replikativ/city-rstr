"""Build a census-constrained household roster and a complete synthetic weekday by resident ID."""
import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from scripts.vancouver_basemap import basemap

SEED = 2021
AGE_IDS = [[10,11],[12],[14],[15],[16],[17],[18],[19],[20],[21],[22,23],[25,26],[27,28,29]]
AGES = ["0–9","10–14","15–19","20–24","25–29","30–34","35–39","40–44","45–49","50–54","55–64","65–74","75+"]
BANDS = [[0,1],[2,3],[4,5,6,7],[8,9,10],[11,12]]
DAY_AGE = [None,None,"a15-24","a15-24","a25-34","a25-34","a35-44","a35-44","a45-54","a45-54","a55-64","a65-74","a75+"]
INCOME = [[156,158,159,160],[161,162,163],[164,165,166,167],[168]]
ROSTER_CELLS = {1, 5, 8, 9, 10, 11, 12, 50, 51, 52, 53, 54, 55, 56, 155, 168, 1414, 1415, 2223, 2225, 2226}
ROSTER_CELLS.update(i for group in AGE_IDS + INCOME for i in group)
FIELDS = ["age","gender","labour","income","school","occupation","commute"]
LABELS = ["Age 0–14","Age 15–24","Age 25–44","Age 45–64","Age 65+",
          "Owner households","Employed","Unemployed","Income below $30k","Income $30–59k","Income $60–99k","Income $100k+",
          "Employed · women+","Employed · men+","One-person households","Two-person households","Three-person households",
          "Four-person households","Households of five or more","Women+ in private households",
          "Income $100k+ · women+","Income $100k+ · men+"]


def largest_remainder(expected, total):
    if total == 0:
        return np.zeros(len(expected), dtype=int)
    p = np.asarray(expected, dtype=float)
    if sum(p) <= 0:
        raise ValueError("No support for positive allocation")
    x = p / p.sum() * total
    result = np.floor(x).astype(int)
    result[np.argsort(-(x-result), kind="stable")[:total-int(result.sum())]] += 1
    return result


def size_plan(homes, persons, targets, prior):
    """Keep whole donor rosters while satisfying both population and occupied dwelling counts."""
    sizes = np.arange(1,len(prior)+1)
    if not homes:
        return np.zeros_like(sizes)
    if not homes <= persons <= homes*len(prior):
        raise ValueError("Infeasible private population")
    p = np.asarray(prior,dtype=float).copy()
    if sum(targets):
        p[:4] = targets[:4]
        p[4:] *= targets[4]/p[4:].sum()
    expected = homes*p/p.sum()
    counts = largest_remainder(p,homes)
    gap = persons - int(counts @ sizes)
    step = 1 if gap>0 else -1
    for _ in range(abs(gap)):
        # Prefer the transfer with smallest increase in weighted squared deviation.
        choices = [i for i,n in enumerate(counts) if n and 0<=i+step<len(p)]
        def loss(i):
            j = i+step
            return ((1-2*(counts[i]-expected[i]))/(expected[i]+1)
                    + (1+2*(counts[j]-expected[j]))/(expected[j]+1))
        i = min(choices,key=loss)
        counts[i] -= 1
        counts[i+step] += 1
    return counts


def census(row, ids, col=0):
    cells = [row["m"][str(i)][col] for i in ids]
    return None if any(v is None for v in cells) else int(sum(cells))


def fractions(row):
    specs = [(sum((AGE_IDS[i] for i in band),[]),[8],0) for band in BANDS]
    specs += [([1415],[1414],0),([2225],[2223],0),([2226],[2223],0)]
    specs += [(ids,[155],0) for ids in INCOME]
    specs += [([2225],[2223],g) for g in [2,1]]  # profile order is total, men+, women+
    specs += [([i],[50],0) for i in range(51,56)]
    refs = [(census(row,num,col), census(row,den,col)) for num,den,col in specs]
    refs.append((census(row,[56],2), census(row,[56])))
    refs.extend((census(row,[168],g),census(row,[155],g)) for g in (2,1))
    return refs


def adult(p):
    # A masked age can still have observed fields restricted to ages 15+.
    return 3 <= p[0] <= 13 or (p[0] == 88 and (p[2] != 0 or p[4] in (0,1) or p[3] is not None))


def features(members,tenure):
    ages = Counter(p[0] for p in members)
    group = [sum(ages[i+1] for i in band) for band in BANDS]
    emp = [sum(p[2]==code for p in members) for code in (1,2)]
    inc = [sum(p[3] is not None and adult(p) and lo<=p[3]<hi for p in members)
           for lo,hi in zip([-math.inf,30000,60000,100000],[30000,60000,100000,math.inf])]
    return group+[int(tenure==1)]+emp+inc+[sum(p[1]==1 for p in members)]


def donor_person(r):
    age, labour, income = (int(r[k]) for k in ("AGEGRP","LFACT","TOTINC"))
    status = 1 if 1<=labour<=2 else 2 if 3<=labour<=10 else 3 if 11<=labour<=14 else 0
    return [age,int(r["GENDER"]),status,None if income in (88888888,99999999) else income,
            int(r["ATTSCH"]),int(r["NOC21"]),int(r["MODE"])]


def donors(file):
    rosters = defaultdict(list)
    with file.open() as f:
        for r in csv.DictReader(f):
            if r["CMA"] != "933":
                continue
            rosters[int(r["HH_ID"])].append((int(r["PP_ID"]),int(r["TENUR"]),float(r["WEIGHT"]),donor_person(r)))
    records, weights, sizes, matrix = [],[],[],[]
    for hh in sorted(rosters):
        rows = sorted(rosters[hh])
        people = [r[-1] for r in rows]
        tenure = rows[0][1]
        records.append((tenure,people))
        weights.append(rows[0][2])
        sizes.append(len(people))
        matrix.append(features(people,tenure))
    # Some rare large sizes have no donor. Use the contiguous supported range.
    top = 1
    support = set(sizes)
    while top+1 in support:
        top += 1
    idx = np.flatnonzero(np.asarray(sizes)<=top)
    return ([records[i] for i in idx],np.array(weights)[idx],np.array(sizes)[idx],np.array(matrix,dtype=float)[idx])


def draw_homes(counts, persons, refs, private_adult_share, pool, rng):
    records,weights,sizes,x = pool
    if not counts.sum():
        return []
    controls = refs[:12]+[refs[19]]
    valid = np.array([d is not None and d>0 and n is not None for n,d in controls])
    adults = persons*(1-refs[0][0]/refs[0][1]) if refs[0][1] and refs[0][0] is not None else persons*.85
    if private_adult_share is not None:
        adults = persons*private_adult_share
    scale = [persons]*5+[sum(counts)]+[adults]*6+[persons]
    target = np.array([n/d*s if ok else 0 for (n,d),ok,s in zip(controls,valid,scale,strict=True)])[valid]
    a = np.ascontiguousarray(x[:,valid])
    logw = np.log(weights)
    def distribution(theta):
        logits = logw + np.einsum("ij,j->i",a,theta)
        shift = logits.max()
        w = np.exp(logits-shift)
        z = np.bincount(sizes,weights=w,minlength=len(counts)+1)[1:]
        return shift,z,w*counts[sizes-1]/z[sizes-1]
    def objective(theta):
        shift,z,w = distribution(theta)
        # Regularized exponential calibration conditional on exact household size.
        value = shift + (np.log(z)@counts - target@theta)/counts.sum() + .003*(theta@theta)
        gradient = (np.einsum("i,ij->j",w,a)-target)/counts.sum()+.006*theta
        return value,gradient
    theta = minimize(objective,np.zeros(len(target)),method="L-BFGS-B",jac=True,
                     bounds=[(-5,5)]*len(target),options={"maxiter":80}).x if len(target) else np.empty(0)
    _,_,w = distribution(theta)
    selected = []
    for size,n in enumerate(counts,1):
        if n:
            ix = np.flatnonzero(sizes==size)
            ix = rng.permutation(ix)
            cdf = np.cumsum(w[ix]); cdf /= cdf[-1]
            selected.extend(ix[np.searchsorted(cdf,(rng.random()+np.arange(n))/n)])
    return [records[i] for i in rng.permutation(selected)]


class Weekday:
    def __init__(self, diaries):
        self.templates = []
        self.buckets = defaultdict(list)
        for d in diaries:
            idx = self.add("Urban BC weekday diary (15+)",d["episodes"])
            if "goods" in d:
                self.templates[idx]["goods"] = d["goods"]
            roles = {"any",d["role"]}
            if d["role"] in {"home","retired","other"}:
                roles.add("nonworker")
            for age in (d["age"],"masked"):
                for role in roles:
                    self.buckets[age,role].append((idx,d["weight"]))
        self.cdfs = {}
        for key,entries in self.buckets.items():
            ids,w = zip(*entries)
            self.cdfs[key] = (ids,np.cumsum(w))
        self.childhome = self.add("Illustrative home-care weekday",[[240,180,"sleep","home"],[420,780,"home-care","home"],[1200,480,"sleep","home"]])
        self.school = self.add("Illustrative school weekday",[[240,180,"sleep","home"],[420,90,"personal-care","home"],
            [510,30,"travel","travel-ns"],[540,360,"study","work-or-school"],[900,30,"travel","travel-ns"],
            [930,330,"leisure","home"],[1260,420,"sleep","home"]])
        self.unknown = self.add("Age unavailable",[[240,1440,"unknown","unknown"]])

    def add(self,source,episodes):
        cursor = 240
        for start,dur,*_ in episodes:
            if start!=cursor or dur<=0:
                raise ValueError("Incomplete activity chain")
            cursor+=dur
        if cursor!=1680:
            raise ValueError("Weekday must cover 24 hours")
        self.templates.append({"source":source,"episodes":episodes})
        return len(self.templates)-1

    def assign(self,p,rng,school_share,under15_school_share):
        age,_,labour,_,school,*_=p
        if age==88 and school==9 and not labour:
            return self.school if rng.random()<under15_school_share else self.childhome
        if age not in range(1,14) and not (age==88 and (labour or school in (0,1))):
            return self.unknown
        if age<=2:
            return self.school if age==2 or rng.random()<school_share else self.childhome
        ids,cdf = self.cdfs[self.donor_key(age, labour, school)]
        return ids[np.searchsorted(cdf,rng.random()*cdf[-1])]

    def donor_key(self, age, labour, school):
        role = "worker" if labour==1 else "student" if school==1 else "nonworker" if labour in (2,3) else "any"
        key = ("masked" if age==88 else DAY_AGE[age-1],role)
        return key if key in self.cdfs else (key[0], "any")


def write_json(file, obj):
    file.write_text(json.dumps(obj,separators=(",",":"),ensure_ascii=False,allow_nan=False))


def sums(rows):
    keys = ("population","homes","private","unresolved","legacy","rawPrivate","rawHomes","unknownAge")
    out = {k:sum(r[k] for r in rows) if all(r[k] is not None for r in rows) else None for k in keys}
    out["fit"] = [[sum(r["fit"][i][j] for r in rows) for j in range(5)] for i in range(len(LABELS))]
    # Deserialised city rosters use JSON object keys, while newly drawn rosters use integers.
    days = Counter()
    for row in rows:
        for template, count in row["days"].items():
            days[int(template)] += count
    if sum(days.values()) != out["population"]:
        raise ValueError("Weekday diary counts do not cover the combined population")
    out["days"] = dict(days)
    return out


def neighbourhood_geometry(archive):
    folder = archive / "data/raw/vancouver-ods"
    receipt, = [p for p in folder.glob("*.geojson.receipt.edn") if ':dataset "local-area-boundary"' in p.read_text()]
    shapes = json.loads(Path(str(receipt).removesuffix(".receipt.edn")).read_bytes())["features"]
    return {feature["properties"]["name"]: feature["geometry"] for feature in shapes}


def build(archive, output, days, *, derived=None, area_geometry=None, map_data=None):
    derived = derived or archive/"data/derived"
    pool = donors(archive/"data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv")
    prior = np.bincount(pool[2],weights=pool[1])[1:]
    legacy = Counter()
    da_key = re.compile(r':da "(\d+)"')
    if area_geometry is None:
        with (archive/"data/derived/synth_vancouver_persons.edn").open() as f:
            for line in f:
                legacy[da_key.search(line)[1]]+=1
    with (derived/"vancouver_da_boundaries.jsonl").open() as f:
        boundaries = {r["dauid"]:r["geometry"] for r in map(json.loads,f)}
    data = {}
    areas = defaultdict(list)
    with (derived/"vancouver_da_marginals.jsonl").open() as f:
        for line in f:
            row=json.loads(line); da=row["dauid"]
            if da in data:
                raise ValueError("Duplicate geography")
            refs=fractions(row)
            n=census(row,[1]); homes=census(row,[5]); raw=census(row,[56])
            private = min(n,homes*len(prior),max(homes,raw if raw is not None else homes))
            rng=np.random.default_rng([SEED,int(da)]); clock_rng=np.random.default_rng([SEED,int(da),1])
            sizes=size_plan(homes,private,[census(row,[i]) or 0 for i in range(51,56)],prior)
            adult_reference=census(row,[155])
            share=min(1,adult_reference/raw) if raw and adult_reference is not None else None
            drawn=draw_homes(sizes,private,refs,share,pool,rng)
            residents,groups=[],[]
            age_counts=Counter();day_counts=Counter()
            def person(p):
                template=days.assign(p,clock_rng,school_share,under15_school_share)
                age_counts[p[0]]+=1;day_counts[template]+=1
                residents.append([*p,template])
            children=census(row,[10,11])
            school_share=min(1,census(row,[11])/children) if children else .5
            under15=census(row,[9])
            under15_school_share=min(1,census(row,[11,12])/under15) if under15 else .67
            feat=np.zeros(13,dtype=int)
            for tenure,members in drawn:
                groups.append([len(residents),len(members),tenure])
                feat+=features(members,tenure)
                for p in members:
                    person(p)
            if len(residents)!=private or len(groups)!=homes:
                raise ValueError("Private-household totals disagree")
            missing=n-private
            target=[census(row,ids) for ids in AGE_IDS]
            gap=np.maximum(0,np.array([v or 0 for v in target])-[age_counts[i] for i in range(1,14)])
            if missing:
                if gap.sum():
                    ages=np.repeat(np.arange(1,14),largest_remainder(gap,missing))
                else:
                    ages=np.full(missing,88)
                for age in rng.permutation(ages):
                    person([int(age),8,0,None,8,99,9])
            if len(residents)!=n:
                raise ValueError("Resident count mismatch")
            adults=sum(adult(p) for p in residents[:private])
            genders=[ [p for p in residents[:private] if p[1]==g and adult(p)] for g in (1,2)]
            age_mix=[sum(age_counts[i+1] for i in band) for band in BANDS]
            modeled=age_mix+list(map(int,feat[5:12]))+[sum(p[2]==1 for p in ps) for ps in genders]+list(map(int,sizes[:4]))+[int(sum(sizes[4:]))]
            modeled+=[int(feat[12])]+[sum(p[3] is not None and p[3]>=100000 for p in ps) for ps in genders]
            denominators=[n]*5+[homes]+[adults]*6+[len(ps) for ps in genders]+[homes]*5+[private]+[len(ps) for ps in genders]
            fit=[[m,d,c,t,1] if c is not None and t is not None and t>0 else [0,0,0,0,0]
                 for (c,t),m,d in zip(refs,modeled,denominators,strict=True)]
            data[da]=dict(population=n,homes=homes,private=private,unresolved=missing,legacy=legacy[da],
                          rawPrivate=raw,rawHomes=census(row,[50]),unknownAge=age_counts[88],fit=fit,days=dict(day_counts))
            areas[row["local_area"]].append(da)
            write_json(output/(da+".json"),{"homes":groups,"people":residents,"geometry":boundaries[da]})
    geometry = area_geometry if area_geometry is not None else neighbourhood_geometry(archive)
    if set(geometry)!=set(areas):
        raise ValueError("Boundary and population neighbourhoods differ")
    manifest=dict(labels=LABELS,heldout=[12,13,20,21],ages=AGES,fields=FIELDS+["day"],seed=SEED,templates=days.templates,
                  city=sums(list(data.values())),areas={k:dict(**sums([data[d] for d in ds]),das=sorted(ds),geometry=geometry[k]) for k,ds in areas.items()},
                  das=data)
    write_json(output/"basemap.json",map_data if map_data is not None else basemap(archive/"data/raw"))
    write_json(output/"atlas.json",manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--output",type=Path,default=Path("public/data/vancouver/atlas"))
    parser.add_argument("--geography",type=Path,default=Path("data/mobility/2021_92-151_X.zip"))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temp:
        root=Path(temp)
        diaries=json.loads(subprocess.check_output(["clojure","-M","-m","city.vancouver.atlas-diaries",str(args.archive)]))
        folder=root/"population";folder.mkdir()
        from scripts.vancouver_municipal import prepare
        from scripts.vancouver_census_geography import publish as publish_boundary
        derived=root/"census";derived.mkdir()
        boundary=prepare(args.archive,derived,args.geography)
        manifest=build(args.archive,folder,Weekday(diaries),derived=derived)
        h=hashlib.sha256()
        for file in sorted(folder.iterdir()):
            h.update(file.name.encode());h.update(file.read_bytes())
        version=h.hexdigest()[:20]
        dest=args.output/version
        if not dest.exists():
            folder.rename(dest)
        from scripts.vancouver_population_check import publish as check_population
        check_population(args.archive, dest)
        publish_boundary(args.output, version, boundary)
        pointer=root/"current.json";write_json(pointer,{"version":version});pointer.replace(args.output/"current.json")
        print(version,len(manifest["das"]),manifest["city"]["population"],manifest["city"]["homes"])

if __name__=="__main__":
    main()
