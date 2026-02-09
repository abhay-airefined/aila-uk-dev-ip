import os
import logging
from dotenv import load_dotenv
import openai
from neo4j import GraphDatabase
from langchain_neo4j import Neo4jGraph
import json

import re
from typing import Any, Dict, List, Union
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



class GraphRAGService:
    def __init__(self,testing: bool = False):
        """Initialize the GraphRAGService."""
        logger.info("Initializing GraphRAGService")
        if  not testing:
            load_dotenv()
        self.testing = testing
        # Initialize any required resources here
        self.chat_api_key = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        self.chat_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.chat_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        self.chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        self.mem_api_key = os.getenv("MEM0_API_KEY")
        self.openai_api_base=os.getenv("OPENAI_API_BASE")
        self.openai_api_version=os.getenv("OPENAI_API_VERSION")
        self.deployment_name=os.getenv("DEPLOYMENT_NAME")
        self.openai_api_key=os.getenv("OPENAI_API_KEY")
        openai.api_type = "azure"
        openai.api_base = os.getenv("OPENAI_API_BASE")
        openai.api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        openai.api_key = os.getenv("OPENAI_API_KEY")
        self.driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            #notifications_min_severity="OFF",
        )
        self.graph = Neo4jGraph(url=os.environ["NEO4J_URI"],database=os.environ["NEO4J_USERNAME"],username=os.environ["NEO4J_USERNAME"],password=os.environ["NEO4J_PASSWORD"],sanitize=True)
        self.REFDATA_QUERIES = [
            ("ProviderType", "name", "ProviderType"),
            ("Offering", "CopayOverrideType", "CopayOverrideType"),
            ("Offering", "OpticalIncluded", "OpticalIncluded"),
            ("Offering", "DentalIncluded", "DentalIncluded"),
            ("Country", "name", "Country"),
            ("Region", "name", "Region"),
            ("Subregion", "name", "Subregion"),
            ("InsuranceCompany", "name", "InsuranceCompany"),
            ("Network", "name", "Network"),
            ("Plan", "name", "Plan"),
            ("Class", "name", "Class")
        ]
        self.ignore_relationship_direction = True
        
        logger.info("GraphRAGService initialized successfully")

    def achat(self,messages:List, model:str = None, temperature:int=0 , config:dict = {}):
        model = model or self.deployment_name
        response = openai.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=messages,
                **config,
            )
        return response.choices[0].message.content
    
    def get_distinct_values(self,label:str, prop:str) -> List[str]:
        """
        Run a Cypher query to fetch distinct values of a given property on nodes with the specified label.
        """
        query = f"MATCH (n:{label}) WHERE n.{prop} IS NOT NULL RETURN DISTINCT n.{prop} AS value ORDER BY value"
        with self.driver.session() as session:
            result = session.run(query)
            return [record["value"] for record in result]

    def build_allowed_values(self) -> str:
        """
        Query all reference data properties and construct the allowed_values string.
        """
        lines = []
        for label, prop, alias in self.REFDATA_QUERIES:
            values = self.get_distinct_values(label, prop)
            # Filter out None and NaN values from the list before joining
            filtered_values = [str(v) for v in values if v is not None and str(v).lower() != "nan"]
            prop_line = f"- {alias}: {', '.join(filtered_values)}"
            lines.append(prop_line)

        return "\n".join(lines)

    def get_system_message(self, schema,examples:List,allowed_values:str) -> str:
        system = """
        Your task is to convert questions about contents in a Neo4j database to Cypher queries to query the Neo4j database.
        Use only the provided relationship types and properties.
        Do not use any other relationship types or properties that are not provided.
        """
        if schema:
            system += f"""
            If you cannot generate a Cypher statement based on the provided schema, explain the reason to the user.
            Schema:
            {schema}
            """
        if examples:
            system += f"""
            You need to follow these Cypher examples when you are constructing a Cypher statement
            {examples}
            """
        if allowed_values:
            system += f"""
            Allowed values for properties:
            ## Allowed Values
            {allowed_values}    
            """
        # Add note at the end and try to prevent LLM injections
        system += """Note: 
                - Do not include any explanations or apologies in your responses.
                - Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
                - Understand the user’s question.
                - Map relevant concepts to schema fields and allowed values.
                - Replace Natural Language with Schema Terms
                    -Translate common or domain-specific phrases into schema-specific 
                        - terms:"hospital", "clinic", "medical center" → ProviderType "eye care", 
                        - "vision services" → OpticalIncluded 
                        - "copay is 20%" → CopayOverridePercent = 20
                - Do not include any text except the generated Cypher statement. This is very important if you want to get paid.
                - Always provide enough context for an LLM to be able to generate valid response.
                - Please wrap the generated Cypher statement in triple backticks (`).
                 """
        return system
    
    def construct_cypher(self,question: str,examples:List,allowed_values:str,history:Dict) -> str:
        messages = [{"role": "system", "content": self.get_system_message(schema=self.graph.schema,examples=examples,allowed_values=allowed_values)}]
        if history:
            messages.append(history)
        messages.append(
            {
                "role": "user",
                "content": question,
            }
        )
        logger.info(
            [el for el in messages if not el["role"] == "system"])
        output = self.achat(messages, model="gpt-4.1")
        return output
    
    def remove_relationship_direction(self,cypher:str) -> str:
        return cypher.replace("->", "-").replace("<-", "-")
    


    def run(self,
            question: str, history: List = [], heal_cypher: bool = True
           ) -> Dict[str, Union[str, List[Dict[str, Any]]]]:
            # Add prefix if not part of self-heal loop
            final_question = (
                "Question to be converted to Cypher: " + question
                if heal_cypher
                else question
            )
            examples = [
                # 1. List all Classes under Plan Care Gold DNE with Dental- Individual
                "USER INPUT: 'list all Classes under Plan Care Gold DNE with Dental- Individual' QUERY: MATCH (off:Offering)-[:FOR_PLAN]->(pl:Plan {name:'Care Gold DNE with Dental- Individual'}), (off)-[:FOR_CLASS]->(cl:Class) RETURN DISTINCT cl.name AS className;",

                # 2. Find Providers offering Class Gold under Plan Care Gold DNE with Dental- Individual in Region Dubai
                "USER INPUT: 'find Providers offering Class Premium Healthcare Plus under Plan Care Gold DNE with Dental- Individual in Region Dubai' QUERY: MATCH (prov:Provider)-[:HAS_OFFERING]->(off:Offering)-[:FOR_PLAN]->(pl:Plan {name:'Care Gold DNE with Dental- Individual'}), (off)-[:FOR_CLASS]->(cl:Class {name:'Premium Healthcare Plus'}), (off)-[:IN_REGION]->(r:Region {name:'Dubai'}) RETURN prov.name_en AS name, off.CopayOverridePercent AS copayPercent;",

                # 3. Get copay override details for a specific Provider-Plan-Class-Region combination
                "USER INPUT: 'get copay override details for Advanced Diagnostics Center under Plan Care Gold DNE with Dental- Individual for Class Premium Healthcare Plus in Region Dubai' QUERY: MATCH (prov:Provider {name_en:'Advanced Diagnostics Center'})-[:HAS_OFFERING]->(off:Offering)-[:FOR_PLAN]->(pl:Plan {name:'Care Gold DNE with Dental- Individual'}), (off)-[:FOR_CLASS]->(cl:Class {name:'Premium Healthcare Plus'}), (off)-[:IN_REGION]->(r:Region {name:'Dubai'}) RETURN off.CopayOverridePercent AS percent, off.CopayOverrideMaxAmount AS maxAED, off.CopayOverrideAmount AS amountAED;",

                # 4. List all Services provided by Provider P123
                "USER INPUT: 'what Services does Dubai International Dental Center offer?' QUERY: MATCH (prov:Provider {name_en:'Dubai International Dental Center'})-[:SERVICES]->(srv:Service) RETURN srv.name AS service;",

                # 5. List all providers that include dental service
                "USER INPUT: 'which Providers include dental service?' QUERY: MATCH (prov:Provider)-[:SERVICES]->(srv:Service {name:'Dental'}) RETURN prov.id AS providerId, prov.name_en AS name;",

                # 6. Find all Providers of type Hospital in Subregion Dubai Marina
                "USER INPUT: 'list all Hospital Providers in Subregion 'Dubai Marina' QUERY: MATCH a=(prov:Provider)-[:HAS_TYPE]->(pt:ProviderType {name:'HOSPITAL'}) ,(prov)-[:LOCATED_IN]->(s:Subregion {name:'Dubai Marina'}) RETURN prov.id AS providerId, prov.name_en AS name;"
                # 7. Hospital located near users location
                "USER INPUT: 'Which hospitals are located near me?' QUERY: MATCH (prov:Provider)-[:HAS_TYPE]-(pt:ProviderType {name:'HOSPITAL'}) WITH prov, point.distance(point({latitude:24.5021, longitude:54.3941}), prov.coords) AS dist RETURN prov.id AS providerId, prov.name_en AS name, prov.address AS address, dist ORDER BY dist ASC LIMIT 5;"
            ]

            allowed_values = self.build_allowed_values()

            cypher =  self.construct_cypher(question=final_question, examples=examples, allowed_values=allowed_values,history=history)
            # finds the first string wrapped in triple backticks. Where the match include the backticks and the first group in the match is the cypher
            match = re.search(r"```([\w\W]*?)```", cypher)

            # If the LLM didn't any Cypher statement (error, missing context, etc..)
            if match is None:
                return {"output": [{"message": cypher}], "generated_cypher": None}
            extracted_cypher = match.group(1)

            if self.ignore_relationship_direction:
                extracted_cypher = self.remove_relationship_direction(extracted_cypher)

            logger.info(
                f"Generated cypher: {extracted_cypher}")
            try:
                output = self.driver.execute_query(extracted_cypher)
            except Exception as e:
                # Catch any low-level driver exception
                error_msg = str(e)
                logging.error(f"Driver error: {error_msg}")

                if heal_cypher:
                    # Feed error back to LLM + original cypher for healing
                    heal_history = [
                        {"role": "system", "content": self.get_system_message(schema=self.graph.schema,examples=examples,allowed_values=allowed_values)},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": extracted_cypher},
                        {"role": "system", "content": f"Error from database: {error_msg}"}
                    ]
                    return self.run(question, history=heal_history, heal_cypher=False)

                # If already healed once, just return the error
                return {"output": [{"message": error_msg}], "generated_cypher": extracted_cypher }
            logger.info(f"Cypher output: {output}")

            return {
                "output": output,
                "generated_cypher": extracted_cypher,
            }

    def extract_records(self,generated_output):
        # 2. Grab the EagerResult
        eager = generated_output['output']

        # 3. Extract the list of neo4j.Record objects
        records = getattr(eager, "records", None)
        if records is None:
            # fallback if your driver returns an iterable of Records
            records = list(eager)

        # 4. Convert each Record to a dict
        records_dicts = [dict(rec) for rec in records]

        # 5. Serialize to JSON
        results_json = json.dumps(records_dicts, ensure_ascii=False, indent=2)

        # 6. Print so you can feed it into your RAG prompt
        logger.info(f"Query Results: {results_json}")

        return results_json

    def useNLP(self,user_question, neo4j_results):
        system_prompt = """
    You are a helpful assistant that takes a user's original question and the corresponding structured Neo4j query results, and responds in a natural, human-readable format.

    Your goal is to:
    - Clearly answer the user’s intent
    - Present the results in an easy-to-read bullet or paragraph style
    - Do not mention technical terms like JSON or databases
    - Just explain the output naturally
    - Any amount/monetary value must be presented in AED
    - If the response contains distance, it should be in kilometers

    Example:
    ## User Input:
    List all Providers offering Class Premium Healthcare Plus under Plan Care Gold DNE with Dental- Individual in Region Dubai

    ## Query Results:
    [
    {"providerId": 7507, "name": "Advanced Diagnostics Center"},
    {"providerId": 7506, "name": "Dubai Day Surgery Center"},
    {"providerId": 7505, "name": "Vision Plus Optical Center"}
    ]

    ## Output:
    Here are the list of providers:
    • Advanced Diagnostics Center
    • Dubai Day Surgery Center
    • Vision Plus Optical Center
    """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Question: {user_question}\n\nQuery Results: {neo4j_results}"}
        ]
        logger.info(f"Messages for explanation: {messages}")
        response = self.achat(messages)
        return response

    def generate(self, rewritten_data: Dict,metadata:Dict, heal_cypher: bool = True,) -> str:
        """
        Generate a response based on the request.
        This function handles the chat completion and streaming of responses.
        """
        user_question = rewritten_data.get("rewrittenQuery", ""
                                           )
        if not user_question:
            logger.error("No user question provided in the request.")
            return ""
        locationQuestion = rewritten_data.get("isUserLocationQuestion", "")
        lattitude = metadata.get("lattitude", "24.5021")
        longitude = metadata.get("longitude", "54.3941")
        if(locationQuestion == "True"):
            user_question += f" with location lattidute: {lattitude}, longitude:{longitude}"
            logger.info("User question is related to location, add location from metadata ")
            
        logger.info(f"Generating response for question: {user_question}")
        try:
            graph_rag_output =  self.run(user_question, history=[])
            logger.info("Graph RAG output:%s", graph_rag_output)
            neo4j_results = self.extract_records(graph_rag_output)
            logger.info(f"Extracted Neo4j results: {neo4j_results}")
            
            if self.testing:
                # For testing, just return the Neo4j results
                explanation = self.useNLP(user_question, neo4j_results)
                logger.info(f"Generated explanation: {explanation}")
                return explanation
            else:
                return neo4j_results
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return ""

