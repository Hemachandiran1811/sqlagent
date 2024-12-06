import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import create_sql_query_chain
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from langchain_community.utilities import SQLDatabase
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
from sqlalchemy.orm import scoped_session, sessionmaker
import logging

GOOGLE_API_KEY = "AIzaSyADQZ40SYbAqq6lRSKtodlRLNXM5EZK_mc"

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SQLAgent",
    description="This is CDA SQL Agent",
    version="0.1.0",
    openapi_url="/api/v0.1.1/openapi.json",
)

# Allow CORS for your frontend origin
origins = [
    "http://127.0.0.1:5501",
]

# Load the environment variables
load_dotenv()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow specific frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variable to store the database name
DB_Name = None

class DBRequest(BaseModel):
    db_name: str

@app.get("/")
async def index():
    return {"SQLAgent is Up and Running"}

@app.post("/set_db_name")
def set_db_name(request: DBRequest):
    global DB_Name, Session, engine
    DB_Name = request.db_name
    logger.debug(f"Database name set to: {DB_Name}")

    # Reinitialize the engine and session whenever the DB name changes
    engine = create_engine(get_connection_string(DB_Name))
    Session = scoped_session(sessionmaker(bind=engine))

    return {"message": "Database name set successfully", "db_name": DB_Name}

# Set up database connection parameters
hostname = "cdaserver.mysql.database.azure.com"
password = "Qwerty*1"
user = "cdaadmin"

def get_connection_string(db_name=None):
    if db_name:
        connection_string = f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306/{db_name}"
    else:
        connection_string = f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306/resource_allocations"
    logger.debug(f"Using connection string: {connection_string}")
    return connection_string

# Initialize the SQLAlchemy engine globally
engine = create_engine(get_connection_string(DB_Name))
Session = scoped_session(sessionmaker(bind=engine))

@app.get("/schemas")
def get_schemas():
    try:
        connection_string = (
            f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306/cda"
        )
        logger.debug(f"Schema connection string: {connection_string}")
        with engine.connect() as connection:
            result = connection.execute(text("SHOW DATABASES"))
            schemas = [
                row[0]
                for row in result
                if row[0] not in ("information_schema", "performance_schema", "mysql", "sys", "doctrans")
            ]
        return {"schemas": schemas}
    except SQLAlchemyError as e:
        logger.error(f"Error fetching schemas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Set up the LLM
llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro-exp-0827", api_key=GOOGLE_API_KEY)

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    result: list
    sql_query: str

@app.post("/query")
def query_database(request: QueryRequest):
    with Session() as session:
        try:
            # Initialize the database object using SQLAlchemy engine
            db = SQLDatabase(engine)  # Ensure you are getting a fresh database object for each query
            logger.debug(f"Database object: {db}")
            # Generate the SQL query using LLM
            chain = create_sql_query_chain(llm, db)
            # Generate the SQL query using LLM
            sql_query_raw = chain.invoke({"question": request.query})
            logger.debug(f"Raw SQL Query: {sql_query_raw}")

            # Improved query cleaning logic
            if "SQLQuery:" in sql_query_raw:
                sql_query = sql_query_raw.split("SQLQuery:")[-1].strip()
            else:
                sql_query = sql_query_raw.strip()

            # Remove Markdown code fences and ensure proper query formatting
            sql_query = re.sub(r"```(\w+)?\n?", "", sql_query).strip()
            sql_query = re.sub(r"```\n?", "", sql_query).strip()

            logger.debug(f"Cleaned SQL Query: {sql_query}")

            # Execute the SQL query safely and fetch all results
            with session.begin():  # Proper transaction management with `begin` context
                result = session.execute(text(sql_query))  # Execute the query
                fetched_rows = result.fetchall()  # Fetch all rows at once
                column_names = result.keys()  # Fetch the column names
            logger.debug(f"Fetched rows: {fetched_rows}")
            logger.debug(f"Column names: {column_names}")

            # Convert rows to a list of dictionaries for the response
            output_response = [
                {column: value for column, value in zip(column_names, row)} for row in fetched_rows
            ]
            logger.debug(f"Query results: {output_response}")

            return {"result": output_response, "sql_query": sql_query}

        except SQLAlchemyError as e:
            logger.error(f"SQLAlchemy error: {str(e)}")
            session.rollback()  # Rollback session on error
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            session.rollback()  # Rollback session on error
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            session.close()  # Ensure session is always closed after execution

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
