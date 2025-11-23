from pymongo import MongoClient
import sys

# Replace with your actual credentials from Atlas
connection_string = "mongodb+srv://Phone:extract112122@cluster0.tot0bqe.mongodb.net/?appName=Cluster0"

try:
    client = MongoClient(connection_string)
    # Test the connection
    client.admin.command('ping')
    print("✅ MongoDB Atlas connection successful!")
    
    # List databases
    dbs = client.list_database_names()
    print("📊 Available databases:", dbs)
    
    # Test creating our database
    db = client.phonescraper
    collections = db.list_collection_names()
    print("📁 Collections in phonescraper:", collections)
    
except Exception as e:
    print(f"❌ MongoDB Atlas connection failed: {e}")
    print("💡 Common issues:")
    print("   - Incorrect username/password")
    print("   - IP address not whitelisted in Atlas")
    print("   - Network connectivity issues")