from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Dict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import os
from dotenv import load_dotenv

load_dotenv()

class Appeal(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    case_name: Optional[str] = Field(alias="Case_name", default=None)
    case_details: Optional[str] = Field(alias="Case_details", default=None)
    from_tribunal: Optional[List[str]] = Field(alias="From", default=None)
    published_date: Optional[date] = Field(alias="Published_date", default=None)
    category: Optional[List[str]] = Field(alias="Category", default=None)
    sub_category: Optional[List[str]] = Field(alias="SubCategory", default=None)
    landmark: Optional[str] = Field(alias="Landmark", default=None)
    decision_date: Optional[date] = Field(alias="Decision_date", default=None)
    appeal_judgement_file_path: Optional[List[str]] = Field(alias="Appeal_Judgement_file_path", default=None)
    pdf_urls: Optional[List[str]] = None
    md_file_paths: Optional[Dict[str, str]] = None
    
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True
    )

class AppealModel:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self._connection_attempted = False
        self._connection_successful = False
    
    def _ensure_connection(self) -> bool:
        """Ensure MongoDB connection is established. Returns True if successful."""
        if self._connection_attempted and self._connection_successful:
            return True
        
        if self._connection_attempted and not self._connection_successful:
            return False
        
        self._connection_attempted = True
        
        mongodb_host = os.getenv("MONGODB_HOST")
        
        try:
            self.client = MongoClient(mongodb_host, serverSelectionTimeoutMS=3000)
            self.db = self.client.get_default_database()
            self.collection = self.db["employment-appeal-tribunal-decisions"]
            
            self._connection_successful = True
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"MongoDB connection error: {e}")
            self._connection_successful = False
            self.client = None
            self.db = None
            self.collection = None
            return False
        except Exception as e:
            print(f"An unexpected error occurred during MongoDB connection: {e}")
            self._connection_successful = False
            self.client = None
            self.db = None
            self.collection = None
            return False
    
    def check_document_exists_by_hash(self, documentHash: str) -> bool:
        if not self._ensure_connection():
            return False
        try:
            return self.collection.count_documents({"documentHash": documentHash}) > 0
        except Exception as e:
            print(f"Error checking document existence by hash: {e}")
            return False

    def create_document_from_metadata(self, documentHash: str, filename: str, blobUrl: str) -> bool:
        if not self._ensure_connection():
            return False
        try:
            document_record = {
                "documentHash": documentHash,
                "filename": filename,
                "blobUrl": blobUrl,
                "indexedAt": datetime.utcnow()
            }
            self.collection.insert_one(document_record)
            return True
        except Exception as e:
            print(f"Error creating document from metadata: {e}")
            return False

    def getAll_appeal(self) -> Optional[List[Appeal]]:
        """
        Get all appeal records.
        
        Returns:
            List of Appeal objects or None
        """
        if not self._ensure_connection():
            return None
            
        try:
            documents_data = list(self.collection.find())
            for doc in documents_data:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            return [Appeal(**doc) for doc in documents_data]
        except Exception as e:
            print(f"Error retrieving appeal records: {str(e)}")
            return None
         
    def get_paginated_appeal(self, page: int, page_size: int) -> Optional[List[Appeal]]:
        """
        Get a paginated list of appeals.
        
        Args:
            page: The page number
            page_size: The number of decisions per page
            
        Returns:
            List of Appeal objects
        """
        if not self._ensure_connection():
            return None
        
        try:
            skip = (page - 1) * page_size
            appeals_data = list(self.collection.find().skip(skip).limit(page_size))
            for appeal in appeals_data:
                if "_id" in appeal:
                    appeal["_id"] = str(appeal["_id"])
            return [Appeal(**appeal) for appeal in appeals_data]
        except Exception as e:
            print(f"Error retrieving paginated appeals: {str(e)}")
            return None
    
    def close(self):
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            self.collection = None
            self._connection_successful = False
