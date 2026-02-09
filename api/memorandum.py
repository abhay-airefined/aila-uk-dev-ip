import os
import sys
import logging
from typing import List , Annotated
import uuid
from fastapi import APIRouter, HTTPException, Request, Response, File, UploadFile,Form
from fastapi.responses import StreamingResponse, JSONResponse
import json
import datetime
# from service.azureTableService import AzureTableService
from dotenv import load_dotenv
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient,ContentSettings
from service.memorandumUtils import get_client_memorandum, fetch_opponent_memorandum_markdown
from service.file_utils import extract_text_from_bytes
from service.prompts import memorandum_system_prompt_plaintiff, memorandum_human_prompt_plaintiff, memorandum_system_prompt_defence, memorandum_human_prompt_defence
from service.rag import get_llm_response_with_retry
from service.models import CaseMemorandum
import requests
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
table_service = TableServiceClient.from_connection_string(connection_string)
aila_log_table = table_service.get_table_client("ailalogs")
case_status_table = table_service.get_table_client("ailacasestatus")


@router.post('/get_memorandum')
async def get_memorandum(req: Request) -> Response:
    """
    Fetch an existing memorandum for a case from the ailacases table.
    """
    logging.info("[API INFO][get_memorandum] Processing memorandum fetch request")
    
    try:
        # Get request body
        req_body = await req.json()
        case_number = req_body.get('caseNumber')
        firm_short_name = req_body.get('firmShortName')
        
        if not case_number or not firm_short_name:
            return Response(
                json.dumps({
                    "error": "Case number and firm short name are required"
                }),
                status_code=400,
                media_type="application/json"
            )
            
        # Use the utility function to get the memorandum
        english_memorandum, arabic_memorandum, error_message, status_code = get_client_memorandum(firm_short_name, case_number)
        
        if error_message and status_code != 404:
            return Response(
                json.dumps({
                    "error": error_message
                }),
                status_code=status_code,
                media_type="application/json"
            )
        
        # If no memorandum exists, return a 404 with a specific message
        if not english_memorandum and not arabic_memorandum:
            return Response(
                json.dumps({
                    "error": "No memorandum found",
                    "english_memorandum": None,
                    "arabic_memorandum": None
                }),
                status_code=404,
                media_type="application/json"
            )
        
        return Response(
            json.dumps({
                "english_memorandum": english_memorandum,
                "arabic_memorandum": arabic_memorandum
            }),
            status_code=200,
            media_type="application/json"
        )
            
    except Exception as e:
        logging.error(f"[API ERROR][get_memorandum] Error processing request: {str(e)}")
        return Response(
            json.dumps({
                "error": str(e)
            }),
            status_code=500,
            media_type="application/json"
        )

