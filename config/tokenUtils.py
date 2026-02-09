import jwt
from fastapi import HTTPException, Depends, Request
from functools import wraps
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError, InvalidSignatureError,DecodeError
from datetime import datetime
import OpenSSL.crypto
import json
from dotenv import load_dotenv
import os
import inspect
load_dotenv()

def decode_token_from_request(request: Request):
    try:
        token_with_bearer = request.headers.get('X-Authorization')  
        token = token_with_bearer.split(" ")[1]
    except:
        raise HTTPException(status_code=401, detail="Invalid token, Please Check your provided token")
        
    try:
        public_key_pem = os.getenv('PUBLIC_KEY_PEM_PATH')
        
        # Load the public key from the file
        with open(public_key_pem, 'rb') as pem_file:
            public_key_pem_content = pem_file.read()

        # Load the X.509 certificate
        certificate = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, public_key_pem_content)

        # Get the public key in PEM format
        public_key_pem = OpenSSL.crypto.dump_publickey(OpenSSL.crypto.FILETYPE_PEM, certificate.get_pubkey())

        # Decode and verify the JWT token using the public key
        payload = jwt.decode(token, public_key_pem, algorithms=['RS512'])

        # Convert 'exp' claim to a datetime object
        exp_timestamp = payload.get('exp')
        if exp_timestamp:
            exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
        else:
            exp_datetime = None

        '''# Check expiration
        if exp_datetime and exp_datetime < expected_exp:
            raise HTTPException(status_code=401, detail='Token expired')'''

        return payload
    
    except InvalidSignatureError:
        raise HTTPException(status_code=401, detail='Signature verification failed')
    except DecodeError:
        raise HTTPException(status_code=401, detail="No JWT token provided")
    except ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail='Token expired')
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail='Invalid Token')
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


def check_feature_and_operation_access(list_resource, required_fid, required_op_ids):
    """
    Check if user has access to a specific feature and operations
    
    Args:
        list_resource: List of resource objects from token payload
        required_fid: Feature ID required for the endpoint
        required_op_ids: List of operation IDs required (user needs at least one)
        
    Returns:
        bool: True if user has access, False otherwise
    """
    if not list_resource or not required_fid:
        return False
    
    # Convert single operation ID to list
    if isinstance(required_op_ids, int):
        required_op_ids = [required_op_ids]
    
    # Find the feature in user's resources
    for resource in list_resource:
        if resource.get('fid') == required_fid:
            user_op_ids = resource.get('opId', [])
            # Check if user has at least one required operation
            if any(op_id in user_op_ids for op_id in required_op_ids):
                return True
    
    return False


def check_role_access(role_id, required_role_ids):
    """
    Check if user has any of the required roles
    
    Args:
        role_id: Role ID from token payload
        required_role_ids: List of role IDs required for the endpoint
        
    Returns:
        bool: True if user has at least one required role, False otherwise
    """
    if not required_role_ids:
        return True  # No role restriction
    
    # Convert single role to list
    if isinstance(required_role_ids, int):
        required_role_ids = [required_role_ids]
    
    return role_id in required_role_ids


class AuthContext:
    """Class to hold authentication context"""
    def __init__(self, payload: dict):
        self.payload = payload
        self.user_id = payload.get('userId')
        self.user_name = payload.get('userName', '')
        self.user_type = payload.get('userType')
        self.role_id = payload.get('roleId')
        self.org_id = payload.get('loggedInAppId')
        self.client_id = payload.get('loggedInClientId')
        self.user_id = payload.get('userId')
        self.list_resource = payload.get('listResource', [])
        self.user_name = payload.get('userName')


def create_auth_dependency(required_fid=None, required_op_ids=None, required_role_ids=None):
    """
    Create a FastAPI dependency for authentication and authorization
    
    Args:
        required_fid: Feature ID required for access
        required_op_ids: List of operation IDs required (user needs at least one)
        required_role_ids: List of role IDs allowed
    """
    def auth_dependency(request: Request) -> AuthContext:
        # Decode and validate token
        payload = decode_token_from_request(request)
        
        # Extract user information from token payload
        list_resource = payload.get('listResource', [])
        role_id = payload.get('roleId')
        user_id = payload.get('userId')
        org_id = payload.get('loggedInAppId')
        client_id = payload.get('loggedInClientId')
        user_id = payload.get('userId')
        user_name = payload.get('userName')
        
        # Check feature and operation access if required
        if required_fid is not None and required_op_ids is not None:
            if not check_feature_and_operation_access(list_resource, required_fid, required_op_ids):
                # Get user's available features for debugging
                user_features = [{"fid": r.get('fid'), "opId": r.get('opId')} for r in list_resource]
                raise HTTPException(
                    status_code=403,
                    detail={
                        'error': f'Access denied. Feature ID {required_fid} with operation IDs {required_op_ids} is required.'
                    }
                )
        
        # Check role access if required
        if required_role_ids is not None:
            if not check_role_access(role_id, required_role_ids):
                raise HTTPException(
                    status_code=403,
                    detail={
                        'error': f'Access denied. Role ID must be one of: {required_role_ids}. Your role ID: {role_id}'
                    }
                )
        
        return AuthContext(payload)
    
    return auth_dependency


def require_feature_and_operation(required_fid=None, required_op_ids=None, required_role_ids=None):
    """
    Decorator for FastAPI endpoints that require feature and operation authorization
    
    Usage:
        @require_feature_and_operation(required_fid=6, required_op_ids=[1, 2])
        async def my_endpoint(request: MyRequest, auth: AuthContext = Depends()):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        
        # Create the auth dependency
        auth_dep = create_auth_dependency(required_fid, required_op_ids, required_role_ids)
        
        # Store the dependency in the wrapper function for FastAPI to use
        wrapper._auth_dependency = Depends(auth_dep)
        
        return wrapper
    
    return decorator


# Function to get auth dependency - to be used in function parameters
def get_auth(required_fid=None, required_op_ids=None, required_role_ids=None):
    """
    Get auth dependency for FastAPI function parameters
    
    Usage:
        async def my_endpoint(auth: AuthContext = get_auth(required_fid=6, required_op_ids=[1, 2])):
            ...
    """
    return Depends(create_auth_dependency(required_fid, required_op_ids, required_role_ids))


# Convenience functions for common auth patterns
def require_feature(required_fid, required_op_ids):
    """
    Create a FastAPI dependency for specific feature/operation access
    
    Args:
        required_fid: Feature ID required for access
        required_op_ids: Operation ID(s) required for access
    """
    return Depends(create_auth_dependency(required_fid=required_fid, required_op_ids=required_op_ids))


def require_role(required_role_ids):
    """
    Create a FastAPI dependency for role access
    
    Args:
        required_role_ids: Role ID(s) required for access
    """
    return Depends(create_auth_dependency(required_role_ids=required_role_ids))
