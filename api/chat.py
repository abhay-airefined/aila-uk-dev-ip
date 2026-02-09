import os
import sys
import logging
from typing import List
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json

# from com.sequation.document.service.azureTableService import AzureTableService
from service.chatService import ChatService
from models.chatModels import ChatRequest, ChatResponse
from dotenv import load_dotenv
from config.tokenUtils import get_auth, AuthContext
import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()

# Global singleton instances to prevent multiple initializations
_chat_service_instance = None

def get_chat_service(lat: str = None, long: str = None) -> ChatService:
    """Get singleton instance of ChatService"""
    global _chat_service_instance
    if _chat_service_instance is None:
        try:
            logger.info("Creating new ChatService instance")
            _chat_service_instance = ChatService()
        except Exception as e:
            logger.error(f"Failed to create ChatService instance: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Service initialization failed: {str(e)}")
    return _chat_service_instance

def cleanup_services():
    """Cleanup function to properly close all service connections"""
    global _chat_service_instance
    logger.info("Cleaning up all service instances")
    
    try:
        if _chat_service_instance:
            logger.info("Cleaning up ChatService instance")
            _chat_service_instance.cleanup()
            _chat_service_instance = None
            logger.info("ChatService instance cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up ChatService: {str(e)}")
    
    logger.info("All service instances cleaned up")

# Register cleanup function for application shutdown
import atexit
atexit.register(cleanup_services)

@router.post('/chat/stream')
async def stream_chat(request: ChatRequest):
    """
    Stream chat response with document context and session-aware memory.
    Args:
        request: ChatRequest containing message, history, and parameters
        
    Returns:
        StreamingResponse with chat chunks including progress indicators
    """
    request_id = str(uuid.uuid4())
    logger.info(f"[{request_id}] Starting stream chat request")
    logger.info(f"[{request_id}] User message: {request.message[:100]}...")
    logger.info(f"[{request_id}] Session ID: {request.session_id}")
    
    try:
        tenant_name = "11"
        orgId = str(1)
        user_id = str(111)
        
        logger.info(f"[{request_id}] Auth context - tenant: {tenant_name}, org: {orgId}, user: {user_id}")
        lattitude = request.lat if request.lat else "24.5021"
        longitude = request.long if request.long else "54.3941"
                
        # Get singleton service instances
        logger.info(f"[{request_id}] Getting ChatService instance")
        chat_service = get_chat_service(lat=lattitude, long=longitude)
        
        def generate():
            """Generator function for streaming response with progress indicators."""
            try:
                logger.info(f"[{request_id}] Starting response generation")
                
                # Generate or use existing session ID
                if not request.session_id:
                    unique_session_id = user_id + "_" + str(uuid.uuid4())
                    logger.info(f"[{request_id}] Generated new session ID: {unique_session_id}")
                else:
                    unique_session_id = request.session_id
                    logger.info(f"[{request_id}] Using existing session ID: {unique_session_id}")

                #SET device location
                
                # Send session start indicator
                session_start = f"data: {json.dumps({'type': 'session_start', 'session_id': unique_session_id})}\n\n"
                logger.info(f"[{request_id}] Sending session start indicator")
                yield session_start
                
                # Prepare metadata with session information
                metadata = {
                    "session_id": unique_session_id,
                    "user_id": user_id,
                    "tenant_name": tenant_name,
                    "org_id": str(orgId),
                    "timestamp": str(datetime.datetime.now()),
                    "lattitude": lattitude,
                    "longitude": longitude
                }
                logger.info(f"[{request_id}] Prepared metadata: {metadata}")
                
                # Stream the chat response
                chunk_count = 0
                logger.info(f"[{request_id}] Starting enhanced chat completion")
                for chunk in chat_service.enhanced_chat_completion(
                    message=request.message,
                    top_k=15,
                    tenant_name=tenant_name,
                    user_id=user_id,
                    metadata=metadata
                ):
                    # Handle different chunk types
                    if isinstance(chunk, dict):
                        chunk_type = chunk.get("type")
                        if chunk_type == "sources":
                            # Send sources chunk
                            sources_chunk = f"data: {json.dumps(chunk)}\n\n"
                            logger.info(f"[{request_id}] Sending sources chunk with {len(chunk.get('sources', []))} sources")
                            yield sources_chunk
                        elif chunk_type == "progress":
                            # Send progress chunk
                            progress_chunk = f"data: {json.dumps(chunk)}\n\n"
                            logger.info(f"[{request_id}] Sending progress chunk: {chunk.get('message', '')}")
                            yield progress_chunk
                        elif chunk_type == "text":
                            # Send text chunk
                            chunk_count += 1
                            text_chunk = f"data: {json.dumps({'type': 'text', 'content': chunk['content']})}\n\n"
                            if chunk_count % 10 == 0:  # Log every 10th chunk to avoid spam
                                logger.info(f"[{request_id}] Sent {chunk_count} text chunks so far")
                            yield text_chunk
                    else:
                        chunk_count += 1
                        text_chunk = f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
                        if chunk_count % 10 == 0:  # Log every 10th chunk to avoid spam
                            logger.info(f"[{request_id}] Sent {chunk_count} text chunks so far")
                        yield text_chunk
                
                logger.info(f"[{request_id}] Completed streaming. Total chunks: {chunk_count}")
                
                # Send completion signal with session summary
                done_chunk = f"data: {json.dumps({'type': 'done', 'session_id': unique_session_id, 'message': 'Response completed successfully'})}\n\n"
                logger.info(f"[{request_id}] Sending completion signal")
                yield done_chunk
                   
            except Exception as e:
                logger.error(f"[{request_id}] Error in generate function: {str(e)}", exc_info=True)
                error_chunk = f"data: {json.dumps({'type': 'error', 'error': str(e), 'session_id': unique_session_id if 'unique_session_id' in locals() else None})}\n\n"
                yield error_chunk
        
        # Use proper headers for streaming
        headers = {
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Content-Type': 'text/event-stream',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Cache-Control',
        }
        
        logger.info(f"[{request_id}] Returning StreamingResponse")
        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)
        
    except Exception as e:
        logger.error(f"[{request_id}] Error in stream_chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