@router.post('/download_memorandum')
def download_memorandum(req: Request) -> Response:
    """
    Download the latest memorandum for a case as a markdown file.
    
    Expected JSON data:
    - caseNumber: The case number
    - firmShortName: The firm's short name
    - role: The party role ('plaintiff' or 'defendant')
    
    Returns:
    - The markdown file content for direct download
    """
    logging.info("[API INFO][download_memorandum] Processing memorandum download request")
    
    try:
        # Get request body
        req_body = req.json()
        case_number = req_body.get('caseNumber')
        firm_short_name = req_body.get('firmShortName')
        role = req_body.get('role')  # 'plaintiff' or 'defendant'
        
        # Validate required parameters
        if not case_number or not firm_short_name or not role:
            missing_params = []
            if not case_number: missing_params.append("caseNumber")
            if not firm_short_name: missing_params.append("firmShortName")
            if not role: missing_params.append("role")
            
            error_msg = f"Missing required parameters: {', '.join(missing_params)}"
            logging.error(f"[API ERROR][download_memorandum] {error_msg}")
            
            return Response(
                json.dumps({"error": error_msg}),
                status_code=400,
                media_type="application/json"
            )
        
        # Initialize blob storage client
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_name = "aila-case-evidence"
        container_client = blob_service.get_container_client(container_name)
        
        # Replace slashes in case number with hyphens for blob storage path
        safe_case_number = case_number.replace('/', '-')
        
        # Set the path to the latest memorandum file
        lawyer_folder = f"{role}_lawyer"
        latest_blob_path = f"{safe_case_number}/{lawyer_folder}/memorandum_latest.md"
        
        try:
            # Get the blob
            blob_client = container_client.get_blob_client(latest_blob_path)
            
            # Check if blob exists
            if not blob_client.exists():
                logging.error(f"[API ERROR][download_memorandum] Memorandum file not found at path: {latest_blob_path}")
                return Response(
                    json.dumps({"error": "Memorandum file not found"}),
                    status_code=404,
                    media_type="application/json"
                )
            
            # Download the blob content
            download_stream = blob_client.download_blob()
            file_content = download_stream.readall()
            
            # Create a filename for the download
            case_type = "Plaintiff" if role == "plaintiff" else "Defence"
            download_filename = f"{case_number}_{case_type}_Memorandum.md"
            
            # Create headers for file download
            headers = {
                'Content-Disposition': f'attachment; filename="{download_filename}"',
                'Content-Type': 'text/markdown'
            }
            
            logging.info(f"[API INFO][download_memorandum] Successfully downloaded memorandum file: {download_filename}")
            
            # Return the file content
            return Response(
                body=file_content,
                status_code=200,
                headers=headers,
                media_type="text/markdown"
            )
            
        except Exception as e:
            logging.error(f"[API ERROR][download_memorandum] Error downloading memorandum file: {str(e)}")
            return Response(
                json.dumps({"error": f"Failed to download memorandum: {str(e)}"}),
                status_code=500,
                media_type="application/json"
            )
            
    except Exception as e:
        logging.error(f"[API ERROR][download_memorandum] Error processing request: {str(e)}")
        return Response(
            json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json"
        )

