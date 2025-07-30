# Google Export Tool for Bedrock Agent

This tool enables Bedrock Agents to export conversation results to Google Docs or Google Sheets.

## Features

- Export text content to Google Docs
- Export structured data to Google Sheets
- Optional folder selection for organizing documents
- Secure credential management through AWS Secrets Manager

## Setup

### 1. Create a Google Cloud Project and Service Account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the following APIs:
   - Google Docs API
   - Google Sheets API
   - Google Drive API
4. Create a service account:
   - Go to "IAM & Admin" > "Service Accounts"
   - Click "Create Service Account"
   - Give it a name and description
   - Grant it the necessary roles (Docs Editor, Sheets Editor, Drive Editor)
   - Create and download the JSON key file

### 2. Store Credentials in AWS Secrets Manager

1. In the AWS Console, navigate to Secrets Manager
2. Create a new secret
3. Select "Other type of secret"
4. Paste the entire contents of the downloaded JSON key file
5. Name the secret according to your environment (e.g., `bedrock-chat-google-api-credentials`)
6. Complete the creation process

### 3. Update CDK Stack

The CDK stack has been updated to create and manage the Google API credentials secret. When deploying, the secret will be created automatically and the necessary permissions will be granted to the Lambda function.

## Usage

### In Bedrock Agent Conversations

Once the tool is set up, you can use it in your Bedrock Agent conversations. Here are some example prompts:

- "Export this conversation to a Google Doc"
- "Save these results to a Google Sheet"
- "Create a Google Doc with this summary"
- "Export this data to a spreadsheet"

### Tool Parameters

The tool accepts the following parameters:

- `content`: The text content to export
- `export_type`: Either "docs" or "sheets"
- `title`: The title for the document or spreadsheet
- `folder_id` (optional): Google Drive folder ID to save the document in

## Example Code

```python
from app.agents.tools.google_export import GoogleExportInput, _google_export

# Export to Google Docs
result = _google_export(
    GoogleExportInput(
        content="This is the content to export",
        export_type="docs",
        title="My Exported Document"
    ),
    bot=None,
    model=None
)

# Export to Google Sheets
result = _google_export(
    GoogleExportInput(
        content="Header1,Header2,Header3\nValue1,Value2,Value3\nValue4,Value5,Value6",
        export_type="sheets",
        title="My Exported Spreadsheet"
    ),
    bot=None,
    model=None
)
```

## Security Considerations

- The service account credentials are stored securely in AWS Secrets Manager
- The Lambda function has the minimum necessary permissions to access the secret
- Consider setting up additional IAM policies to restrict access to the secret
- Regularly rotate the service account key for enhanced security

## Troubleshooting

If you encounter issues with the tool, check the following:

1. Verify that the Google APIs are enabled in your Google Cloud project
2. Ensure the service account has the necessary permissions
3. Check that the secret is correctly stored in AWS Secrets Manager
4. Verify that the Lambda function has permission to access the secret
5. Check the CloudWatch logs for any error messages
