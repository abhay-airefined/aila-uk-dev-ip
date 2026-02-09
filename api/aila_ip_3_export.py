# import json
# import datetime
# import logging
# from io import BytesIO

# from fastapi import APIRouter, Request, Response
# from dotenv import load_dotenv
# import docx

# from api import aila_ip_3

# # Logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# router = APIRouter()
# load_dotenv()


# @router.get("/aila_ip_3/export")
# def export_aila_ip_3_search(req: Request) -> Response:
#     try:
#         title = req.query_params.get("title") or req.query_params.get("query")
#         if not title:
#             return Response(
#                 "title or query parameter is required",
#                 status_code=400,
#             )

#         # Run IP pipeline
#         result = aila_ip_3.run_pipeline(title)

#         # Create Word document
#         doc = docx.Document()

#         # Title
#         doc.add_heading("AILA IP Search Report", 0)

#         # Metadata
#         generated_at = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")
#         doc.add_paragraph(f"Search Query: {title}")
#         doc.add_paragraph(f"Generated on {generated_at}")

#         doc.add_heading("Results", level=1)

#         def render(obj, level=2):
#             """Recursively render JSON into docx"""
#             if isinstance(obj, dict):
#                 for k, v in obj.items():
#                     doc.add_heading(str(k), level=level)
#                     render(v, level + 1)
#             elif isinstance(obj, list):
#                 for i, item in enumerate(obj, 1):
#                     doc.add_paragraph(f"{i}.", style="List Number")
#                     render(item, level + 1)
#             else:
#                 doc.add_paragraph(str(obj))

#         render(result)

#         # Save to memory
#         buffer = BytesIO()
#         doc.save(buffer)
#         buffer.seek(0)

#         return Response(
#             content=buffer.getvalue(),
#             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#             headers={
#                 "Content-Disposition": "attachment; filename=aila_ip_search.docx"
#             },
#         )

#     except Exception as e:
#         logger.exception("[API ERROR][export_aila_ip_3_search]")
#         return Response(
#             "Error generating IP search document",
#             status_code=500,
#         )



import json
import logging
from fastapi import APIRouter, Request, Response
from dotenv import load_dotenv

from api import aila_ip_3

router = APIRouter()
load_dotenv()

logger = logging.getLogger(__name__)


@router.get("/aila_ip_3/search_v2")
def aila_ip_3_search_v2(req: Request) -> Response:
    try:
        title = req.query_params.get("title") or req.query_params.get("query")
        if not title:
            return Response(
                json.dumps({"error": "title or query parameter is required"}),
                status_code=400,
                media_type="application/json",
            )

        result = aila_ip_3.run_pipeline(title)

        # 🔑 IMPORTANT: return exactly what frontend expects
        return Response(
            json.dumps(result),
            status_code=200,
            media_type="application/json",
        )

    except Exception as e:
        logger.exception("[API ERROR][aila_ip_3_search_v2]")
        return Response(
            json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json",
        )
