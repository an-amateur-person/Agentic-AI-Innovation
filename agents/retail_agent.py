# BuyBuddy - MediaMarktSaturn Sales Agent
# PRIMARY ORCHESTRATOR in multi-agent system (Retail ↔ Product/Liebherr ↔ Insurance/ERGO)
# Manages customer interaction through 5 phases: Intake → Inventory → Agreement → Insurance → Consolidation
# Owns conversation state and progression

from azure.identity import InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv
import json
import base64
import re

# Load environment variables
load_dotenv("../.env")

# ==================== STATE PARSING UTILITIES ====================

def parse_buybuddy_state(response):
    """
    Parse structured state metadata from BuyBuddy's response.
    
    Expected format in response:
    ---
    STATE: product_status=agreed | insurance_status=offered | overall_status=insurance_phase
    ROUTING: product_agent|ergo_agent|none
    INVENTORY_CHECKED: true|false
    ITERATION_COUNT: 2
    ---
    
    Returns: dict with parsed state
    """
    default_state = {
        'product_status': 'collecting',
        'insurance_status': 'not_offered',
        'overall_status': 'intake',
        'routing': 'none',
        'inventory_checked': False,
        'iteration_count': 0
    }
    
    # Look for metadata block
    if '---' not in response:
        return default_state
    
    try:
        # Extract metadata section robustly.
        # Typical format is: main text + --- + metadata + ---
        # In that case, split() yields a trailing empty segment, so we pick
        # the last non-empty block that contains state/routing markers.
        parts = [part.strip() for part in response.split('---') if part.strip()]
        if not parts:
            return default_state

        metadata = ""
        for part in reversed(parts):
            part_lower = part.lower()
            if 'state:' in part_lower or 'routing:' in part_lower:
                metadata = part
                break

        if not metadata:
            return default_state
        
        # Parse STATE line
        state_match = re.search(r'STATE:\s*product_status=([\w-]+)\s*\|\s*insurance_status=([\w-]+)\s*\|\s*overall_status=([\w-]+)', metadata, re.IGNORECASE)
        if state_match:
            default_state['product_status'] = state_match.group(1).lower()
            default_state['insurance_status'] = state_match.group(2).lower()
            default_state['overall_status'] = state_match.group(3).lower()
        
        # Parse ROUTING line
        routing_match = re.search(r'ROUTING:\s*([\w-]+)', metadata, re.IGNORECASE)
        if routing_match:
            default_state['routing'] = routing_match.group(1).lower()
        
        # Parse INVENTORY_CHECKED line
        inventory_match = re.search(r'INVENTORY_CHECKED:\s*(true|false)', metadata, re.IGNORECASE)
        if inventory_match:
            default_state['inventory_checked'] = inventory_match.group(1).lower() == 'true'
        
        # Parse ITERATION_COUNT line
        iteration_match = re.search(r'ITERATION_COUNT:\s*(\d+)', metadata)
        if iteration_match:
            default_state['iteration_count'] = int(iteration_match.group(1))
    
    except Exception:
        pass
    
    return default_state

def build_json_context(user_input, conversation_history, buybuddy_state, action="provide_recommendations"):
    """
    Build structured JSON context for specialist agents.
    
    Args:
        user_input: Current customer query
        conversation_history: Previous messages
        buybuddy_state: Parsed state from BuyBuddy
        action: Requested action for specialist
    
    Returns: JSON string for specialist agent
    """
    # Extract requirements from conversation
    requirements = extract_requirements(conversation_history)
    
    context = {
        "customer_context": {
            "original_query": user_input,
            "requirements": requirements,
            "budget": requirements.get('budget', 'not specified'),
            "region": requirements.get('region', 'not specified'),
            "usage_context": requirements.get('usage', 'not specified')
        },
        "product_context": {
            "search_performed": buybuddy_state.get('inventory_checked', False),
            "internal_match_found": buybuddy_state.get('routing') == 'none',
            "product_status": buybuddy_state.get('product_status', 'searching'),
            "constraints": requirements.get('constraints', [])
        },
        "current_state": buybuddy_state,
        "requested_action": action,
        "iteration_limit": 3
    }
    
    return json.dumps(context, indent=2)