@router.post('/generate_memorandum')
async def generate_memorandum(req: Request) -> Response:
    """
    Generate a memorandum for a case given some evidence and case details.
    """
    logging.info("[API INFO][generate_memorandum] Processing memorandum generation request")
    
    try:
        # Get request body and log it
        req_body = await req.json()
        logging.info(f"[API INFO][generate_memorandum] Request body: {json.dumps(req_body, indent=2)}")
        
        case_number = req_body.get('caseNumber')
        firm_short_name = req_body.get('firmShortName')
        party_role = req_body.get('role')  # 'plaintiff' or 'defendant'
        tone_style = req_body.get('toneStyle')
        memo_length_style = req_body.get('lengthStyle')

        # Log all parameters
        logging.info(f"[API INFO][generate_memorandum] Parameters:")
        logging.info(f"  - case_number: {case_number}")
        logging.info(f"  - firm_short_name: {firm_short_name}")
        logging.info(f"  - party_role: {party_role}")
        logging.info(f"  - tone_style: {tone_style}")
        logging.info(f"  - memo_length_style: {memo_length_style}")

        if not case_number or not party_role or not firm_short_name:
            missing_params = []
            if not case_number: missing_params.append("case_number")
            if not firm_short_name: missing_params.append("firm_short_name")
            if not party_role: missing_params.append("party_role")
            
            error_msg = f"Missing required parameters: {', '.join(missing_params)}"
            logging.error(f"[API ERROR][generate_memorandum] {error_msg}")
            
            return Response(
                json.dumps({
                    "error": error_msg
                }),
                status_code=400,
                media_type="application/json"
            )
            
        # Initialize blob storage client
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_name = "aila-case-evidence"
        container_client = blob_service.get_container_client(container_name)
        
        # Replace slashes in case number with hyphens for blob storage path
        safe_case_number = case_number.replace('/', '-')
        
        # Get client's files using {role}_client path
        client_prefix = f"{safe_case_number}/{party_role}_client/"
        logging.info(f"[API INFO][generate_memorandum] Searching for client documents in: {client_prefix}")
        
        client_blobs = list(container_client.list_blobs(name_starts_with=client_prefix))
        logging.info(f"[API INFO][generate_memorandum] Found {len(client_blobs)} client document(s)")
        
        # Log found documents
        for blob in client_blobs:
            logging.info(f"  - Found document: {blob.name}")
        
        # Extract text from client's documents
        all_text = ""
        
        for blob in client_blobs:
            try:
                # Get blob content
                blob_client = container_client.get_blob_client(blob.name)
                file_content = blob_client.download_blob().readall()
                
                # Determine content type from file extension
                filename = blob.name.split('/')[-1]
                content_type = "application/octet-stream"  # default
                
                if filename.lower().endswith('.pdf'):
                    content_type = "application/pdf"
                elif filename.lower().endswith('.docx'):
                    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                elif filename.lower().endswith('.doc'):
                    content_type = "application/msword"
                elif filename.lower().endswith('.txt'):
                    content_type = "text/plain"
                    
                logging.info(f"[API INFO][generate_memorandum] Processing {filename} as {content_type}")
                
                # Extract text
                text = extract_text_from_bytes(file_content, content_type)
                all_text += "\n\n" + text
                
                logging.info(f"[API INFO][generate_memorandum] Successfully extracted text from {filename}")
                
            except Exception as e:
                logging.error(f"[API ERROR][generate_memorandum] Error processing file {blob.name}: {str(e)}")
                continue
            
        all_text = all_text.strip()
        
        if not all_text:
            error_msg = "No text could be extracted from the client's documents"
            logging.error(f"[API ERROR][generate_memorandum] {error_msg}")
            return Response(
                json.dumps({
                    "error": error_msg
                }),
                status_code=400,
                media_type="application/json"
            )
            
        logging.info(f"[API INFO][generate_memorandum] Extracted text length from client documents: {len(all_text)}")
        
        # Fetch case details from table storage
        try:
            aila_lawyer_cases_table = table_service.get_table_client("ailalawyercases")
            case_entity = aila_lawyer_cases_table.get_entity(firm_short_name, case_number)
            
            # Create dictionaries for plaintiff and defendant details based on party role
            if party_role == 'plaintiff':
                # Client is plaintiff, opponent is defendant
                plaintiff_details = {
                    'full_name': case_entity.get('ClientFullName', ''),
                    'emirates_id': case_entity.get('ClientIdNumber', ''),
                    'address': case_entity.get('ClientAddress', ''),
                    'phone': case_entity.get('ClientPhoneNumber', ''),
                    'email': case_entity.get('ClientEmail', ''),
                    'trade_license': case_entity.get('ClientTradeLicenseNumber', '')
                }
                
                defendant_details = {
                    'full_name': case_entity.get('OpponentFullName', ''),
                    'emirates_id': case_entity.get('OpponentIdNumber', ''),
                    'address': case_entity.get('OpponentAddress', ''),
                    'phone': '',  # Not available for opponent
                    'email': '',  # Not available for opponent
                    'trade_license': case_entity.get('OpponentTradeLicenseNumber', '')
                }

                # Get additional defendants if they exist
                additional_defendants = case_entity.get('AdditionalOpponents', '')
                
            else:
                # Client is defendant, opponent is plaintiff
                plaintiff_details = {
                    'full_name': case_entity.get('OpponentFullName', ''),
                    'emirates_id': case_entity.get('OpponentIdNumber', ''),
                    'address': case_entity.get('OpponentAddress', ''),
                    'phone': '',  # Not available for opponent
                    'email': '',  # Not available for opponent
                    'trade_license': case_entity.get('OpponentTradeLicenseNumber', '')
                }
                
                defendant_details = {
                    'full_name': case_entity.get('ClientFullName', ''),
                    'emirates_id': case_entity.get('ClientIdNumber', ''),
                    'address': case_entity.get('ClientAddress', ''),
                    'phone': case_entity.get('ClientPhoneNumber', ''),
                    'email': case_entity.get('ClientEmail', ''),
                    'trade_license': case_entity.get('ClientTradeLicenseNumber', '')
                }
            
            logging.info(f"[API INFO][generate_memorandum] Successfully fetched case details from table storage")
            
        except Exception as e:
            logging.error(f"[API ERROR][generate_memorandum] Error fetching case details from table storage: {str(e)}")
            # Use empty dictionaries if table fetch fails
            plaintiff_details = {
                'full_name': '', 'emirates_id': '', 'address': '', 'phone': '', 'email': '', 'trade_license': ''
            }
            defendant_details = {
                'full_name': '', 'emirates_id': '', 'address': '', 'phone': '', 'email': '', 'trade_license': ''
            }
        
        # Get system and human prompts
        date = datetime.datetime.now().strftime("%d-%m-%Y")
        
        if party_role == 'plaintiff':
            logging.info("[API INFO][generate_memorandum] Generating plaintiff memorandum")
            system_prompt = memorandum_system_prompt_plaintiff(memo_length_style, tone_style)
            human_prompt = memorandum_human_prompt_plaintiff(
                plaintiff_case=all_text,
                date=date,
                plaintiff_details=plaintiff_details,
                defendant_details=defendant_details,
                additional_defendants=additional_defendants
            )
            logging.info("[API INFO][generate_memorandum] Included additional defendants in memorandum generation")
        else:
            logging.info("[API INFO][generate_memorandum] Generating defendant memorandum")
            # For defendant, also get plaintiff's documents from plaintiff_opponent folder
            plaintiff_prefix = f"{safe_case_number}/plaintiff_opponent/"
            logging.info(f"[API INFO][generate_memorandum] Searching for plaintiff documents in: {plaintiff_prefix}")
            
            plaintiff_blobs = list(container_client.list_blobs(name_starts_with=plaintiff_prefix))
            logging.info(f"[API INFO][generate_memorandum] Found {len(plaintiff_blobs)} plaintiff document(s)")
            
            # Log found plaintiff documents
            for blob in plaintiff_blobs:
                logging.info(f"  - Found plaintiff document: {blob.name}")
            
            plaintiff_text = ""
            
            for blob in plaintiff_blobs:
                try:
                    blob_client = container_client.get_blob_client(blob.name)
                    file_content = blob_client.download_blob().readall()
                    
                    filename = blob.name.split('/')[-1]
                    content_type = "application/octet-stream"  # default
                    
                    if filename.lower().endswith('.pdf'):
                        content_type = "application/pdf"
                    elif filename.lower().endswith('.docx'):
                        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    elif filename.lower().endswith('.doc'):
                        content_type = "application/msword"
                    elif filename.lower().endswith('.txt'):
                        content_type = "text/plain"
                    elif filename.lower().endswith('.md'):
                        content_type = "text/markdown"
                        
                    logging.info(f"[API INFO][generate_memorandum] Processing plaintiff document {filename} as {content_type}")
                    
                    # Special handling for markdown files
                    if content_type == "text/markdown":
                        text = file_content.decode('utf-8')
                        logging.info(f"[API INFO][generate_memorandum] Successfully processed markdown file directly")
                    else:
                        # Extract text for other file types
                        text = extract_text_from_bytes(file_content, content_type)
                    
                    plaintiff_text += "\n\n" + text
                    
                    logging.info(f"[API INFO][generate_memorandum] Successfully extracted text from plaintiff document {filename}")
                    
                except Exception as e:
                    logging.error(f"[API ERROR][generate_memorandum] Error processing plaintiff file {blob.name}: {str(e)}")
                    continue
            
            plaintiff_text = plaintiff_text.strip()
            logging.info(f"[API INFO][generate_memorandum] Extracted text length from plaintiff documents: {len(plaintiff_text)}")
            
            system_prompt = memorandum_system_prompt_defence(memo_length_style,tone_style)
            human_prompt = memorandum_human_prompt_defence(
                defence_case=all_text,
                plaintiff_memorandum=plaintiff_text,
                date=date,
                plaintiff_details=plaintiff_details,
                defendant_details=defendant_details
            )
            
        logging.info(f"[API INFO][generate_memorandum] Prompts formatted for {party_role}")
        
        # Get LLM response
        logging.info("[API INFO][generate_memorandum] Calling LLM for response")
        response = get_llm_response_with_retry(
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            response_format=CaseMemorandum
        )
        logging.info("[API INFO][generate_memorandum] Successfully received LLM response")
        
        # Save memorandum to blob storage and update table
        try:
            # Create a timestamp for versioning
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Define the blob path for the memorandum using {role}_client
            lawyer_folder = f"{party_role}_lawyer"
            memorandum_filename = f"memorandum_{timestamp}.md"
            blob_path = f"{safe_case_number}/{lawyer_folder}/{memorandum_filename}"
            
            # Create blob client and upload memorandum
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.upload_blob(response.english_markdown_memorandum.encode('utf-8'))
            
            logging.info(f"[API INFO][generate_memorandum] Memorandum saved to blob storage: {blob_path}")
            
            # Also save a 'latest' version that always gets overwritten
            latest_blob_path = f"{safe_case_number}/{lawyer_folder}/memorandum_latest.md"
            latest_blob_client = container_client.get_blob_client(latest_blob_path)
            
            # Delete if exists (to allow overwrite)
            try:
                latest_blob_client.delete_blob()
            except:
                pass
                
            latest_blob_client.upload_blob(response.english_markdown_memorandum.encode('utf-8'))
            
            # Update case record in table storage
            try:
                aila_lawyer_cases_table = table_service.get_table_client("ailalawyercases")
                case_entity = aila_lawyer_cases_table.get_entity(firm_short_name, case_number)
                
                # Update the memorandum fields
                case_entity['MemorandumEnglish'] = response.english_markdown_memorandum
                case_entity['MemorandumArabic'] = response.arabic_markdown_memorandum
                
                aila_lawyer_cases_table.update_entity(case_entity)
                
                logging.info(f"[API INFO][generate_memorandum] Updated case record with memorandum for {party_role}")
                
            except Exception as table_error:
                logging.error(f"[API ERROR][generate_memorandum] Error updating table storage: {str(table_error)}")
                # Continue execution - we'll still return the memorandum even if table update fails
            
            # Return the memorandum and blob info
            return Response(
                json.dumps({
                    "english_markdown_memorandum": response.english_markdown_memorandum,
                    "arabic_markdown_memorandum": response.arabic_markdown_memorandum,
                    "blob_path": blob_path,
                    "latest_blob_path": latest_blob_path,
                    "url": blob_client.url
                }),
                status_code=200,
                media_type="application/json"
            )
            
        except Exception as e:
            logging.error(f"[API ERROR][generate_memorandum] Error saving memorandum to blob storage: {str(e)}")
            # Still return the memorandum even if saving fails
            return Response(
                json.dumps({
                    "english_markdown_memorandum": response.english_markdown_memorandum,
                    "arabic_markdown_memorandum": response.arabic_markdown_memorandum,
                    "error": f"Failed to save memorandum to storage: {str(e)}"
                }),
                status_code=200,
                media_type="application/json"
            )
            
    except Exception as e:
        logging.error(f"[API ERROR][generate_memorandum] Error generating memorandum: {str(e)}")
        return Response(
            json.dumps({
                "error": str(e)
            }),
            status_code=500,
            media_type="application/json"
        )

