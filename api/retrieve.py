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
from service.damage_breakdown import build_damage_context, run_damage_breakdown
from service.file_utils import extract_text_from_bytes
from service.format_utils import format_timestamp, get_next_case_number

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
table_service = TableServiceClient.from_connection_string(connection_string)
aila_log_table = table_service.get_table_client("ailalogs")
case_status_table = table_service.get_table_client("ailacasestatus")

@router.post('/start_analysis')
async def start_analysis(
    req: Request, 
    defendantDocs: List[UploadFile] = File(...), 
    plaintiffDocs: List[UploadFile] = File(None)
) -> Response:
    """Start the case analysis process and return the result when complete"""
    try:
        form_data = await req.form()
        case_id = form_data.get('case_id')
        if not case_id:
            return Response(content="Case ID is required", status_code=400)
        
        # Get all files from the request
        defendant_files = defendantDocs

        if not defendant_files:
            return Response(
                content="Defendant documents are required",
                status_code=400
            )
        
        # Get case entity
        case_entity = case_status_table.get_entity('cases', case_id)
        if not case_entity:
            return Response(content="Case not found", status_code=404)
        
        # if DEV_MODE:
        #     logging.info("[API INFO][start_analysis] Running in dev mode - returning mock data")
        #     result = mock_case_response(case_id, case_status_table)
        #     result['case_id'] = case_id
        #     formatted_time = format_timestamp(case_entity['StartTime'])
        #     result['formatted_timestamp'] = formatted_time
        #     return Response(
        #         content=json.dumps(result),
        #         status_code=200,
        #         media_type="application/json"
        #     )
        
        # Extract text from all documents and concatenate
        try:
            defendant_text = ""
                        
            # Process defendant documents
            for doc in defendant_files:
                text = extract_text_from_bytes(
                    await doc.read(),
                    doc.content_type
                )
                defendant_text += "\n\n" + text
                
            is_lawyer_case = form_data.get('type') == "lawyer"
            plaintiff_text = ""

            if(is_lawyer_case):
                plaintiff_text = ""
                plaintiff_files = plaintiffDocs
                
                if not plaintiff_files:
                        return Response(
                            content="Plaintiff documents are required",
                            status_code=400
                        )
                
                # Process plaintiff documents
                for doc in plaintiff_files:
                    text = extract_text_from_bytes(
                        await doc.read(),
                        doc.content_type
                    )
                    plaintiff_text += "\n\n" + text

            case_entity['DamageContext'] = build_damage_context(
                defendant_text.strip(),
                plaintiff_text.strip() if plaintiff_text else None
            )
                
            # Update status
            case_entity['Status'] = 'processing'
            case_entity['CurrentStep'] = 'Analysing case documents'
            case_status_table.update_entity(case_entity)
            
            if(is_lawyer_case):
            # Run analysis and wait for result
                result = run_lawyer_rag(
                    plaintiff_text.strip(),
                    defendant_text.strip(),
                    case_id,
                    case_status_table
                )
            else:    
                # Run analysis and wait for result
                result = run_rag(
                    defendant_text.strip(),
                    case_id,
                    case_status_table
                )
            
            # Add case ID and timestamp to result
            result['case_id'] = case_id
            formatted_time = format_timestamp(case_entity['StartTime'])
            logging.info(f"[API INFO][start_analysis] Case {case_id} StartTime: {case_entity['StartTime']}")
            logging.info(f"[API INFO][start_analysis] Formatted timestamp: {formatted_time}")
            result['formatted_timestamp'] = formatted_time
            
            logging.info(f"[API INFO][start_analysis] Final result object for case {case_id}: {json.dumps(result)}")
            
            logging.info(f"[API INFO][start_analysis] Completed analysis for case ID: {case_id}")
            
            # Return the final result
            return Response(
                content=json.dumps(result),
                status_code=200,
                media_type="application/json"
            )
            
        except ValueError as e:
            logging.error(f"[API ERROR][start_analysis] Validation error: {str(e)}")
            return Response(content=str(e), status_code=400)
            
    except Exception as e:
        logging.error(f"[API ERROR][start_analysis] Error starting analysis: {str(e)}")
        return Response(content=str(e), status_code=500)

@router.post('/damage_breakdown')
async def damage_breakdown(req: Request) -> Response:
    """Create a damages-focused breakdown after case analysis is complete."""
    try:
        content_type = req.headers.get("content-type", "")
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            payload = dict(await req.form())
        else:
            try:
                payload = await req.json()
            except Exception:
                payload = {}

        case_id = payload.get('case_id')
        if not case_id:
            return Response(content="Case ID is required", status_code=400)

        case_entity = case_status_table.get_entity('cases', case_id)
        if not case_entity:
            return Response(content="Case not found", status_code=404)

        if case_entity.get('Status') != 'completed':
            return Response(
                content=json.dumps({
                    "message": "Case analysis must be completed before generating a damage breakdown",
                    "status": case_entity.get('Status'),
                    "currentStep": case_entity.get('CurrentStep')
                }),
                status_code=409,
                media_type="application/json"
            )

        analysis = payload.get('analysis')
        if isinstance(analysis, str) and analysis.strip():
            analysis = json.loads(analysis)

        if not analysis:
            stored_result = case_entity.get('Result')
            analysis = json.loads(stored_result) if stored_result else None

        if not analysis:
            return Response(
                content="Completed case analysis was not found",
                status_code=400
            )

        damage_context = (
            payload.get('damage_context')
            or payload.get('case_text')
            or case_entity.get('DamageContext')
            or ""
        )

        case_entity['CurrentStep'] = 'Preparing damage breakdown'
        case_status_table.update_entity(case_entity)

        result = run_damage_breakdown(
            analysis=analysis,
            damage_context=damage_context,
            case_id=case_id
        )
        result['case_id'] = case_id
        result['case_number'] = case_entity.get('CaseNumber')
        result['generated_at'] = datetime.datetime.utcnow().isoformat() + "Z"

        if case_entity.get('StartTime'):
            result['formatted_timestamp'] = format_timestamp(case_entity['StartTime'])

        case_entity['DamageBreakdown'] = json.dumps(result)
        case_entity['CurrentStep'] = 'Complete'
        case_status_table.update_entity(case_entity)

        logging.info(f"[API INFO][damage_breakdown] Completed damage breakdown for case ID: {case_id}")

        return Response(
            content=json.dumps(result),
            status_code=200,
            media_type="application/json"
        )

    except ValueError as e:
        logging.error(f"[API ERROR][damage_breakdown] Validation error: {str(e)}")
        return Response(content=str(e), status_code=400)
    except Exception as e:
        logging.error(f"[API ERROR][damage_breakdown] Error generating damage breakdown: {str(e)}")
        return Response(content=str(e), status_code=500)
