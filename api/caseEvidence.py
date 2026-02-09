import os
import sys
import logging
from typing import List
import uuid
from fastapi import APIRouter, HTTPException, Request, Response, File, UploadFile,Form
from typing import List, Literal, Annotated
from fastapi.responses import StreamingResponse,JSONResponse
import json

# from com.sequation.document.service.azureTableService import AzureTableService
from dotenv import load_dotenv
import datetime
from azure.data.tables import TableServiceClient
from service.rag import run_rag
from service.lawyer_rag import run_lawyer_rag
from service.file_utils import extract_text_from_bytes
from service.commonCaseUtils import format_timestamp, get_next_case_number
from azure.storage.blob import BlobServiceClient,ContentSettings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
table_service = TableServiceClient.from_connection_string(connection_string)
aila_log_table = table_service.get_table_client("ailalogs")
case_status_table = table_service.get_table_client("ailacasestatus")

@router.post('/upload_evidence')
async def upload_evidence(
    caseNumber: Annotated[str, Form(...)],
    firmShortName: Annotated[str, Form(...)],
    role: Annotated[Literal["plaintiff","defendant"], Form(...)],
    files: Annotated[List[UploadFile], File(..., alias="files")]) -> Response:
    """
    Upload evidence files for a case participant
    
    Expected form data:
    - caseNumber: The case number
    - firmShortName: The firm short name
    - role: Either 'plaintiff' or 'defendant'
    - files: One or more files to upload
    
    Returns:
    - JSON with success message and file URLs
    """
    logging.info("[API INFO][upload_evidence] Processing evidence upload request")

    # Basic validation (FastAPI already enforces most of this)
    if role not in ("plaintiff", "defendant"):
        raise HTTPException(status_code=400, detail="Valid role (plaintiff or defendant) is required")
    if not files:
        raise HTTPException(status_code=400, detail="At least one file must be uploaded")

    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_name = "aila-case-evidence"
        container_client = blob_service.get_container_client(container_name)

        uploaded_files = []
        safe_case_number = caseNumber.replace("/", "-")
        role_path = f"{role}_client"

        for up in files:
            original_filename = up.filename or "upload.bin"

            # sanitize name (spaces allowed)
            safe_filename = original_filename
            for ch in ['\\', '?', '%', '*', ':', '|', '"', '<', '>', '/']:
                safe_filename = safe_filename.replace(ch, '_')

            if '.' in safe_filename:
                file_name_without_ext, file_extension = safe_filename.rsplit('.', 1)
            else:
                file_name_without_ext, file_extension = safe_filename, "bin"

            # check duplicates (same base, any sequence)
            prefix = f"{safe_case_number}/{role_path}/{file_name_without_ext}"
            existing = list(container_client.list_blobs(name_starts_with=prefix))

            # compute next sequence if needed
            next_name = file_name_without_ext
            if existing:
                seqs = []
                for b in existing:
                    tail = b.name.split('/')[-1]
                    # matches "name.ext" or "name (N).ext"
                    if tail.startswith(file_name_without_ext + " (") and tail.endswith(f".{file_extension}"):
                        try:
                            num = tail[len(file_name_without_ext) + 2 : -(len(file_extension) + 2)]  # inside (N)
                            if num.isdigit():
                                seqs.append(int(num))
                        except Exception:
                            pass
                    elif tail == f"{file_name_without_ext}.{file_extension}":
                        seqs.append(0)
                n = (max(seqs) + 1) if seqs else 1
                if n > 0:
                    next_name = f"{file_name_without_ext} ({n})"

            blob_path = f"{safe_case_number}/{role_path}/{next_name}.{file_extension}"
            blob_client = container_client.get_blob_client(blob_path)

            # STREAM upload (no large byte buffer in memory)
            # Ensure file pointer at start:
            try:
                up.file.seek(0)
            except Exception:
                pass

            # Optional: set content type if FastAPI provided one
            content_settings = ContentSettings(content_type=up.content_type or None)

            # Important: do NOT pass a coroutine. Use the file object or await read()
            blob_client.upload_blob(
                data=up.file,                 # <— stream the temp file
                overwrite=False,              # we already made the name unique
                content_settings=content_settings,
                max_concurrency=2,            # tweak as desired
            )

            uploaded_files.append({
                "fileName": original_filename,
                "blobPath": blob_path,
                "url": blob_client.url,
            })

        # Update the case record to set DocumentsUploaded to True
        try:
            # Update case in ailalawyercases table
            lawyer_cases_table = table_service.get_table_client("ailalawyercases")
            try:
                # Get the case entity
                case_entity = lawyer_cases_table.get_entity(firmShortName, caseNumber)
                
                # Update the DocumentsUploaded field
                case_entity["DocumentsUploaded"] = True
                
                # Update the entity in the table
                lawyer_cases_table.update_entity(case_entity)
                logging.info(f"[API INFO][upload_evidence] Updated DocumentsUploaded for case: {caseNumber}")
            except Exception as case_error:
                logging.info(f"Connection string: {connection_string}")
                logging.info(f"firm_short_name: {firmShortName}")
                logging.info(f"case_number: {caseNumber}")
                logging.error(f"[API ERROR][upload_evidence] Error updating case record: {case_error}")
        except Exception as table_error:
            logging.error(f"[API ERROR][upload_evidence] Error with table operations: {table_error}")

        return JSONResponse({
            "message": f"Successfully uploaded {len(uploaded_files)} files",
            "files": uploaded_files
        })

    except Exception as e:
        logging.exception(f"[API ERROR][upload_evidence] Error uploading evidence: {str(e)}")
        return JSONResponse(
            {"message": f"Failed to upload evidence: {str(e)}"},
            status_code=500
        )

