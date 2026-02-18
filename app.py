import streamlit as st
import os
import html
import re
from dotenv import load_dotenv
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER

from agents.retail_agent import initialize_customer_facing_agent, collect_customer_input_packet
from agents.retail_orchestrator_agent import initialize_orchestrator_agent, orchestrate_customer_packet
from agents.utilities import map_state_to_phase
from agents.product_agent import initialize_product_agent
from agents.insurance_agent import initialize_insurance_agent

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

IS_APP_SERVICE = bool(os.getenv("WEBSITE_SITE_NAME") or os.getenv("WEBSITE_INSTANCE_ID"))

REQUIRED_ENV_VARS = [
    "AZURE_AIPROJECT_ENDPOINT",
    "AZURE_TENANT_ID",
    "AGENT_RETAIL",
    "AGENT_ORCHESTRATOR",
    "AGENT_PRODUCT",
    "AGENT_INSURANCE",
]


def get_missing_required_env_vars():
    return [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]


def _extract_inventory_structured_info(details_text):
    details = str(details_text or "")
    details_lower = details.lower()

    brands = []
    for brand in ["Bosch", "Siemens", "Neff", "Constructa", "Liebherr"]:
        if brand.lower() in details_lower:
            brands.append(brand)

    model_matches = re.findall(
        r"\b(Bosch|Siemens|Neff|Constructa|Liebherr)\s+([A-Za-z]{2,8}[A-Za-z0-9/-]{2,})\b",
        details,
        re.IGNORECASE,
    )
    model_candidates = []
    for brand, model in model_matches:
        candidate = f"{brand.title()} {model.upper()}"
        if candidate not in model_candidates:
            model_candidates.append(candidate)

    raw_segments = [seg.strip(" •-\n\t") for seg in re.split(r"\n|;", details) if seg.strip()]
    parsed_model_rows = []
    for segment in raw_segments:
        if not re.search(r"\b(bosch|siemens|neff|constructa|liebherr)\b", segment, re.IGNORECASE):
            continue

        model_match = re.search(
            r"\b(Bosch|Siemens|Neff|Constructa|Liebherr)\s+([A-Za-z]{2,8}[A-Za-z0-9/-]{2,})\b",
            segment,
            re.IGNORECASE,
        )
        if not model_match:
            continue

        brand = model_match.group(1).title()
        model = model_match.group(2).upper()

        dimension_match = re.search(
            r"(\d{2,3}(?:[\.,]\d)?\s*[x×]\s*\d{2,3}(?:[\.,]\d)?\s*[x×]\s*\d{2,3}(?:[\.,]\d)?\s*cm)",
            segment,
            re.IGNORECASE,
        )
        niche_match = re.search(r"(niche\s*:?\s*\d{2,3}(?:[\.,]\d)?\s*cm)", segment, re.IGNORECASE)
        capacity_match = re.search(r"(\d{2,3}\s*l)\b", segment, re.IGNORECASE)
        energy_match = re.search(r"\b([A-F])\b\s*(?:energy|class|label)?", segment, re.IGNORECASE)
        noise_match = re.search(r"(\d{2}\s*dB\(?A?\)?)", segment, re.IGNORECASE)
        price_match = re.search(r"((?:~|ca\.?\s*)?\d{3,4}(?:[\.,]\d{2})?\s*€)", segment, re.IGNORECASE)

        parsed_model_rows.append(
            {
                "model_name": f"{brand} {model}",
                "dimensions": dimension_match.group(1) if dimension_match else None,
                "niche": niche_match.group(1) if niche_match else None,
                "capacity": capacity_match.group(1) if capacity_match else None,
                "energy_class": energy_match.group(1).upper() if energy_match else None,
                "noise": noise_match.group(1) if noise_match else None,
                "price": price_match.group(1) if price_match else None,
            }
        )

    unique_rows = []
    seen_models = set()
    for row in parsed_model_rows:
        model_key = row.get("model_name")
        if not model_key or model_key in seen_models:
            continue
        seen_models.add(model_key)
        unique_rows.append(row)

    price_band = None
    price_patterns = [
        r"\b\d{3,4}\s*[–-]\s*\d{3,4}\s*€",
        r"~\s*\d{3,4}\s*€",
        r"\b\d{3,4}\s*€\b",
    ]
    for pattern in price_patterns:
        match = re.search(pattern, details)
        if match:
            price_band = match.group(0)
            break

    niche_match = re.search(r"(?:height|heights?|niche heights?)\s*(?:around|roughly)?\s*([\d\s~–\-]{3,20}cm)", details_lower)
    niche_range = niche_match.group(1) if niche_match else None

    capacity_match = re.search(r"(\d{2,3}\s*[–-]\s*\d{2,3}\s*l)", details_lower)
    capacity_range = capacity_match.group(1) if capacity_match else None

    noise_match = re.search(r"(\d{2}\s*[–-]\s*\d{2}\s*dB\(?a?\)?)", details, re.IGNORECASE)
    noise_range = noise_match.group(1) if noise_match else None

    energy_match = re.search(r"energy\s*(?:class|classes|labels?)\s*\(?\s*([A-F]\s*[–-]\s*[A-F]|[A-F])", details, re.IGNORECASE)
    energy_range = energy_match.group(1).replace(" ", "") if energy_match else None

    return {
        "brands": brands,
        "model_candidates": model_candidates,
        "parsed_model_rows": unique_rows,
        "price_band": price_band,
        "niche_range": niche_range,
        "capacity_range": capacity_range,
        "noise_range": noise_range,
        "energy_range": energy_range,
    }

