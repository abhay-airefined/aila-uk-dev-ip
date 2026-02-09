# import azure.functions as func
import logging
import jwt as pyjwt
import bcrypt
from datetime import datetime, timedelta
import json
import os
from azure.data.tables import TableServiceClient
import uuid
from fastapi import Request, Response
from fastapi import APIRouter
from dotenv import load_dotenv



# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()
connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING") # Debug print
table_service = TableServiceClient.from_connection_string(connection_string)
table_client = table_service.get_table_client("ailausers")
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "your-secret-key")
aila_log_table = table_service.get_table_client("ailalogs")
case_status_table = table_service.get_table_client("ailacasestatus")


@router.post('/login')
async def login(req: Request) -> Response:
    try:
        body =  await req.json()
        username = body.get('username')
        password = body.get('password')

        if not username or not password:
            return Response(
                "Username and password are required",
                status_code=400,
                media_type="application/json"
            )

        try:
            user = table_client.get_entity(
                partition_key="users",
                row_key=username
            )
            
            if not bcrypt.checkpw(
                password.encode('utf-8'), 
                user['PasswordHash'].encode('utf-8')
            ):
                return Response(
                    "Invalid credentials",
                    status_code=401,
                    media_type="application/json"
                )

            user['LastLogin'] = datetime.now().isoformat()
            table_client.update_entity(entity=user)

            token = pyjwt.encode({
                'username': username,
                'email': user['Email'],
                'firstName': user['FirstName'],
                'lastName': user['LastName'],
                'userRole': user['UserRole'],
                'firmName': user.get('FirmName', ''),
                'firmShortName': user.get('FirmShortName', ''),
                'exp': datetime.now() + timedelta(hours=24)
            }, SECRET_KEY, algorithm='HS256')

            return Response(
                json.dumps({
                    'token': token,
                    'user': {
                        'username': username,
                        'email': user['Email'],
                        'firstName': user['FirstName'],
                        'lastName': user['LastName'],
                        'userRole': user['UserRole'],
                        'firmName': user.get('FirmName', ''),
                        'firmShortName': user.get('FirmShortName', '')
                    }
                }),
                status_code=200,
                media_type="application/json"
            )

        except Exception as e:
            logging.error(f"[API ERROR][login] User retrieval error: {str(e)}")
            return Response(
                "Invalid credentials",
                status_code=401,
                media_type="application/json"
            )

    except Exception as e:
        logging.error(f"[API ERROR][login] Login error: {str(e)}")
        return Response(
            "Internal server error",
            status_code=500,
            media_type="application/json"
        )


