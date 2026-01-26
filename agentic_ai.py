import streamlit as st
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv
import sys
import json

# Add agents directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'agents'))

from product_agent import initialize_product_agent, get_product_response
from manufacturing_agent import initialize_manufacturing_agent, get_manufacturing_response
from finance_agent import initialize_finance_agent, get_finance_response

# Load environment variables from .env file
load_dotenv(".env")

# Webpage configurations
st.set_page_config(page_title="Agentic AI Interface", page_icon=":bot:")
st.title("Agentic AI Interface")
st.write("Welcome to the Agentic AI interface. Configure your agent and interact with it below.")

# Define custom CSS for styling
custom_css = """
<style>
/*body {
    background-image: url('https://wallpaper.dog/large/10991978.jpg');
    background-size: cover;
    background-repeat: no-repeat;
    opacity: 0.85;
}*/

/* Bot icon styling */
.bot-icon {
    position: fixed;
    top: 75px;
    left: 500px;
    font-size: 100px;
    z-index: 1000;
    animation: float 3s ease-in-out infinite;
}

@keyframes float {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-10px); }
}

/* Bot icon for chat messages */
.stChatMessage [data-testid="chatAvatarIcon-assistant"]::before {
    content: "🤖";
    font-size: 24px;
}
</style>
"""

# Apply the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Add floating bot icon
st.markdown('<div class="bot-icon">🤖</div>', unsafe_allow_html=True)

# Initialize all agents
@st.cache_resource
def initialize_all_agents():
    """Initialize analysis, product, manufacturing, and finance agents"""
    agents = {}
    clients = {}
    errors = {}
    
    # Analysis Agent
    try:
        myEndpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
        tenant_id = os.getenv("AZURE_TENANT_ID")
        
        if not myEndpoint or not tenant_id:
            raise ValueError("Missing required environment variables: AZURE_AIPROJECT_ENDPOINT or AZURE_TENANT_ID")
        
        credential = InteractiveBrowserCredential(
            tenant_id=tenant_id,
            additionally_allowed_tenants=["*"]
        )
        
        project_client = AIProjectClient(
            endpoint=myEndpoint,
            credential=credential,
        )
        
        # Analysis agent (orchestrator)
        try:
            agent_name = os.getenv("AGENT_ANALYSIS", "analysis-agent")
            agents['analysis'] = project_client.agents.get(agent_name=agent_name)
        except:
            agents['analysis'] = None
            errors['analysis'] = "Analysis agent not found in Azure"
        
        clients['openai'] = project_client.get_openai_client()
        
        # Initialize specialized agents
        try:
            product_agent, product_client = initialize_product_agent()
            agents['product'] = product_agent
            clients['product'] = product_client
        except Exception as e:
            agents['product'] = None
            errors['product'] = str(e)
        
        try:
            mfg_agent, mfg_client = initialize_manufacturing_agent()
            agents['manufacturing'] = mfg_agent
            clients['manufacturing'] = mfg_client
        except Exception as e:
            agents['manufacturing'] = None
            errors['manufacturing'] = str(e)
        
        try:
            finance_agent, finance_client = initialize_finance_agent()
            agents['finance'] = finance_agent
            clients['finance'] = finance_client
        except Exception as e:
            agents['finance'] = None
            errors['finance'] = str(e)
            
    except Exception as e:
        errors['main'] = str(e)
    
    return agents, clients, errors

agents, clients, init_errors = initialize_all_agents()

# Display initialization status in sidebar
with st.sidebar:
    st.subheader("🤖 Agent Status")
    if 'main' in init_errors:
        st.error(f"❌ Main initialization failed: {init_errors['main']}")
    else:
        for agent_name in ['analysis', 'product', 'manufacturing', 'finance']:
            if agent_name in agents and agents[agent_name]:
                st.success(f"✅ {agent_name.capitalize()} Agent")
            else:
                error_msg = init_errors.get(agent_name, "Not configured")
                st.warning(f"⚠️ {agent_name.capitalize()}: {error_msg}")

