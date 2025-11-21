# AWS Bedrock Knowledge Base - Automated Document Processing Pipeline

An automated data pipeline that processes documents and creates a searchable Knowledge Base using AWS Glue, Amazon Bedrock, and OpenSearch Serverless.

> **Purpose:** Upload files → S3 → Glue ETL → Bedrock KB → OpenSearch → Test on Console

---

## 🎯 Overview

This system automatically:
1. **Processes** documents uploaded to S3 (PDF, DOCX, TXT, MD, HTML, CSV, XLSX)
2. **Routes** files based on size:
   - Small files (<300KB): Direct text extraction
   - Large files (≥300KB): Claude 3.5 Sonnet multimodal parsing
3. **Chunks** content intelligently (by headers for large files)
4. **Ingests** into Bedrock Knowledge Base with auto-embedding
5. **Indexes** vectors in OpenSearch Serverless
6. **Enables** immediate testing via Bedrock Console

---

## 🏗️ Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   S3 Upload │─────▶│  EventBridge │─────▶│   Lambda    │
│ original_   │      │     Rule     │      │  Trigger    │
└─────────────┘      └──────────────┘      └─────────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────┐
                                          │   Glue Job      │
                                          │   (ETL)         │
                                          └─────────────────┘
                                                    │
                     ┌──────────────────────────────┼──────────────────────┐
                     ▼                              ▼                      ▼
            ┌────────────────┐          ┌────────────────┐      ┌──────────────┐
            │ Small Files    │          │ Large Files    │      │  DynamoDB    │
            │ (<300KB)       │          │ (≥300KB)       │      │  Registry    │
            │ Text Extract   │          │ Claude Parse   │      │  (KB IDs)    │
            └────────────────┘          └────────────────┘      └──────────────┘
                     │                              │
                     └──────────────┬───────────────┘
                                    ▼
                          ┌──────────────────┐
                          │ processed_docs/  │
                          │     small/       │
                          └──────────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │  Bedrock KB      │
                          │  S3 DataSource   │
                          │  (NONE chunking) │
                          └──────────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │  OpenSearch      │
                          │  Serverless      │
                          │  (Vector Store)  │
                          └──────────────────┘
```

---

## 📋 Prerequisites

### AWS Services Required
- AWS Glue (Python Shell Job)
- Amazon Bedrock (Knowledge Base + Claude 3.5 Sonnet)
- Amazon S3
- Amazon EventBridge
- AWS Lambda
- Amazon OpenSearch Serverless
- Amazon DynamoDB
- AWS IAM

### Tools Required
- AWS CLI v2 (`aws --version`)
- jq (`brew install jq` or `apt-get install jq`)
- Bash shell
- Python 3.9+ (for local testing)

### AWS Region Support
Bedrock Knowledge Base is available in:
- `us-east-1` (N. Virginia) ✅ **Recommended**
- `us-west-2` (Oregon)
- `ap-southeast-1` (Singapore)
- `eu-central-1` (Frankfurt)

### AWS Permissions Required
Your IAM user/role needs:
- Full access to: S3, Glue, Bedrock, OpenSearch Serverless, DynamoDB, Lambda, EventBridge
- IAM role creation and policy attachment
- CloudWatch Logs access

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Clone and Configure

```bash
cd /path/to/your/workspace
git clone <your-repo-url>
cd build-datapipeline+create-KB

# Make scripts executable
chmod +x deploy.sh cleanup.sh check_opensearch_index.sh fix_opensearch_access.sh
```

### Step 2: Configure Region (if not us-east-1)

Edit `deploy.sh`:
```bash
nano deploy.sh
# Change line 10:
REGION="us-east-1"  # Change to your region
```

Edit `glue_kb_processor_techfest.py`:
```bash
nano glue_kb_processor_techfest.py
# Change line 22:
REGION = 'us-east-1'  # Change to your region
```

### Step 3: Verify AWS Credentials

```bash
# Check AWS CLI is configured
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "AIDAXXXXXXXXX",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/YourUser"
# }

