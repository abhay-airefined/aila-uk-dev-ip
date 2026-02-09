from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pymongo import MongoClient

env_files = [
    ".env.development.local",
    ".env"
]

for env_file in env_files:
    if os.path.exists(env_file):
        load_dotenv(env_file)
        break
else:
    load_dotenv()

client = AsyncIOMotorClient(os.getenv("MONGODB_HOST"))

db = client.get_default_database()