import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
import json
from langchain_google_genai import ChatGoogleGenerativeAI

import time
import fastapi
from langchain.chains import create_sql_query_chain
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from langchain_community.utilities import SQLDatabase

# from langchain_openai import AzureChatOpenAI
# from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent

# from langchain.agents import AgentExecutor
# from langchain.agents.agent_types import AgentType
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
from sqlalchemy.orm import sessionmaker
import pandas as pd
import csv
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotPromptTemplate,
    MessagesPlaceholder,
    PromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
    PromptTemplate,
)
import logging

GOOGLE_API_KEY = "AIzaSyC2ykmE8kwmam1D6Xn60l7XE964CuTKGS8"


# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = fastapi.FastAPI(
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
    global DB_Name
    DB_Name = request.db_name
    logger.debug(f"Database name set to: {DB_Name}")
    return {"message": "Database name set successfully", "db_name": DB_Name}


# Set up database connection parameters
hostname = "cdaserver.mysql.database.azure.com"
password = "Qwerty*1"
user = "cdaadmin"


def get_connection_string(db_name=None):
    if db_name:
        return f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306/{db_name}"
    return f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306"


# Initialize SQLAlchemy engine and session
def get_engine(db_name=None):
    connection_string = get_connection_string(db_name)
    logger.debug(f"Connection string: {connection_string}")
    return create_engine(connection_string)


def get_db():
    engine = get_engine(DB_Name)
    return SQLDatabase(engine)


@app.get("/schemas")
def get_schemas():
    try:
        connection_string = (
            f"mysql+mysqlconnector://{user}:{password}@{hostname}:3306/cda"
        )
        logger.debug(f"Schema connection string: {connection_string}")
        engine = create_engine(connection_string)
        with engine.connect() as connection:
            result = connection.execute(text("SHOW DATABASES"))
            schemas = [
                row[0]
                for row in result
                if row[0]
                not in ("information_schema", "performance_schema", "mysql", "sys","doctrans")
            ]
        return {"schemas": schemas}
    except SQLAlchemyError as e:
        logger.error(f"Error fetching schemas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


from langchain.agents.mrkl import prompt as react_prompt


# Set up Azure OpenAI
# llm = AzureChatOpenAI(
#     deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
#     temperature=0,
#     api_version=os.getenv("OPENAI_API_VERSION"),
#     azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
#     max_tokens=None,
#     timeout=None,
#     max_retries=2,
#     api_key=os.getenv("AZURE_OPENAI_API_KEY"),
# )


llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro-exp-0827", api_key=GOOGLE_API_KEY)


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    result: list
    sql_query: str


@app.post("/query")
def query_database(request: QueryRequest):
    try:
        db = get_db()
        logger.debug(f"Database object: {db}")

        chain = create_sql_query_chain(llm, db)
        sql_query_raw = chain.invoke(
            {"question": request.query}
        )  # Ensure this matches the request model
        logger.debug(f"Raw SQL Query: {sql_query_raw}")

        # Extract the actual SQL query if there is additional text
        if "SQLQuery:" in sql_query_raw:
            sql_query = sql_query_raw.split("SQLQuery:")[-1].strip()
        else:
            sql_query = sql_query_raw.strip()

        # Remove code block delimiters if present
        sql_query = sql_query.replace("sql", "").replace("", "").strip()
        logger.debug(f"Cleaned SQL Query: {sql_query}")

        # Execute the SQL query
        engine = get_engine(DB_Name)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            df = pd.read_sql_query(sql_query, engine)
            output_response = df.to_dict(orient="records")
            logger.debug(f"Query results: {output_response}")

            # Save the DataFrame to a CSV file
            df.to_csv("output.csv", index=False)
            logger.debug("Data saved to output.csv")
        except SQLAlchemyError as e:
            logger.error(f"SQLAlchemy error during query execution: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"SQLAlchemy error during query execution: {str(e)}",
            )
        finally:
            session.close()

        return {"result": output_response, "sql_query": sql_query}
    except SQLAlchemyError as e:
        logger.error(f"SQLAlchemy error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"SQLAlchemy error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


if __name__ == "_main_":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