# Verify region
aws configure get region
```

### Step 4: Deploy Infrastructure

```bash
./deploy.sh
```

**Deployment creates:**
- ✅ 2 S3 buckets (documents + Glue scripts)
- ✅ DynamoDB table (KB registry)
- ✅ 3 IAM roles (Glue, Bedrock, Lambda)
- ✅ OpenSearch Serverless collection
- ✅ Glue Python Shell job
- ✅ Lambda trigger function
- ✅ EventBridge rule

**Deployment time:** ~3-5 minutes

### Step 5: Request Bedrock Model Access( if you have not already requested)

**⚠️ CRITICAL:** You must enable Claude model access before processing large files.

```bash
# Option 1: AWS Console (Recommended)
# 1. Go to AWS Console → Bedrock → Model access
# 2. Click "Manage model access"
# 3. Check "Anthropic Claude 3.5 Sonnet v2"
# 4. Click "Request model access"
# 5. Wait ~15 minutes (usually instant)

# Option 2: AWS CLI
aws bedrock list-foundation-models --region us-east-1 \
  --query 'modelSummaries[?contains(modelId, `claude-3-5-sonnet`)].modelId'
```


### Step 7: Upload Test Document

```bash
# Upload documents into s3-bucket using console or cli .Then the pipeline will run automatically.

### Step 8: Monitor Processing

```bash
# Check Glue job status
aws glue get-job-runs --job-name KnowledgeBaseProcessor \
  --max-results 1 \
  --query 'JobRuns[0].[JobRunState,StartedOn,ExecutionTime]'

# View logs (wait 1-2 minutes after upload)
aws logs tail /aws-glue/python-jobs/output --follow

```

### Step 9: Test Knowledge Base

**Option A: AWS Console (Recommended)**
1. Go to **AWS Console** → **Amazon Bedrock**
2. Click **Knowledge bases** (left sidebar)
3. Find your KB (name: `kb-techfest-XXXXXX`)
4. Click **Test knowledge base** tab
5. Enter query: "What is this document about?"
6. View results with source citations

**Option B: AWS CLI**
```bash
# Get KB ID
KB_ID=$(aws dynamodb scan --table-name KnowledgeBaseRegistry \
  --query 'Items[0].kb_id.S' --output text)

# Test retrieve
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id $KB_ID \
  --retrieval-query text="test document" \
  --region us-east-1
```

---

## 📂 S3 Folder Structure

```
techfest-documents-{timestamp}/
├── original_docs/              # ← Upload all files here
│   ├── document1.pdf
│   ├── document2.docx
│   ├── data.csv
│   └── large/                  # Large files auto-moved here
│       └── big-document.pdf
└── processed_docs/
    └── small/                  # All processed chunks (KB datasource)
        ├── document1.txt
        ├── document2.txt
        ├── data.txt
        └── big-document_part1.txt
```

---

## 🔄 Workflow Details

### Small Files (<300KB)

1. **Upload** → `s3://bucket/original_docs/file.docx`
2. **EventBridge** triggers Lambda
3. **Lambda** starts Glue job
4. **Glue** extracts text:
   - DOCX → Parse with python-docx
   - CSV/XLSX → Convert to Markdown tables
   - PDF → PyPDF2 extraction
   - TXT/MD → Direct read
5. **Save** → `s3://bucket/processed_docs/small/file.txt`
6. **Trigger** KB sync (S3 datasource)
7. **Bedrock** embeds and indexes (no chunking)

### Large Files (≥300KB)

1. **Upload** → `s3://bucket/original_docs/large-file.pdf`
2. **EventBridge** triggers Lambda
3. **Lambda** starts Glue job
4. **Glue** moves file → `s3://bucket/original_docs/large/`
5. **Claude 3.5 Sonnet** parses PDF/image:
   - Multimodal understanding (text + tables + images)
   - Vietnamese language support
   - Outputs structured Markdown
6. **Split** by main headers (`#`) with context
7. **Merge** small chunks (<10 lines)
8. **Save** chunks → `s3://bucket/processed_docs/small/large-file_part1.txt`
9. **Trigger** KB sync
10. **Bedrock** embeds and indexes

### Processing Timeline (100MB file)

| Time | Event |
|------|-------|
| T+0s | File uploaded to S3 |
| T+1s | EventBridge triggers Lambda |
| T+2s | Lambda starts Glue job |
| T+30s | Glue: KB lookup/create |
| T+60s | Glue: File routing (small vs large) |
| T+120s | Glue: Claude parsing (if large) |
| T+180s | Glue: Save to processed_docs/small/ |
| T+240s | Glue: Trigger KB sync |
| T+300s | Bedrock: Embedding complete |
| T+360s | OpenSearch: Indexed & searchable |
| **T+6min** | **✅ Ready to query!** |

