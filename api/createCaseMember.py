import os
import sys
import logging
from typing import List
import uuid
from fastapi import APIRouter, HTTPException, Request, Response, File, UploadFile
from fastapi.responses import StreamingResponse
import json

# from com.sequation.document.service.azureTableService import AzureTableService
from dotenv import load_dotenv
import datetime
from azure.data.tables import TableServiceClient
from service.rag import run_rag
from service.lawyer_rag import run_lawyer_rag
from service.file_utils import extract_text_from_bytes
from service.commonCaseUtils import format_timestamp, get_next_case_number

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
table_service = TableServiceClient.from_connection_string(connection_string)
aila_log_table = table_service.get_table_client("ailalogs")
case_status_table = table_service.get_table_client("ailacasestatus")

@router.post('/create_case_reference')
async def create_case_reference(req: Request) -> Response:
    """
    Create a new case reference and store case details in the 'ailalawyercases' table.
    Uses the case number as the RowKey for direct access.
    
    Expected JSON data:
    - firmShortName: Short name of the law firm
    - lawyerUsername: Username of the lawyer creating the case
    - representingParty: Which party the lawyer represents ('plaintiff' or 'defendant') - This determines which details map to Plaintiff/Defendant in the DB.
    - natureOfClaimCategory: Category of the claim
    - caseSummary: Detailed summary for 'Other' category
    - clientFullName: Full name of the client
    - clientIdNumber: ID number of the client
    - clientAddress: Address of the client
    - clientPhoneNumber: Phone number of the client
    - clientEmail: Email of the client
    - clientTradeLicenseNumber: Trade license number if client is a business and representing defendant (optional)
    - opponentFullName: Full name of the opponent
    - opponentAddress: Address of the opponent
    - opponentIdNumber: ID number of the opponent (optional)
    - opponentTradeLicenseNumber: Trade license number if opponent is a business and representing plaintiff (optional)
    
    Returns:
    - JSON with case_number
    """
    logging.info("[API INFO][create_case_reference] Processing new case reference request")
    
    try:
        # Get JSON data from request
        req_body = await req.json()
        
        # --- Updated Required Fields ---
        required_fields = [
            'firmShortName',
            'lawyerUsername',
            'representingParty',
            'natureOfClaimCategory',
            'clientFullName',
            'clientIdNumber',
            'clientAddress',
            'clientPhoneNumber',
            'clientEmail',
            'opponentFullName',
            'opponentAddress'
        ]
        
        # Validate required fields
        for field in required_fields:
            if not req_body.get(field):
                return Response(
                    json.dumps({"message": f"'{field}' is required"}), # Added quotes for clarity
                    status_code=400,
                    media_type="application/json"
                )
        
        # Validate representing party value
        representing_party = req_body['representingParty']
        if representing_party not in ['plaintiff', 'defendant']:
            return Response(
                json.dumps({"message": "representingParty must be either 'plaintiff' or 'defendant'"}),
                status_code=400,
                media_type="application/json"
            )
        
        # Extract optional fields with defaults
        case_summary = req_body.get('caseSummary', '')  # Only required if natureOfClaimCategory is 'Other'
        if req_body['natureOfClaimCategory'] == 'Other' and not case_summary:
            return Response(
                json.dumps({"message": "Case summary is required for 'Other' category"}),
                status_code=400,
                media_type="application/json"
            )
            
        # --- Extract Client/Opponent Optional Fields ---
        client_trade_license = req_body.get('clientTradeLicenseNumber', '')
        opponent_id_number = req_body.get('opponentIdNumber', '')
        opponent_trade_license = req_body.get('opponentTradeLicenseNumber', '')
        
        # Get the next case number using the modified utility function
        lawyer_cases_table = table_service.get_table_client("ailalawyercases")
        case_number = get_next_case_number(lawyer_cases_table, req_body['firmShortName'])
        
        # Create entity for ailalawyercases table using Client/Opponent terminology
        case_entity = {
            'PartitionKey': req_body['firmShortName'],
            'RowKey': case_number,
            'CreatedAt': datetime.datetime.utcnow().isoformat(),
            'Status': 'pending',
            'LawyerUsername': req_body['lawyerUsername'],
            'RepresentingParty': representing_party, # Still store who the lawyer represents
            # Nature of Claim
            'NatureOfClaim': req_body['natureOfClaimCategory'],
            'CaseSummary': case_summary,
            # --- Client Details ---
            'ClientFullName': req_body['clientFullName'],
            'ClientIdNumber': req_body['clientIdNumber'],
            'ClientAddress': req_body['clientAddress'],
            'ClientPhoneNumber': req_body['clientPhoneNumber'],
            'ClientEmail': req_body['clientEmail'],
            'ClientTradeLicenseNumber': client_trade_license, # Store optional field
            # --- Opponent Details ---
            'OpponentFullName': req_body['opponentFullName'],
            'OpponentAddress': req_body['opponentAddress'],
            'OpponentIdNumber': opponent_id_number, # Store optional field
            'OpponentTradeLicenseNumber': opponent_trade_license, # Store optional field
            # Additional tracking fields (Keep existing names unless specified otherwise)
            'DocumentsUploaded': False,
            'OpponentMemorandum': False,
            'MemorandumEnglish': "",
            'MemorandumArabic': "",
            "AdditionalOpponents": req_body['additionalOpponents']
        }

        # Store in ailalawyercases table
        lawyer_cases_table.create_entity(entity=case_entity)
        
        # Log success
        logging.info(f"[API INFO][create_case_reference] Created case reference: {case_number}")
        
        # Return case reference details
        return Response(
            json.dumps({
                "case_number": case_number
            }),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][create_case_reference] Error creating case reference: {str(e)}")
        return Response(
            json.dumps({"message": f"Failed to create case reference: {str(e)}"}),
            status_code=500,
            media_type="application/json"
        )


