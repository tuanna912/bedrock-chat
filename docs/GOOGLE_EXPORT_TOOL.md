# Google Export Tool for Bedrock Agent

This document provides comprehensive instructions for implementing and using the Google Export tool with Amazon Bedrock Agents. This tool allows agents to export conversation results to Google Docs or Google Sheets.

## Overview

The Google Export tool enables Bedrock Agents to:

- Export conversation text to Google Docs
- Export structured data to Google Sheets
- Save documents to specific Google Drive folders
- Provide direct links to the created documents

## Implementation Details

### Architecture

The implementation consists of:

1. **Backend Tool**: A Python module that interfaces with Google APIs
2. **AWS Secret**: Secure storage for Google API credentials
3. **CDK Configuration**: Infrastructure setup for the tool
4. **Agent Integration**: Configuration for Bedrock Agent to use the tool

### Prerequisites

- AWS account with permissions to use Bedrock and Secrets Manager
- Google Cloud Platform account
- Google service account with appropriate permissions

## Setup Instructions

### 1. Google Cloud Platform Setup

1. **Create a Google Cloud Project**:

   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one

2. **Enable Required APIs**:

   - Navigate to "APIs & Services" > "Library"
   - Search for and enable:
     - Google Docs API
     - Google Sheets API
     - Google Drive API

3. **Create a Service Account**:
   - Go to "IAM & Admin" > "Service Accounts"
   - Click "Create Service Account"
   - Enter a name and description
   - Grant the following roles:
     - "Docs Editor" (roles/docs.editor)
     - "Sheets Editor" (roles/sheets.editor)
     - "Drive File Creator" (roles/drive.fileCreator)
   - Create and download the JSON key file

### 2. AWS Setup

1. **Store Google Credentials in AWS Secrets Manager**:

   - The CDK stack will create a secret named `{envPrefix}-bedrock-chat-google-api-credentials`
   - After deployment, manually update this secret with the contents of the Google service account JSON key file

2. **Deploy the CDK Stack**:

   ```bash
   cd cdk
   npm install
   cdk deploy
   ```

3. **Update Lambda Environment Variables**:
   - The CDK stack automatically sets the `GOOGLE_API_SECRET_ARN` environment variable for the Lambda function

### 3. Bedrock Agent Configuration

1. **Create a Bedrock Agent**:

   - Go to the Amazon Bedrock console
   - Navigate to "Agents" and create a new agent
   - Configure the basic settings

2. **Add the Google Export Action Group**:

   - In your agent, add a new action group
   - Configure it to use the Lambda function that includes the Google Export tool
   - Define the schema for the action group based on the GoogleExportInput model

3. **Test the Agent**:
   - Use the Bedrock console to test the agent
   - Try prompts like "Export this conversation to a Google Doc" or "Save these results to a Google Sheet"

## Using the Tool

### Example Prompts

Users can interact with the agent using prompts like:

- "Export our conversation to a Google Doc titled 'Meeting Notes'"
- "Save this data to a Google Sheet called 'Sales Report'"
- "Create a Google Doc with the summary of our discussion"
- "Export these statistics to a spreadsheet"

### Tool Parameters

The tool accepts these parameters:

| Parameter   | Description            | Required |
| ----------- | ---------------------- | -------- |
| content     | Text content to export | Yes      |
| export_type | "docs" or "sheets"     | Yes      |
| title       | Document title         | Yes      |
| folder_id   | Google Drive folder ID | No       |

### Code Examples

#### Exporting to Google Docs

```python
from app.agents.tools.google_export import GoogleExportInput, _google_export

result = _google_export(
    GoogleExportInput(
        content="This is the content to export",
        export_type="docs",
        title="My Exported Document"
    ),
    bot=None,
    model=None
)
```

#### Exporting to Google Sheets

```python
from app.agents.tools.google_export import GoogleExportInput, _google_export

result = _google_export(
    GoogleExportInput(
        content="Header1,Header2,Header3\nValue1,Value2,Value3",
        export_type="sheets",
        title="My Exported Spreadsheet"
    ),
    bot=None,
    model=None
)
```

## Security Considerations

- **Credential Security**: Google API credentials are stored in AWS Secrets Manager
- **Permission Scope**: The service account has only the necessary permissions
- **Access Control**: The Lambda function has limited access to the secret
- **Key Rotation**: Regularly rotate the service account key

## Troubleshooting

### Common Issues

1. **Authentication Errors**:

   - Verify the secret is correctly stored in AWS Secrets Manager
   - Check that the Lambda function has permission to access the secret

2. **API Errors**:

   - Ensure all required Google APIs are enabled
   - Verify the service account has appropriate permissions

3. **Export Failures**:
   - Check CloudWatch logs for detailed error messages
   - Verify the format of the content being exported (especially for sheets)

### Logging

The tool uses Python's logging module to log information and errors:

- INFO level: Successful operations and general information
- ERROR level: Failed operations with error details

Check CloudWatch logs for these entries when troubleshooting.

## Additional Resources

- [Google Docs API Documentation](https://developers.google.com/docs/api)
- [Google Sheets API Documentation](https://developers.google.com/sheets/api)
- [Google Drive API Documentation](https://developers.google.com/drive)
- [AWS Secrets Manager Documentation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
- [Amazon Bedrock Agents Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