---

## ⚙️ Configuration

### Change File Size Threshold

Edit `glue_kb_processor_techfest.py`:
```python
# Line 40
FILE_SIZE_THRESHOLD = 300 * 1024  # 300KB (change as needed)
```

### Change Embedding Model

Edit `glue_kb_processor_techfest.py`:
```python
# Line 39
EMBEDDING_MODEL = 'amazon.titan-embed-text-v2:0'
# Options:
#   'amazon.titan-embed-text-v2:0' (1024 dims)
#   'cohere.embed-english-v3' (1024 dims)
#   'cohere.embed-multilingual-v3' (1024 dims)
```

### Change Claude Model

Edit `glue_kb_processor_techfest.py`:
```python
# Line 41
CLAUDE_MODEL = 'us.anthropic.claude-3-5-sonnet-20241022-v2:0'
# Options:
#   'us.anthropic.claude-3-5-sonnet-20241022-v2:0' (cross-region)
#   'anthropic.claude-3-5-sonnet-20241022-v2:0' (standard)
```

After changes:
```bash
# Re-upload Glue script
GLUE_BUCKET=$(aws s3 ls | grep techfest-glue-scripts | awk '{print $3}')
aws s3 cp glue_kb_processor_techfest.py s3://$GLUE_BUCKET/scripts/
```

---

## 🐛 Common Issues & Solutions

### Issue 1: "Model use case details have not been submitted"

**Error:**
```
ResourceNotFoundException: Model use case details have not been submitted
```

**Cause:** Claude model access not enabled

**Solution:**
```bash
# Go to AWS Console → Bedrock → Model access
# Enable "Anthropic Claude 3.5 Sonnet v2"
# Wait 15 minutes

# Or system will fallback to PyPDF2 (lower quality)
```

---

### Issue 2: "AuthorizationException(403)" when checking OpenSearch

**Error:**
```
AuthorizationException(403, 'User does not have permissions')
```

**Cause:** Your IAM user not in OpenSearch data access policy

**Solution:**
```bash
./fix_opensearch_access.sh
```

---

### Issue 3: Glue job fails with "Collection not found"

**Error:**
```
Exception: OpenSearch collection 'kb-collection-1' not found
```

**Cause:** OpenSearch collection not created or still creating

**Solution:**
```bash
# Check collection status
aws opensearchserverless batch-get-collection \
  --names kb-collection-1 \
  --query 'collectionDetails[0].status'

# If "CREATING", wait 2-3 minutes
# If not found, re-run deployment:
./deploy.sh
```

---

### Issue 4: KB not appearing in Bedrock Console

**Cause:** Wrong region or KB still creating

**Solution:**
```bash
# Check KB status
aws bedrock-agent list-knowledge-bases --region us-east-1

# Verify region matches
aws configure get region

# Check DynamoDB registry
aws dynamodb scan --table-name KnowledgeBaseRegistry
```

---

### Issue 5: "ThrottlingException" during ingestion

**Error:**
```
TooManyRequestsException: Rate exceeded
```

**Cause:** Too many concurrent ingestion jobs

**Solution:**
Edit `glue_kb_processor_techfest.py`:
```python
# Add delays between sync jobs
time.sleep(30)  # Wait 30s between batches
```

---

### Issue 6: Files not processing automatically

**Cause:** EventBridge rule not triggering

**Solution:**
```bash
# Check EventBridge rule
aws events describe-rule --name S3ToGlueKnowledgeBase

# Check Lambda permissions
aws lambda get-policy --function-name TriggerGlueFromS3

# Manual trigger
aws glue start-job-run \
  --job-name KnowledgeBaseProcessor \
  --arguments '{"--BUCKET_NAME":"techfest-documents-XXXXX"}'
```

---

### Issue 7: "Index not found" in OpenSearch

**Cause:** Index not created yet

**Solution:**
```bash
# Index is created automatically on first KB creation
# If missing, trigger Glue job to recreate:
BUCKET=$(aws s3 ls | grep techfest-documents | awk '{print $3}')
aws glue start-job-run \
  --job-name KnowledgeBaseProcessor \
  --arguments "{\"--BUCKET_NAME\":\"$BUCKET\"}"
```