def extract_requirements(conversation_history):
    """
    Extract key requirements from conversation history.
    
    Returns: dict with extracted requirements
    """
    requirements = {
        'budget': None,
        'region': None,
        'usage': None,
        'features': [],
        'constraints': []
    }
    
    if not conversation_history:
        return requirements
    
    # Concatenate recent messages
    text = ' '.join([msg.get('content', '') for msg in conversation_history[-5:]])
    text_lower = text.lower()
    
    # Extract budget
    budget_match = re.search(r'(\d+(?:,\d+)?(?:\.\d+)?)\s*(eur|euro|€|dollar|\$)', text_lower)
    if budget_match:
        requirements['budget'] = budget_match.group(0)
    
    # Extract region
    regions = ['germany', 'france', 'austria', 'switzerland', 'europe']
    for region in regions:
        if region in text_lower:
            requirements['region'] = region.title()
            break
    
    # Extract features
    features = ['ice maker', 'water dispenser', 'french door', 'energy efficient', 'smart']
    requirements['features'] = [f for f in features if f in text_lower]
    
    return requirements

def map_state_to_phase(state):
    """
    Map BuyBuddy's overall_status to UI phase number (1-5).
    
    Args:
        state: Parsed state dict from BuyBuddy
    
    Returns: int (1-5)
    """
    overall_status = state.get('overall_status', 'intake')
    
    phase_map = {
        'intake': 1,
        'inventory_check': 2,
        'product_negotiation': 3,
        'insurance_phase': 4,
        'ready_to_checkout': 5,
        'stopped': 5  # Map to final phase
    }
    
    return phase_map.get(overall_status, 1)

def validate_insurance_context(state, conversation_history):
    """
    Validate that required fields are present before routing to ERGO.
    
    Args:
        state: Parsed BuyBuddy state
        conversation_history: Previous messages
    
    Returns: (bool, str) - (is_valid, error_message)
    """
    # Check product agreement reached
    if state.get('product_status') != 'agreed':
        return False, "Product not yet agreed - cannot offer insurance"
    
    # Extract product details from conversation
    requirements = extract_requirements(conversation_history)
    
    # Check for minimum required fields
    if not requirements.get('budget'):
        return False, "Product price not confirmed - cannot calculate premium"
    
    return True, None

def validate_product_context(conversation_history):
    """
    Validate that minimum requirements are gathered before routing to FridgeBuddy.
    
    Args:
        conversation_history: Previous messages
    
    Returns: bool - True if we have enough context to consult Liebherr
    """
    requirements = extract_requirements(conversation_history)
    
    # Check for at least one requirement dimension
    has_budget = requirements.get('budget') is not None
    has_region = requirements.get('region') is not None
    has_features = len(requirements.get('features', [])) > 0
    
    # Need at least one concrete requirement to make a meaningful query
    return has_budget or has_region or has_features

