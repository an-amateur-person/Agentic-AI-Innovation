import streamlit as st
from azure.identity import InteractiveBrowserCredential
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

from retail_agent import (
    initialize_retail_agent, 
    get_retail_response, 
    get_coordinated_response
)
from product_agent import initialize_product_agent, get_product_response
from insurance_agent import initialize_insurance_agent, get_insurance_response

# Load environment variables from .env file
load_dotenv(".env")

# Helper function to get icon (image or emoji fallback)
def get_agent_icon(agent_name):
    """Get base64 encoded image for agent icon or return emoji fallback"""
    import base64
    icon_mapping = {
        'buybuddy': ('buybuddy.png', '🛒'),
        'fridgebuddy': ('fridgebuddy.png', '📦'),
        'insurancebuddy': ('insurancebuddy.png', '🛡️'),
        'customer': (None, '👤')
    }
    
    icon_file, fallback_emoji = icon_mapping.get(agent_name.lower(), (None, '💬'))
    
    if icon_file:
        icon_path = os.path.join(os.path.dirname(__file__), 'assets', icon_file)
        if os.path.exists(icon_path):
            try:
                with open(icon_path, 'rb') as f:
                    img_bytes = f.read()
                img_base64 = base64.b64encode(img_bytes).decode()
                return f'<img src="data:image/png;base64,{img_base64}" class="chat-icon-img" alt="{agent_name}">'
            except:
                return fallback_emoji
    return fallback_emoji

# Webpage configurations
st.set_page_config(page_title="Agentic AI System Interface", page_icon="🛒")

# Define custom CSS for styling
custom_css = """
<style>
/* Title with icon styling */
.title-with-icon {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 1rem;
}

.title-with-icon h1 {
    margin: 0;
    font-size: 2.5rem;
    font-weight: 600;
}

.title-icon {
    width: 60px;
    height: 60px;
    animation: float 3s ease-in-out infinite;
}

.title-icon img {
    width: 100%;
    height: 100%;
    object-fit: contain;
}

.title-icon-emoji {
    font-size: 60px;
    line-height: 60px;
}

@keyframes float {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-10px); }
}

/* Chat message styling */
.chat-message {
    padding: 12px;
    margin: 8px 0;
    border-radius: 10px;
    border-left: 4px solid #ddd;
    color: #FFFFFF;
}

.user-message {
    border-left-color: #2196F3;
}

.retail-message {
    border-left-color: #FF6B35;
}

.product-message {
    border-left-color: #FFC107;
}

.insurance-message {
    border-left-color: #F44336;
}

.sender-name {
    font-weight: bold;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #FFFFFF;
}

.timestamp {
    font-size: 0.75em;
    color: #BDBDBD;
    margin-left: auto;
}

.message-content {
    margin-top: 4px;
    line-height: 1.6;
    color: #E0E0E0;
}

.specialist-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
    margin-left: 8px;
    background-color: #FFF9C4;
    color: #F57F17;
}

/* Chat icon image styling */
.chat-icon-img {
    width: 24px;
    height: 24px;
    object-fit: contain;
    vertical-align: middle;
    margin-right: 4px;
}
</style>
"""

# Apply the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Display title with icon
icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'buybuddy.png')
if os.path.exists(icon_path):
    # Read and encode the image for display
    import base64
    with open(icon_path, 'rb') as f:
        img_bytes = f.read()
    img_base64 = base64.b64encode(img_bytes).decode()
    icon_html = f'<div class="title-icon"><img src="data:image/png;base64,{img_base64}" alt="BuyBuddy"></div>'
else:
    # Fallback to emoji if image not found
    icon_html = '<div class="title-icon title-icon-emoji">🛒</div>'

st.markdown(f'''
<div class="title-with-icon">
    {icon_html}
    <h1>BuyBuddy - Customer Service</h1>
</div>
''', unsafe_allow_html=True)