@router.post('/case_login')
def case_login(req: Request) -> Response:
    """
    Handle login for case participants (plaintiffs and defendants)
    
    Expected request body:
    - caseNumber: The case number
    - email: Email address of the participant
    - password: Password (fixed as 'mega123')
    
    Returns:
    - JSON with token, role, case_id on success
    - Error message on failure
    """
    logging.info("[API INFO][case_login] Processing case participant login request")
    
    try:
        # Parse request body
        req_body = req.json()
        
        case_number = req_body.get('caseNumber')
        email = req_body.get('email')
        password = req_body.get('password')
        
        # Validate required fields
        if not case_number:
            return Response(
                json.dumps({"message": "Case number is required"}),
                status_code=400,
                media_type="application/json"
            )
        
        if not email:
            return Response(
                json.dumps({"message": "Email is required"}),
                status_code=400,
                media_type="application/json"
            )
        
        if not password:
            return Response(
                json.dumps({"message": "Password is required"}),
                status_code=400,
                media_type="application/json"
            )
        
        # Check password (fixed for demo)
        if password != "mega123":
            return Response(
                json.dumps({"message": "Invalid credentials"}),
                status_code=401,
                media_type="application/json"
            )
        
        # Find case by case number
        aila_cases_table = table_service.get_table_client("ailacases")
        
        # Query for case with the provided case number
        query_filter = f"PartitionKey eq 'cases' and CaseNumber eq '{case_number}'"
        cases = list(aila_cases_table.query_entities(query_filter))
        
        if not cases:
            return Response(
                json.dumps({"message": "Case not found"}),
                status_code=404,
                media_type="application/json"
            )
        
        case = cases[0]
        
        # Check if email matches plaintiff or defendant
        role = None
        if email == case['PlaintiffEmail']:
            role = 'plaintiff'
        elif email == case['DefendantEmail']:
            role = 'defendant'
        else:
            return Response(
                json.dumps({"message": "Email does not match case records"}),
                status_code=401,
                media_type="application/json"
            )
        
        # Record in participants table
        participants_table = table_service.get_table_client("ailacaseparticipants")
        
        # Check if participant entry already exists
        participant_key = f"{case['RowKey']}_{email}"
        try:
            participant = participants_table.get_entity('cases', participant_key)
            # Update last login time
            participant['LastLogin'] = datetime.datetime.now().isoformat()
            participants_table.update_entity(entity=participant)
        except:
            # Create new participant entry
            participant_entity = {
                'PartitionKey': 'cases',
                'RowKey': participant_key,
                'CaseId': case['RowKey'],
                'Email': email,
                'Role': role,
                'LastLogin': datetime.now().isoformat()
            }
            participants_table.create_entity(entity=participant_entity)
        
        # Generate JWT token
        token = pyjwt.encode({
            'email': email,
            'role': role,
            'caseId': case['RowKey'],
            'caseNumber': case_number,
            'userRole': 'case-participant',
            'exp': datetime.now() + timedelta(hours=24)
        }, SECRET_KEY, algorithm='HS256')
        
        return Response(
            json.dumps({
                "token": token,
                "role": role,
                "case_id": case['RowKey'],
                "case_number": case_number
            }),
            status_code=200,
            media_type="application/json"
        )
        
    except Exception as e:
        logging.error(f"[API ERROR][case_login] Error during case login: {str(e)}")
        return Response(
            json.dumps({"message": f"Login failed: {str(e)}"}),
            status_code=500,
            media_type="application/json"
        )
    
from fastapi import Header

@router.post('/change_password')
async def change_password(req: Request, authorization: str = Header(None)):
    try:
        if not authorization:
            return Response(json.dumps({"message": "Auth token required"}),
                            status_code=401, media_type="application/json")

        token = authorization.replace("Bearer ", "")
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        username = payload.get('username')

        body = await req.json()
        old_password = body.get('oldPassword')
        new_password = body.get('newPassword')

        if not old_password or not new_password:
            return Response(json.dumps({"message": "Old and new password required"}),
                            status_code=400, media_type="application/json")

        user = table_client.get_entity("users", username)

        if not bcrypt.checkpw(old_password.encode('utf-8'), user["PasswordHash"].encode('utf-8')):
            return Response(json.dumps({"message": "Old password incorrect"}),
                            status_code=401, media_type="application/json")

        user["PasswordHash"] = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        table_client.update_entity(user)

        return Response(json.dumps({"message": "Password changed successfully"}),
                        status_code=200, media_type="application/json")

    except Exception as e:
        logging.error(f"[API ERROR][change_password] {str(e)}")
        return Response(json.dumps({"message": "Failed to change password"}),
                        status_code=500, media_type="application/json")



@router.post('/change_username')
async def change_username(req: Request, authorization: str = Header(None)):
    try:
        if not authorization:
            return Response(json.dumps({"message": "Auth token required"}),
                            status_code=401, media_type="application/json")

        token = authorization.replace("Bearer ", "")
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        old_username = payload.get('username')

        body = await req.json()
        new_username = body.get('newUsername')

        if not new_username:
            return Response(json.dumps({"message": "newUsername required"}),
                            status_code=400, media_type="application/json")

        user = table_client.get_entity("users", old_username)

        # Copy entity
        new_user = user.copy()
        new_user["RowKey"] = new_username

        table_client.create_entity(new_user)
        table_client.delete_entity("users", old_username)

        return Response(
            json.dumps({
                "message": "Username changed successfully. Please login again.",
                "newUsername": new_username
            }),
            status_code=200,
            media_type="application/json",
        )

    except Exception as e:
        logging.error(f"[API ERROR][change_username] {str(e)}")
        return Response(
            json.dumps({"message": "Failed to change username"}),
            status_code=500,
            media_type="application/json"
        )
