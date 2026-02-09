from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import os
from dotenv import load_dotenv

load_dotenv()

class DocumentRecordManager(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    parentDocumentId: str = Field(..., description="Parent document ID")
    documentHash: str = Field(..., description="MD5 hash of the document")
    filename: str = Field(..., description="Original filename of the document")
    blobUrl: str = Field(..., description="Azure cdn URL")
    type: str = Field(..., description="Type of the document") 
    clientId: int = Field(..., description="Client ID")
    orgId: int = Field(..., description="Organization ID")
    isActive: bool = Field(default=True, description="Whether the document is active")
    uploadedById: int = Field(..., description="User ID who uploaded the document")
    uploadedByName: str = Field(..., description="User name who uploaded the document")
    indexedAt: datetime = Field(default_factory=datetime.utcnow, description="When the document was indexed")
    
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True
    )

class DocumentRecordModel:
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
            self.collection = self.db["DecisionDocumentRecordManager"]
            
            self._connection_successful = True
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError):
            self._connection_successful = False
            self.client = None
            self.db = None
            self.collection = None
            return False
        except Exception:
            self._connection_successful = False
            self.client = None
            self.db = None
            self.collection = None
            return False
    
    def check_document_exists(self, documentHash: str, clientId: int, orgId: int) -> bool:
        """
        Check if a document with the given hash already exists in the database.
        """
        if not self._ensure_connection():
            return False
            
        try:
            existing_document = self.collection.find_one({
                "documentHash": documentHash,
                "clientId": clientId,
                "orgId": orgId
            })
            return existing_document is not None
        except Exception as e:
            print(f"Error checking document existence: {str(e)}")
            return False
    
    def create_document_record(
        self,
        parentDocumentId: str,
        documentHash: str,
        filename: str,
        blobUrl: str,
        clientId: int,
        orgId: int,
        type: str,
        uploadedById: int,
        uploadedByName: str
    ) -> bool:
        """
        Create a new document record in the database.
        """
        if not self._ensure_connection():
            return False
            
        try:
            document_record = {
                "parentDocumentId": parentDocumentId,
                "documentHash": documentHash,
                "filename": filename,
                "blobUrl": blobUrl,
                "type": type,
                "clientId": clientId,
                "orgId": orgId,
                "isActive": True,
                "uploadedById": uploadedById,
                "uploadedByName": uploadedByName,
                "indexedAt": datetime.utcnow()
            }
            
            result = self.collection.insert_one(document_record)
            return result.inserted_id is not None
        except Exception as e:
            print(f"Error creating document record: {str(e)}")
            return False
    
    def close(self):
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            self.collection = None
            self._connection_successful = False 
