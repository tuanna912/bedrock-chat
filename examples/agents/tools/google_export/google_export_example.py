#!/usr/bin/env python3
"""
Example script demonstrating the use of the Google Export tool.
"""

import logging
import json
import os
import sys
import boto3

# Add the project root to Python path to import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../'))

from app.agents.tools.google_export import GoogleExportInput, _google_export, GoogleExportTool
from app.utils import get_google_api_credentials

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def example_export_to_docs():
    """Example of exporting content to Google Docs"""
    try:
        # Create input for the function
        tool_input = GoogleExportInput(
            content="# Bedrock Agent Export Example\n\nThis document was created by a Bedrock Agent using the Google Export tool.\n\n## Features\n\n- Export conversation results to Google Docs\n- Export data to Google Sheets\n- Easy integration with Bedrock Agents\n\n## Example Data\n\nHere's some example data that was exported from a conversation with a Bedrock Agent.",
            export_type="docs",
            title="Bedrock Agent Export Example"
        )

        # Call the export function
        result = _google_export(tool_input, None, None)

        # Display the result
        logger.info(f"Export result: {json.dumps(result, indent=2)}")

        return result

    except Exception as e:
        logger.error(f"Error in example_export_to_docs: {e}")
        return {"error": str(e)}


def example_export_to_sheets():
    """Example of exporting content to Google Sheets"""
    try:
        # Create sample CSV-like content
        csv_content = """Product,Category,Price,Stock
Product A,Electronics,$599.99,125
Product B,Home & Garden,$49.95,78
Product C,Electronics,$1299.00,42
Product D,Office Supplies,$12.49,356
Product E,Clothing,$39.99,210"""

        # Create input for the function
        tool_input = GoogleExportInput(
            content=csv_content,
            export_type="sheets",
            title="Bedrock Agent Data Export"
        )

        # Call the export function
        result = _google_export(tool_input, None, None)

        # Display the result
        logger.info(f"Export result: {json.dumps(result, indent=2)}")

        return result

    except Exception as e:
        logger.error(f"Error in example_export_to_sheets: {e}")
        return {"error": str(e)}


def check_credentials():
    """Check if Google API credentials are properly configured"""
    try:
        credentials = get_google_api_credentials()
        if not credentials:
            logger.error("Google API credentials not found. Please configure them in AWS Secrets Manager.")
            return False

        logger.info("Google API credentials found.")
        return True

    except Exception as e:
        logger.error(f"Error checking credentials: {e}")
        return False


if __name__ == "__main__":
    # Check if credentials are properly configured
    if not check_credentials():
        logger.error("Exiting due to credential configuration issues.")
        sys.exit(1)

    # Run examples
    logger.info("Running Google Docs export example...")
    docs_result = example_export_to_docs()

    logger.info("Running Google Sheets export example...")
    sheets_result = example_export_to_sheets()

    # Display summary
    if "source_link" in docs_result:
        print(f"\nGoogle Docs export successful! Document available at: {docs_result['source_link']}")
    else:
        print("\nGoogle Docs export failed.")

    if "source_link" in sheets_result:
        print(f"\nGoogle Sheets export successful! Spreadsheet available at: {sheets_result['source_link']}")
    else:
        print("\nGoogle Sheets export failed.")