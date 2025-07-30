import logging
import json
import os
from typing import Dict, Any, Optional, Literal

from app.agents.tools.agent_tool import AgentTool
from app.repositories.models.custom_bot import BotModel
from app.routes.schemas.conversation import type_model_name
from app.utils import get_google_api_credentials
from pydantic import BaseModel, Field

# Google API libraries
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GoogleExportInput(BaseModel):
    """Input schema for Google Export tool"""
    content: str = Field(description="The content to export to Google Docs or Sheets")
    export_type: Literal["docs", "sheets"] = Field(
        description="The type of export: 'docs' for Google Docs or 'sheets' for Google Sheets"
    )
    title: str = Field(description="The title of the document or spreadsheet")
    folder_id: Optional[str] = Field(
        default=None,
        description="Optional Google Drive folder ID to save the document in"
    )


class GoogleExportTool:
    """Tool for exporting content to Google Docs or Google Sheets"""

    def __init__(self):
        """Initialize the Google Export Tool with required scopes"""
        # Credentials should be stored securely and accessed via environment variables or AWS Secrets Manager
        self.credentials = None
        self.scopes = [
            'https://www.googleapis.com/auth/documents',
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

    def _get_credentials(self):
        """
        Get Google API credentials from AWS Secrets Manager

        Returns:
            Credentials: Google OAuth credentials

        Raises:
            ValueError: If credentials are not found
            Exception: For other errors
        """
        try:
            # Get credentials from AWS Secrets Manager
            service_account_info = get_google_api_credentials()

            if not service_account_info:
                raise ValueError("Google service account info not found in Secrets Manager")

            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=self.scopes
            )
            return credentials

        except Exception as e:
            logger.error(f"Error getting Google credentials: {e}")
            raise e

    def export_to_docs(self, content: str, title: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Export content to a new Google Doc

        Args:
            content: Text content to export
            title: Document title
            folder_id: Optional Google Drive folder ID

        Returns:
            Dict with content, source_name and source_link
        """
        try:
            credentials = self._get_credentials()
            docs_service = build('docs', 'v1', credentials=credentials)
            drive_service = build('drive', 'v3', credentials=credentials)

            # Create a new document
            document = docs_service.documents().create(body={'title': title}).execute()
            document_id = document.get('documentId')

            # Insert content into the document
            requests = [
                {
                    'insertText': {
                        'location': {
                            'index': 1,
                        },
                        'text': content
                    }
                }
            ]

            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()

            # Move to specific folder if provided
            if folder_id:
                drive_service.files().update(
                    fileId=document_id,
                    addParents=folder_id,
                    removeParents='root',
                    fields='id, parents'
                ).execute()

            # Get the document URL
            doc_url = f"https://docs.google.com/document/d/{document_id}/edit"

            return {
                "content": f"Content successfully exported to Google Docs. You can access it at: {doc_url}",
                "source_name": "Google Docs Export",
                "source_link": doc_url
            }

        except HttpError as error:
            logger.error(f"Google Docs API error: {error}")
            return {
                "content": f"Error exporting to Google Docs: {str(error)}",
                "source_name": "Google Docs Export Error"
            }
        except Exception as e:
            logger.error(f"Error exporting to Google Docs: {e}")
            return {
                "content": f"Error exporting to Google Docs: {str(e)}",
                "source_name": "Google Docs Export Error"
            }

    def export_to_sheets(self, content: str, title: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Export content to a new Google Sheet

        Args:
            content: Text content to export (CSV format)
            title: Spreadsheet title
            folder_id: Optional Google Drive folder ID

        Returns:
            Dict with content, source_name and source_link
        """
        try:
            credentials = self._get_credentials()
            sheets_service = build('sheets', 'v4', credentials=credentials)
            drive_service = build('drive', 'v3', credentials=credentials)

            # Create a new spreadsheet
            spreadsheet = sheets_service.spreadsheets().create(
                body={
                    'properties': {
                        'title': title
                    }
                }
            ).execute()
            spreadsheet_id = spreadsheet.get('spreadsheetId')

            # Process content for sheets (simple CSV-like format)
            # This is a basic implementation - in production, you'd want more sophisticated parsing
            rows = content.strip().split('\n')
            values = [row.split(',') for row in rows]

            # Update the sheet with content
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='Sheet1!A1',
                valueInputOption='RAW',
                body={'values': values}
            ).execute()

            # Move to specific folder if provided
            if folder_id:
                drive_service.files().update(
                    fileId=spreadsheet_id,
                    addParents=folder_id,
                    removeParents='root',
                    fields='id, parents'
                ).execute()

            # Get the spreadsheet URL
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

            return {
                "content": f"Content successfully exported to Google Sheets. You can access it at: {sheet_url}",
                "source_name": "Google Sheets Export",
                "source_link": sheet_url
            }

        except HttpError as error:
            logger.error(f"Google Sheets API error: {error}")
            return {
                "content": f"Error exporting to Google Sheets: {str(error)}",
                "source_name": "Google Sheets Export Error"
            }
        except Exception as e:
            logger.error(f"Error exporting to Google Sheets: {e}")
            return {
                "content": f"Error exporting to Google Sheets: {str(e)}",
                "source_name": "Google Sheets Export Error"
            }


def _google_export(
    tool_input: GoogleExportInput, bot: BotModel | None, model: type_model_name | None
) -> Dict[str, Any]:
    """
    Function to handle Google export requests

    Args:
        tool_input: Input parameters for the export
        bot: Bot model (optional)
        model: Model name (optional)

    Returns:
        Dict with export result
    """
    content = tool_input.content
    export_type = tool_input.export_type
    title = tool_input.title
    folder_id = tool_input.folder_id

    logger.info(
        f"Google Export request - Type: {export_type}, Title: {title}"
    )

    export_tool = GoogleExportTool()

    if export_type == "docs":
        return export_tool.export_to_docs(content, title, folder_id)
    elif export_type == "sheets":
        return export_tool.export_to_sheets(content, title, folder_id)
    else:
        # This shouldn't happen with Literal type validation, but keeping as a fallback
        error_message = f"Unsupported export type: {export_type}. Use 'docs' or 'sheets'."
        logger.error(error_message)
        return {
            "content": error_message,
            "source_name": "Google Export Error"
        }


# Create an instance of AgentTool
google_export_tool = AgentTool(
    name="google_export",
    description="Export content to Google Docs or Google Sheets. Use this tool when you need to save conversation results to a Google document.",
    args_schema=GoogleExportInput,
    function=_google_export,
)