st.write("Welcome! I'm your BuyBuddy. Ask me anything, and I'll coordinate with specialized teams when needed.")

# Initialize all agents
@st.cache_resource
def initialize_all_agents():
    """Initialize retail agent and specialized agents"""
    agents = {}
    clients = {}
    errors = {}
    
    try:
        # Initialize Retail Agent (primary)
        try:
            retail_agent, retail_client, project_client = initialize_retail_agent()
            agents['retail'] = retail_agent
            clients['retail'] = retail_client
            clients['project'] = project_client
        except Exception as e:
            agents['retail'] = None
            errors['retail'] = str(e)
        
        # Initialize Product Agent (specialist)
        try:
            mfg_agent, mfg_client = initialize_product_agent()
            agents['product'] = mfg_agent
            clients['product'] = mfg_client
        except Exception as e:
            agents['product'] = None
            errors['product'] = str(e)
        
        # Initialize Insurance Agent (specialist)
        try:
            insurance_agent, insurance_client = initialize_insurance_agent()
            agents['insurance'] = insurance_agent
            clients['insurance'] = insurance_client
        except Exception as e:
            agents['insurance'] = None
            errors['insurance'] = str(e)
            
    except Exception as e:
        errors['main'] = str(e)
    
    return agents, clients, errors

agents, clients, init_errors = initialize_all_agents()

# Import state mapping utility
from agents.retail_agent import map_state_to_phase

def determine_current_phase(conversation_history, last_state=None):
    """
    Determine the current phase based on BuyBuddy's state or conversation history.
    
    PHASES:
    1. Customer Intake - Gathering requirements
    2. Inventory Decision - Checking internal stock
    3. Product Agreement - Validating product selection
    4. Insurance - Offering protection plans
    5. Final Consolidation - Generating quotation
    
    Args:
        conversation_history: Previous messages
        last_state: Parsed state from BuyBuddy's last response
    
    Returns: int (1-5)
    """
    # Prefer using BuyBuddy's actual state if available
    if last_state:
        return map_state_to_phase(last_state)
    
    # Fallback to keyword-based detection
    if not conversation_history or len(conversation_history) <= 1:
        return 1  # Starting phase
    
    # Analyze last few messages for phase indicators
    recent_messages = conversation_history[-5:] if len(conversation_history) >= 5 else conversation_history
    conversation_text = " ".join([msg.get("content", "").lower() for msg in recent_messages])
    
    # Phase 5: Final consolidation keywords
    if any(kw in conversation_text for kw in ['quotation', 'final price', 'ready to checkout', 'confirm order', 'total cost']):
        return 5
    
    # Phase 4: Insurance keywords
    if any(kw in conversation_text for kw in ['insurance', 'warranty', 'protection plan', 'coverage', 'ergo']):
        return 4
    
    # Phase 3: Product agreement keywords
    if any(kw in conversation_text for kw in ['confirm', 'agreed', 'accept', 'this model', 'go with']):
        return 3
    
    # Phase 2: Inventory/product search keywords
    if any(kw in conversation_text for kw in ['product', 'fridge', 'looking for', 'need', 'stock', 'available', 'liebherr']):
        return 2
    
    # Default: Phase 1 (intake)
    return 1

# Initialize phase tracking and iteration counters in session state
if "current_phase" not in st.session_state:
    st.session_state.current_phase = 1

if "buybuddy_state" not in st.session_state:
    st.session_state.buybuddy_state = None

if "iteration_counts" not in st.session_state:
    st.session_state.iteration_counts = {
        'customer_clarifications': 0,
        'product_agent_calls': 0,
        'insurance_agent_calls': 0
    }

if "inventory_checked_once" not in st.session_state:
    st.session_state.inventory_checked_once = False

