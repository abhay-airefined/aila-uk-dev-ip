from pypdf import PdfReader
import docx
import os
from io import BytesIO

def extract_text_from_bytes(file_bytes: bytes, content_type: str) -> str:
    """
    Extract text content from uploaded file bytes.
    """
    try:
        if content_type == 'application/pdf':
            pdf_file = BytesIO(file_bytes)
            reader = PdfReader(pdf_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
                
        elif content_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']:
            docx_file = BytesIO(file_bytes)
            doc = docx.Document(docx_file)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            
        elif content_type == 'text/plain':
            text = file_bytes.decode('utf-8')
        else:
            raise ValueError(f"Unsupported content type: {content_type}")

        if not text.strip():
            raise ValueError("Could not extract text from the document")
        
        return text.strip()

    except Exception as e:
        raise ValueError(f"Error processing document: {str(e)}")