from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Dict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import os
from dotenv import load_dotenv

load_dotenv()

class Decision(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    case_name: Optional[str] = Field(alias="Case_name", default=None)
    from_tribunal: Optional[List[str]] = Field(alias="From", default=None)
    published_date: Optional[date] = Field(alias="Published_date", default=None)
    country: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    decision_date: Optional[date] = Field(alias="Decision_date", default=None)
    pdf_urls: Optional[List[str]] = None
    judgement_file_path: Optional[List[str]] = Field(alias="Judgement_file_path", default=None)
    md_file_paths: Optional[Dict[str, str]] = None
    
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True
    )

class DecisionModel:
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
            self.collection = self.db["employment-tribunal-decisions"]
            
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

    def getAll_decision(self) -> Optional[List[Decision]]:
        """
        Get all decision records.
        
        Returns:
            List of Decision objects or None
        """
        if not self._ensure_connection():
            return None
            
        try:
            documents_data = self.collection.find()
            return documents_data
        except Exception as e:
            print(f"Error retrieving decision records: {str(e)}")
            return None
         
    def get_paginated_decision(self, page_start: int, page_size: int) -> Optional[List[Decision]]:
        """
        Get a paginated list of decisions.
        
        Args:
            page: The page number
            page_size: The number of decisions per page
            
        Returns:
            List of Decision objects
        """
        if not self._ensure_connection():
            return None
        
        try:
            skip = (page_start - 1) * page_size
            decisions_data = list(self.collection.find().skip(skip).limit(page_size))
            for decision in decisions_data:
                if "_id" in decision:
                    decision["_id"] = str(decision["_id"])
            return [Decision(**decision) for decision in decisions_data]
        except Exception as e:
            print(f"Error retrieving paginated decisions: {str(e)}")
            return None
        
    def get_paginated_decision_by_jurisdiction_code(self, page_start: int, page_size: int, jurisdiction_code: str) -> Optional[List[Decision]]:
        """
        Get a paginated list of decisions.
        
        Args:
            page: The page number
            page_size: The number of decisions per page
            
        Returns:
            List of Decision objects
        """
        if not self._ensure_connection():
            return None
        
        try:
            skip = (page_start - 1) * page_size
            decisions_data = list(self.collection.find({"jurisdiction_code": jurisdiction_code}).skip(skip).limit(page_size))
            for decision in decisions_data:
                if "_id" in decision:
                    decision["_id"] = str(decision["_id"])
            return [Decision(**decision) for decision in decisions_data]
        except Exception as e:
            print(f"Error retrieving paginated decisions: {str(e)}")
            return None
    
    def close(self):
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            self.collection = None
            self._connection_successful = False
