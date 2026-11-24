"""Calibrate intact diaries against overlapping income and home-zone trip margins."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from scripts.vancouver_atlas import Weekday
from scripts.vancouver_diary_fit import coupling, donor_probabilities, draw, features, locate, publish_atlas
from scripts.vancouver_income_travel import BANDS, OBSERVED_2023, SOURCE_2023, roster_bands
from scripts.vancouver_region import read
from scripts.vancouver_survey_zones import geography
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_trip_demand import MODES, SHARES, publish as trip_demand
from scripts.vancouver_zone_check import publish as check_zones

SEED = 20261123
RATE_2023 = 3.03
PENALTY = 0.015


def fit_probabilities(donors, cohorts, x, shares, target_rate):
    """Use weighted donor probabilities with shared income and home-zone constraints."""
    keys = list(cohorts)
    people = np.asarray(list(cohorts.values()),dtype=float)
    mass = people/people.sum()
    group_ids = {group:i for i,group in enumerate(shares)}
    targets = np.asarray(list(shares.values()),dtype=float)
    targets /= targets.sum(axis=1,keepdims=True)
    memberships = np.zeros((len(keys),len(targets)))
    for j,(band,zone,_) in enumerate(keys):
        for group in (("income",band),("zone",zone)):
            if group in group_ids:
                memberships[j,group_ids[group]] = 1
    group_mass = mass @ memberships
    baseline = np.zeros(x.shape[1])
    blocks = []
    for key,(ids,prior) in donors.items():
        use = np.array([i for i,(_,_,k) in enumerate(keys) if k==key])
        values = x[ids]
        baseline += mass[use].sum()*(prior @ values)
        blocks.append((use,ids,prior,values,np.log(prior)))
    urban_target = np.r_[target_rate-baseline[5],baseline[5:]]

    def objective(theta):
        common, effects = theta[:5],theta[5:].reshape(targets.shape)
        # Share constraints are linear in raw mode counts once the target
        # proportion times the sum of the comparable counts is subtracted.
        group_tilts = effects-(effects*targets).sum(axis=1,keepdims=True)
        tilts = np.empty((len(keys),x.shape[1]))
        tilts[:,:5] = common[0]+memberships @ group_tilts
        tilts[:,5:] = common[1:]
        loss = PENALTY*(common @ common + group_mass @ (effects**2).sum(axis=1))/2 - urban_target @ common
        means = np.empty_like(tilts)
        probabilities = []
        for use,ids,prior,values,base in blocks:
            logits = tilts[use] @ values.T + base
            normalizer = logsumexp(logits,axis=1)
            loss += mass[use] @ normalizer
            fitted = np.exp(logits-normalizer[:,None])
            means[use] = fitted @ values
            probabilities.append(fitted)
        known = means[:,:5].sum(axis=1)
        overall = mass @ np.column_stack((known,means[:,5:]))
        per_group = memberships.T @ (mass[:,None]*means[:,:5])
        moments = per_group-targets*per_group.sum(axis=1,keepdims=True)
        gradient = np.r_[overall-urban_target+PENALTY*common,
                         (moments+PENALTY*effects*group_mass[:,None]).ravel()]
        return loss,gradient,probabilities,means

    fit = minimize(lambda t: objective(t)[:2],np.zeros(5+targets.size),jac=True,method="L-BFGS-B",
                   options={"gtol":1e-8,"ftol":1e-13,"maxiter":1200})
    if not fit.success or np.linalg.norm(fit.jac,ord=np.inf)>3e-5:
        raise ValueError("The paired income and home-zone fit did not converge")
    _,_,probabilities,means = objective(fit.x)
    pools = {}
    prior_mix,fitted_mix = np.zeros(len(x)),np.zeros(len(x))
    for (use,ids,prior,_,_), probabilities_by_group in zip(blocks,probabilities,strict=True):
        prior_mix[ids] += mass[use].sum()*prior
        fitted_mix[ids] += mass[use] @ probabilities_by_group
        for i,probs in zip(use,probabilities_by_group,strict=True):
            pools[keys[i]] = coupling(ids,prior,probs)
    return pools, dict(original=baseline.tolist(),calibrated=(mass @ means).tolist(),
                       effectiveDonors=[float(1/(p @ p)) for p in (prior_mix,fitted_mix)])


def publish(root, archive, diary_path, boundaries, income_fit, target_rate):
    parent = read(root/"diary-fit"/(income_fit+".json"))
    base = parent["atlas"]
    day = read(root/"cityday"/parent["locations"]["day"]/"day.json")["diaryFit"]["baselineDay"]
    day_dir = root/"cityday"/day
    directory = root/"atlas"/base
    atlas = read(directory/"atlas.json")
    weekday = Weekday([d for d in read(diary_path) if d["split"]=="fit"])
    if weekday.templates!=atlas["templates"]:
        raise ValueError("The donor pool differs from the pinned diary catalogue")
    geo = geography(boundaries,read(day_dir/"places.json"))
    codes = [str(z["code"]) for z in geo["zones"]]
    shares = {("zone",code):row for code,row in zip(codes,SHARES,strict=True)}
    shares.update({("income",band):row for band,row in enumerate(OBSERVED_2023) if row})
    terms = np.asarray([features(d) for d in atlas["templates"]])

    def residents(da,roster):
        homes = read(day_dir/(da+".json"))["home"]
        bands = roster_bands(roster)
        for i,person in enumerate(roster["people"][:atlas["das"][da]["private"]]):
            age,_,labour,_,school,*_ = person
            if 3<=age<=13:
                zone = geo["zone"][homes[i]] if homes[i]>=0 else -1
                yield i,(bands[i],codes[zone] if zone>=0 else "unknown",weekday.donor_key(age,labour,school)),2 if age==3 else 5

    cohorts = Counter()
    for da in atlas["das"]:
        for _,cohort,weight in residents(da,read(directory/(da+".json"))):
            cohorts[cohort] += weight
    donors = donor_probabilities(weekday,{key for _,_,key in cohorts})
    pools,expected = fit_probabilities(donors,cohorts,terms,shares,target_rate)
    actual = defaultdict(lambda: np.zeros((2,terms.shape[1])))
    changed = Counter()

    def reassign(da,roster):
        rng = np.random.default_rng([SEED,int(da)])
        for i,cohort,weight in residents(da,roster):
            person = roster["people"][i]
            old = person[7]
            new = draw(old,pools[cohort],rng)
            person[7] = new
            changed[cohort[0]] += old!=new
            actual[cohort[0]] += weight*terms[[old,new]]

    fitted = publish_atlas(root,directory,atlas,reassign)
    weights = Counter()
    for (band,_,_),n in cohorts.items():
        weights[band] += n
    results = {}
    for band,weight in weights.items():
        old,new=(actual[band]/weight).tolist()
        results[band] = dict(assigned=dict(original=old,fitted=new),adults=weight/5,changed=changed[band])
    data = dict(atlas=base,fittedAtlas=fitted,incomeFit=income_fit,method="income-and-home-zone",
                source=SOURCE_2023,figure=55,zoneTable=16,targetTripRate=target_rate,seed=SEED,penalty=PENALTY,
                bands=[*BANDS,"Income unresolved"],units=[*MODES,"Other / unspecified","paid-work hours","study hours","sleep hours"],
                results=results,expected=expected)
    versions = locate(root,archive,data,day)
    demand = trip_demand(root,boundaries,versions["day"],fitted)
    original_demand = read(root/"trip-demand"/f"{base}_{day}.json")["version"]
    income_demand = read(root/"trip-demand"/f"{income_fit}_{parent['locations']['day']}.json")["version"]
    check = check_zones(root,original_demand,income_demand,[demand])
    pointer(root/"diary-fit"/(fitted+".json"),dict(data,locations=versions,demand=demand))
    print(fitted,sum(changed.values()),"changed diaries","trip rates",(check["runs"][-1]["cityTrips"]+
          check["runs"][-1]["unclassified"])/check["runs"][-1]["adults"],flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("income_fit")
    parser.add_argument("diaries",type=Path)
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    parser.add_argument("--boundaries",type=Path,default=Path("data/mobility/taz-gvrd.geojson"))
    args=parser.parse_args()
    publish(args.root,args.archive,args.diaries,args.boundaries,args.income_fit,RATE_2023)
