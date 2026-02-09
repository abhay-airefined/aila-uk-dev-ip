from fastapi import APIRouter, HTTPException, Query
import os
from service.azureBlobService import AzureBlobService
from service.weaviateService import WeaviateService
from service.rag_utils import find_relevant_chunks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


router = APIRouter()
blobservice = AzureBlobService()
weaviateService = WeaviateService()

@router.get('/paginateMongoCases')
async def paginate_cases(
    casetype: str = Query(..., description="Type of case: 'appeal' or 'decision'"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100)
):
    if casetype == "appeal":
        collection = os.getenv("container_name_appeal")
    elif casetype == "decision":
        collection = os.getenv("container_name_decision")
    else:
        raise HTTPException(status_code=400, detail="Invalid case type")

    try:
        data, total = await blobservice.paginate_mongo_cases(collection, page, page_size)
        total_pages = (total + page_size - 1) // page_size
        return {
            "status": "success",
             "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages
            },
            "data": data           
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
    
class SearchRequest(BaseModel):
    query: str

@router.get('/paginateWeaviateCases')
def paginate_weaviate_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100)):
    paginated_response = blobservice.paginate_weaviate_cases(page,page_size)
    return paginated_response


# Pydantic model for request body
class SearchPaginationRequest(BaseModel):
    query: str = Field(..., description="Search query (can be very long)", min_length=1, max_length=10000)
    page: int = Field(1, description="Page number", ge=1)
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    # limit: int = Field(description="Number of top matched results")

class SearchPaginationResponse(BaseModel):
    query: str
    page: int
    page_size: int
    total_records: int
    # total_pages: int
    # has_next: bool
    # has_previous: bool
    results: List[Dict[str, Any]]

@router.post('/caseSearch', response_model=SearchPaginationResponse)
def search_relevant_docs(request: SearchPaginationRequest):
    try:
        paginated_response = weaviateService.search_relevant_docs(
            query=request.query, 
            page=request.page, 
            page_size=request.page_size
        )
        return paginated_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# @router.post('/search-weaviate-paginated', response_model=SearchPaginationResponse)
# def search_weaviate_paginated_post(request: SearchPaginationRequest):
#     """
#     Search Weaviate with pagination - POST method for long queries
#     Handles queries up to 10,000 characters
#     """
#     try:
#         paginated_response = blobservice.search_weaviate_paginated(
#             query=request.query, 
#             page=request.page, 
#             page_size=request.page_size
#         )
#         return paginated_response
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
