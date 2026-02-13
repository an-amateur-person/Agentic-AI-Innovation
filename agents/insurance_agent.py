# Insurance Agent
# Handles insurance and budget-related queries

from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv("../.env")

def initialize_insurance_agent():
    """Initialize the insurance agent"""
    myEndpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if not myEndpoint or not tenant_id:
        raise ValueError("Missing required environment variables")
    
    credential = InteractiveBrowserCredential(
        tenant_id=tenant_id,
        additionally_allowed_tenants=["*"]
    )
    
    project_client = AIProjectClient(
        endpoint=myEndpoint,
        credential=credential,
    )
    
    # Get or create insurance agent
    myAgent = os.getenv("AGENT_INSURANCE", "insurance-agent")
    try:
        agent = project_client.agents.get(agent_name=myAgent)
    except:
        # If agent doesn't exist, this is a placeholder
        agent = None
    
    openai_client = project_client.get_openai_client()
    return agent, openai_client

def get_insurance_response(user_input, agent, openai_client):
    """Get response from insurance agent"""
    if not agent:
        return f"InsuranceBuddy: Analyzing insurance query - '{user_input}'"
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": user_input}],
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
        return response.output_text
    except Exception as e:
        return f"InsuranceBuddy Error: {str(e)}"

if __name__ == "__main__":
    agent, client = initialize_insurance_agent()
    print("InsuranceBuddy initialized successfully")
