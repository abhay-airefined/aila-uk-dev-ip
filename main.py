from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import os
from dotenv import load_dotenv
from api.auth import router as auth_router
from api.caseEvidence import router as case_evidence_router
from api.caseHistory import router as case_history_router
from api.chat import router as chat_router
from api.createCaseMember import router as create_case_member_router
from api.export  import router as export_router
from api.healthCheck import router as healthCheck_router
from api.ingest import router as ingest_router
from api.memorandum import router as memorandum_router
from api.retrieve import router as retrieve_router
from api.searchCases import router as search_case_router
from api.cases import router as cases_router

load_dotenv()

app = FastAPI(title="RAG API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=False,  # Must be False when allow_origins is ["*"]
    allow_methods=["POST", "GET", "OPTIONS", "DELETE", "PATCH", "PUT"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Add middleware to check CORS headers
# @app.middleware("http")
# async def add_cors_headers(request: Request, call_next):
#     response = await call_next(request)
    
#     # Ensure CORS headers are present
#     response.headers["Access-Control-Allow-Origin"] = "*"
#     response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS, DELETE, PATCH, PUT"
#     response.headers["Access-Control-Allow-Headers"] = "*"
    
#     # Log headers for debugging
#     print("Response Headers:", dict(response.headers))
    
    # return response

prefix = "/rag-api"

# Include all routers with the /rag-api prefix
app.include_router(ingest_router, prefix=prefix)
app.include_router(healthCheck_router, prefix=prefix)
app.include_router(chat_router, prefix=prefix)
app.include_router(retrieve_router, prefix=prefix)
app.include_router(create_case_member_router, prefix=prefix)
app.include_router(case_history_router, prefix=prefix)
app.include_router(auth_router, prefix=prefix)
app.include_router(memorandum_router, prefix=prefix)
app.include_router(search_case_router, prefix=prefix)
app.include_router(export_router, prefix=prefix)
app.include_router(case_evidence_router, prefix=prefix)
app.include_router(cases_router, prefix=prefix)
from api.aila_ip_3_export import router as aila_ip_3_export_router

app.include_router(aila_ip_3_export_router)
from api.aila_ip4_router import router as aila_ip4_router
app.include_router(aila_ip4_router, prefix=prefix)