---

### Issue 8: Large PDF fails to parse

**Error:**
```
Error: Image file too large: 20.5MB. Max 15MB for images.
```

**Cause:** PDF too large for Claude API (>15MB after base64)

**Solution:**
- Split PDF into smaller files (<15MB each)
- Or convert to images and process separately
- System will auto-fallback to PyPDF2 for PDFs

---

### Issue 9: Vietnamese text garbled

**Cause:** Encoding issue

**Solution:**
```bash
# Always upload with UTF-8 encoding
aws s3 cp file.txt s3://$BUCKET/original_docs/ \
  --content-type "text/plain; charset=utf-8"
```

---

### Issue 10: Deployment fails with "Role already exists"

**Cause:** Previous deployment not cleaned up

**Solution:**
```bash
# Clean up old resources
./cleanup.sh

# Wait 1 minute, then re-deploy
./deploy.sh
```

---

## 🧹 Cleanup

### Remove All Resources

```bash
./cleanup.sh
# Type "DELETE" to confirm
```

**This will delete:**
- ✅ S3 buckets (all files)
- ✅ Glue jobs
- ✅ Lambda functions
- ✅ EventBridge rules
- ✅ OpenSearch collection
- ✅ DynamoDB table
- ✅ Knowledge Bases
- ✅ IAM roles and policies
- ✅ CloudWatch log groups

---

## 📊 Monitoring

### Check System Health

```bash
# 1. Check S3 buckets
aws s3 ls | grep techfest

# 2. Check Glue job
aws glue get-job --job-name KnowledgeBaseProcessor

# 3. Check Lambda
aws lambda get-function --function-name TriggerGlueFromS3

# 4. Check OpenSearch
aws opensearchserverless batch-get-collection --names kb-collection-1

# 5. Check KB
aws bedrock-agent list-knowledge-bases --region us-east-1

# 6. Check DynamoDB
aws dynamodb scan --table-name KnowledgeBaseRegistry
```

### View Logs

```bash
# Glue job logs (real-time)
aws logs tail /aws-glue/python-jobs/output --follow

# Lambda logs
aws logs tail /aws/lambda/TriggerGlueFromS3 --follow

# Recent Glue errors
aws logs tail /aws-glue/python-jobs/error --since 1h
```

### Check Processing Status

```bash
# Get latest Glue job run
aws glue get-job-runs --job-name KnowledgeBaseProcessor \
  --max-results 1 \
  --query 'JobRuns[0].[JobRunState,StartedOn,ExecutionTime,ErrorMessage]'

# Check KB sync jobs
KB_ID=$(aws dynamodb scan --table-name KnowledgeBaseRegistry \
  --query 'Items[0].kb_id.S' --output text)
DS_ID=$(aws dynamodb scan --table-name KnowledgeBaseRegistry \
  --query 'Items[0].ds_small_id.S' --output text)

aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID \
  --max-results 5
```

---

## 💰 Cost Estimation

### Monthly Cost (1000 documents, 10MB each)

| Service | Usage | Cost/Month |
|---------|-------|-----------|
| **S3 Storage** | 10GB | $0.23 |
| **S3 Requests** | 1000 PUT | $0.005 |
| **EventBridge** | 1000 events | $0.001 |
| **Lambda** | 1000 invocations | $0.20 |
| **Glue Python Shell** | 1000 runs × 5min | $2.20 |
| **Bedrock Claude** | 100 large files | $3.00 |
| **Bedrock Embedding** | 1M tokens | $0.10 |
| **OpenSearch Serverless** | 1 OCU | $700 |
| **DynamoDB On-Demand** | Minimal | <$1 |
| **CloudWatch Logs** | 1GB | $0.50 |
| **Total** | | **~$707/month** |

⚠️ **OpenSearch Serverless** is 99% of the cost!

### Cost Optimization Tips

1. **Pause OpenSearch** when not in use (stop collection)
2. **Use OpenSearch Managed** with auto-scaling (cheaper for small workloads)
3. **Batch uploads** instead of one-by-one
4. **Adjust file size threshold** to reduce Claude API calls
5. **Use S3 Lifecycle policies** to archive old files

---

## 🔐 Security Best Practices

### Production Checklist

