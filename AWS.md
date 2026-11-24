# AWS: what exists, what is planned, and what it will cost

Written 24 November 2026.

## What exists in AWS right now

**Nothing.** No AWS command has been run for this project, no resource has been created, and this project has added nothing to your AWS bill.

What has been done so far is all on your laptop:

| Item | Where | Costs money? |
|---|---|---|
| The job worker (`arena job`) | Code in this repository | No |
| The container image `arena-worker` | Built locally with Docker | No |
| The website | GitHub and Vercel | No |

Your laptop does have the AWS command line installed, with saved credentials and the default region `eu-north-1` (Stockholm). They were there already and have not been used for this project. Nothing will be created in AWS until you say so.

To confirm for yourself that the account holds nothing from this project, see [Check what is running](#check-what-is-running).

## What is planned

Each item below would be created only when you approve it. Every resource will carry the tag `project = stress-test-arena`, so you can list them all and delete them all.

| # | Resource | AWS service | Planned name | Purpose | Charged when |
|---|---|---|---|---|---|
| 1 | Image store | ECR | `arena-worker` | Holds the worker's container image | Always, by size |
| 2 | Job queue | SQS | `arena-jobs` | Holds test requests until a worker takes them | Per request; free at this volume |
| 3 | Results bucket | S3 | `arena-results-<account id>` | Results pages, audio and scores | Always, by size stored |
| 4 | Task definition and cluster | ECS on Fargate | `arena` | Starts one container per test, which stops when the test ends | **Only while a test runs** |
| 5 | Logs | CloudWatch Logs | `/arena/worker` | The worker's output, for debugging | By volume written |
| 6 | Permissions | IAM | `arena-worker-task`, `arena-submit` | Lets the worker read the queue and write the bucket; lets the website add jobs | Free |
| 7 | Spending alarm | AWS Budgets | `arena-monthly` | Emails you when the month's cost passes a limit you set | Free |

Deliberately left out, because they charge by the hour even when idle:

- **NAT gateway** (about $32 a month plus traffic). The worker will run in a public subnet with its own public address instead.
- **Load balancer** (about $16 a month). Not needed: nothing connects in to the worker.
- **An always-on EC2 instance.** The point of the design is to pay only while a test runs.
- **Secrets Manager** ($0.40 per secret per month). A visitor's API key is handed to the one task that needs it and is never stored.

## Estimated bill

**These are estimates, not quotes.** The prices are US-region list prices as I know them; they change, and other regions differ by up to about 15%. The duration of a test on AWS has not been measured yet. Check current prices with the AWS Pricing Calculator (calculator.aws) before relying on any figure here.

### Cost of one test

Assumed worker size: 2 vCPU and 4 GB of memory, running about 30 minutes per test (10 minutes of calls in real time, the rest starting up and transcribing).

| Item | Price | Per test |
|---|---|---|
| Fargate vCPU | about $0.040 per vCPU per hour | 2 × 0.5 h = $0.040 |
| Fargate memory | about $0.0045 per GB per hour | 4 × 0.5 h = $0.009 |
| Public IPv4 address | $0.005 per hour | $0.003 |
| Logs | about $0.50 per GB written | under $0.001 |
| Results stored in S3 | about $0.023 per GB per month | about 45 MB with full recordings: $0.001 per month kept |
| **Total** | | **about $0.05** |

If transcription turns out slower and a test takes an hour, the figure doubles to about $0.10.

### Monthly bill

| Tests in the month | Compute | Fixed (image and results storage) | Estimated total |
|---|---|---|---|
| 0 (idle) | $0 | about $0.30 | **about $0.30** |
| 20 | $1 | about $0.35 | **about $1.50** |
| 100 | $5 | about $0.50 | **about $6** |
| 1,000 | $50 | about $2 | **about $55** |

What the fixed part is:

- **Image storage (ECR):** about $0.10 per GB per month. The image is 5.1 GB on disk, mostly the speech recogniser and its libraries; ECR stores it compressed and bills the compressed size, which should be around 2 to 3 GB, so about $0.30. The exact size will be known when it is first pushed. Old image versions add up, so the setup will keep only the latest two.
- **Results storage (S3):** grows with every test. A rule to delete results after 30 days keeps it flat.

### What is not in these numbers

- **The platform's own charges.** A test holds about 10 minutes of conversation with the visitor's agent. ElevenLabs, Vapi, Retell or smallest.ai bill that to the owner of the API key, not to AWS.
- **Vercel.** The form and its small API function fit the free plan at this volume.
- **Data transfer out of AWS.** The first 100 GB a month is free; a results page with audio is a few MB per view, so this stays at zero unless traffic is large.
- **Taxes.**
- **AWS free tier.** A new account gets some of this free for 12 months, which would lower the bill.

### Where the bill could surprise you

| Risk | What it would cost | Guard |
|---|---|---|
| A worker hangs and never exits | About $0.10 per hour, $70 if left a month | A hard time limit on every task (60 minutes), enforced by the worker and by a stop rule |
| Someone submits thousands of tests | $0.05 each | Access code on the form, a cap on tests per person per day, and a cap on tasks running at once |
| Results pile up | Small, but grows forever | Delete after 30 days |
| A NAT gateway or load balancer gets added later | $16–32 a month each, idle | Not part of this design; do not add one |

**Recommended first step in AWS, before anything else:** create the budget alarm (item 7) with a limit of $10 a month. It is free and emails you at 80% and 100%.

## How to manage it

All commands assume the resources are in one region. Replace `REGION` with the one chosen.

**Choosing the region.** Response delay includes the network time between the worker and the platform being tested, so the region should be decided once and kept. Mumbai (`ap-south-1`) matches where Indian callers are; a US region is usually nearer the platforms' servers and slightly cheaper. Your current default, Stockholm, suits neither. This is still to be decided.

### Check what is running

```
# Everything tagged for this project, in one list
aws resourcegroupstaggingapi get-resources --region REGION \
  --tag-filters Key=project,Values=stress-test-arena \
  --query 'ResourceTagMappingList[].ResourceARN'

# Workers running right now (the only thing that charges by the minute)
aws ecs list-tasks --region REGION --cluster arena

# Jobs waiting
aws sqs get-queue-attributes --region REGION --queue-url QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages
```

Today the first command returns an empty list, and the other two fail because the cluster and queue do not exist.

### See what you have been charged

- In the AWS console: **Billing and Cost Management → Cost Explorer**, filter by tag `project = stress-test-arena`. The tag must first be switched on under **Cost allocation tags**, and costs appear about a day late.
- From the command line, month to date for the whole account:

```
aws ce get-cost-and-usage --time-period Start=2026-11-01,End=2026-12-01 \
  --granularity MONTHLY --metrics UnblendedCost
```

### Stop a test that is running

```
aws ecs stop-task --region REGION --cluster arena --task TASK_ID
```

### Pause everything without deleting it

Remove waiting jobs, so no new worker starts. The idle cost of about $0.30 a month continues.

```
aws sqs purge-queue --region REGION --queue-url QUEUE_URL
```

### Delete everything

After this the project costs nothing in AWS. The results in the bucket are lost.

```
aws s3 rb s3://arena-results-ACCOUNT_ID --force --region REGION
aws ecr delete-repository --repository-name arena-worker --force --region REGION
aws sqs delete-queue --queue-url QUEUE_URL --region REGION
aws ecs delete-cluster --cluster arena --region REGION
aws logs delete-log-group --log-group-name /arena/worker --region REGION
```

The two IAM roles and the budget cost nothing and can be removed in the console.

## Order of work, and what each step costs

| Step | Creates in AWS | Starts costing |
|---|---|---|
| 1. Make one platform adapter work, from your laptop | Nothing | Nothing in AWS; the platform bills your key for the calls |
| 2. Budget alarm | The budget | Free |
| 3. Push the image | ECR repository | About $0.30 a month |
| 4. Queue, bucket, permissions, task definition | Items 2–6 | Cents |
| 5. Run one test job by hand on Fargate | A task for about 30 minutes | About $0.05 |
| 6. Connect the website form | Nothing new in AWS | $0.05 per test |

This file will be updated with the real names, the region and measured test durations as each step is done.
