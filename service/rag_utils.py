from openai import AzureOpenAI
from typing import List
import os
import logging
from pydantic import BaseModel
from dotenv import load_dotenv
from service.config import Config

load_dotenv()


# Azure OpenAI Chat configuration
chat_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
chat_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
openai_api_key=os.getenv("OPENAI_API_KEY")
chat_model = os.getenv("DEPLOYMENT_NAME")

embedding_client = AzureOpenAI(
    api_key=openai_api_key,
    azure_endpoint=chat_endpoint,
    api_version=chat_api_version
)

llm_client = AzureOpenAI(
    api_key=openai_api_key,
    azure_endpoint=chat_endpoint,
    api_version=chat_api_version
)

client = Config.buildWeaviateConnection()
weaviate_collection_name = os.getenv("WEAVIATE_COLLECTION_NAME")

def embed_text(text: str) -> List[float]:
        """
        Generate embeddings for a text using Azure OpenAI.
        """
        try:
            response = embedding_client.embeddings.create(
                input=text,
                model="text-embedding-3-large"
            )
            return response.data[0].embedding
        except Exception as e:
            logging.error(f"[API ERROR][embed_text] Error generating embeddings: {str(e)}")
            raise
        
def find_relevant_chunks(query: str, n_results: int = 3) -> List[dict]:
    """
    Find relevant chunks for a query using similarity search.
    """
    # query_vector = embed_text(query)
    
    policy_collection = client.collections.get(weaviate_collection_name)
    tenant_collection = policy_collection.with_tenant("1")
    
    # logger.info(f"Performing hybrid search in '{self.policy_benefit_collection_name}' collection...")
                
    response = tenant_collection.query.hybrid(
        query=query,
        limit=n_results,
        alpha=0.7,
        query_properties=["rawText", "caseName", "jurisdictionCode"]
    )
    
    # logger.info(f"Search completed. Found {len(response.objects)} potential benefit results.")
    
    # Format results with the rich, structured data
    results = []
    for obj in response.objects:
        properties = obj.properties
        result = {
            "rawText": properties.get("rawText"),
            "caseName": properties.get("caseName"),
            "jurisdictionCode": properties.get("jurisdictionCode")
        }
        results.append(result)

    # logger.info(f"Policy benefit search completed successfully. Returning {len(results)} structured results.")
    return results

    # def fetch_article_text(self, article_id: str) -> dict:
    #     """
    #     Fetch an article from the Pinecone vector store.
    #     """
    #     pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
    #     index = pc.Index("aila-articles")
        
    #     article_result = index.query(
    #         namespace="aida-policy",
    #         id=article_id,
    #         top_k=1,
    #         include_values=False,
    #         include_metadata=True
    #     )
        
    #     if not article_result.matches:
    #         raise ValueError(f"Article with ID {article_id} not found in Pinecone")
            
    #     return article_result.matches[0]["metadata"]["article_text"]


def get_llm_response(system_prompt: str, human_prompt: str, response_format: BaseModel) -> BaseModel:
    llm_response = llm_client.beta.chat.completions.parse(
        model=chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": human_prompt}
        ],
        temperature=0,
        response_format=response_format,
    )
    print(llm_response.choices[0].message.parsed)

    return llm_response.choices[0].message.parsed