# Retail Agent
# Primary agent that handles all customer interactions
# Can coordinate with Product and Finance agents when needed

from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv
import json
import base64

# Load environment variables
load_dotenv("../.env")

def get_agent_icon(agent_name):
    """Get the custom icon for an agent (PNG or fallback to emoji)"""
    icon_mapping = {
        'buybuddy': ('assets/buybuddy.png', '🛒'),
        'fridgebuddy': ('assets/fridgebuddy.png', '📦'),
        'insurancebuddy': ('assets/insurancebuddy.png', '🛡️'),
        'customer': (None, '👤')
    }
    
    png_path, emoji_fallback = icon_mapping.get(agent_name.lower(), (None, '💬'))
    
    # If no PNG path or file doesn't exist, return emoji
    if not png_path or not os.path.exists(png_path):
        return emoji_fallback
    
    # Try to load and encode the PNG
    try:
        with open(png_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        return f'<img src="data:image/png;base64,{image_data}" class="chat-icon-img"/>'
    except Exception:
        return emoji_fallback

def initialize_retail_agent():
    """Initialize the retail agent"""
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
    
    # Get or create retail agent
    myAgent = os.getenv("AGENT_RETAIL", "retail-agent")
    try:
        agent = project_client.agents.get(agent_name=myAgent)
    except:
        # If agent doesn't exist, this is a placeholder
        agent = None
    
    openai_client = project_client.get_openai_client()
    return agent, openai_client, project_client

def analyze_query_needs(user_input):
    """
    Analyze the user query to determine if specialized agents are needed
    Returns: dict with agents needed and reasoning
    """
    user_input_lower = user_input.lower()
    
    needs_product = any(kw in user_input_lower for kw in [
        'manufacturing', 'production', 'assembly', 'inventory', 'supply',
        'operations', 'factory', 'capacity', 'process', 'equipment', 'workflow'
    ])
    
    needs_finance = any(kw in user_input_lower for kw in [
        'cost', 'price', 'budget', 'finance', 'revenue', 'profit',
        'expense', 'investment', 'roi', 'financial', 'accounting', 'payment'
    ])
    
    return {
        "needs_manufacturing": needs_product,
        "needs_finance": needs_finance,
        "agents_needed": [
            "product" if needs_product else None,
            "finance" if needs_finance else None
        ]
    }

def get_retail_response(user_input, agent, openai_client, conversation_history=None):
    """
    Get response from retail agent
    Retail agent now handles all customer queries directly
    """
    if not agent:
        return f"BuyBuddy: I'm here to help with your inquiry about: '{user_input}'"
    
    try:
        # Build conversation context if available
        messages = []
        if conversation_history:
            for msg in conversation_history[-5:]:  # Last 5 messages for context
                role = "user" if msg.get("role") == "user" else "assistant"
                messages.append({"role": role, "content": msg.get("content", "")})
        
        # Add current user input
        messages.append({"role": "user", "content": user_input})
        
        response = openai_client.responses.create(
            input=messages,
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
        return response.output_text
    except Exception as e:
        return f"BuyBuddy Error: {str(e)}"

def get_coordinated_response(user_input, retail_agent, openai_client, 
                            product_agent=None, finance_agent=None,
                            conversation_history=None):
    """
    BuyBuddy coordinates with other agents when needed
    Returns: dict with main_response and specialist_responses
    """
    # Analyze what's needed
    analysis = analyze_query_needs(user_input)
    
    # Get primary response from Retail Agent
    main_response = get_retail_response(user_input, retail_agent, openai_client, conversation_history)
    
    result = {
        "main_response": main_response,
        "specialist_responses": []
    }
    
    # Get specialist input if needed
    if analysis["needs_manufacturing"] and product_agent:
        try:
            from product_agent import get_product_response
            prod_response = get_product_response(
                f"Regarding: {user_input}\n\nBuyBuddy says: {main_response[:200]}...\n\nProvide product insights:",
                product_agent[0], 
                product_agent[1]
            )
            result["specialist_responses"].append({
                "agent": "FridgeBuddy",
                "response": prod_response,
                "icon": get_agent_icon('fridgebuddy')
            })
        except Exception as e:
            pass
    
    if analysis["needs_finance"] and finance_agent:
        try:
            from finance_agent import get_finance_response
            finance_response = get_finance_response(
                f"Regarding: {user_input}\n\nBuyBuddy says: {main_response[:200]}...\n\nProvide financial insights:",
                finance_agent[0],
                finance_agent[1]
            )
            result["specialist_responses"].append({
                "agent": "InsuranceBuddy",
                "response": finance_response,
                "icon": get_agent_icon('insurancebuddy')
            })
        except Exception as e:
            pass
    
    return result

if __name__ == "__main__":
    agent, client, project = initialize_retail_agent()
    print("BuyBuddy initialized successfully")
