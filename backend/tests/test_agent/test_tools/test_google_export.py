import json
import unittest
from unittest.mock import patch, MagicMock

from app.agents.tools.google_export import GoogleExportTool, _google_export, GoogleExportInput


class TestGoogleExport(unittest.TestCase):
    @patch("app.agents.tools.google_export.get_google_api_credentials")
    @patch("app.agents.tools.google_export.build")
    def test_export_to_docs(self, mock_build, mock_get_credentials):
        # Mock credentials
        mock_get_credentials.return_value = {"client_email": "test@example.com"}

        # Mock Google API services
        mock_docs = MagicMock()
        mock_drive = MagicMock()
        mock_build.side_effect = lambda service, version, credentials: mock_docs if service == 'docs' else mock_drive

        # Mock document creation
        mock_docs.documents().create().execute.return_value = {"documentId": "test_doc_id"}

        # Create instance of GoogleExportTool
        export_tool = GoogleExportTool()

        # Test export_to_docs method
        result = export_tool.export_to_docs("Test content", "Test Document")

        # Verify results
        self.assertEqual(result["source_name"], "Google Docs Export")
        self.assertTrue("test_doc_id" in result["source_link"])
        self.assertTrue("successfully exported" in result["content"])

        # Verify API calls
        mock_docs.documents().create.assert_called_once()
        mock_docs.documents().batchUpdate.assert_called_once()

    @patch("app.agents.tools.google_export.get_google_api_credentials")
    @patch("app.agents.tools.google_export.build")
    def test_export_to_sheets(self, mock_build, mock_get_credentials):
        # Mock credentials
        mock_get_credentials.return_value = {"client_email": "test@example.com"}

        # Mock Google API services
        mock_sheets = MagicMock()
        mock_drive = MagicMock()
        mock_build.side_effect = lambda service, version, credentials: mock_sheets if service == 'sheets' else mock_drive

        # Mock spreadsheet creation
        mock_sheets.spreadsheets().create().execute.return_value = {"spreadsheetId": "test_sheet_id"}

        # Create instance of GoogleExportTool
        export_tool = GoogleExportTool()

        # Test export_to_sheets method
        result = export_tool.export_to_sheets("Test,Content\nRow2,Value2", "Test Spreadsheet")

        # Verify results
        self.assertEqual(result["source_name"], "Google Sheets Export")
        self.assertTrue("test_sheet_id" in result["source_link"])
        self.assertTrue("successfully exported" in result["content"])

        # Verify API calls
        mock_sheets.spreadsheets().create.assert_called_once()
        mock_sheets.spreadsheets().values().update.assert_called_once()

    @patch("app.agents.tools.google_export.GoogleExportTool")
    def test_google_export_function_docs(self, mock_export_tool_class):
        # Mock GoogleExportTool instance
        mock_export_tool = MagicMock()
        mock_export_tool_class.return_value = mock_export_tool
        mock_export_tool.export_to_docs.return_value = {
            "content": "Content successfully exported to Google Docs",
            "source_name": "Google Docs Export",
            "source_link": "https://docs.google.com/document/d/test_id/edit"
        }

        # Create input for the function
        tool_input = GoogleExportInput(
            content="Test content",
            export_type="docs",
            title="Test Document"
        )

        # Test _google_export function
        result = _google_export(tool_input, None, None)

        # Verify results
        self.assertEqual(result["source_name"], "Google Docs Export")
        mock_export_tool.export_to_docs.assert_called_once_with("Test content", "Test Document", None)

    @patch("app.agents.tools.google_export.GoogleExportTool")
    def test_google_export_function_sheets(self, mock_export_tool_class):
        # Mock GoogleExportTool instance
        mock_export_tool = MagicMock()
        mock_export_tool_class.return_value = mock_export_tool
        mock_export_tool.export_to_sheets.return_value = {
            "content": "Content successfully exported to Google Sheets",
            "source_name": "Google Sheets Export",
            "source_link": "https://docs.google.com/spreadsheets/d/test_id/edit"
        }

        # Create input for the function
        tool_input = GoogleExportInput(
            content="Test,Content\nRow2,Value2",
            export_type="sheets",
            title="Test Spreadsheet"
        )

        # Test _google_export function
        result = _google_export(tool_input, None, None)

        # Verify results
        self.assertEqual(result["source_name"], "Google Sheets Export")
        mock_export_tool.export_to_sheets.assert_called_once_with("Test,Content\nRow2,Value2", "Test Spreadsheet", None)

    @patch("app.agents.tools.google_export.GoogleExportTool")
    def test_google_export_function_invalid_type(self, mock_export_tool_class):
        # Create input for the function with invalid export_type
        tool_input = GoogleExportInput(
            content="Test content",
            export_type="invalid",
            title="Test Document"
        )

        # Test _google_export function
        result = _google_export(tool_input, None, None)

        # Verify results
        self.assertEqual(result["source_name"], "Google Export Error")
        self.assertTrue("Unsupported export type" in result["content"])

        # Verify that neither export method was called
        mock_export_tool_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()