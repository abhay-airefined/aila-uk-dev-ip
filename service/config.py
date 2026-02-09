# import boto3
import weaviate
from weaviate.classes.init import Auth
import os

class Config:
    
    @staticmethod
    def buildWeaviateConnection()->weaviate:
        print("Connecting to weaviate")
        print(f"WEAVIATE_HOST: {os.getenv('WEAVIATE_HOST')}")
        print(f"WEAVIATE_GRPC_HOST: {os.getenv('WEAVIATE_GRPC_HOST')}")
        print(f"WEAVIATE_API_KEY: {os.getenv('WEAVIATE_API_KEY')}")
        print(f"WEAVIATE_PORT: {os.getenv('WEAVIATE_PORT')}")
        print(f"WEAVIATE_GRPC_PORT: {os.getenv('WEAVIATE_GR PC_PORT')}")
        client = weaviate.connect_to_custom(
            http_host=os.getenv("WEAVIATE_HOST"),  # Your Kubernetes service hostname/IP
            http_port=os.getenv("WEAVIATE_PORT"),          # Default REST port, adjust if needed
            http_secure=False,        # Set to True for HTTPS, False for HTTP
            grpc_host=os.getenv("WEAVIATE_GRPC_HOST"),  # Usually the same as http_host
            grpc_port=os.getenv("WEAVIATE_GRPC_PORT"),         # Default gRPC port, adjust if needed
            grpc_secure=False,        # Set to True for secure gRPC
            auth_credentials=Auth.api_key(
                os.getenv("WEAVIATE_API_KEY")
            ),
            headers={ "X-Azure-Api-Key": os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")}
        )
        return client   