def get_agent_icon(agent_name):
    """Get the custom icon for an agent (PNG or fallback to emoji)"""
    icon_mapping = {
        'buybuddy': ('buybuddy.png', '🛒'),
        'fridgebuddy': ('fridgebuddy.png', '📦'),
        'insurancebuddy': ('insurancebuddy.png', '🛡️'),
        'customer': (None, '👤')
    }
    
    icon_file, emoji_fallback = icon_mapping.get(agent_name.lower(), (None, '💬'))
    
    # If no icon file specified, return emoji
    if not icon_file:
        return emoji_fallback
    
    # Construct path to assets folder (go up one level from agents folder)
    icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', icon_file)
    
    # Try to load and encode the PNG
    if os.path.exists(icon_path):
        try:
            with open(icon_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            return f'<img src="data:image/png;base64,{image_data}" class="chat-icon-img"/>'
        except Exception:
            return emoji_fallback
    
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

def get_retail_response(user_input, agent, openai_client, conversation_history=None):
    """
    Get response from BuyBuddy (MediaMarktSaturn Sales Agent).
    
    BuyBuddy's responsibilities:
    - Customer intake and requirement gathering (max 5 question iterations)
    - Internal inventory validation (check knowledge base first)
    - Phase management and state progression
    - Translation of agent responses into customer-friendly messages
    - Final quotation consolidation
    """
    if not agent:
        return f"BuyBuddy: Hello! I'm your MediaMarktSaturn sales assistant. How can I help you find the perfect product today?"
    
    try:
        # Build conversation context if available
        messages = []
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages for context
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
                            product_agent=None, insurance_agent=None,
                            conversation_history=None, iteration_counts=None):
    """
    BuyBuddy orchestrates multi-agent coordination following strict phase-based logic.
    
    PHASE-BASED ROUTING (per instructions):
    1. INTAKE: BuyBuddy gathers requirements
    2. INVENTORY: Check internal stock FIRST, route to Product Agent only if needed
    3. AGREEMENT: Validate product selection with customer
    4. INSURANCE: Route to ERGO Agent ONLY after product agreement
    5. CONSOLIDATION: Generate final quotation
    
    ITERATION LIMITS:
    - Customer questions: max 5 iterations
    - Agent coordination: max 3 iterations per specialist
    
    Returns: dict with main_response, state, and specialist_responses
    """
    # ALWAYS get BuyBuddy's primary response first
    # BuyBuddy handles inventory checks and determines routing through its prompt
    main_response = get_retail_response(user_input, retail_agent, openai_client, conversation_history)
    
    # Parse structured state from BuyBuddy's response
    buybuddy_state = parse_buybuddy_state(main_response)
    
    # Determine routing based on parsed state (primary method)
    routing = buybuddy_state.get('routing', 'none')
    
    # Fallback: keyword-based detection if state parsing fails
    # BUT only route if we're past the intake phase (not just collecting requirements)
    response_lower = main_response.lower()
    user_input_lower = (user_input or '').lower()
    if routing == 'none':
        # Explicit user intent override: if customer directly asks to consult
        # FridgeBuddy/Product Agent, route immediately.
        explicit_product_request = any(term in user_input_lower for term in [
            'fridgebuddy',
            'product_agent',
            'product agent',
            'liebherr specialist',
            'refer to product',
            'refer to fridgebuddy'
        ])

        if explicit_product_request:
            routing = 'product_agent'

        # Only use keyword fallback if we're past initial intake
        product_status = buybuddy_state.get('product_status', 'collecting')
        overall_status = buybuddy_state.get('overall_status', 'intake')
        
        # Route to product agent only if:
        # 1. Keywords present AND
        # 2. We're past intake phase (inventory_check or later) AND
        # 3. Product status indicates searching (not just collecting) AND
        # 4. We have minimum requirements to make a meaningful query
        if (routing == 'none' and overall_status != 'intake' and 
            product_status in ['searching', 'proposed'] and
            validate_product_context(conversation_history)) and \
           any(kw in response_lower for kw in ['liebherr', 'fridgebuddy', 'product specialist', 'external catalog']):
            routing = 'product_agent'
        # Route to insurance only if product is agreed
        elif (routing == 'none' and product_status == 'agreed') and \
             any(kw in response_lower for kw in ['ergo', 'insurancebuddy', 'insurance offer']):
            routing = 'ergo_agent'
    
    # Extract inventory check info (only mark as checked if it's the first time)
    inventory_check_result = None
    if buybuddy_state.get('inventory_checked'):
        # Will be filtered in agentic_ai.py to show only once
        inventory_check_result = {
            "checked": True,
            "phase": map_state_to_phase(buybuddy_state),
            "summary": "Internal inventory check performed",
            "details": "Checked MediaMarktSaturn internal systems for product availability.",
            "first_check": True  # Flag for filtering
        }
    
    result = {
        "main_response": main_response,
        "state": buybuddy_state,
        "inventory_check": inventory_check_result,
        "specialist_responses": []
    }
    
    # PHASE 2: Route to Product Agent only if routing indicates need
    if routing == 'product_agent' and product_agent:
        # Check iteration limit
        if iteration_counts and iteration_counts.get('product_agent_calls', 0) >= 3:
            result["specialist_responses"].append({
                "agent": "System",
                "response": "⚠️ Maximum FridgeBuddy iterations reached. Using best available information.",
                "icon": "⚠️",
                "css_class": "system-message"
            })
        else:
            try:
                from product_agent import get_product_response
                
                # Build structured JSON context
                json_context = build_json_context(
                    user_input, 
                    conversation_history, 
                    buybuddy_state, 
                    action="provide_liebherr_recommendations"
                )
                
                # Format as message with context
                context_message = f"""You are receiving a structured request from MediaMarktSaturn Sales Agent.

Context (JSON):
{json_context}

Please provide Liebherr product recommendations based on the customer requirements in the JSON above. Return your response in the structured JSON format specified in your instructions."""
                
                prod_response = get_product_response(context_message, product_agent[0], product_agent[1])
                
                result["specialist_responses"].append({
                    "agent": "FridgeBuddy (Liebherr Specialist)",
                    "response": prod_response,
                    "icon": get_agent_icon('fridgebuddy'),
                    "css_class": "product-message"
                })
                
                # Increment counter
                if iteration_counts is not None:
                    iteration_counts['product_agent_calls'] = iteration_counts.get('product_agent_calls', 0) + 1
            
            except Exception as e:
                result["specialist_responses"].append({
                    "agent": "System",
                    "response": f"⚠️ FridgeBuddy unavailable: {str(e)}",
                    "icon": "⚠️",
                    "css_class": "system-message"
                })
    
    # PHASE 4: Route to Insurance Agent only if routing indicates need
    if routing == 'ergo_agent' and insurance_agent:
        # Validate insurance eligibility
        is_valid, error_msg = validate_insurance_context(buybuddy_state, conversation_history)
        
        if not is_valid:
            result["specialist_responses"].append({
                "agent": "System",
                "response": f"⚠️ Cannot route to InsuranceBuddy: {error_msg}",
                "icon": "⚠️",
                "css_class": "system-message"
            })
        elif iteration_counts and iteration_counts.get('insurance_agent_calls', 0) >= 3:
            result["specialist_responses"].append({
                "agent": "System",
                "response": "⚠️ Maximum InsuranceBuddy iterations reached.",
                "icon": "⚠️",
                "css_class": "system-message"
            })
        else:
            try:
                from insurance_agent import get_insurance_response
                
                # Build structured JSON context with required fields
                requirements = extract_requirements(conversation_history)
                insurance_context = {
                    "manufacturer": "Liebherr",
                    "product_type": "Refrigerator",
                    "product_model": "Model from conversation",  # Extract from history
                    "key_features": requirements.get('features', []),
                    "configuration_class": "Standard",
                    "purchase_price": requirements.get('budget', 'TBD')
                }
                
                # Format as message with context
                context_message = f"""You are receiving a structured request from MediaMarktSaturn Sales Agent.

Product Information (JSON):
{json.dumps(insurance_context, indent=2)}

Please assess insurability and calculate premium based on the product information above. Return your response in the structured JSON format specified in your instructions."""
                
                insurance_response = get_insurance_response(
                    context_message,
                    insurance_agent[0], 
                    insurance_agent[1]
                )
                
                result["specialist_responses"].append({
                    "agent": "InsuranceBuddy (ERGO Specialist)",
                    "response": insurance_response,
                    "icon": get_agent_icon('insurancebuddy'),
                    "css_class": "insurance-message"
                })
                
                # Increment counter
                if iteration_counts is not None:
                    iteration_counts['insurance_agent_calls'] = iteration_counts.get('insurance_agent_calls', 0) + 1
            
            except Exception as e:
                result["specialist_responses"].append({
                    "agent": "System",
                    "response": f"⚠️ InsuranceBuddy unavailable: {str(e)}",
                    "icon": "⚠️",
                    "css_class": "system-message"
                })
    
    return result

if __name__ == "__main__":
    agent, client, project = initialize_retail_agent()
    print("BuyBuddy initialized successfully")
