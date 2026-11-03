# AWS cost estimate for the dev design

What the [AWS track's](specs/aws-track.md) dev environment would cost a month in `ap-southeast-1`, from AWS's
public price list, and which discount moves which line. Produced
by [estimate.py](../infra/aws/cost/estimate.py) on 2026-11-04 from the price files named in the Source column
(each is a dated version of the Price List bulk API, [docs](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-ppslong.html),
2026-11-04); prices change, so rerun the script before quoting a number.

## What is priced

| Line | From the design | Usage |
|---|---|---|
| EKS control plane | [eks module](../infra/aws/terraform/modules/eks) | 1 cluster, 730 h |
| System nodes | managed node group, on-demand only | 2 x m7i.large |
| Workers | Karpenter NodePools ([eks overlay](../infra/platform/manifests/eks/karpenter.yaml)) | **Assumed** 3 x m7i.xlarge on average |
| RDS | [database module](../infra/aws/terraform/modules/database) | db.t4g.medium Single-AZ, 20 GB gp3 |
| NAT gateway | one in dev ([network module](../infra/aws/terraform/modules/network)) | **Assumed** 100 GB a month (S3 uses the free gateway endpoint) |
| Load balancer | the Gateway's NLB | **Assumed** 1 LCU on average |

Not priced: S3, CloudWatch Logs, KMS, Secrets Manager and data transfer out, each a few dollars at dev's size.

## REAL, 2026-11-04

### Unit prices

| Item | USD | Source |
|---|---|---|
| EKS cluster, per hour | 0.1000 | `20261027191639` |
| m7i.large on-demand, per hour | 0.1260 | `20261029175634` |
| m7i.xlarge on-demand, per hour | 0.2520 | `20261029175634` |
| m7i.xlarge spot: advisor's typical saving 55%, interruption <5% | 0.1134 | `spot-advisor-data.json` |
| m7i.large Compute Savings Plan 1 yr no upfront, per hour | 0.0833 | `20261029175641` |
| db.t4g.medium PostgreSQL Single-AZ on-demand, per hour | 0.1020 | `20261029070635` |
| db.t4g.medium PostgreSQL Single-AZ reserved 1 yr no upfront, per hour | 0.0803 | `20261029070635` |
| db.t4g.medium PostgreSQL Multi-AZ on-demand, per hour | 0.2030 | `20261029070635` |
| RDS gp3 storage, per GB-month | 0.1380 | `20261029070635` |
| NAT gateway, per hour | 0.0590 | `20261029175634` |
| NAT gateway, per GB processed | 0.0590 | `20261029175634` |
| Network Load Balancer, per hour | 0.0252 | `20261102102527` |
| Network Load Balancer, per LCU-hour | 0.0060 | `20261102102527` |

### Monthly cost (730 hours), USD

| Line | A. All on-demand | B. Workers on spot (Karpenter) | C. B + Savings Plan on system nodes + RDS reservation |
|---|---|---|---|
| System nodes 2 x m7i.large | 184 | 184 | 122 |
| Workers 3 x m7i.xlarge | 552 | 248 | 248 |
| RDS db.t4g.medium | 74 | 74 | 59 |
| EKS control plane | 73 | 73 | 73 |
| NAT gateway (1) + data | 49 | 49 | 49 |
| Network Load Balancer (1) | 23 | 23 | 23 |
| RDS storage | 3 | 3 | 3 |
| **Total** | **958** | **654** | **576** |
| Saving against A | 0% | 32% | 40% |

## What the numbers say

- **Workers are the biggest line, and spot is the biggest lever:** 552 to 248 USD. The advisor's typical saving for
  m7i.xlarge in Singapore is 55% with an interruption frequency under 5%; the drill in
  [runbook 4.3](runbooks/aws-track.md#43-karpenter-on-kwok-spot-first-a-reclaim-consolidation-c12) is what makes
  that saving safe to take.
- **Commitments fit only what always runs:** the Savings Plan on the two system nodes (184 to 122) and the RDS
  reservation (74 to 59). The workers are not committed: Karpenter changes their type and count, and spot is already
  cheaper than a plan.
- **Fixed lines do not move with discounts:** the control plane, the NAT gateway and the load balancer are 145 USD in
  every scenario; the levers there are design (one cluster, one NAT in dev, the S3 endpoint).
- **Multi-AZ RDS doubles the database line** (0.2030 against 0.1020 per hour): production pays it for automatic
  failover, dev does not.
- **Right-size before committing:** the HPA drill measured podinfo at 1,308% of a 50m CPU request under 900 requests
  a second, so its request was too small for that load; requests set from measured use decide how many workers there
  are, and a plan bought before that pays for the wrong size.
