from typing import List
from fastapi import APIRouter, File, HTTPException, UploadFile
import logging
from service.azureBlobService import AzureBlobService
from service.weaviateService import WeaviateService
from models.decision import DecisionModel
from models.appeal import AppealModel
from models.documentRecord import DocumentRecordModel
from dotenv import load_dotenv
import os
from datetime import datetime, time
import hashlib
import traceback
from service.splitter import SuperRecursiveSplitter
from models.chatModels import IngestRequest
from pathlib import Path
import time as sleep
import tiktoken

router = APIRouter()
logger = logging.getLogger(__name__)
log_path = Path("ingest_debug.log")
try:
    log_path.write_text("", encoding="utf-8", errors="ignore")
except Exception:
    pass
logger.setLevel(logging.DEBUG)
 
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
 
file_handler = logging.FileHandler(log_path)
file_handler.setFormatter(formatter)
 
if not logger.handlers:
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
 
logger.info("✅ Logging system initialized (ingest.py)")

load_dotenv()

@router.post('/ingest')
async def ingest(request: IngestRequest):
    try:
        if request.type not in ['decision', 'appeal']:
            raise HTTPException(status_code=400, detail="Invalid type specified. Type must be 'decision' or 'appeal'.")

        sourceModel = DecisionModel() if request.type == 'decision' else AppealModel()
        caseRecordModel = DocumentRecordModel()
        weaviateService = WeaviateService()
        azureBlobService = AzureBlobService()
        
        processed_files = []
        skipped_files = []
        
        orgId = 1
        tenantId = 1
        
        page_start = request.page_start
        page_end = request.page_end
        page_size = request.page_size

        logger.info(f"Starting ingestion process for {request.type} documents from page {page_start} to {page_end} (page size: {page_size})")
        while True and page_start <= page_end:
            logger.info(f"Processing page {page_start} of {request.type} documents")
            
            documents = sourceModel.get_paginated_decision_by_jurisdiction_code(page_start, page_size, request.jurisdiction_code) if request.type == 'decision' else sourceModel.get_paginated_appeal(page_start, page_size)    
            
            if not documents:
                logger.info(f"No more documents to process")
                break

            for doc in documents:
                logger.info(f"Processing document: {doc.id}")
                if not doc.md_file_paths:
                    continue

                for pdf_path, md_path in doc.md_file_paths.items():
                    
                    logger.info(f"Processing document: {doc.id} with pdf_path: {pdf_path} and md_path: {md_path}")
                    container_name = os.getenv("DECISION_CONTAINER_NAME") if request.type == 'decision' else os.getenv("APPEAL_CONTAINER_NAME")
                    full_md_blob_path = f"{container_name}/{md_path}"
                    full_pdf_blob_path = f"{container_name}/{pdf_path}"
                    
                    db_path_clean = md_path.lstrip("/\\")
                    db_path_clean = db_path_clean.replace("\\", "/")  # unify separators
                    db_path_clean = Path(db_path_clean)  # let Path handle OS format
                    
                    full_path = Path(os.getenv("LOCAL_PATH"))/container_name/db_path_clean
                    try:
                        logger.info(f"Fetching file content for md_path: {md_path}")

                        file_content = azureBlobService.fetch_files_locally(full_path)
                        
                        if file_content is None:
                            logger.error(f"File content not found for md_path: {md_path}")
                            skipped_files.append({"filename": md_path, "reason": "File not found in Azure Blob Storage"})
                            continue
                        
                        logger.info(f"File content fetched for md_path: {md_path}")
                        full_text = file_content
                        
                        md5Hash = hashlib.md5(full_text.encode('UTF-8')).hexdigest()
                        
                        document_record = {
                            "parentDocumentId": doc.id,
                            "documentHash": md5Hash,
                            "filename": md_path,
                            "blobUrl": f"{full_md_blob_path}",
                            "clientId": tenantId,
                            "orgId": orgId,
                            "type": request.type,
                            "uploadedById": tenantId,
                            "uploadedByName": "Meganexus"
                        }   

                        # Check if document already exists
                        documentExists = caseRecordModel.check_document_exists(md5Hash, tenantId, orgId)
                        weaviateDocumentExists = weaviateService.check_document_exists(md5Hash, str(tenantId), orgId)

                        if documentExists and not weaviateDocumentExists:
                            logger.info(f"Document already exists in caseRecordModel but not in weaviate: {md_path}")
                            
                            encoding = tiktoken.get_encoding("cl100k_base")
                            token_count = len(encoding.encode(full_text))

                            if token_count > 8000:
                                chunks = weaviateService.chunk_and_embed_document(full_text, request.type, doc, full_pdf_blob_path, md5Hash, orgId)
                            else:
                                chunks = weaviateService.create_document_chunk(full_text, request.type, doc, full_pdf_blob_path, md5Hash, orgId)
                            
                            weaviateService.upload_documents(chunks, str(tenantId))
                            processed_files.append({"filename": md_path, "reason": "Successfully ingested"})
                        elif not documentExists and weaviateDocumentExists:
                            logger.info(f"Document already exists in weaviate but not in caseRecordModel: {md_path}")
                            # Create a record in CaseDocumentRecordManager
                            caseRecordModel.create_document_record(**document_record)
                            skipped_files.append({"filename": md_path, "reason": "Already ingested"})
                            continue
                        elif not documentExists and not weaviateDocumentExists:
                            logger.info(f"Document does not exist in caseRecordModel or weaviate: {md_path}")
                            
                            encoding = tiktoken.get_encoding("cl100k_base")
                            token_count = len(encoding.encode(full_text))

                            if token_count > 8000:
                                chunks = weaviateService.chunk_and_embed_document(full_text, request.type, doc, full_pdf_blob_path, md5Hash, orgId)
                            else:
                                chunks = weaviateService.create_document_chunk(full_text, request.type, doc, full_pdf_blob_path, md5Hash, orgId)
                            
                            weaviateService.upload_documents(chunks, str(tenantId))
                            
                            caseRecordModel.create_document_record(**document_record)
                            processed_files.append({"filename": md_path, "reason": "Successfully ingested"})
                        else:
                            logger.info(f"Document already exists in caseRecordModel and weaviate: {md_path}")
                            skipped_files.append({"filename": md_path, "reason": "Already ingested"})
                            continue
                        
                        logger.info(f"Uploaded document: {md_path} to weaviate and id: {doc.id}")
                        
                        # sleep.sleep(request.sleep_seconds)
                        
                    except Exception as e:
                        logger.error(f"Error processing file {md_path}: {e}")
                        skipped_files.append({"filename": md_path, "reason": str(e)})

            page_start += 1

        sourceModel.close()
        caseRecordModel.close()
        weaviateService.close()
            
        return {
            "message": "File ingestion completed",
            "summary": {
                "processed": len(processed_files), 
                "skipped": len(skipped_files)
            }
        }
    except Exception as e:
        logger.error(f"Error during file ingestion: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/deleteCollection')
async def deleteCollection():
    weaviateService = WeaviateService()
    weaviateService.delete_collection()
    return {"message": "Collection deleted"}
