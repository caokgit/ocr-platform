#!/usr/bin/env python3
"""Monthly cost of the AWS track's dev design from AWS's public price list, no account needed (spec C18).

    python3 infra/aws/cost/estimate.py [--cache DIR]

Reads the current Price List files for ap-southeast-1 (EC2 and Compute Savings Plans as CSV, streamed; EKS, RDS
and ELB as JSON) and the Spot Instance Advisor data, keeps only the rows the design uses, and prints a Markdown
report: every unit price with the file version it came from, then three scenarios. Usage amounts (hours, GB,
worker count) are the design's assumptions, listed in USAGE.
"""
import argparse, csv, json, os, sys, time, urllib.request

REGION, LOCATION, PREFIX = "ap-southeast-1", "Asia Pacific (Singapore)", "APS1"
BASE = "https://pricing.us-east-1.amazonaws.com"
SPOT_ADVISOR = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"
HOURS = 730

# What dev runs in a month (the Terraform defaults and the Karpenter NodePools); ASSUMED where marked.
USAGE = {
    "system_nodes": ("m7i.large", 2),        # the managed node group, on-demand only
    "worker_nodes": ("m7i.xlarge", 3),       # ASSUMED: what Karpenter keeps on average for the lab's workloads
    "rds": ("db.t4g.medium", 20),            # instance class, GB of gp3
    "nat_gb": 100,                           # ASSUMED: GB through the NAT gateway (S3 goes by the free endpoint)
    "nlb_lcu": 1,                            # ASSUMED: average load balancer capacity units
}