# Helper function to get icon (image or emoji fallback)
def get_agent_icon(agent_name):
    """Get base64 encoded image for agent icon or return emoji fallback"""
    import base64
    icon_mapping = {
        'retail_agent': ('buybuddy.png', '🛒'),
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
    border-left: none;
    border-right: 4px solid #2196F3;
    margin-left: auto;
    margin-right: 0;
    max-width: 80%;
    text-align: right;
}

.user-message .sender-name {
    justify-content: flex-end;
}

.user-message .timestamp {
    margin-left: 8px;
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

.system-message {
    border-left-color: #9E9E9E;
    background-color: rgba(158, 158, 158, 0.08);
    opacity: 0.82;
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
    <h1>BuyBuddy - Your Personal Customer Service</h1>
</div>
''', unsafe_allow_html=True)

st.write("Welcome! I'm BuyBuddy. Ask me anything, and I'll coordinate with specialized teams when needed.")

# Initialize all agents
@st.cache_resource
def initialize_all_agents():
    """Initialize customer-facing retail_agent and specialized agents"""
    agents = {}
    clients = {}
    errors = {}
    
    try:
        # Initialize Customer-facing retail_agent
        try:
            customer_agent, customer_client, project_client = initialize_customer_facing_agent()
            agents['customer'] = customer_agent
            clients['customer'] = customer_client
            clients['project'] = project_client
            if customer_agent is None:
                errors['customer'] = "Agent not found or inaccessible. Verify AGENT_RETAIL and Azure permissions."
        except Exception as e:
            agents['customer'] = None
            errors['customer'] = str(e)

        # Initialize Backend Orchestrator retail_agent
        try:
            orchestrator_agent, orchestrator_client = initialize_orchestrator_agent(clients.get('project'))
            agents['orchestrator'] = orchestrator_agent
            clients['orchestrator'] = orchestrator_client
            if orchestrator_agent is None:
                errors['orchestrator'] = "Agent not found or inaccessible. Verify AGENT_ORCHESTRATOR and Azure permissions."
        except Exception as e:
            agents['orchestrator'] = None
            errors['orchestrator'] = str(e)
        
        # Initialize Product Agent (specialist)
        try:
            mfg_agent, mfg_client = initialize_product_agent()
            agents['product'] = mfg_agent
            clients['product'] = mfg_client
            if mfg_agent is None:
                errors['product'] = "Agent not found or inaccessible. Verify AGENT_PRODUCT and Azure permissions."
        except Exception as e:
            agents['product'] = None
            errors['product'] = str(e)
        
        # Initialize Insurance Agent (specialist)
        try:
            insurance_agent, insurance_client = initialize_insurance_agent()
            agents['insurance'] = insurance_agent
            clients['insurance'] = insurance_client
            if insurance_agent is None:
                errors['insurance'] = "Agent not found or inaccessible. Verify AGENT_INSURANCE and Azure permissions."
        except Exception as e:
            agents['insurance'] = None
            errors['insurance'] = str(e)
            
    except Exception as e:
        errors['main'] = str(e)
    
    return agents, clients, errors

def get_agent_runtime(force_initialize=False):
    if "agent_runtime" not in st.session_state:
        st.session_state.agent_runtime = {
            "agents": {},
            "clients": {},
            "errors": {},
            "initialized": False,
        }

    runtime = st.session_state.agent_runtime
    missing_env_vars = get_missing_required_env_vars()

    if missing_env_vars:
        runtime["errors"] = {
            "env": "Missing required environment variables: " + ", ".join(missing_env_vars)
        }
        runtime["initialized"] = False
        return runtime["agents"], runtime["clients"], runtime["errors"], runtime["initialized"]

    should_initialize = force_initialize or (not runtime["initialized"] and not IS_APP_SERVICE)

    if should_initialize:
        agents_local, clients_local, errors_local = initialize_all_agents()
        runtime["agents"] = agents_local
        runtime["clients"] = clients_local
        runtime["errors"] = errors_local
        runtime["initialized"] = True

    return runtime["agents"], runtime["clients"], runtime["errors"], runtime["initialized"]


agents, clients, init_errors, agents_initialized = get_agent_runtime()

def determine_current_phase(conversation_history, last_state=None):
    """
    Determine the current phase based on retail_agent state or conversation history.
    
    PHASES:
    1. Customer Intake - Gathering requirements
    2. Inventory Decision - Checking internal stock
    3. Product Agreement - Validating product selection
    4. Insurance - Offering protection plans
    5. Final Consolidation - Generating quotation
    
    Args:
        conversation_history: Previous messages
        last_state: Parsed state from retail_agent last response
    
    Returns: int (1-5)
    """
    # Prefer using retail_agent's actual state if available
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

if "retail_state" not in st.session_state:
    st.session_state.retail_state = None

if "iteration_counts" not in st.session_state:
    st.session_state.iteration_counts = {
        'customer_clarifications': 0,
        'product_agent_calls': 0,
        'insurance_agent_calls': 0
    }

# Display initialization status in sidebar
with st.sidebar:
    # Phase Tracker - Compact view
    st.subheader("📋 Progress")
    
    # Update current phase based on retail_agent state or conversation
    current_phase = determine_current_phase(
        st.session_state.get('messages', []),
        st.session_state.get('retail_state')
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
    
    st.markdown("---")
    
    # Agent Status - Compact
    st.subheader("🤖 Agents")

    missing_env_vars = get_missing_required_env_vars()
    if missing_env_vars:
        st.error("Missing App Settings: " + ", ".join(missing_env_vars))

    if not agents_initialized:
        st.info("Agents will initialize on first request.")
    elif 'main' not in init_errors:
        agent_icons = []
        if agents.get('customer'):
            agent_icons.append("🛒 BuyBuddy (Customer)")
        if agents.get('orchestrator'):
            agent_icons.append("⚙️ BuyBuddy (Orchestrator)")
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
    global agents, clients, init_errors, agents_initialized

    missing_env_vars = get_missing_required_env_vars()
    if missing_env_vars:
        return None, "Missing required App Settings: " + ", ".join(missing_env_vars)

    if not agents_initialized:
        agents, clients, init_errors, agents_initialized = get_agent_runtime(force_initialize=True)

    if len(st.session_state.messages) <= 1:
        return None, "No conversation to generate quotation from. Start chatting with BuyBuddy first!"
    
    # Build conversation context
    conversation_text = ""
    for msg in st.session_state.messages:
        sender = msg.get("sender", "Unknown")
        content = msg.get("content", "")
        conversation_text += f"{sender}: {content}\n\n"
    
    # Create prompt for customer-facing retail_agent to generate quotation after collaboration
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
        if agents.get('customer') and clients.get('customer'):
            response = clients['customer'].responses.create(
                input=[{"role": "user", "content": quotation_prompt}],
                extra_body={"agent": {"name": agents['customer'].name, "type": "agent_reference"}},
            )
            quotation_text = response.output_text
            return quotation_text, None
        else:
            return None, "BuyBuddy customer-facing agent is not available to generate quotation."
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
    Handle customer query through retail_agent
    retail_agent coordinates with specialists when needed
    """
    thinking_steps = []
    
    def add_thinking_step(step):
        thinking_steps.append(step)
        with thinking_container:
            st.markdown("\n\n".join(thinking_steps))
    
    add_thinking_step("🛒 BuyBuddy is analyzing your query...")
    
    # Check iteration limits
    if st.session_state.iteration_counts['customer_clarifications'] >= 10:
        add_thinking_step("⚠️ Maximum BuyBuddy conversation iterations reached (10/10)")
        add_thinking_step("💡 Please reset chat to start a new conversation.")
        return {
            'thinking': "\n\n".join(thinking_steps),
            'main_response': "I have reached the maximum of 10 conversation iterations for this session. Please click 'Reset Chat' to continue with a new request.",
            'inventory_check': None,
            'specialist_responses': []
        }
    
    try:
        global agents, clients, init_errors, agents_initialized

        missing_env_vars = get_missing_required_env_vars()
        if missing_env_vars:
            add_thinking_step("⚠️ Missing required App Settings")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': "Configuration incomplete. Missing App Settings: " + ", ".join(missing_env_vars),
                'inventory_check': None,
                'specialist_responses': []
            }

        if not agents_initialized:
            add_thinking_step("🔄 Initializing agents...")
            agents, clients, init_errors, agents_initialized = get_agent_runtime(force_initialize=True)

        if agents.get('customer'):
            add_thinking_step("🧾 BuyBuddy is collecting your requirements...")

            customer_packet = collect_customer_input_packet(
                user_input,
                agents['customer'],
                clients['customer'],
                st.session_state.messages,
                st.session_state.iteration_counts,
            )

            add_thinking_step("⚙️ Orchestrator is coordinating specialist requests...")

            orchestrator_result = orchestrate_customer_packet(
                customer_packet,
                agents.get('orchestrator'),
                clients.get('orchestrator'),
                (agents.get('product'), clients.get('product')),
                (agents.get('insurance'), clients.get('insurance')),
                st.session_state.messages,
                st.session_state.iteration_counts,
            )

            if not isinstance(orchestrator_result, dict):
                orchestrator_result = {
                    'customer_response': 'I completed your request intake, but the orchestrator returned an unexpected response format. Please try again.',
                    'state': st.session_state.retail_state or {},
                    'inventory_check': None,
                    'specialist_responses': [
                        {
                            'agent': 'System',
                            'response': 'Orchestrator returned an invalid payload. Please retry this step.',
                            'icon': 'ℹ️',
                            'css_class': 'system-message',
                            'exchange_format': 'json',
                        }
                    ],
                }

            result = {
                'main_response': orchestrator_result.get('customer_response', ''),
                'state': orchestrator_result.get('state'),
                'inventory_check': orchestrator_result.get('inventory_check'),
                'specialist_responses': orchestrator_result.get('specialist_responses', []),
            }
            
            # Store retail_agent state
            st.session_state.retail_state = result.get('state')
            
            # Increment customer clarification counter
            st.session_state.iteration_counts['customer_clarifications'] += 1
            
            # Show thinking steps based on what retail agent decided
            if (result.get('inventory_check') or {}).get('checked'):
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
        "icon": get_agent_icon('retail_agent')
    }]

# Reset chat history button
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.messages = [{
        "role": "agent",
        "sender": "BuyBuddy",
        "content": "Hello! I'm your BuyBuddy. I can help you with information, specifications, features, and more. I can also coordinate with our FridgeBuddy and InsuranceBuddy teams when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": get_agent_icon('retail_agent')
    }]
    # Reset all tracking flags
    st.session_state.iteration_counts = {
        'customer_clarifications': 0,
        'product_agent_calls': 0,
        'insurance_agent_calls': 0
    }
    st.session_state.retail_state = None
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
    
    # Show internal inventory check results when available
    if msg.get("inventory_check") and msg["inventory_check"].get("checked"):
        inventory = msg["inventory_check"]
        internal_options = inventory.get("internal_options", []) if isinstance(inventory, dict) else []
        if not isinstance(internal_options, list):
            internal_options = []

        inventory_details_text = str(inventory.get("details", "Checked our internal database for available products."))
        parsed_info = _extract_inventory_structured_info(inventory_details_text)

        options_lines = []
        for option in internal_options[:4]:
            if not isinstance(option, dict):
                continue
            model_name = option.get("model_name") or option.get("model_number") or option.get("name") or "Internal model"
            price = option.get("price") or option.get("base_price")
            availability = option.get("availability")
            dimensions = option.get("dimensions") or option.get("dimension") or option.get("size")
            niche = option.get("niche") or option.get("niche_height")
            capacity = option.get("capacity") or option.get("volume")
            energy_class = option.get("energy_class") or option.get("energy")
            noise = option.get("noise") or option.get("noise_level")
            option_line = f"• {model_name}"
            detail_parts = []
            if dimensions:
                detail_parts.append(f"Size: {dimensions}")
            if niche:
                detail_parts.append(f"Niche: {niche}")
            if capacity:
                detail_parts.append(f"Capacity: {capacity}")
            if energy_class:
                detail_parts.append(f"Energy: {energy_class}")
            if noise:
                detail_parts.append(f"Noise: {noise}")
            if price:
                detail_parts.append(f"Price: {price}")
            if availability:
                detail_parts.append(f"Stock: {availability}")
            if detail_parts:
                option_line += " — " + " | ".join([str(part) for part in detail_parts])
            options_lines.append(option_line)

        if not options_lines and parsed_info.get("parsed_model_rows"):
            for row in parsed_info.get("parsed_model_rows", [])[:6]:
                model_name = row.get("model_name") or "Internal model"
                detail_parts = []
                if row.get("dimensions"):
                    detail_parts.append(f"Size: {row['dimensions']}")
                if row.get("niche"):
                    detail_parts.append(f"Niche: {row['niche']}")
                if row.get("capacity"):
                    detail_parts.append(f"Capacity: {row['capacity']}")
                if row.get("energy_class"):
                    detail_parts.append(f"Energy: {row['energy_class']}")
                if row.get("noise"):
                    detail_parts.append(f"Noise: {row['noise']}")
                if row.get("price"):
                    detail_parts.append(f"Price: {row['price']}")
                option_line = f"• {model_name}"
                if detail_parts:
                    option_line += " — " + " | ".join(detail_parts)
                options_lines.append(option_line)

        if not options_lines and parsed_info.get("model_candidates"):
            options_lines = [f"• {item}" for item in parsed_info.get("model_candidates", [])[:6]]

        if not options_lines and parsed_info.get("brands"):
            options_lines = [f"• {brand} built-in range" for brand in parsed_info.get("brands", [])]

        no_match_reason = str(inventory.get("no_match_reason", "")).strip()
        internal_match_found = inventory.get("internal_match_found") if isinstance(inventory, dict) else None

        profile_lines = []
        match_status = "Confirmed internal matches" if internal_match_found is True else (
            "No internal match found" if internal_match_found is False else "Internal match status pending"
        )
        profile_lines.append(f"• Match status: {match_status}")
        if parsed_info.get("price_band"):
            profile_lines.append(f"• Price band observed: {parsed_info['price_band']}")
        if parsed_info.get("energy_range"):
            profile_lines.append(f"• Energy class range: {parsed_info['energy_range']}")
        if parsed_info.get("niche_range"):
            profile_lines.append(f"• Niche height range: {parsed_info['niche_range']}")
        if parsed_info.get("capacity_range"):
            profile_lines.append(f"• Capacity range: {parsed_info['capacity_range']}")
        if parsed_info.get("noise_range"):
            profile_lines.append(f"• Noise range: {parsed_info['noise_range']}")
        if parsed_info.get("brands"):
            profile_lines.append(f"• Candidate brands: {', '.join(parsed_info['brands'])}")

        profile_html = "<strong>Inventory profile:</strong><br/>" + "<br/>".join([html.escape(line) for line in profile_lines])

        if options_lines:
            inventory_result_html = "<strong>Internal options:</strong><br/>" + "<br/>".join([html.escape(line) for line in options_lines])
            details_html = "Internal knowledge-base candidates were found and structured below."
        elif no_match_reason:
            inventory_result_html = f"<strong>Internal result:</strong> {html.escape(no_match_reason)}"
            details_html = inventory_details_text
        else:
            inventory_result_html = "<strong>Internal result:</strong> No internal model suggestions were returned in this turn."
            details_html = inventory_details_text

        st.markdown(f"""
        <div class="chat-message retail-message" style="border-left-color: #FF9800; background-color: rgba(255, 152, 0, 0.1);">
            <div class="sender-name">
                <span>📦 <strong>Internal Inventory Check</strong></span>
                <span class="specialist-badge" style="background-color: #FFE0B2; color: #E65100;">MediaMarktSaturn</span>
            </div>
            <div class="message-content">
                <strong>{inventory.get('summary', 'Inventory check completed')}</strong><br/>
                {html.escape(details_html)}<br/><br/>
                {profile_html}<br/><br/>
                {inventory_result_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Show specialist responses directly when present
    if msg["role"] == "agent" and msg.get("specialist_responses"):
        for specialist in msg.get("specialist_responses", []):
            specialist_sender = specialist.get("agent", "Specialist")
            specialist_icon = specialist.get("icon", "💬")
            specialist_css = specialist.get("css_class", "chat-message")
            specialist_content = str(specialist.get("response", "")).strip()

            if "system" in str(specialist_sender).lower():
                specialist_sender = "System"
                specialist_css = "system-message"
                specialist_icon = "ℹ️"

            if not specialist_content:
                continue

            specialist_content_html = html.escape(specialist_content).replace("\n", "<br/>")

            st.markdown(f"""
        <div class="chat-message {specialist_css}">
            <div class="sender-name">
                <span>{specialist_icon} <strong>{specialist_sender}</strong></span>
                <span class="timestamp">{timestamp}</span>
            </div>
            <div class="message-content">{specialist_content_html}</div>
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
    
    # Add BuyBuddy response to message history
    response_time = datetime.now().strftime("%I:%M %p")
    agent_message = {
        "role": "agent",
        "sender": "BuyBuddy",
        "content": result['main_response'],
        "timestamp": response_time,
        "icon": get_agent_icon('retail_agent'),
        "thinking": result['thinking'],
        "inventory_check": result.get('inventory_check'),
        "specialist_responses": result.get('specialist_responses', [])
    }
    st.session_state.messages.append(agent_message)
    
    st.rerun()