@router.get('/get_evidence')
def get_evidence(req: Request) -> Response:
    """
    Get evidence files for a case and role
    
    Query parameters:
    - caseNumber: The case number
    - firmShortName: The firm short name
    - role: Either 'plaintiff' or 'defendant'
    
    Returns:
    - JSON with list of evidence files
    """
    logging.info("[API INFO][get_evidence] Processing evidence retrieval request")
    
    try:
        # Extract query parameters
        case_number = req.query_params.get('caseNumber')
        firm_short_name = req.query_params.get('firmShortName')
        role = req.query_params.get('role')
        
        # Validate required parameters
        if not case_number:
            return Response(
                json.dumps({"message": "Case number is required"}),
                status_code=400,
                media_type="application/json"
            )
            
        if not firm_short_name:
            return Response(
                json.dumps({"message": "Firm short name is required"}),
                status_code=400,
                media_type="application/json"
            )
        
        if not role or role not in ['plaintiff', 'defendant']:
            return Response(
                json.dumps({"message": "Valid role (plaintiff or defendant) is required"}),
                status_code=400,
                media_type="application/json"
            )
        
        # Initialize blob storage client
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_name = "aila-case-evidence"
        container_client = blob_service.get_container_client(container_name)
        
        # Replace slashes in case number with hyphens for blob storage path
        safe_case_number = case_number.replace('/', '-')
        
        # Format path to case-number/role_of_client/
        role_path = f"{role}_client"
        
        # List blobs with prefix case_number/role_of_client/
        prefix = f"{safe_case_number}/{role_path}/"
        blobs = container_client.list_blobs(name_starts_with=prefix)
        
        # Process blob list into a more user-friendly format
        files = []
        for blob in blobs:
            # Extract filename from the blob path
            path_parts = blob.name.split('/')
            if len(path_parts) > 2:
                file_name = path_parts[-1]
                
                # Handle display of numbered duplicate files
                # If filename has a number suffix pattern like "document (1).pdf"
                if " (" in file_name and ")" in file_name.split(" (")[-1]:
                    try:
                        # Extract the parts
                        base_part = file_name.split(" (")[0]
                        seq_part = file_name.split(" (")[-1]
                        extension_part = ""
                        
                        # Check if there's an extension
                        if "." in seq_part:
                            extension_part = "." + seq_part.split(".")[-1]
                            seq_part = seq_part.split(".")[0]
                        
                        # Extract sequence number
                        seq_number = seq_part.split(")")[0]
                        if seq_number.isdigit():
                            # This is a numbered duplicate
                            display_name = f"{base_part} ({seq_number}){extension_part}"
                        else:
                            # Not a duplicate, keep original
                            display_name = file_name
                    except:
                        # If any parsing errors occur, use the original name
                        display_name = file_name
                # Keep old timestamp handling for backward compatibility
                elif '_202' in file_name and len(file_name.split('_')) > 2:
                    # Try to find the timestamp part (e.g., "20230815_123045")
                    parts = file_name.split('_')
                    timestamp_index = -1
                    for i, part in enumerate(parts):
                        if part.startswith('202') and len(part) == 8 and i < len(parts) - 1 and parts[i+1].isdigit():
                            timestamp_index = i
                            break
                    
                    if timestamp_index > 0:
                        # Reconstruct display name without timestamp
                        display_name = '_'.join(parts[:timestamp_index])
                        extension = file_name.split('.')[-1] if '.' in file_name else ''
                        if extension:
                            display_name += '.' + extension
                    else:
                        # If timestamp format is different, just use the filename
                        display_name = file_name
                else:
                    display_name = file_name
                
                file_id = file_name.split('.')[0]
                
                # Get blob URL
                blob_client = container_client.get_blob_client(blob.name)
                
                files.append({
                    "fileName": display_name,
                    "originalFileName": file_name,
                    "blobPath": blob.name,
                    "fileId": file_id,
                    "url": blob_client.url,
                    "contentLength": blob.size,
                    "lastModified": blob.last_modified.isoformat()
                })
        
        return Response(
            json.dumps({
                "caseNumber": case_number,
                "safeCaseNumber": safe_case_number,
                "role": role,
                "files": files
            }),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][get_evidence] Error retrieving evidence: {str(e)}")
        return Response(
            json.dumps({"message": f"Failed to retrieve evidence: {str(e)}"}),
            status_code=500,
            media_type="application/json"
        ) 
        
