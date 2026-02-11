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

from product_agent import (
    initialize_product_agent, 
    get_product_response, 
    get_coordinated_response,
    analyze_query_needs
)
from manufacturing_agent import initialize_manufacturing_agent, get_manufacturing_response
from finance_agent import initialize_finance_agent, get_finance_response

# Load environment variables from .env file
load_dotenv(".env")

# Webpage configurations
st.set_page_config(page_title="Product Agent Interface", page_icon="🤖")
st.title("🤖 Product Agent - Customer Service")
st.write("Welcome! I'm your Product Agent. Ask me anything about products, and I'll coordinate with specialized teams when needed.")

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

/* Chat message styling */
.chat-message {
    padding: 12px;
    margin: 8px 0;
    border-radius: 10px;
    border-left: 4px solid #ddd;
}

.user-message {
    border-left-color: #2196F3;
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
    line-height: 1.6;
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
</style>
"""

# Apply the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Add floating bot icon
st.markdown('<div class="bot-icon">🤖</div>', unsafe_allow_html=True)

# Initialize all agents
@st.cache_resource
def initialize_all_agents():
    """Initialize product agent and specialized agents"""
    agents = {}
    clients = {}
    errors = {}
    
    try:
        # Initialize Product Agent (primary)
        try:
            product_agent, product_client, project_client = initialize_product_agent()
            agents['product'] = product_agent
            clients['product'] = product_client
            clients['project'] = project_client
        except Exception as e:
            agents['product'] = None
            errors['product'] = str(e)
        
        # Initialize Manufacturing Agent (specialist)
        try:
            mfg_agent, mfg_client = initialize_manufacturing_agent()
            agents['manufacturing'] = mfg_agent
            clients['manufacturing'] = mfg_client
        except Exception as e:
            agents['manufacturing'] = None
            errors['manufacturing'] = str(e)
        
        # Initialize Finance Agent (specialist)
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
        st.error(f"❌ Initialization failed: {init_errors['main']}")
    else:
        # Product Agent status
        if agents.get('product'):
            st.success("✅ Product Agent (Primary)")
        else:
            error_msg = init_errors.get('product', "Not configured")
            st.error(f"❌ Product Agent: {error_msg}")
        
        st.markdown("**Specialist Agents:**")
        # Specialist agents
        for agent_name in ['manufacturing', 'finance']:
            if agent_name in agents and agents[agent_name]:
                st.success(f"✅ {agent_name.capitalize()}")
            else:
                error_msg = init_errors.get(agent_name, "Not configured")
                st.warning(f"⚠️ {agent_name.capitalize()}: {error_msg}")

def generate_proposal_summary():
    """Generate a comprehensive proposal summary from the conversation history"""
    if len(st.session_state.messages) <= 1:
        return None, "No conversation to summarize yet. Start chatting with the Product Agent first!"
    
    # Build conversation context
    conversation_text = ""
    for msg in st.session_state.messages:
        sender = msg.get("sender", "Unknown")
        content = msg.get("content", "")
        conversation_text += f"{sender}: {content}\n\n"
    
    # Create prompt for product agent to generate proposal
    proposal_prompt = f"""Based on the following conversation with the customer, create a comprehensive draft proposal document.

The proposal should include:
1. Executive Summary
2. Customer Requirements and Discussion Points
3. Product Recommendations
4. Manufacturing Considerations (if applicable)
5. Financial Overview (if applicable)
6. Recommendations and Next Steps
7. Conclusion

Conversation History:
{conversation_text}

Generate a well-structured, professional proposal document."""
    
    try:
        if agents.get('product') and clients.get('product'):
            response = clients['product'].responses.create(
                input=[{"role": "user", "content": proposal_prompt}],
                extra_body={"agent": {"name": agents['product'].name, "type": "agent_reference"}},
            )
            proposal_text = response.output_text
            return proposal_text, None
        else:
            return None, "Product agent is not available to generate proposal."
    except Exception as e:
        return None, f"Error generating proposal: {str(e)}"

def get_pdf_buffer(proposal_text):
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
    title = Paragraph("Customer Proposal - Product Agent", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    # Add date
    date_text = f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
    elements.append(Paragraph(date_text, styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Process the proposal text
    paragraphs = proposal_text.split('\n\n')
    
    for para in paragraphs:
        if para.strip():
            # Check if it's a heading
            if any(keyword in para for keyword in ['Executive Summary', 'Customer Requirements', 
                                                    'Product Recommendations', 'Manufacturing',
                                                    'Financial', 'Recommendations', 'Conclusion', 'Next Steps']):
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
    Handle customer query through Product Agent
    Product Agent coordinates with specialists when needed
    """
    thinking_steps = []
    
    def add_thinking_step(step):
        thinking_steps.append(step)
        with thinking_container:
            st.markdown("\n\n".join(thinking_steps))
    
    add_thinking_step("🤖 Product Agent is analyzing your query...")
    
    # Analyze what specialists might be needed
    analysis = analyze_query_needs(user_input)
    
    if analysis['needs_manufacturing'] or analysis['needs_finance']:
        specialist_list = []
        if analysis['needs_manufacturing']:
            specialist_list.append("Manufacturing")
        if analysis['needs_finance']:
            specialist_list.append("Finance")
        add_thinking_step(f"🔍 Will consult with: {', '.join(specialist_list)} specialist(s)")
    
    # Get coordinated response
    add_thinking_step("💬 Preparing comprehensive response...")
    
    try:
        if agents.get('product'):
            # Get coordinated response
            result = get_coordinated_response(
                user_input,
                agents['product'],
                clients['product'],
                (agents.get('manufacturing'), clients.get('manufacturing')) if analysis['needs_manufacturing'] else None,
                (agents.get('finance'), clients.get('finance')) if analysis['needs_finance'] else None,
                st.session_state.messages
            )
            
            add_thinking_step("✅ Response ready!")
            
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': result['main_response'],
                'specialist_responses': result['specialist_responses']
            }
        else:
            add_thinking_step("⚠️ Product Agent not fully configured, using demo mode")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': f"Product Agent (Demo): Thank you for your query about '{user_input}'. I can help you with product information, specifications, and coordinate with our manufacturing and finance teams as needed.",
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
        "sender": "Product Agent",
        "content": "Hello! I'm your Product Agent. I can help you with product information, specifications, features, and more. I can also coordinate with our Manufacturing and Finance teams when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": "🤖"
    }]