- [ ] Enable S3 bucket encryption (SSE-S3 or KMS)
- [ ] Enable S3 versioning
- [ ] Enable CloudTrail for audit logging
- [ ] Use VPC endpoints for S3, Bedrock, OpenSearch
- [ ] Restrict IAM policies to least privilege
- [ ] Enable MFA for IAM users
- [ ] Use AWS Secrets Manager for sensitive data
- [ ] Enable CloudWatch alarms for failures
- [ ] Set up SNS notifications for errors
- [ ] Configure S3 access logging
- [ ] Use private subnets for Glue jobs
- [ ] Enable encryption at rest for DynamoDB
- [ ] Rotate IAM credentials regularly

---

## 🌍 Multi-Account / Multi-Region Setup

### Deploy to Different Account

```bash
# 1. Configure AWS CLI for target account
aws configure --profile production
aws sts get-caller-identity --profile production

# 2. Set profile for deployment
export AWS_PROFILE=production

# 3. Deploy
./deploy.sh
```

### Deploy to Different Region

```bash
# 1. Edit deploy.sh
nano deploy.sh
# Change: REGION="ap-southeast-1"

# 2. Edit glue_kb_processor_techfest.py
nano glue_kb_processor_techfest.py
# Change: REGION = 'ap-southeast-1'

# 3. Deploy
./deploy.sh
```

### Cross-Region Considerations

- Bedrock KB only available in: us-east-1, us-west-2, ap-southeast-1, eu-central-1
- Claude models may have different availability
- OpenSearch Serverless pricing varies by region
- S3 cross-region transfer costs apply

---

## 📚 Additional Resources

### AWS Documentation
- [Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [OpenSearch Serverless](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)
- [AWS Glue Python Shell](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-python.html)
- [Bedrock Claude Models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude.html)

### Useful Commands

```bash
# List all resources
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=KnowledgeBase

# Estimate costs
aws ce get-cost-and-usage \
  --time-period Start=2025-01-01,End=2025-01-31 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=SERVICE

# Export KB data
aws bedrock-agent get-knowledge-base --knowledge-base-id <kb-id>
```

---

## 🤝 Support

### Getting Help

1. **Check logs:** `aws logs tail /aws-glue/python-jobs/output --follow`
2. **Review this README:** Common issues section
3. **Check AWS Service Health:** [status.aws.amazon.com](https://status.aws.amazon.com)
4. **AWS Support:** [console.aws.amazon.com/support](https://console.aws.amazon.com/support)

### Debugging Steps

```bash
# 1. Verify all resources exist
./check_opensearch_index.sh

# 2. Check IAM permissions
aws iam get-role --role-name GlueKnowledgeBaseRole
aws iam get-role --role-name BedrockKnowledgeBaseRole

# 3. Test Glue job manually
BUCKET=$(aws s3 ls | grep techfest-documents | awk '{print $3}')
aws glue start-job-run \
  --job-name KnowledgeBaseProcessor \
  --arguments "{\"--BUCKET_NAME\":\"$BUCKET\"}"

# 4. Check CloudWatch logs
aws logs tail /aws-glue/python-jobs/output --since 30m
```

---

## 📝 License

MIT License - Free to use and modify

---

## ⚠️ Important Notes

1. **Demo System:** This is a reference implementation. For production:
   - Add comprehensive monitoring & alerting
   - Implement CI/CD pipeline
   - Use Infrastructure as Code (Terraform/CloudFormation)
   - Add comprehensive testing
   - Set up VPC and private networking
   - Implement disaster recovery

2. **Cost Warning:** OpenSearch Serverless costs ~$700/month for 1 OCU. Consider alternatives for development.

3. **Region Availability:** Bedrock KB only available in select regions. Check before deploying.

4. **API Limits:** Bedrock has rate limits. System implements backoff but monitor throttling.

5. **File Size Limits:** 
   - Claude API: 15MB per request (after base64 encoding)
   - S3 single PUT: 5GB
   - Glue Python Shell: 1 DPU (limited memory)

---

**🚀 Ready to deploy? Run:** `./deploy.sh`

**📖 Questions? Check:** Common Issues section above

**🐛 Issues? Run:** `aws logs tail /aws-glue/python-jobs/output --follow`

---

*Last updated: January 2025*
*Version: 1.0.0*