# Display initialization status in sidebar
with st.sidebar:
    # Phase Tracker - Compact view
    st.subheader("📋 Progress")
    
    # Update current phase based on BuyBuddy state or conversation
    current_phase = determine_current_phase(
        st.session_state.get('messages', []),
        st.session_state.get('buybuddy_state')
    )
    st.session_state.current_phase = current_phase
    
    phases = [
        (1, "Intake"),
        (2, "Inventory"),
        (3, "Agreement"),
        (4, "Insurance"),
        (5, "Quotation")
    ]
    
    # Compact phase display
    phase_status = []
    for num, title in phases:
        if num < current_phase:
            phase_status.append(f"✅ {title}")
        elif num == current_phase:
            phase_status.append(f"▶️ **{title}**")
        else:
            phase_status.append(f"⏸️ {title}")
    
    st.markdown(" → ".join(phase_status))
    
    # Show iteration counts (for debugging/transparency)
    with st.expander("📊 Iteration Stats", expanded=False):
        counts = st.session_state.iteration_counts
        st.metric("Customer Q&A", f"{counts['customer_clarifications']}/5")
        st.metric("FridgeBuddy Calls", f"{counts['product_agent_calls']}/3")
        st.metric("InsuranceBuddy Calls", f"{counts['insurance_agent_calls']}/3")
    
    st.markdown("---")
    
    # Agent Status - Compact
    st.subheader("🤖 Agents")
    if 'main' not in init_errors:
        agent_icons = []
        if agents.get('retail'):
            agent_icons.append("🛒 BuyBuddy")
        if agents.get('product'):
            agent_icons.append("📦 FridgeBuddy")
        if agents.get('insurance'):
            agent_icons.append("🛡️ InsuranceBuddy")
        
        if agent_icons:
            st.success(" | ".join(agent_icons))
        else:
            st.warning("No agents configured")
    else:
        st.error("Initialization failed")

def generate_quotation():
    """Generate a product quotation after all agents collaborate to finalize the offer"""
    if len(st.session_state.messages) <= 1:
        return None, "No conversation to generate quotation from. Start chatting with BuyBuddy first!"
    
    # Build conversation context
    conversation_text = ""
    for msg in st.session_state.messages:
        sender = msg.get("sender", "Unknown")
        content = msg.get("content", "")
        conversation_text += f"{sender}: {content}\n\n"
    
    # Create prompt for retail agent to generate quotation after collaboration
    quotation_prompt = f"""Based on the collaboration between BuyBuddy, FridgeBuddy, and InsuranceBuddy agents in the conversation below, create a formal product quotation for the customer.

The quotation should include:
1. Quotation Summary
2. Customer Requirements
3. Product Specifications & Offerings
4. Product Details (production timeline, capacity, delivery)
5. Pricing & Financial Terms
6. Terms & Conditions
7. Validity Period

Conversation History:
{conversation_text}

Generate a comprehensive, professional product quotation document that consolidates inputs from all three agents."""
    
    try:
        if agents.get('retail') and clients.get('retail'):
            response = clients['retail'].responses.create(
                input=[{"role": "user", "content": quotation_prompt}],
                extra_body={"agent": {"name": agents['retail'].name, "type": "agent_reference"}},
            )
            quotation_text = response.output_text
            return quotation_text, None
        else:
            return None, "BuyBuddy is not available to generate quotation."
    except Exception as e:
        return None, f"Error generating quotation: {str(e)}"

