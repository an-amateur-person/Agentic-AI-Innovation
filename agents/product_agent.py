# Product Agent
# Handles product and operations queries

from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv
from .utilities import create_azure_credential

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=False)

def initialize_product_agent():
    """Initialize the product agent"""
    myEndpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if not myEndpoint:
        raise ValueError("Missing required environment variable: AZURE_AIPROJECT_ENDPOINT")

    credential = create_azure_credential(tenant_id)
    
    project_client = AIProjectClient(
        endpoint=myEndpoint,
        credential=credential,
    )
    
    # Get or create product agent
    myAgent = os.getenv("AGENT_PRODUCT", "product-agent")
    try:
        agent = project_client.agents.get(agent_name=myAgent)
    except:
        # If agent doesn't exist, this is a placeholder
        agent = None
    
    openai_client = project_client.get_openai_client()
    return agent, openai_client

def get_product_response(user_input, agent, openai_client):
    """Get response from product agent"""
    if not agent:
        return f"Product Specialist: Processing product query - '{user_input}'"
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": user_input}],
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
        return response.output_text
    except Exception as e:
        return f"Product Specialist Error: {str(e)}"

if __name__ == "__main__":
    agent, client = initialize_product_agent()
    print("Product Specialist initialized successfully")
