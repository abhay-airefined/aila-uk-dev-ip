import os
import json
import logging
import shutil
import tempfile
import threading
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI
from dotenv import load_dotenv

from service.graphRAGService import GraphRAGService
from service.weaviateService import WeaviateService
from models.chatModels import Message
from mem0 import MemoryClient, Memory
# from service.langchain_memory_adapter import MemoryClient, Memory

import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

class ChatService:
    def __init__(self):
        logger.info("Initializing ChatService")
        
        # Add request locks to prevent concurrent processing
        self._request_locks = {}
        self._locks_lock = threading.Lock()
        
        # Azure OpenAI Chat configuration
        self.chat_api_key = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        self.chat_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.chat_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        self.chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        self.mem_api_key = os.getenv("MEM0_API_KEY")
        self.openai_api_base=os.getenv("OPENAI_API_BASE")
        self.openai_api_version=os.getenv("OPENAI_API_VERSION")
        self.deployment_name=os.getenv("DEPLOYMENT_NAME")
        self.openai_api_key=os.getenv("OPENAI_API_KEY")
        self.rewrite_deployment_name=os.getenv("REWRITE_DEPLOYMENT_NAME")
        
 
        
        logger.info(f"ChatService config - deployment: {self.deployment_name}, api_base: {self.openai_api_base}")
        
        # Initialize services
        logger.info("Initializing WeaviateService")
        self.weaviate_service = WeaviateService()
        
        self.graphRAGService = GraphRAGService(testing=True)

        logger.info("Initializing Azure OpenAI client")
        self.chat_client = AzureOpenAI(
            api_key=self.openai_api_key,
            azure_endpoint=self.openai_api_base,
            api_version=self.openai_api_version
        )
        
        # Initialize MemoryClient (this is safe and doesn't create lock files)
        logger.info("Initializing MemoryClient")
        self.memClient = MemoryClient(api_key=self.mem_api_key, org_id="org_Om85bktrlf7dY7QvEjmLMNVNolB4SSA6Sm5Ti9Nq", project_id="proj_lu96pH2wqgk5ejKGtF9AfwpWjBHowfcIgp5C3m8m")

        # Initialize Memory config with error handling to avoid lock file conflicts
        self.memoryConfig = None
        try:
            logger.info("Initializing Memory config")
            
            # Clean up any existing Qdrant lock files
            self._cleanup_qdrant_locks()
            
            self.memory_config = {
                "llm": {
                    "provider": "azure_openai",
                    "config": {
                        "model": self.deployment_name,
                        "temperature": 0.1,
                        "max_tokens": 2000,
                        "azure_kwargs": {
                            "azure_deployment": self.deployment_name,
                            "api_version": self.openai_api_version,
                            "azure_endpoint": self.openai_api_base,
                            "api_key": self.openai_api_key,
                        }
                    }
                }
            }
            
            # Try to initialize Memory, but don't fail if it has lock issues
            self.memoryConfig = Memory.from_config(self.memory_config)
            logger.info("Memory config initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Memory config (this is okay for consecutive requests): {str(e)}")
            logger.info("Continuing without local Memory config - will use MemoryClient only")
            self.memoryConfig = None
        
        logger.info("ChatService initialization completed")

    def _get_request_lock(self, user_id: str, session_id: str = None) -> threading.Lock:
        """Get or create a lock for a specific user/session combination"""
        lock_key = f"{user_id}_{session_id}" if session_id else user_id
        
        with self._locks_lock:
            if lock_key not in self._request_locks:
                logger.info(f"Creating new request lock for: {lock_key}")
                self._request_locks[lock_key] = threading.Lock()
            return self._request_locks[lock_key]

    def _cleanup_old_locks(self):
        """Clean up old locks to prevent memory leaks"""
        with self._locks_lock:
            # Keep only the most recent locks (simple cleanup)
            if len(self._request_locks) > 100:  # Arbitrary limit
                logger.info("Cleaning up old request locks")
                # For simplicity, just clear all locks
                self._request_locks.clear()

    def _cleanup_qdrant_locks(self):
        """Clean up Qdrant lock files that might be causing conflicts"""
        try:
            # Common paths where Qdrant might create lock files
            qdrant_paths = [
                "/tmp/qdrant",
                os.path.join(tempfile.gettempdir(), "qdrant"),
                os.path.join(os.getcwd(), "qdrant"),
                os.path.join(os.path.expanduser("~"), ".qdrant")
            ]
            
            for path in qdrant_paths:
                if os.path.exists(path):
                    logger.info(f"Found Qdrant path: {path}")
                    try:
                        # Try to remove lock files specifically
                        lock_file = os.path.join(path, ".lock")
                        if os.path.exists(lock_file):
                            logger.info(f"Removing Qdrant lock file: {lock_file}")
                            os.remove(lock_file)
                        
                        # Also try to clean up the entire directory if it's empty
                        if os.path.isdir(path) and not os.listdir(path):
                            logger.info(f"Removing empty Qdrant directory: {path}")
                            shutil.rmtree(path, ignore_errors=True)
                    except Exception as e:
                        logger.warning(f"Could not clean up Qdrant path {path}: {str(e)}")
        except Exception as e:
            logger.warning(f"Error during Qdrant cleanup: {str(e)}")

    def cleanup(self):
        """Cleanup method to properly close connections and clean up resources"""
        try:
            logger.info("Cleaning up ChatService resources")
            
            # Clean up request locks
            with self._locks_lock:
                logger.info(f"Cleaning up {len(self._request_locks)} request locks")
                self._request_locks.clear()
            
            # Clean up Weaviate connection
            if hasattr(self, 'weaviate_service') and self.weaviate_service:
                try:
                    self.weaviate_service.close()
                    logger.info("Weaviate service closed successfully")
                except Exception as e:
                    logger.warning(f"Error closing Weaviate service: {str(e)}")
                finally:
                    self.weaviate_service = None
            
            # Clean up Qdrant locks
            self._cleanup_qdrant_locks()
            
            logger.info("ChatService cleanup completed")
        except Exception as e:
            logger.error(f"Error during ChatService cleanup: {str(e)}")

    def __del__(self):
        """Destructor to ensure cleanup happens when object is garbage collected"""
        try:
            self.cleanup()
        except Exception as e:
            logger.warning(f"Error in ChatService destructor: {str(e)}")

    def search_documents(self, query: str, top_k: int, tenant_name: str) -> List[Dict[str, Any]]:
        """
        Search for relevant documents using the WeaviateService.
        
        Args:
            query: Search query
            top_k: Number of top results to return
            tenant_name: Name of the tenant
        Returns:
            List of relevant documents
        """
        logger.info(f"Searching documents - query: {query}, top_k: {top_k}, tenant: {tenant_name}")
        try:
            # Ensure Weaviate service is properly initialized
            if not hasattr(self, 'weaviate_service') or self.weaviate_service is None:
                logger.warning("Weaviate service not initialized, reinitializing")
                self.weaviate_service = WeaviateService()
            
            documents = self.weaviate_service.search_documents(query, top_k, tenant_name)
            logger.info(f"Document search completed. Found {len(documents)} documents")
            return documents
        except Exception as e:
            logger.error(f"Error in search_documents: {str(e)}", exc_info=True)
            # Try to reinitialize Weaviate service on error
            try:
                logger.info("Attempting to reinitialize Weaviate service after error")
                if hasattr(self, 'weaviate_service') and self.weaviate_service:
                    self.weaviate_service.close()
                self.weaviate_service = WeaviateService()
                # Retry the search
                documents = self.weaviate_service.search_documents(query, top_k, tenant_name)
                logger.info(f"Document search retry completed. Found {len(documents)} documents")
                return documents
            except Exception as retry_error:
                logger.error(f"Error in search_documents retry: {str(retry_error)}", exc_info=True)
                raise

    def build_context_from_documents(self, documents: List[Dict[str, Any]]) -> str:
        """
        Builds a context string from retrieved documents, optimized for the
        new structured 'PolicyBenefit' format.
        
        Args:
            documents: List of document dictionaries from Weaviate.
            
        Returns:
            A formatted context string to be sent to the LLM.
        """
        logger.info(f"Building context from {len(documents)} structured documents")
        if not documents:
            logger.warning("No documents found for context building")
            return "No sources found. I can only help with questions that are related to the documents in the content library."
        
        fileNames = ["Policy wording 1.pdf", "Schedule of benefits.pdf", "General exclusions 1.pdf"]
        policy_wording_source_info = ""
        schedule_of_benefits_source_info = ""
        general_exclusions_source_info = ""
        for i, doc in enumerate(documents, 1):
            # Build comprehensive context from available fields
            context_text = doc.get("rawText", "")
            
            # Get filename for source attribution
            filename = doc.get("filename", "")
            
            #use enum to get the filename
            if filename == "Policy wording 1.pdf":
                policy_wording_source_info += (f"{context_text} \n\n")
            elif filename == "Schedule of benefits.pdf":
                schedule_of_benefits_source_info += (f"{context_text} \n\n")
            elif filename == "General exclusions 1.pdf":
                general_exclusions_source_info += (f"{context_text} \n\n")
            
        return policy_wording_source_info, schedule_of_benefits_source_info, general_exclusions_source_info

    def build_messages(self, message: str, policy_wording_source: str, schedule_of_benefits_source: str, general_exclusions_source: str, memory_context: str, graphrag_flag: bool, graphrag_response: str = None) -> List[Dict]:
        """
        Build the message array for OpenAI chat completion.
        
        Args:
            user_message: The user's current message
            context: Retrieved document context
            history: Previous conversation messages
        Returns:
            List of message dictionaries
        """
        logger.info(f"Start building messages")
        
        system_prompt = f"""You are an AI assistant designed to help users with their insurance policies. Your personality is polite, natural, and human-like. Your main goal is to answer questions based *only* on the provided documents: policy wordings, insurance plan details (including coverage and costs), and general exclusion documents.
 
            == Provided Documents Guide ==
            You are provided with key document types to help you answer user queries. It is crucial to synthesize information from all of them to provide accurate and comprehensive responses.
            - **Schedule of Benefits**: This document is the most important for benefit and coverage questions. It lists the specific benefits and the monetary coverage for each. It should be given the highest priority when forming an answer about coverage.
            - **Policy Wording**: This is a comprehensive document outlining the terms, conditions, and full details of the insurance policy. It is the legal contract between the insurer and the policyholder.
            - **General Exclusions**: This document specifies what is NOT covered. Always check this to ensure a requested benefit is not excluded.
            """
        if graphrag_flag and graphrag_response != "":
            system_prompt += """
            - **Insurance Network Details**: This response contains information about a network in health insurance which consists of group of doctors, hospitals, and clinics that work within your insurance plan.
            """
        system_prompt += f"""
            
            WHEN CREATING A RESPONSE, YOU MUST CONSIDER THE DETAILS FROM ALL SOURCES.
            
            == Terminology Understanding ==
            - When users ask about "details", they mean "benefits" or "services" - respond accordingly with benefit or service information.
            - When users ask about "co-pay", they mean "co-payment" - search for and provide co-payment information related to question
            - When answering coverage questions if no specific amount is present for a particular service or benefit, include the total plan amount if available in the documents
            
            == Core Behavior (Strict Rule) ==
            - You must base your answers strictly on the information from the user's documents and our **conversation history (memory)**.
            - Do NOT use any external or general knowledge. Never make things up.
            - If a question seems unrelated to our previous chat, treat it as a new question and find the answer in the documents.
            - If you can't find an answer in either the documents or our conversation history, clearly state "I’m afraid I do not have information on that specific topic. May I assist you with anything else related to your policy coverage or benefits?".
            - If the response contains amount/monetary value, it must be presented in AED
            - If the response contains distance, it should be in kilometers
            
            == Content Usage Rules (Strict Rule) ==
            - For follow-up questions, memory is your starting point. Always use it to understand the flow of the conversation before you look at the documents.
            - For all questions, the factual answer must come from the user's documents.
            - If a new question isn't related to our past conversation, rely only on the documents.
            - When both memory and documents are relevant, use the memory to create a smooth, natural follow-up, and use the documents for the facts. Use context to understand pronouns or implied references.
            - If neither helps, just say so: "I’m afraid I do not have information on that specific topic. May I assist you with anything else related to your policy coverage or benefits?"
            
            == Response Strategy (Strict Rule) ==
            1. **For follow-up questions:**
                - If the user's question is clearly related to something we've just discussed, your primary goal is to show you remember the context.
                - Pay close attention to pronouns like "he," "she," "it," "they," or "them," and connect them to the people or topics mentioned in previous questions.
                - Start by connecting back to the previous topic, then use the documents to provide any additional clarification or confirmation.
            
            2. **For new questions:**
                - Answer with a brief confirmation first (e.g., “Yes, it’s covered.”).
                Example: > “Yes, your policy covers accidental dental treatment.”
            
            3. **When information isn't available:**
                - Be honest and say you can't find the information.
                - Example: "I couldn't find any details about dental coverage in your documents.May I assist you with anything else related to your policy coverage or benefits?"
            
            == Answering Style (Strict Rule) ==
            - Be warm, professional, and human-like. Avoid sounding like a robot.
            - **Start with a short, direct answer first** (e.g., “Yes, this is covered.”).**
            - **Ask to offer more detail only if the situation is unclear, if the user asks, or if clarification is needed.**
            - Be helpful and human — avoid excessive detail unless it improves clarity.
            - Actively remember the key subjects of our conversation (like people, specific coverages, or situations). When the user asks a follow-up question using pronouns (like 'they' or 'it'), you must know who or what they are referring to based on our chat history.
            - You can use phrases like "Based on your policy documents..." or "Looking at the policy details...".
            - Do not cite specific source document names unless the user asks for them.
            - Answers should not contain any exclamations
            - Do not end with phrases like:
                “Let me know if you need more info”
                “Is there anything else I can help you with?”
                “Please feel free to ask”
                Instead, end with the answer. Full stop.
            
            == Provided Context ==
            Below is the information available for this session:
            === Context from Retrieved Documents ===
            -- Schedule of Benefits --
            {schedule_of_benefits_source}

            -- Policy Wording --
            {policy_wording_source}

            -- General Exclusions --
            {general_exclusions_source}
            """

        if graphrag_flag and graphrag_response != "":
                system_prompt += f"""
                === Context from Insurance Network Details ===
                {graphrag_response}
                """

        system_prompt += f"""
            === Context from Relevant Memory ===
            {memory_context}
            """

        messages = [{"role": "system", "content": system_prompt}]
            
        # Add current user message
        messages.append({"role": "user", "content": message})
        logger.info(f"Messages built successfully. Total messages: {len(messages)}")
        
        return messages

    def search_relevant_memories(self, message: str, user_id: str, session_id: str) -> List[Dict]:
        """Search for relevant memories using Mem0 with session awareness"""
        logger.info(f"Searching relevant memories - user: {user_id}, session: {session_id}, message: {message[:50]}...")
        try:
            query = message
            
            # Build filters to be user and session aware
            filter_conditions = [
                {"user_id": user_id},
                {"app_id": "ttyd_chat"} #todo: add app id params
            ]
            
            if session_id:
                filter_conditions.append({"run_id": session_id})
            
            filters = {"AND": filter_conditions}
            logger.info(f"Using filters for memory search: {filters} and session id: {session_id}")
            
            logger.info(f"Calling memClient.search with query: {query}...")
            memories = self.memClient.search(
                query, 
                top_k=7,
                threshold=0,
                rerank=True,
                keyword_search=False,   
                version="v2", 
                filters=filters,
                )
            logger.info(f"Memories: {memories} for session id: {session_id}")
            
            if memories and 'results' in memories:
                results = memories['results']
                logger.info(f"Found {len(results)} memories for session {session_id}")
                return results
            elif memories and isinstance(memories, list):
                logger.info(f"Found {len(memories)} memories (direct list) for session {session_id}")
                return memories
            else:
                logger.info(f"No memories found for session {session_id}")
                return []
        except Exception as e:
            logger.error(f"Error searching memories: {e}", exc_info=True)
            return []

    def store_conversation_memory(self, user_message: str, assistant_response: str, user_id: str, 
                                 session_id: str = None):
        """Store the conversation in Mem0 with session context"""
        logger.info(f"Storing conversation memory - user: {user_id}, session: {session_id}, message length: {len(user_message)}, response length: {len(assistant_response)}")
        try:
            conversation = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response}
            ]
            
            includes = "health and policy related things"
            
            # Store conversation with session metadata
            logger.info("Calling memClient.add to store conversation for session: " + session_id)
            response = self.memClient.add(
                conversation, 
                user_id=user_id, 
                app_id="ttyd_chat",
                run_id=session_id,
                version="v2",
                infer=False
                # includes=includes
            )
            
            logger.info(f"Response from memClient.add: {response} for session: {session_id}") 
            logger.info(f"Conversation: {conversation} for session: {session_id}") 

            logger.info(f"Memory stored successfully for user {user_id}, session {session_id}")
        except Exception as e:
            logger.error(f"Error storing memory: {e}", exc_info=True)

    def build_memory_context(self, memories: List[Dict]) -> str:
        """Build context string from retrieved memories"""
        logger.info(f"Building memory context from {len(memories)} memories")
        if not memories:
            logger.info("No memories found for context building")
            return ""
        
        memory_texts = []
        for mem in memories:
            # Try different possible field names for memory content
            memory_content = mem.get('memory', '') or mem.get('content', '') or mem.get('text', '')
            if memory_content:
                memory_texts.append(memory_content)
        
        if memory_texts:
            context = f"\n\nRelevant conversation history:\n" + "\n".join([f"- {mem}" for mem in memory_texts])
            logger.info(f"Memory context built successfully. Length: {len(context)}")
            return context
        logger.info("No memory content found")
        return ""
    
    def rewrite_query_with_memory(self, message: str, memory_context: str) -> Dict[str, Any]:
        """
        Rewrite the user's query using memory to create a standalone query and extract structured data.
        """
        logger.info("Rewriting query with memory context.")

        rewrite_prompt = f"""
            You are a query analysis expert. Your task is to analyze a user's message in the context of a conversation history and return a JSON object with four fields: "rewrittenQuery", "questionType", "isUserLocationQuestion", and "intent".

            Rules:
            1.  **rewrittenQuery**:
                - If `memory_context` is empty, do not rewrite the user query; return the original message.
                - If the user's message is a greeting or small talk (e.g., "hi", "thanks"), keep it as is.
                - If the question is unrelated to prior conversation, rewrite it as a new standalone query without adding past context.
                - For generic references ("this", "that", "they", "it", "he", "she"), resolve meaning using the last 2–3 user messages from the conversation history.
                - Always preserve critical entities (e.g., parents, spouse, children).
                - If the last question referred to a policy or benefit type, inject relevant memory context into the rewritten query.
                - For vague questions ("what is the limit?", "is it covered?"), infer the subject based on the immediate previous turn, not the entire history.
                - Maintain the tone and intent exactly as the user expressed it.

            2.  **questionType**:
                - Identify if the user is asking about in-network or out-of-network services.
                - If the question involves hospitals, clinics, providers, facilities, or network services, this will be in-network.
                - Set to "Network" if the user is asking about in-network options.
                - Set to "NonNetwork" if the question is about benefits not tied to a specific network (e.g., "is dental covered?").

            3.  **isUserLocationQuestion**:
                - Determine if the user's query implies a geographic location.
                - Set to "True" if the user asks about their current location (e.g., "near me", "in my city").
                - Otherwise, set to "False".

            4.  **intent**:
                - If `memory_context` is empty, the intent is always "New".
                - If `memory_context` is present, analyze if the user's query is a follow-up to the existing conversation.
                - If the query is related to the memory, set to "FollowUp".
                - If the query is on a new topic despite the memory, set to "New".

            Output only the JSON object, with no additional explanations or formatting.

            Conversation History:
            {memory_context}

            User Message: "{message}"
        """

        try:
            response = self.chat_client.chat.completions.create(
                model=self.rewrite_deployment_name,
                messages=[{"role": "system", "content": "You are a query analysis assistant that returns JSON."},
                          {"role": "user", "content": rewrite_prompt}],
                max_tokens=300,
                temperature=0.0,
                stream=False,
                response_format={"type": "json_object"}
            )

            response_content = response.choices[0].message.content.strip()
            logger.info(f"Raw response from rewrite model: {response_content}")

            # Clean the response to ensure it's valid JSON
            try:
                # Find the start and end of the JSON object
                start_index = response_content.find('{')
                end_index = response_content.rfind('}') + 1
                if start_index != -1 and end_index != 0:
                    json_str = response_content[start_index:end_index]
                    rewritten_data = json.loads(json_str)
                else:
                    raise json.JSONDecodeError("No JSON object found", response_content, 0)
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from response: {response_content}")
                # Fallback to a default structure if JSON parsing fails
                return {
                    "rewrittenQuery": message,
                    "questionType": "NonNetwork",
                    "isUserLocationQuestion": "False",
                    "intent": "New"
                }

            logger.info(f"Original query: '{message}'")
            logger.info(f"Rewritten data: {rewritten_data}")
            return rewritten_data
        except Exception as e:
            logger.error(f"Error rewriting query: {e}", exc_info=True)
            # Fallback to original message in a structured format
            return {
                "rewrittenQuery": message,
                "questionType": "NonNetwork",
                "isUserLocationQuestion": "False",
                "intent": "New"
            }
    
    def enhanced_chat_completion(self, message: str, top_k: int, tenant_name: str, user_id: str, metadata: Optional[Dict] = None):
        """Enhanced chat completion with session-aware RAG and memory"""
        logger.info(f"Starting enhanced_chat_completion - user: {user_id}, message length: {len(message)}, top_k: {top_k}, tenant: {tenant_name}")
        
        # Extract session_id from metadata
        session_id = metadata.get("session_id") if metadata else None
        logger.info(f"Extracted session_id from metadata: {session_id}")
        
        # Get request lock for this user/session
        request_lock = self._get_request_lock(user_id, session_id)
        logger.info(f"Acquiring request lock for user: {user_id}, session: {session_id}")
        
        graphrag_response = None
        graphrag_flag = False
        
        try:
            # Acquire lock to ensure only one request is processed at a time
            if not request_lock.acquire(timeout=30):  # 30 second timeout
                logger.warning(f"Timeout waiting for request lock for user: {user_id}, session: {session_id}")
                yield {"type": "error", "content": "Request timeout - please try again"}
                return
            
            logger.info(f"Request lock acquired for user: {user_id}, session: {session_id}")
            
            # Clean up old locks periodically
            self._cleanup_old_locks()
            
            # Step 1: Search for relevant memories to build context
            logger.info("Step 1: Searching relevant memories for session: " + session_id)
         
            memories = self.search_relevant_memories(message, user_id, session_id)
            
            # Step 1.1: Build memory context
            memory_context = self.build_memory_context(memories)
            logger.info(f"Memory context: {memory_context} for session: {session_id}")
            
            # Step 2: Rewrite the user's query using memory context
            logger.info("Step 2: Rewriting query with memory context and search query: " + message + " and session id: " + session_id)
            rewritten_data = self.rewrite_query_with_memory(message, memory_context)
            search_query = rewritten_data.get("rewrittenQuery", message)
            if rewritten_data.get("questionType") == "Network":
                graphrag_flag = True

            
            logger.info(f"Call neo4j graphrag service with graphrag flag: {graphrag_flag} and search query: {search_query}")
            
            if graphrag_flag:
                graphrag_response = self.graphRAGService.generate(rewritten_data, metadata)
                logger.info(f"Graphrag response: {graphrag_response}")
                
            # Step 3: Search for documents using the rewritten query
            logger.info(f"Step 3: Searching for relevant documents with query: '{search_query}' and session id: {session_id}")
            documents = self.search_documents(search_query, top_k, tenant_name)
            logger.info(f"Total documents found in weaviate: {len(documents)} for session: {session_id}")
            
            # Step 4: Build RAG context from the retrieved documents
            logger.info(f"Step 4: Building RAG context from documents for session: " + session_id)
            policy_wording_source, schedule_of_benefits_source, general_exclusions_source = self.build_context_from_documents(documents)
                
            # Send progress indicator for response generation
            logger.info("Step 5: Sending progress indicator for session: " + session_id)
            yield {"type": "progress", "stage": "generating_response", "message": "Generating response..."}
            
            # Step 6: Build enhanced messages with all contexts
            logger.info("Step 6: Building enhanced messages with all contexts for session: " + session_id)
            messages = self.build_messages(search_query, policy_wording_source, schedule_of_benefits_source, general_exclusions_source, memory_context, graphrag_flag, graphrag_response)
            logger.info(f"Build Messages user and assistant messages: {json.dumps(messages)} for session: {session_id}")
            
            logger.info(f"Step 7: Creating streaming chat completion for user {user_id} and session id: {session_id}")
            # Step 7: Create streaming chat completion
            stream = self.chat_client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                max_tokens=1500,
                temperature=float(os.getenv("TEMPERATURE", "0.7")),
                stream=True
            )
            
            # Step 8: Stream the response and collect it simultaneously
            logger.info("Step 8: Starting response streaming for user: " + user_id + " and session id: " + session_id)
            full_response = ""
            chunk_count = 0
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    chunk_count += 1
                    # Stream the entire chunk immediately
                    if chunk_count % 10 == 0:  # Log every 10th chunk to avoid spam
                        logger.info(f"Streamed {chunk_count} chunks so far")
                    yield {"type": "text", "content": content}
            
            logger.info(f"Step 9: Streaming completed. Total chunks: {chunk_count}, response length: {len(full_response)} for user: " + user_id + " and session id: " + session_id)
            
            
            # Step 10: Store the conversation in memory with session context
            if full_response:
                logger.info("Step 10: Storing conversation in memory for user: " + user_id + " and session id: " + session_id)
                self.store_conversation_memory(
                    user_message=search_query,
                    assistant_response=full_response,
                    user_id=user_id,
                    session_id=session_id
                )
            
            logger.info("Enhanced chat completion completed successfully for user: " + user_id + " and session id: " + session_id)
            
        except Exception as e:
            logger.error(f"Error in enhanced_chat_completion: {str(e)} for session: {session_id}", exc_info=True)
            yield {"type": "error", "content": f"Error generating response: {str(e)}"}
        finally:
            # Always release the lock
            logger.info(f"Releasing request lock for user: {user_id}, session: {session_id}")
            request_lock.release()