# Reset chat history button
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.messages = [{
        "role": "agent",
        "sender": "Product Agent",
        "content": "Hello! I'm your Product Agent. I can help you with product information, specifications, features, and more. I can also coordinate with our Manufacturing and Finance teams when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": "🤖"
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
            with st.spinner("Product Agent is creating your proposal..."):
                proposal_text, error = generate_proposal_summary()
                
                if error:
                    st.error(error)
                elif proposal_text:
                    # Generate PDF
                    pdf_buffer = get_pdf_buffer(proposal_text)
                    
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

# Display chat messages
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
if prompt := st.chat_input(placeholder="Ask me anything about products..."):
    current_time = datetime.now().strftime("%I:%M %p")
    
    # Add user message
    user_message = {
        "role": "user",
        "sender": "Customer",
        "content": prompt,
        "timestamp": current_time,
        "icon": "👤"
    }
    st.session_state.messages.append(user_message)
    
    # Display user message immediately
    st.markdown(f"""
    <div class="chat-message user-message">
        <div class="sender-name">
            <span>👤 <strong>Customer</strong></span>
            <span class="timestamp">{current_time}</span>
        </div>
        <div class="message-content">{prompt}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Get response from Product Agent
    with st.status("🤖 Product Agent is working on your request...", expanded=True) as status:
        thinking_container = st.empty()
        
        # Handle the customer query
        result = handle_customer_query(prompt, thinking_container)
        
        status.update(label="✅ Response ready!", state="complete", expanded=False)
    
    # Add Product Agent's response to message history
    response_time = datetime.now().strftime("%I:%M %p")
    agent_message = {
        "role": "agent",
        "sender": "Product Agent",
        "content": result['main_response'],
        "timestamp": response_time,
        "icon": "🤖",
        "thinking": result['thinking'],
        "specialist_responses": result.get('specialist_responses', [])
    }
    st.session_state.messages.append(agent_message)
    
    st.rerun()