def get_pdf_buffer(quotation_text):
    """Generate a PDF document from the quotation text"""
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
    title = Paragraph("Product Quotation", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    # Add date
    date_text = f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
    elements.append(Paragraph(date_text, styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Process the quotation text
    paragraphs = quotation_text.split('\n\n')
    
    for para in paragraphs:
        if para.strip():
            # Check if it's a heading
            if any(keyword in para for keyword in ['Quotation Summary', 'Customer Requirements', 
                                                    'Product Specifications', 'Product Details',
                                                    'Pricing', 'Financial Terms', 'Terms & Conditions', 'Validity']):
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

def handle_customer_query(user_input, thinking_container):
    """
    Handle customer query through BuyBuddy
    BuyBuddy coordinates with specialists when needed
    """
    thinking_steps = []
    
    def add_thinking_step(step):
        thinking_steps.append(step)
        with thinking_container:
            st.markdown("\n\n".join(thinking_steps))
    
    add_thinking_step("🛒 BuyBuddy is analyzing your query...")
    
    # Check iteration limits
    if st.session_state.iteration_counts['customer_clarifications'] >= 5:
        add_thinking_step("⚠️ Max clarifications reached - proposing best match")
    
    try:
        if agents.get('retail'):
            # Get coordinated response - retail agent handles routing decisions
            result = get_coordinated_response(
                user_input,
                agents['retail'],
                clients['retail'],
                (agents.get('product'), clients.get('product')),
                (agents.get('insurance'), clients.get('insurance')),
                st.session_state.messages,
                st.session_state.iteration_counts  # Pass iteration counters
            )
            
            # Store BuyBuddy's state
            st.session_state.buybuddy_state = result.get('state')
            
            # Increment customer clarification counter
            st.session_state.iteration_counts['customer_clarifications'] += 1
            
            # Show thinking steps based on what retail agent decided
            if result.get('inventory_check'):
                add_thinking_step("📦 Checked internal MediaMarktSaturn inventory")
            
            if result.get('specialist_responses'):
                specialists = [s['agent'] for s in result['specialist_responses']]
                add_thinking_step(f"🔍 Consulted with: {', '.join(specialists)}")
            
            add_thinking_step("💬 Response ready!")
            
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': result['main_response'],
                'inventory_check': result.get('inventory_check'),
                'specialist_responses': result['specialist_responses']
            }
        else:
            add_thinking_step("⚠️ BuyBuddy not fully configured, using demo mode")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': f"BuyBuddy (Demo): Thank you for your query about '{user_input}'. I can help you with information, specifications, and coordinate with our product and insurance teams as needed.",
                'inventory_check': None,
                'specialist_responses': []
            }
    except Exception as e:
        add_thinking_step(f"❌ Error: {str(e)}")
        return {
            'thinking': "\n\n".join(thinking_steps),
            'main_response': f"I apologize, but I encountered an error: {str(e)}",
            'inventory_check': None,
            'specialist_responses': []
        }

# Initialize session state for chat messages
if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "agent",
        "sender": "BuyBuddy",
        "content": "Hello! I'm your BuyBuddy. I can help you with information, specifications, features, and more. I can also coordinate with our FridgeBuddy and InsuranceBuddy teams when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": get_agent_icon('buybuddy')
    }]

# Reset chat history button
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.messages = [{
        "role": "agent",
        "sender": "BuyBuddy",
        "content": "Hello! I'm your BuyBuddy. I can help you with information, specifications, features, and more. I can also coordinate with our FridgeBuddy and InsuranceBuddy teams when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": get_agent_icon('buybuddy')
    }]
    # Reset all tracking flags
    st.session_state.inventory_checked_once = False
    st.session_state.iteration_counts = {
        'customer_clarifications': 0,
        'product_agent_calls': 0,
        'insurance_agent_calls': 0
    }
    st.session_state.buybuddy_state = None
    st.session_state.current_phase = 1
    st.rerun()

