import logging
import json
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient
import os

# Get connection string from environment variables
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
table_service = TableServiceClient.from_connection_string(connection_string)

def get_client_memorandum(firm_short_name, case_number):
    """
    Args:
        firm_short_name (str): The short name of the firm
        case_number (str): The case number
        
    Returns:
        tuple: (memorandum, error_message, status_code)
            - memorandum: The memorandum text if found, None otherwise
            - error_message: Error message if an error occurred, None otherwise
            - status_code: HTTP status code (200 for success, 404 for not found, 500 for server error)
    """
    try:
        # Get case record from table storage
        aila_cases_table = table_service.get_table_client("ailalawyercases")
        case_entity = aila_cases_table.get_entity(firm_short_name, case_number)
        
        # Get the appropriate memorandum field based on party role
        english_memorandum = case_entity['MemorandumEnglish']
        arabic_memorandum = case_entity['MemorandumArabic']
        
        if not english_memorandum and not arabic_memorandum:
            return None, None, f"No memorandum found for {firm_short_name} and {case_number}", 404
        else:
            logging.info(f"[API INFO][get_memorandum] Found memorandum for {firm_short_name} and {case_number}: \n\nEnglish: {english_memorandum}\n\n")
            return english_memorandum, arabic_memorandum, None, 200
        
    except Exception as table_error:
        logging.error(f"[API ERROR][get_party_memorandum] Error fetching from table storage: {str(table_error)}")
        return None, None, f"Failed to fetch memorandum: {str(table_error)}", 500

def fetch_opponent_memorandum_markdown(case_number):
    """
    Fetch the opponent plaintiff's memorandum markdown file from blob storage.
    
    Args:
        case_number (str): The case number
        
    Returns:
        tuple: (markdown_content, error_message, status_code)
            - markdown_content: The memorandum markdown content if found, None otherwise
            - error_message: Error message if an error occurred, None otherwise
            - status_code: HTTP status code (200 for success, 404 for not found, 500 for server error)
    """
    try:
        # Initialize blob storage client
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_name = "aila-case-evidence"
        container_client = blob_service.get_container_client(container_name)
        
        # Replace slashes in case number with hyphens for blob storage path
        safe_case_number = case_number.replace('/', '-')
        
        # Set the path for plaintiff opponent folder
        opponent_folder = "plaintiff_opponent"
        blob_path = f"{safe_case_number}/{opponent_folder}/memorandum.md"
        
        # Get the blob client
        blob_client = container_client.get_blob_client(blob_path)
        
        # Check if blob exists
        if not blob_client.exists():
            logging.error(f"[API ERROR][fetch_opponent_memorandum] Memorandum file not found at path: {blob_path}")
            return None, "Memorandum file not found", 404
        
        # Download the blob content
        download_stream = blob_client.download_blob()
        file_content = download_stream.readall().decode('utf-8')
        
        logging.info(f"[API INFO][fetch_opponent_memorandum] Successfully retrieved memorandum from: {blob_path}")
        
        return file_content, None, 200
        
    except Exception as e:
        error_message = f"Failed to fetch opponent memorandum: {str(e)}"
        logging.error(f"[API ERROR][fetch_opponent_memorandum] {error_message}")
        return None, error_message, 500
