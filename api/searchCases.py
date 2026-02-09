import logging
from fastapi import APIRouter, Request, Response
import json

from dotenv import load_dotenv
from service.rag_utils import find_relevant_chunks

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()


@router.get('/search_articles')
def search_articles(req: Request) -> Response:
    """Search for relevant articles based on a query string"""
    try:
        query = req.query_params.get('query', '')
        
        if not query:
            return Response(
                "Query parameter is required",
                status_code=400
            )
            
        # Use RAG utils to find relevant chunks
        matches = find_relevant_chunks(query, n_results=20)
        
        # Format the response
        articles = [{
            'id': 1,
            'score': 0,
            'article_text': match.get('rawText', ''),
            'legislation_title': match.get('caseName', ''),
            'article_number': match.get('jurisdictionCode', '')
        } for match in matches]
        
        return Response(
            json.dumps({'articles': articles}),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][search_articles] Error searching articles: {str(e)}")
        return Response(str(e), status_code=500)