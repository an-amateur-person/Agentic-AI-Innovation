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

from retail_agent import (
    initialize_retail_agent, 
    get_retail_response, 
    get_coordinated_response,
    analyze_query_needs
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
        'buybuddy': ('buybuddy_icon.png', '🛒'),
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

# Display initialization status in sidebar
with st.sidebar:
    st.subheader("🤖 Agent Status")
    if 'main' in init_errors:
        st.error(f"❌ Initialization failed: {init_errors['main']}")
    else:
        # Retail Agent status
        if agents.get('retail'):
            st.success("✅ BuyBuddy (Primary)")
        else:
            error_msg = init_errors.get('retail', "Not configured")
            st.error(f"❌ BuyBuddy: {error_msg}")
        
        st.markdown("**Specialist Agents:**")
        # Specialist agents
        for agent_name in ['product', 'insurance']:
            if agent_name in agents and agents[agent_name]:
                display_name = "FridgeBuddy" if agent_name == 'product' else "InsuranceBuddy"
                st.success(f"✅ {display_name}")
            else:
                error_msg = init_errors.get(agent_name, "Not configured")
                display_name = "FridgeBuddy" if agent_name == 'product' else "InsuranceBuddy"
                st.warning(f"⚠️ {display_name}: {error_msg}")

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
    
    # Analyze what specialists might be needed
    analysis = analyze_query_needs(user_input)
    
    if analysis['needs_manufacturing'] or analysis['needs_insurance']:
        specialist_list = []
        if analysis['needs_manufacturing']:
            specialist_list.append("FridgeBuddy")
        if analysis['needs_insurance']:
            specialist_list.append("InsuranceBuddy")
        add_thinking_step(f"🔍 Will consult with: {', '.join(specialist_list)} specialist(s)")
    
    # Get coordinated response
    add_thinking_step("💬 Preparing comprehensive response...")
    
    try:
        if agents.get('retail'):
            # Get coordinated response
            result = get_coordinated_response(
                user_input,
                agents['retail'],
                clients['retail'],
                (agents.get('product'), clients.get('product')) if analysis['needs_manufacturing'] else None,
                (agents.get('insurance'), clients.get('insurance')) if analysis['needs_insurance'] else None,
                st.session_state.messages
            )
            
            add_thinking_step("✅ Response ready!")
            
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': result['main_response'],
                'specialist_responses': result['specialist_responses']
            }
        else:
            add_thinking_step("⚠️ BuyBuddy not fully configured, using demo mode")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': f"BuyBuddy (Demo): Thank you for your query about '{user_input}'. I can help you with information, specifications, and coordinate with our product and insurance teams as needed.",
                'specialist_responses': []
            }
    except Exception as e:
        add_thinking_step(f"❌ Error: {str(e)}")
        return {
            'thinking': "\n\n".join(thinking_steps),
            'main_response': f"I apologize, but I encountered an error: {str(e)}",
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
    st.rerun()

# Quotation generation section
st.sidebar.markdown("---")
st.sidebar.subheader("💰 Generate Quotation")
st.sidebar.write("Generate a product quotation based on collaboration between BuyBuddy, FridgeBuddy, and InsuranceBuddy.")

if st.sidebar.button("Generate Quotation PDF", type="primary"):
    if len(st.session_state.messages) <= 1:
        st.sidebar.warning("Start a conversation first before generating a quotation!")
    else:
        with st.sidebar:
            with st.spinner("Agents are finalizing your quotation..."):
                quotation_text, error = generate_quotation()
                
                if error:
                    st.error(error)
                elif quotation_text:
                    # Generate PDF
                    pdf_buffer = get_pdf_buffer(quotation_text)
                    
                    # Offer download
                    st.success("✅ Quotation generated successfully!")
                    st.download_button(
                        label="📥 Download Quotation PDF",
                        data=pdf_buffer,
                        file_name=f"quotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                    
                    # Show preview
                    with st.expander("Preview Quotation"):
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
        "specialist_responses": result.get('specialist_responses', [])
    }
    st.session_state.messages.append(agent_message)
    
    st.rerun()