# Initialize Azure AI agent
@st.cache_resource
def initialize_agent():
    # Load endpoint from environment
    myEndpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if not myEndpoint or not tenant_id:
        raise ValueError("Missing required environment variables")
    
    # Use InteractiveBrowserCredential with specific tenant
    # This will open a browser window for authentication to the correct tenant
    credential = InteractiveBrowserCredential(
        tenant_id=tenant_id,
        additionally_allowed_tenants=["*"]
    )
    
    project_client = AIProjectClient(
        endpoint=myEndpoint,
        credential=credential,
    )
    agent_name = os.getenv("AGENT_ANALYSIS", "analysis-agent")
    agent = project_client.agents.get(agent_name=agent_name)
    openai_client = project_client.get_openai_client()
    return agent, openai_client

try:
    agent, openai_client = initialize_agent()
    agent_initialized = True
except Exception as e:
    agent_initialized = False
    st.error(f"Failed to initialize agent: {str(e)}")
    st.info("Falling back to placeholder responses.")

def get_agent_response(user_input, thinking_container):
    """Get response from appropriate agent via analysis agent triage"""
    
    thinking_steps = []
    
    def add_thinking_step(step):
        """Add a thinking step and display it immediately"""
        thinking_steps.append(step)
        with thinking_container:
            st.markdown("\n\n".join(thinking_steps))
    
    add_thinking_step("🔍 Analysis Agent is evaluating your query...")
    
    # Step 1: Ask analysis agent to triage the request
    triage_prompt = f"""Analyze this user query and determine which specialist agent should handle it.

User Query: "{user_input}"

Available Specialists:
1. PRODUCT - handles product features, design, specifications, quality, development, releases
2. MANUFACTURING - handles production, operations, inventory, supply chain, factory processes
3. FINANCE - handles costs, budget, revenue, expenses, financial planning, investments
4. GENERAL - for queries that don't fit above categories or need general analysis

Respond in JSON format:
{{
    "agent": "PRODUCT|MANUFACTURING|FINANCE|GENERAL",
    "reasoning": "Brief explanation of why this agent was chosen",
    "confidence": "high|medium|low"
}}"""

    try:
        # Call analysis agent for triage
        add_thinking_step("🤔 Analyzing query context and intent...")
        
        if agents.get('analysis') and clients.get('openai'):
            triage_response = clients['openai'].responses.create(
                input=[{"role": "user", "content": triage_prompt}],
                extra_body={"agent": {"name": agents['analysis'].name, "type": "agent_reference"}},
            )
            triage_text = triage_response.output_text
            
            # Parse the JSON response
            try:
                # Extract JSON from response (handle markdown code blocks)
                if "```json" in triage_text:
                    triage_text = triage_text.split("```json")[1].split("```")[0].strip()
                elif "```" in triage_text:
                    triage_text = triage_text.split("```")[1].split("```")[0].strip()
                
                triage_data = json.loads(triage_text)
                agent_type = triage_data.get("agent", "GENERAL").upper()
                reasoning = triage_data.get("reasoning", "No reasoning provided")
                confidence = triage_data.get("confidence", "medium")
                
                add_thinking_step(f"📊 Triage Decision: {agent_type} (Confidence: {confidence})")
                add_thinking_step(f"💡 Reasoning: {reasoning}")
                
            except json.JSONDecodeError:
                # Fallback to text parsing if JSON fails
                add_thinking_step("⚠️ Using fallback text analysis...")
                triage_text_upper = triage_text.upper()
                if "PRODUCT" in triage_text_upper:
                    agent_type = "PRODUCT"
                elif "MANUFACTURING" in triage_text_upper:
                    agent_type = "MANUFACTURING"
                elif "FINANCE" in triage_text_upper:
                    agent_type = "FINANCE"
                else:
                    agent_type = "GENERAL"
                reasoning = triage_text
        else:
            # Fallback to simple keyword matching if analysis agent not available
            add_thinking_step("⚠️ Analysis agent unavailable, using keyword matching...")
            user_input_lower = user_input.lower()
            
            if any(kw in user_input_lower for kw in ['product', 'feature', 'design', 'quality', 'development']):
                agent_type = "PRODUCT"
                reasoning = "Product-related keywords detected"
            elif any(kw in user_input_lower for kw in ['manufacturing', 'production', 'inventory', 'operations', 'factory']):
                agent_type = "MANUFACTURING"
                reasoning = "Manufacturing-related keywords detected"
            elif any(kw in user_input_lower for kw in ['cost', 'budget', 'finance', 'revenue', 'expense', 'profit']):
                agent_type = "FINANCE"
                reasoning = "Finance-related keywords detected"
            else:
                agent_type = "GENERAL"
                reasoning = "General query, no specific domain detected"
            
            add_thinking_step(f"📊 Triage Decision: {agent_type}")
            add_thinking_step(f"💡 Reasoning: {reasoning}")
        
        # Step 2: Route to appropriate specialist agent
        add_thinking_step(f"🎯 Routing to {agent_type} Agent...")
        
        if agent_type == "PRODUCT":
            if agents.get('product'):
                response = get_product_response(user_input, agents['product'], clients.get('product', clients['openai']))
                add_thinking_step("✅ Product Agent response received")
            else:
                response = f"🔧 **Product Agent** (Simulated)\n\nHandling your product-related query: '{user_input}'\n\nThis is a placeholder response. The product agent will be configured in Azure to provide detailed product insights."
                add_thinking_step("⚠️ Using simulated Product Agent response")
        
        elif agent_type == "MANUFACTURING":
            if agents.get('manufacturing'):
                response = get_manufacturing_response(user_input, agents['manufacturing'], clients.get('manufacturing', clients['openai']))
                add_thinking_step("✅ Manufacturing Agent response received")
            else:
                response = f"🏭 **Manufacturing Agent** (Simulated)\n\nProcessing your operations query: '{user_input}'\n\nThis is a placeholder response. The manufacturing agent will be configured in Azure to provide detailed operational insights."
                add_thinking_step("⚠️ Using simulated Manufacturing Agent response")
        
        elif agent_type == "FINANCE":
            if agents.get('finance'):
                response = get_finance_response(user_input, agents['finance'], clients.get('finance', clients['openai']))
                add_thinking_step("✅ Finance Agent response received")
            else:
                response = f"💰 **Finance Agent** (Simulated)\n\nAnalyzing your financial query: '{user_input}'\n\nThis is a placeholder response. The finance agent will be configured in Azure to provide detailed financial analysis."
                add_thinking_step("⚠️ Using simulated Finance Agent response")
        
        else:  # GENERAL
            if agents.get('analysis') and clients.get('openai'):
                response_obj = clients['openai'].responses.create(
                    input=[{"role": "user", "content": user_input}],
                    extra_body={"agent": {"name": agents['analysis'].name, "type": "agent_reference"}},
                )
                response = response_obj.output_text
                add_thinking_step("✅ Analysis Agent handled query directly")
            else:
                response = f"📊 **Analysis Agent** (Simulated)\n\nProviding general analysis for: '{user_input}'\n\nThis is a placeholder response. The analysis agent will be configured in Azure to provide comprehensive insights."
                add_thinking_step("⚠️ Using simulated Analysis Agent response")
        
        thinking_process = "\n\n".join(thinking_steps)
        return thinking_process, response
        
    except Exception as e:
        add_thinking_step(f"❌ Error: {str(e)}")
        thinking_process = "\n\n".join(thinking_steps)
        return thinking_process, f"Error processing request: {str(e)}"

# Initialize session state for chat messages
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "How can I help you?"}]

# Reset chat history button
if st.sidebar.button("Reset chat history"):
    st.session_state.messages = [{"role": "assistant", "content": "How can I help you?"}]
    st.rerun()

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        # Show thinking process for assistant messages if available
        if msg["role"] == "assistant" and "thinking" in msg:
            with st.expander("🧠 Thinking Process", expanded=False):
                st.markdown(msg["thinking"])

# Receive user input and generate response
if prompt := st.chat_input(placeholder="Ask me anything..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    
    # Create a status container for real-time thinking process
    with st.status("🤔 Analysis Agent is thinking...", expanded=True) as status:
        thinking_container = st.empty()
        
        # Generate response from appropriate agent via orchestration
        thinking_process, response = get_agent_response(prompt, thinking_container)
        
        status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
    
    # Add assistant response
    st.session_state.messages.append({
        "role": "assistant", 
        "content": response,
        "thinking": thinking_process
    })
    with st.chat_message("assistant"):
        st.write(response)
    
    st.rerun()