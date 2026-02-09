from dotenv import load_dotenv
from urllib.parse import urljoin
import os
import logging
from azure.data.tables import TableServiceClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
class AzureTableService:

    def __init__(self):
        # logger.info("Initializing AzureTableService")
        self.connection_string = os.getenv("CONNECTION_STRING")
        self.table_service_client = TableServiceClient.from_connection_string(conn_str=self.connection_string)
        self.table_name = "Configurations"
        self.top_k = 12
        # logger.info(f"AzureTableService initialized - table: {self.table_name}")

    def getCitationCountByClientId(self, client_id):
        # logger.info(f"Getting citation count for client_id: {client_id}")
        try:
            # logger.info("Getting table client")
            table_client = self.table_service_client.get_table_client(table_name=self.table_name)
            
            my_filter = (
                "Template eq 'search_policy' and "
                "Name eq 'citationCount' and "
                f"ClientId eq '{client_id}'"
            )
            # logger.info(f"Query filter: {my_filter}")
            
            # logger.info("Executing query on Azure Table")
            entities = table_client.query_entities(query_filter=my_filter)
            entity_count = 0
            
            for entity in entities:
                entity_count += 1
                # logger.info(f"Found entity {entity_count}: {entity}")
                for key in entity.keys():
                    if key == 'Value':
                        citation_count = int(entity[key])
                        # logger.info(f"Retrieved citation count: {citation_count}")
                        return citation_count
            
            if entity_count == 0:
                logger.warning(f"No entities found for client_id: {client_id}")
            else:
                logger.warning(f"Found {entity_count} entities but none had 'Value' key")
            
            # logger.info("No citation count found, returning None")
            return None
            
        except Exception as e:
            logger.error(f"Error getting citation count for client_id {client_id}: {str(e)}", exc_info=True)
            return None
