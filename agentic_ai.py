import streamlit as st
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv
import sys
import json
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER

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

/* Group chat message styling */
.chat-message {
    padding: 12px;
    margin: 8px 0;
    border-radius: 10px;
    border-left: 4px solid #ddd;
}

.user-message {
    border-left-color: #2196F3;
}

.analyzer-message {
    border-left-color: #9C27B0;
}

.product-message {
    border-left-color: #4CAF50;
}

.manufacturing-message {
    border-left-color: #FF9800;
}

.finance-message {
    border-left-color: #E91E63;
}

.sender-name {
    font-weight: bold;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.timestamp {
    font-size: 0.75em;
    color: #666;
    margin-left: auto;
}

.message-content {
    margin-top: 4px;
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
    """Initialize analyzer, product, manufacturing, and finance agents"""
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
        
        # Analyzer (orchestrator)
        try:
            agent_name = os.getenv("AGENT_ANALYSIS", "analysis-agent")
            agents['analyzer'] = project_client.agents.get(agent_name=agent_name)
        except:
            agents['analyzer'] = None
            errors['analyzer'] = "Analyzer not found in Azure"
        
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
        for agent_name in ['analyzer', 'product', 'manufacturing', 'finance']:
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

def generate_proposal_summary():
    """Generate a comprehensive proposal summary from the conversation history"""
    if len(st.session_state.messages) <= 1:
        return None, "No conversation to summarize yet. Start chatting with the agents first!"
    
    # Build conversation context
    conversation_text = ""
    for msg in st.session_state.messages:
        sender = msg.get("sender", "Unknown")
        content = msg.get("content", "")
        conversation_text += f"{sender}: {content}\n\n"
    
    # Create prompt for analyzer to generate proposal
    proposal_prompt = f"""Based on the following multi-agent conversation, create a comprehensive draft proposal document.

The proposal should include:
1. Executive Summary
2. Key Discussion Points
3. Insights from Product Agent
4. Insights from Manufacturing Agent
5. Insights from Finance Agent
6. Recommendations and Next Steps
7. Conclusion

Conversation History:
{conversation_text}

Generate a well-structured, professional proposal document."""
    
    try:
        if agents.get('analyzer') and clients.get('openai'):
            response = clients['openai'].responses.create(
                input=[{"role": "user", "content": proposal_prompt}],
                extra_body={"agent": {"name": agents['analyzer'].name, "type": "agent_reference"}},
            )
            proposal_text = response.output_text
            return proposal_text, None
        else:
            return None, "Analyzer agent is not available to generate proposal."
    except Exception as e:
        return None, f"Error generating proposal: {str(e)}"

def generate_pdf(proposal_text):
    """Generate a PDF document from the proposal text"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                          rightMargin=72, leftMargin=72,
                          topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Justify', alignment=TA_JUSTIFY))
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor='#1E88E5',
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Add title
    title = Paragraph("Multi-Agent Collaboration Proposal", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    # Add date
    date_text = f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
    elements.append(Paragraph(date_text, styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Process the proposal text
    # Split by double newlines to get paragraphs
    paragraphs = proposal_text.split('\n\n')
    
    for para in paragraphs:
        if para.strip():
            # Check if it's a heading (contains certain keywords or is short)
            if any(keyword in para for keyword in ['Executive Summary', 'Key Discussion', 'Insights from', 
                                                    'Recommendations', 'Conclusion', 'Next Steps']):
                # It's likely a heading
                elements.append(Spacer(1, 12))
                elements.append(Paragraph(para.strip(), styles['Heading2']))
                elements.append(Spacer(1, 6))
            else:
                # Regular paragraph
                elements.append(Paragraph(para.strip(), styles['Justify']))
                elements.append(Spacer(1, 12))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

def get_multi_agent_conversation(user_input, thinking_container, conversation_history, agent_placeholders=None):
    """Orchestrate a multi-agent conversation where agents can respond to each other"""
    
    thinking_steps = []
    agent_responses = []
    
    def add_thinking_step(step):
        """Add a thinking step and display it immediately"""
        thinking_steps.append(step)
        with thinking_container:
            st.markdown("\n\n".join(thinking_steps))
    
    def display_agent_response_realtime(agent_name, content, icon, css_class):
        """Display agent response in real-time"""
        if agent_placeholders and agent_name in agent_placeholders:
            response_time = datetime.now().strftime("%I:%M %p")
            agent_placeholders[agent_name].markdown(f"""
            <div class="chat-message {css_class}">
                <div class="sender-name">
                    <span>{icon} <strong>{agent_name}</strong></span>
                    <span class="timestamp">{response_time}</span>
                </div>
                <div class="message-content">{content}</div>
            </div>
            """, unsafe_allow_html=True)
    
    add_thinking_step("🔍 Analysis Agent is evaluating the conversation...")
    
    # Step 1: Determine which agents should participate
    context_messages = "\n".join([f"{msg['sender']}: {msg['content']}" for msg in conversation_history[-5:]])
    
    triage_prompt = f"""Analyze this conversation and determine which specialist agents should participate in the response.

Recent Conversation:
{context_messages}

Latest User Message: "{user_input}"

Available Specialists:
1. PRODUCT - handles product features, design, specifications, quality, development, releases
2. MANUFACTURING - handles production, operations, inventory, supply chain, factory processes
3. FINANCE - handles costs, budget, revenue, expenses, financial planning, investments

Respond in JSON format with agents that should participate (can be multiple):
{{
    "agents": ["PRODUCT", "MANUFACTURING", "FINANCE"],  // List relevant agents
    "reasoning": "Brief explanation",
    "conversation_order": ["PRODUCT", "FINANCE", "MANUFACTURING"]  // Order they should respond
}}"""

    try:
        # Call analyzer for triage
        add_thinking_step("🤔 Analyzing which agents should participate...")
        
        participating_agents = []
        agent_order = []
        
        if agents.get('analyzer') and clients.get('openai'):
            triage_response = clients['openai'].responses.create(
                input=[{"role": "user", "content": triage_prompt}],
                extra_body={"agent": {"name": agents['analyzer'].name, "type": "agent_reference"}},
            )
            triage_text = triage_response.output_text
            
            # Parse the JSON response
            try:
                if "```json" in triage_text:
                    triage_text = triage_text.split("```json")[1].split("```")[0].strip()
                elif "```" in triage_text:
                    triage_text = triage_text.split("```")[1].split("```")[0].strip()
                
                triage_data = json.loads(triage_text)
                participating_agents = [a.upper() for a in triage_data.get("agents", [])]
                agent_order = [a.upper() for a in triage_data.get("conversation_order", participating_agents)]
                reasoning = triage_data.get("reasoning", "")
                
                add_thinking_step(f"📊 Participating Agents: {', '.join(participating_agents)}")
                add_thinking_step(f"💡 Reasoning: {reasoning}")
                
            except json.JSONDecodeError:
                add_thinking_step("⚠️ Using fallback analysis...")
                user_input_lower = user_input.lower()
                if any(kw in user_input_lower for kw in ['product', 'feature', 'design']):
                    participating_agents.append("PRODUCT")
                if any(kw in user_input_lower for kw in ['manufacturing', 'production', 'inventory']):
                    participating_agents.append("MANUFACTURING")
                if any(kw in user_input_lower for kw in ['cost', 'budget', 'finance']):
                    participating_agents.append("FINANCE")
                agent_order = participating_agents
        else:
            # Fallback
            add_thinking_step("⚠️ Analyzer unavailable, using keyword matching...")
            user_input_lower = user_input.lower()
            if any(kw in user_input_lower for kw in ['product', 'feature', 'design']):
                participating_agents.append("PRODUCT")
            if any(kw in user_input_lower for kw in ['manufacturing', 'production', 'inventory']):
                participating_agents.append("MANUFACTURING")
            if any(kw in user_input_lower for kw in ['cost', 'budget', 'finance']):
                participating_agents.append("FINANCE")
            agent_order = participating_agents
        
        # If no specific agents identified, use analyzer
        if not participating_agents:
            participating_agents = ["ANALYZER"]
            agent_order = ["ANALYZER"]
            add_thinking_step("📊 Analyzer will handle this directly")
        
        # Step 2: Get responses from each agent in order
        for idx, agent_type in enumerate(agent_order):
            add_thinking_step(f"🎯 Getting response from {agent_type} Agent ({idx+1}/{len(agent_order)})...")
            
            # Build context including previous agent responses in this round
            agent_context = f"User Query: {user_input}\n\n"
            if agent_responses:
                agent_context += "Previous Agent Responses in this conversation:\n"
                for prev_response in agent_responses:
                    agent_context += f"\n{prev_response['sender']}: {prev_response['content'][:200]}...\n"
            
            agent_prompt = f"{agent_context}\n\nProvide your specialized perspective on this query. You can reference or build upon what other agents have shared."
            
            if agent_type == "PRODUCT":
                if agents.get('product'):
                    response = get_product_response(agent_prompt, agents['product'], clients.get('product', clients['openai']))
                else:
                    response = f"Based on the product perspective: {user_input}\n\nI can provide insights on product features, design, and specifications."
                agent_responses.append({"sender": "Product Agent", "content": response, "icon": "🔧"})
                add_thinking_step("✅ Product Agent responded")
            
            elif agent_type == "MANUFACTURING":
                if agents.get('manufacturing'):
                    response = get_manufacturing_response(agent_prompt, agents['manufacturing'], clients.get('manufacturing', clients['openai']))
                else:
                    response = f"From a manufacturing standpoint: {user_input}\n\nI can analyze production processes, operations, and supply chain considerations."
                agent_responses.append({"sender": "Manufacturing Agent", "content": response, "icon": "🏭"})
                add_thinking_step("✅ Manufacturing Agent responded")
            
            elif agent_type == "FINANCE":
                if agents.get('finance'):
                    response = get_finance_response(agent_prompt, agents['finance'], clients.get('finance', clients['openai']))
                else:
                    response = f"Looking at the financial aspects: {user_input}\n\nI can provide analysis on costs, budgets, and financial impacts."
                agent_responses.append({"sender": "Finance Agent", "content": response, "icon": "💰"})
                add_thinking_step("✅ Finance Agent responded")
            
            elif agent_type == "ANALYZER":
                if agents.get('analyzer') and clients.get('openai'):
                    response_obj = clients['openai'].responses.create(
                        input=[{"role": "user", "content": agent_prompt}],
                        extra_body={"agent": {"name": agents['analyzer'].name, "type": "agent_reference"}},
                    )
                    response = response_obj.output_text
                else:
                    response = f"Analyzing your query: {user_input}\n\nI can provide comprehensive analysis and coordinate with specialist agents."
                agent_responses.append({"sender": "Analyzer", "content": response, "icon": "📊"})
                add_thinking_step("✅ Analyzer responded")
        
        # Step 3: Optional follow-up round where agents can respond to each other
        if len(agent_responses) > 1:
            add_thinking_step("🔄 Checking if agents want to respond to each other...")
            # Limit to prevent infinite loops - just one follow-up round
            follow_up_responses = []
            
            for agent_resp in agent_responses:
                # Each agent can optionally add a brief follow-up
                agent_name = agent_resp['sender']
                other_responses = "\n".join([f"{r['sender']}: {r['content'][:150]}..." for r in agent_responses if r['sender'] != agent_name])
                
                follow_up_prompt = f"""Other agents have shared their perspectives:
{other_responses}

If you have a brief follow-up comment or want to build on what others said, share it (max 2 sentences). 
If not needed, respond with 'NONE'."""
                
                # For simplicity, only allow follow-ups for configured agents
                if "Product" in agent_name and agents.get('product'):
                    try:
                        follow_up = get_product_response(follow_up_prompt, agents['product'], clients.get('product', clients['openai']))
                        if follow_up and "NONE" not in follow_up.upper() and len(follow_up.strip()) > 10:
                            follow_up_responses.append({"sender": agent_name, "content": follow_up, "icon": agent_resp['icon'], "is_followup": True})
                    except:
                        pass
            
            if follow_up_responses:
                add_thinking_step(f"💬 {len(follow_up_responses)} follow-up comments added")
                agent_responses.extend(follow_up_responses)
        
        thinking_process = "\n\n".join(thinking_steps)
        return thinking_process, agent_responses
        
    except Exception as e:
        add_thinking_step(f"❌ Error: {str(e)}")
        thinking_process = "\n\n".join(thinking_steps)
        return thinking_process, [{"sender": "System", "content": f"Error: {str(e)}", "icon": "⚠️"}]

# Initialize session state for chat messages with new structure
if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "agent",
        "sender": "Analyzer",
        "content": "Welcome to the multi-agent chat! I can coordinate with Product, Manufacturing, and Finance agents to help answer your questions.",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": "📊"
    }]

# Reset chat history button
if st.sidebar.button("Reset chat history"):
    st.session_state.messages = [{
        "role": "agent",
        "sender": "Analyzer",
        "content": "Welcome to the multi-agent chat! I can coordinate with Product, Manufacturing, and Finance agents to help answer your questions.",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": "📊"
    }]
    st.rerun()

# Proposal generation section
st.sidebar.markdown("---")
st.sidebar.subheader("📄 Generate Proposal")
st.sidebar.write("Create a comprehensive proposal document from the conversation.")

if st.sidebar.button("Generate Proposal PDF", type="primary"):
    if len(st.session_state.messages) <= 1:
        st.sidebar.warning("Start a conversation first before generating a proposal!")
    else:
        with st.sidebar:
            with st.spinner("Analyzer is creating your proposal..."):
                proposal_text, error = generate_proposal_summary()
                
                if error:
                    st.error(error)
                elif proposal_text:
                    # Generate PDF
                    pdf_buffer = generate_pdf(proposal_text)
                    
                    # Offer download
                    st.success("✅ Proposal generated successfully!")
                    st.download_button(
                        label="📥 Download Proposal PDF",
                        data=pdf_buffer,
                        file_name=f"proposal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                    
                    # Show preview
                    with st.expander("Preview Proposal Content"):
                        st.markdown(proposal_text)

# Display chat messages in group chat style
for msg in st.session_state.messages:
    sender = msg.get("sender", "Unknown")
    icon = msg.get("icon", "💬")
    timestamp = msg.get("timestamp", "")
    content = msg.get("content", "")
    
    # Determine CSS class based on sender
    if msg["role"] == "user":
        css_class = "user-message"
    elif "Product" in sender:
        css_class = "product-message"
    elif "Manufacturing" in sender:
        css_class = "manufacturing-message"
    elif "Finance" in sender:
        css_class = "finance-message"
    elif "Analyzer" in sender:
        css_class = "analyzer-message"
    else:
        css_class = "chat-message"
    
    # Display message with custom styling
    st.markdown(f"""
    <div class="chat-message {css_class}">
        <div class="sender-name">
            <span>{icon} <strong>{sender}</strong></span>
            <span class="timestamp">{timestamp}</span>
        </div>
        <div class="message-content">{content}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Show thinking process for agent messages if available
    if msg["role"] == "agent" and "thinking" in msg:
        with st.expander("🧠 Thinking Process", expanded=False):
            st.markdown(msg["thinking"])

# Receive user input and generate multi-agent conversation
if prompt := st.chat_input(placeholder="Ask me anything..."):
    current_time = datetime.now().strftime("%I:%M %p")
    
    # Add user message with new structure
    user_message = {
        "role": "user",
        "sender": "User",
        "content": prompt,
        "timestamp": current_time,
        "icon": "👤"
    }
    st.session_state.messages.append(user_message)
    
    # Display user message immediately
    st.markdown(f"""
    <div class="chat-message user-message">
        <div class="sender-name">
            <span>👤 <strong>User</strong></span>
            <span class="timestamp">{current_time}</span>
        </div>
        <div class="message-content">{prompt}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Create a status container for real-time thinking process
    with st.status("🤔 Coordinating agents...", expanded=True) as status:
        thinking_container = st.empty()
        
        # Create placeholders for each agent response (real-time display)
        agent_placeholders = {}
        for agent_name in ["Product Agent", "Manufacturing Agent", "Finance Agent"]:
            agent_placeholders[agent_name] = st.empty()
        
        # Generate multi-agent conversation with real-time updates
        thinking_process, agent_responses = get_multi_agent_conversation(
            prompt, 
            thinking_container, 
            st.session_state.messages,
            agent_placeholders  # Pass placeholders for real-time updates
        )
        
        status.update(label="✅ Agents have responded!", state="complete", expanded=False)
    
    # Add each agent's response to message history
    response_time = datetime.now().strftime("%I:%M %p")
    for agent_resp in agent_responses:
        agent_message = {
            "role": "agent",
            "sender": agent_resp["sender"],
            "content": agent_resp["content"],
            "timestamp": response_time,
            "icon": agent_resp.get("icon", "🤖"),
            "thinking": thinking_process if agent_resp == agent_responses[0] else None  # Only attach thinking to first response
        }
        st.session_state.messages.append(agent_message)
    
    st.rerun()