@router.get('/get_case_status')
def get_case_status(req: Request) -> Response:
    """Get the current status of a case analysis"""
    try:
        case_id = req.query_params.get('case_id')
        silent = req.query_params.get('silent', 'false').lower() == 'true'
        is_warmup = case_id == "warmup-test-case"
        
        if not case_id:
            if not is_warmup and not silent:
                logging.error("[API ERROR][get_case_status] Case ID is required")
            return Response("Case ID is required", status_code=400)
        
        # Handle warmup request first
        if is_warmup:
            if not silent:
                logging.info("[API INFO][get_case_status] Endpoint warmup complete")
            mock_response = {
                "status": "warmup",
                "currentStep": "Warmup test",
                "completedSteps": [],
                "result": None,
                "case_number": None
            }
            return Response(
                json.dumps(mock_response),
                status_code=200,
                media_type="application/json"
            )
            
        # Only query the table for non-warmup requests
        case_entity = case_status_table.get_entity('cases', case_id)
        if not case_entity:
            if not silent:
                logging.error(f"[API ERROR][get_case_status] Case {case_id} not found")
            return Response("Case not found", status_code=404)
            
        response = {
            "status": case_entity['Status'],
            "currentStep": case_entity['CurrentStep'],
            "completedSteps": json.loads(case_entity['CompletedSteps']),
            "result": json.loads(case_entity['Result']) if case_entity['Result'] else None,
            "case_number": case_entity.get('CaseNumber')
        }
        
        if not silent:
            logging.info(f"[API INFO][get_case_status] Case {case_id} status: {json.dumps(response)}")
        
        return Response(
            json.dumps(response),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        if not is_warmup and not silent:
            logging.error(f"[API ERROR][get_case_status] Error getting case status: {str(e)}")
        return Response(str(e), status_code=500)