def fetch(path, cache):
    """Download once into the cache; return the local file."""
    os.makedirs(cache, exist_ok=True)
    local = os.path.join(cache, path.strip("/").replace("/", "_"))
    url = path if path.startswith("http") else BASE + path
    for attempt in range(4):
        if os.path.exists(local):
            break
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(local + ".part", "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            os.rename(local + ".part", local)
        except OSError as e:
            print(f"retrying {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return local


def current(offer, cache, savings_plan=False):
    kind = "savingsPlan/v1.0/aws" if savings_plan else "offers/v1.0/aws"
    index = json.load(open(fetch(f"/{kind}/{offer}/current/region_index.json", cache)))
    if savings_plan:
        return next(r["versionUrl"] for r in index["regions"] if r["regionCode"] == REGION)
    return index["regions"][REGION]["currentVersionUrl"]


def stream_csv(path):
    """Price List CSVs start with five metadata lines, then the header."""
    with open(path, newline="", encoding="utf-8") as f:
        for _ in range(5):
            f.readline()
        yield from csv.DictReader(f)


def ec2_prices(cache):
    url = current("AmazonEC2", cache).replace("index.json", "index.csv")
    wanted = {USAGE["system_nodes"][0], USAGE["worker_nodes"][0]}
    out = {}
    for row in stream_csv(fetch(url, cache)):
        if row["TermType"] != "OnDemand":
            continue
        if row["Product Family"] == "NAT Gateway" and row["Location"] == LOCATION:
            key = "nat_hour" if row["usageType"].endswith("NatGateway-Hours") else "nat_gb" if row["usageType"].endswith("NatGateway-Bytes") else None
            if key:
                out[key] = float(row["PricePerUnit"])
        elif (row["Instance Type"] in wanted and row["Tenancy"] == "Shared" and row["Operating System"] == "Linux"
              and row["Pre Installed S/W"] == "NA" and row["License Model"] == "No License required"
              and row["CapacityStatus"] == "Used" and row["operation"] == "RunInstances"):
            out[row["Instance Type"]] = float(row["PricePerUnit"])
    return out, url


def savings_plan_rates(cache):
    url = current("AWSComputeSavingsPlan", cache, savings_plan=True).replace("index.json", "index.csv")
    out = {}
    for row in stream_csv(fetch(url, cache)):
        if (row["PurchaseOption"] == "No Upfront" and row["LeaseContractLength"] == "1"
                and row["DiscountedOperation"] == "RunInstances"):
            itype = row["DiscountedUsageType"].removeprefix(f"{PREFIX}-BoxUsage:")
            if itype in (USAGE["system_nodes"][0], USAGE["worker_nodes"][0]) and row["DiscountedUsageType"].startswith(PREFIX):
                out[itype] = float(row["DiscountedRate"])
    return out, url


def json_offer(offer, cache):
    url = current(offer, cache)
    return json.load(open(fetch(url, cache))), url


def ondemand(offer, sku):
    term = next(iter(offer["terms"]["OnDemand"][sku].values()))
    return float(next(iter(term["priceDimensions"].values()))["pricePerUnit"]["USD"])


def rds_prices(cache):
    offer, url = json_offer("AmazonRDS", cache)
    itype, out = USAGE["rds"][0], {}
    for sku, p in offer["products"].items():
        a = p["attributes"]
        if a.get("databaseEngine") != "PostgreSQL":
            continue
        if a.get("instanceType") == itype and a.get("deploymentOption") in ("Single-AZ", "Multi-AZ"):
            az = a["deploymentOption"]
            out[f"{az} on-demand"] = ondemand(offer, sku)
            for term in offer["terms"].get("Reserved", {}).get(sku, {}).values():
                t = term["termAttributes"]
                if t.get("LeaseContractLength") == "1yr" and t.get("PurchaseOption") == "No Upfront":
                    hrs = [d for d in term["priceDimensions"].values() if d["unit"] == "Hrs"]
                    out[f"{az} reserved 1yr no upfront"] = float(hrs[0]["pricePerUnit"]["USD"])
        elif p.get("productFamily") == "Database Storage" and a.get("volumeType") == "General Purpose-GP3" \
                and a.get("deploymentOption") == "Single-AZ":
            out["gp3 GB-month"] = ondemand(offer, sku)
    return out, url


def eks_price(cache):
    offer, url = json_offer("AmazonEKS", cache)
    for sku, p in offer["products"].items():
        if p["attributes"].get("usagetype", "").endswith("AmazonEKS-Hours:perCluster"):
            return ondemand(offer, sku), url


def nlb_prices(cache):
    offer, url = json_offer("AWSELB", cache)
    out = {}
    for sku, p in offer["products"].items():
        u = p["attributes"].get("usagetype", "")
        if u.endswith("LoadBalancerUsage") and p["attributes"].get("operation") == "LoadBalancing:Network":
            out["hour"] = ondemand(offer, sku)
        elif u.endswith("LCUUsage") and p["attributes"].get("operation") == "LoadBalancing:Network":
            out["lcu"] = ondemand(offer, sku)
    return out, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(__file__), "../../../.scratch_lab/pricing"))
    cache = ap.parse_args().cache
    ec2, ec2_url = ec2_prices(cache)
    sp, sp_url = savings_plan_rates(cache)
    rds, rds_url = rds_prices(cache)
    eks, eks_url = eks_price(cache)
    nlb, nlb_url = nlb_prices(cache)
    advisor = json.load(open(fetch(SPOT_ADVISOR, cache)))
    ranges = {r["index"]: r["label"] for r in advisor["ranges"]}

    sys_t, sys_n = USAGE["system_nodes"]; wrk_t, wrk_n = USAGE["worker_nodes"]; rds_t, rds_gb = USAGE["rds"]
    spot = advisor["spot_advisor"][REGION]["Linux"][wrk_t]
    spot_rate = ec2[wrk_t] * (1 - spot["s"] / 100)

    print("## Unit prices\n")
    print("| Item | USD | Source |\n|---|---|---|")
    rows = [
        (f"EKS cluster, per hour", eks, eks_url),
        (f"{sys_t} on-demand, per hour", ec2[sys_t], ec2_url),
        (f"{wrk_t} on-demand, per hour", ec2[wrk_t], ec2_url),
        (f"{wrk_t} spot: advisor's typical saving {spot['s']}%, interruption {ranges[spot['r']]}", spot_rate, SPOT_ADVISOR),
        (f"{sys_t} Compute Savings Plan 1 yr no upfront, per hour", sp[sys_t], sp_url),
        (f"{rds_t} PostgreSQL Single-AZ on-demand, per hour", rds["Single-AZ on-demand"], rds_url),
        (f"{rds_t} PostgreSQL Single-AZ reserved 1 yr no upfront, per hour", rds["Single-AZ reserved 1yr no upfront"], rds_url),
        (f"{rds_t} PostgreSQL Multi-AZ on-demand, per hour", rds["Multi-AZ on-demand"], rds_url),
        ("RDS gp3 storage, per GB-month", rds["gp3 GB-month"], rds_url),
        ("NAT gateway, per hour", ec2["nat_hour"], ec2_url),
        ("NAT gateway, per GB processed", ec2["nat_gb"], ec2_url),
        ("Network Load Balancer, per hour", nlb["hour"], nlb_url),
        ("Network Load Balancer, per LCU-hour", nlb["lcu"], nlb_url),
    ]
    for name, usd, src in rows:
        print(f"| {name} | {usd:.4f} | `{src.rsplit('/', 3)[-3] if src.startswith('/') else 'spot-advisor-data.json'}` |")

    fixed = {
        "EKS control plane": eks * HOURS,
        "NAT gateway (1) + data": ec2["nat_hour"] * HOURS + ec2["nat_gb"] * USAGE["nat_gb"],
        "Network Load Balancer (1)": (nlb["hour"] + nlb["lcu"] * USAGE["nlb_lcu"]) * HOURS,
        "RDS storage": rds["gp3 GB-month"] * rds_gb,
    }
    scenarios = {
        "A. All on-demand": {
            f"System nodes {sys_n} x {sys_t}": ec2[sys_t] * sys_n * HOURS,
            f"Workers {wrk_n} x {wrk_t}": ec2[wrk_t] * wrk_n * HOURS,
            f"RDS {rds_t}": rds["Single-AZ on-demand"] * HOURS,
        },
        "B. Workers on spot (Karpenter)": {
            f"System nodes {sys_n} x {sys_t}": ec2[sys_t] * sys_n * HOURS,
            f"Workers {wrk_n} x {wrk_t}": spot_rate * wrk_n * HOURS,
            f"RDS {rds_t}": rds["Single-AZ on-demand"] * HOURS,
        },
        "C. B + Savings Plan on system nodes + RDS reservation": {
            f"System nodes {sys_n} x {sys_t}": sp[sys_t] * sys_n * HOURS,
            f"Workers {wrk_n} x {wrk_t}": spot_rate * wrk_n * HOURS,
            f"RDS {rds_t}": rds["Single-AZ reserved 1yr no upfront"] * HOURS,
        },
    }
    print(f"\n## Monthly cost ({HOURS} hours)\n")
    names = list(scenarios)
    lines = list(next(iter(scenarios.values()))) + list(fixed)
    print("| Line | " + " | ".join(names) + " |\n|---|" + "---|" * len(names))
    for line in lines:
        vals = [scenarios[n].get(line, fixed.get(line)) for n in names]
        print(f"| {line} | " + " | ".join(f"{v:,.0f}" for v in vals) + " |")
    totals = [sum(scenarios[n].values()) + sum(fixed.values()) for n in names]
    print("| **Total** | " + " | ".join(f"**{t:,.0f}**" for t in totals) + " |")
    print("| Saving against A | " + " | ".join(f"{(1 - t / totals[0]) * 100:.0f}%" for t in totals) + " |")


if __name__ == "__main__":
    main()
