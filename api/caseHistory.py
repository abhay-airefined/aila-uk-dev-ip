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

@router.get('/get_cases')
def get_cases(req: Request) -> Response:
    """
    Retrieve a list of cases for a specific law firm from the ailalawyercases table.
    
    Parameters:
    - firmShortName: The short name of the law firm to filter cases
    
    Returns:
    - JSON array of case objects
    """
    logging.info("[API INFO][get_cases] Processing lawyer case list request")
    
    try:
        # Get firm short name from query parameters
        firm_short_name = req.query_params.get('firmShortName')
        logging.info(f"[API INFO][get_cases] Received firmShortName: {firm_short_name}")
        
        if not firm_short_name:
            return Response(
                json.dumps({
                    "message": "firmShortName is required",
                    "received_params": dict(req.query_params)
                }),
                status_code=400,
                media_type="application/json"
            )

        # Get lawyer cases table
        cases_table = table_service.get_table_client("ailalawyercases")
        
        # Query cases for the specific law firm
        query_filter = f"PartitionKey eq '{firm_short_name}'"
        entities = cases_table.query_entities(query_filter)
        
        # Convert to list and format for frontend
        case_list = []
        for entity in entities:
            case_list.append({
                "caseNumber": entity["RowKey"],
                "caseType": entity.get("NatureOfClaim", "Unknown"),
                "clientRole": entity.get("RepresentingParty", "Unknown"),
                "clientName": entity.get("ClientFullName", "Unknown"),
                "status": entity["Status"],
                "documentsUploaded": entity.get("DocumentsUploaded", False),
                "memorandumGenerated": bool(entity.get("MemorandumEnglish")) or bool(entity.get("MemorandumArabic")),
                "createdAt": entity["CreatedAt"]
            })
        
        # Sort by creation date, most recent first
        case_list.sort(key=lambda x: x["createdAt"], reverse=True)
        
        return Response(
            json.dumps({"cases": case_list}),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][get_cases] Error retrieving lawyer cases: {str(e)}")
        return Response(
            json.dumps({"message": f"Failed to retrieve lawyer cases: {str(e)}"}),
            status_code=500,
            media_type="application/json"
        )
        
@router.get('/get_case_details')
def get_case_details(req: Request) -> Response:
    """
    Retrieve detailed information for a specific case.
    
    Parameters:
    - firmShortName: The short name of the law firm
    - caseNumber: The unique case number to retrieve
    
    Returns:
    - JSON object with case details
    """
    logging.info("[API INFO][get_case_details] Processing case details request")
    
    try:
        # Get query parameters
        firm_short_name = req.query_params.get('firmShortName')
        case_number = req.query_params.get('caseNumber')
        
        if not firm_short_name or not case_number:
            return Response(
                json.dumps({
                    "message": "Both firmShortName and caseNumber are required",
                    "received_params": dict(req.query_params)
                }),
                status_code=400,
                media_type="application/json"
            )

        # Get cases table
        cases_table = table_service.get_table_client("ailalawyercases")
        
        try:
            # Get specific case entity
            case_entity = cases_table.get_entity(firm_short_name, case_number)
            
            # Format case details for frontend
            case_details = {
                "caseNumber": case_entity["RowKey"],
                "status": case_entity["Status"],
                "lawyerUsername": case_entity["LawyerUsername"],
                "representingParty": case_entity["RepresentingParty"],
                "natureOfClaim": case_entity["NatureOfClaim"],
                "caseSummary": case_entity.get("CaseSummary", ""),
                "clientDetails": {
                    "fullName": case_entity["ClientFullName"],
                    "idNumber": case_entity["ClientIdNumber"],
                    "address": case_entity["ClientAddress"],
                    "phoneNumber": case_entity["ClientPhoneNumber"],
                    "email": case_entity["ClientEmail"],
                    "tradeLicenseNumber": case_entity.get("ClientTradeLicenseNumber", "")
                },
                "opponentDetails": {
                    "fullName": case_entity["OpponentFullName"],
                    "address": case_entity["OpponentAddress"],
                    "idNumber": case_entity.get("OpponentIdNumber", ""),
                    "tradeLicenseNumber": case_entity.get("OpponentTradeLicenseNumber", "")
                },
                "documentsUploaded": case_entity.get("DocumentsUploaded", False),
                "memorandumStatus": {
                    "english": bool(case_entity.get("MemorandumEnglish")),
                    "arabic": bool(case_entity.get("MemorandumArabic"))
                },
                "createdAt": case_entity["CreatedAt"],
                "opponentMemorandum": case_entity.get("OpponentMemorandum", False)
            }
            
            return Response(
                json.dumps({"case": case_details}),
                status_code=200,
                media_type="application/json"
            )
            
        except Exception as e:
            return Response(
                json.dumps({"message": f"Case not found: {str(e)}"}),
                status_code=404,
                media_type="application/json"
            )
        
    except Exception as e:
        logging.error(f"[API ERROR][get_case_details] Error retrieving case details: {str(e)}")
        return Response(
            json.dumps({"message": f"Failed to retrieve case details: {str(e)}"}),
            status_code=500,
            media_type="application/json"
        ) 