@router.post('/upload_plaintiff_memorandum')
async def upload_plaintiff_memorandum(
    file: Annotated[UploadFile, File(...)],               # field name must be "file"
    caseNumber: Annotated[str, Form(...)],
    firmShortName: Annotated[str, Form(...)]
):
    """
    Upload a plaintiff's memorandum DOCX, convert to Markdown via external service,
    and save under: {caseNumber}/plaintiff_opponent/memorandum.md
    """
    logging.info("[API INFO][upload_plaintiff_memorandum] Processing plaintiff memorandum upload request")

    # --- Validate inputs ---
    if not (file.filename and file.filename.lower().endswith(".docx")):
        raise HTTPException(status_code=400, detail="Invalid file format. Only .docx files are accepted.")
    if not caseNumber or not firmShortName:
        raise HTTPException(status_code=400, detail="Missing required parameters: caseNumber, firmShortName")

    doc_converter_base = os.getenv("DOC_CONVERTER_BASE_URL")
    if not doc_converter_base:
        raise HTTPException(status_code=500, detail="DOC_CONVERTER_BASE_URL is not configured")

    try:
        # --- Convert DOCX to Markdown via external service (non-blocking) ---
        convert_url = f"{doc_converter_base.rstrip('/')}/docx_to_markdown"

        # Ensure stream is at start; stream the temp file instead of reading into RAM
        try:
            file.file.seek(0)
        except Exception:
            pass

        files = {
            "file": (
                file.filename,
                file.file,  # stream
                file.content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }

        logging.info(f"[API INFO][upload_plaintiff_memorandum] Converting docx using {convert_url}")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(convert_url, files=files)

        if resp.status_code >= 400:
            logging.error(f"[API ERROR][upload_plaintiff_memorandum] Converter error {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=500, detail=f"Failed to convert document: {resp.text}")

        markdown_content = resp.text

        # --- Upload Markdown to Azure Blob Storage ---
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service.get_container_client("aila-case-evidence")

        safe_case_number = caseNumber.replace("/", "-")
        blob_path = f"{safe_case_number}/plaintiff_opponent/memorandum.md"
        blob_client = container_client.get_blob_client(blob_path)

        blob_client.upload_blob(
            markdown_content.encode("utf-8"),
            overwrite=True,  # replace previous memorandum if present
            content_settings=ContentSettings(content_type="text/markdown; charset=utf-8"),
        )
        logging.info(f"[API INFO][upload_plaintiff_memorandum] Memorandum saved: {blob_path}")

        # --- Update Table Storage flag (best-effort) ---
        try:
            aila_lawyer_cases_table = table_service.get_table_client("ailalawyercases")
            case_entity = aila_lawyer_cases_table.get_entity(firmShortName, caseNumber)
            case_entity["OpponentMemorandum"] = True
            aila_lawyer_cases_table.update_entity(case_entity)
            logging.info("[API INFO][upload_plaintiff_memorandum] OpponentMemorandum=True updated")
        except Exception as table_error:
            logging.error(f"[API ERROR][upload_plaintiff_memorandum] Table update failed: {table_error}")

        return JSONResponse({
            "success": True,
            "message": "Plaintiff's memorandum uploaded and converted successfully",
            "blob_path": blob_path,
        })

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[API ERROR][upload_plaintiff_memorandum] Unexpected error")
        return JSONResponse({"error": f"Failed to process memorandum: {str(e)}"}, status_code=500)

@router.get('/fetch_memorandum_markdown')
def fetch_memorandum_markdown(req: Request) -> Response:
    """
    Fetch the opponent plaintiff's memorandum markdown file and return the markdown content.
    
    Expected query parameters:
    - caseNumber: The case number
    
    Returns:
    - The markdown content as plain text
    """
    logging.info("[API INFO][fetch_memorandum_markdown] Processing request to fetch opponent memorandum markdown")
    
    try:
        # Get query parameters
        case_number = req.query_params.get('caseNumber')
        
        # Validate required parameters
        if not case_number:
            error_msg = "Missing required parameter: caseNumber"
            logging.error(f"[API ERROR][fetch_memorandum_markdown] {error_msg}")
            
            return Response(
                json.dumps({"error": error_msg}),
                status_code=400,
                media_type="application/json"
            )
        
        # Use the utility function to fetch the markdown content
        markdown_content, error_message, status_code = fetch_opponent_memorandum_markdown(case_number)
        
        if error_message:
            return Response(
                json.dumps({"error": error_message}),
                status_code=status_code,
                media_type="application/json"
            )
        
        # Return the markdown content as plain text
        return Response(
            markdown_content,
            status_code=200,
            media_type="text/markdown"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][fetch_memorandum_markdown] Error processing request: {str(e)}")
        return Response(
            json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json"
        )