# Show quotation section only in final phase (Phase 5)
if st.session_state.current_phase >= 5:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💰 Final Proposal")
    if st.sidebar.button("📄 Generate Proposal", type="primary", use_container_width=True):
        if len(st.session_state.messages) <= 1:
            st.sidebar.warning("Start a conversation first!")
        else:
            with st.sidebar:
                with st.spinner("Finalizing proposal..."):
                    quotation_text, error = generate_quotation()
                    
                    if error:
                        st.error(error)
                    elif quotation_text:
                        # Generate PDF
                        pdf_buffer = get_pdf_buffer(quotation_text)
                        
                        # Offer download
                        st.success("✅ Ready!")
                        st.download_button(
                            label="📥 Download PDF",
                            data=pdf_buffer,
                            file_name=f"proposal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                        
                        # Show preview
                        with st.expander("Preview"):
                            st.markdown(quotation_text)

# Display chat messages
for msg in st.session_state.messages:
    sender = msg.get("sender", "Unknown")
    icon = msg.get("icon", "💬")
    timestamp = msg.get("timestamp", "")
    content = msg.get("content", "")
    
    # Determine CSS class based on sender
    if msg["role"] == "user":
        css_class = "user-message"
    elif "BuyBuddy" in sender:
        css_class = "retail-message"
    elif "FridgeBuddy" in sender:
        css_class = "product-message"
    elif "InsuranceBuddy" in sender:
        css_class = "insurance-message"
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
        with st.expander("🧠 Agent Coordination Process", expanded=False):
            st.markdown(msg["thinking"])
    
    # Show internal inventory check results if available (only once per session)
    if msg.get("inventory_check") and msg["inventory_check"].get("checked"):
        # Only show if we haven't shown it before
        if not st.session_state.inventory_checked_once:
            st.session_state.inventory_checked_once = True
            inventory = msg["inventory_check"]
            st.markdown(f"""
        <div class="chat-message retail-message" style="border-left-color: #FF9800; background-color: rgba(255, 152, 0, 0.1);">
            <div class="sender-name">
                <span>📦 <strong>Internal Inventory Check</strong></span>
                <span class="specialist-badge" style="background-color: #FFE0B2; color: #E65100;">MediaMarktSaturn</span>
            </div>
            <div class="message-content">
                <strong>{inventory.get('summary', 'Inventory check completed')}</strong><br/>
                {inventory.get('details', 'Checked our internal database for available products.')}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Show specialist responses if available
    if msg.get("specialist_responses"):
        for specialist in msg["specialist_responses"]:
            st.markdown(f"""
            <div class="chat-message {specialist.get('css_class', 'chat-message')}">
                <div class="sender-name">
                    <span>{specialist['icon']} <strong>{specialist['agent']}</strong></span>
                    <span class="specialist-badge">Specialist Input</span>
                </div>
                <div class="message-content">{specialist['response']}</div>
            </div>
            """, unsafe_allow_html=True)

# Receive user input and generate response
if prompt := st.chat_input(placeholder="Ask me anything..."):
    current_time = datetime.now().strftime("%I:%M %p")
    
    # Add user message
    user_message = {
        "role": "user",
        "sender": "Customer",
        "content": prompt,
        "timestamp": current_time,
        "icon": get_agent_icon('customer')
    }
    st.session_state.messages.append(user_message)
    
    # Display user message immediately
    st.markdown(f"""
    <div class="chat-message user-message">
        <div class="sender-name">
            <span>{user_message['icon']} <strong>Customer</strong></span>
            <span class="timestamp">{current_time}</span>
        </div>
        <div class="message-content">{prompt}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Get response from BuyBuddy
    with st.status("🛒 BuyBuddy is working on your request...", expanded=True) as status:
        thinking_container = st.empty()
        
        # Handle the customer query
        result = handle_customer_query(prompt, thinking_container)
        
        status.update(label="✅ Response ready!", state="complete", expanded=False)
    
    # Add BuyBuddy's response to message history
    response_time = datetime.now().strftime("%I:%M %p")
    agent_message = {
        "role": "agent",
        "sender": "BuyBuddy",
        "content": result['main_response'],
        "timestamp": response_time,
        "icon": get_agent_icon('buybuddy'),
        "thinking": result['thinking'],
        "inventory_check": result.get('inventory_check'),
        "specialist_responses": result.get('specialist_responses', [])
    }
    st.session_state.messages.append(agent_message)
    
    st.rerun()
