import time
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from fastapi import UploadFile
from config.dbConfig import db
import os
import logging
from service.config import Config
from fastapi import HTTPException

logger = logging.getLogger(__name__)

client = Config.buildWeaviateConnection()
weaviate_collection_name = os.getenv("WEAVIATE_COLLECTION_NAME")
load_dotenv()
class AzureBlobService:

    def __init__(self):
        self.connection_string = os.getenv("CONNECTION_STRING")
        self.container_name = os.getenv("CONTAINER_NAME")
        self.common_cases_blob_name = os.getenv("COMMON_CASES_BLOB_NAME")
        self.cases_azure_connection_string = os.getenv("CASES_AZURE_STORAGE_CONNECTION_STRING")

    def upload_file(self, file: UploadFile, file_name_override: str = None):
        blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        container_client = blob_service_client.get_container_client(self.container_name)
        blob_name = file_name_override if file_name_override else file.filename
        blob_client = container_client.get_blob_client(blob=blob_name)
        blob_client.upload_blob(file.file, overwrite=True)
        return blob_client.url
        
    def fetch_file(self, file_path: str, container_name: str = None):
        try:
            blob_service_client = BlobServiceClient.from_connection_string(self.cases_azure_connection_string)
            container_client = blob_service_client.get_container_client(container_name)
            blob_client = container_client.get_blob_client(blob=file_path)
            return blob_client.download_blob().readall()
        except ResourceNotFoundError:
            logger.error(f"File not found: {file_path} in container: {container_name}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching file {file_path}: {e}")
            return None

    def fetch_files_locally(self, file_path: str):
        try:
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except ResourceNotFoundError:
            logger.error(f"File not found: {file_path}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching file {file_path}: {e}")
            return None
