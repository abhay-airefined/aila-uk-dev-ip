import json
import logging
from fastapi import APIRouter, Query
from dotenv import load_dotenv

from api import aila_ip4

router = APIRouter()
load_dotenv()

logger = logging.getLogger(__name__)


@router.get("/aila_ip_4/search")
def aila_ip_4_search(
    title: str | None = Query(None),
    author: str | None = Query(None),
    isbn: str | None = Query(None),
):
    try:
        # require at least one
        if not any([title, author, isbn]):
            return {
                "error": "Provide at least one of title, author or isbn"
            }

        result = aila_ip4.run_pipeline(
            title=title,
            author=author,
            isbn=isbn,
        )

        return result

    except Exception as e:
        logger.exception("[API ERROR][aila_ip_4_search]")
        return {"error": str(e)}
