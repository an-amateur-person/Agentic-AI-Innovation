import streamlit as st
import os
import json
import html
import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dotenv import load_dotenv
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER

from agents.retail_agent import initialize_customer_facing_agent, collect_customer_input_packet
from agents.retail_orchestrator_agent import initialize_orchestrator_agent, orchestrate_customer_packet
from agents.utilities import map_state_to_phase, extract_product_details
from agents.product_agent import initialize_product_agent
from agents.finance_agent import initialize_finance_agent

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

IS_APP_SERVICE = bool(os.getenv("WEBSITE_SITE_NAME") or os.getenv("WEBSITE_INSTANCE_ID"))

REQUIRED_ENV_VARS = [
    "AZURE_AIPROJECT_ENDPOINT",
    "AZURE_TENANT_ID",
    "AGENT_RETAIL",
    "AGENT_ORCHESTRATOR",
    "AGENT_PRODUCT",
    "AGENT_FINANCE",
]


def get_missing_required_env_vars():
    return [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]


def _safe_text(value):
    return str(value).strip() if value is not None else ""


def _sanitize_proposal_text(text):
    if not text:
        return ""

    disallowed_prefixes = (
        "STATE:",
        "ROUTING:",
        "INVENTORY_CHECKED:",
        "ITERATION_COUNT:",
    )

    cleaned_lines = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if any(stripped.upper().startswith(prefix) for prefix in disallowed_prefixes):
            continue
        if "STATE:" in stripped.upper() and "ROUTING:" in stripped.upper():
            continue
        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines).strip()
    return cleaned_text or str(text).strip()


def _get_asset_icon_tag(file_name, alt_text, css_class="chat-icon-img"):
    icon_path = os.path.join(os.path.dirname(__file__), "assets", file_name)
    if not os.path.exists(icon_path):
        return ""
    try:
        with open(icon_path, "rb") as icon_file:
            encoded = base64.b64encode(icon_file.read()).decode()
        return f'<img src="data:image/png;base64,{encoded}" class="{css_class}" alt="{alt_text}">' 
    except Exception:
        return ""


def _build_inventory_profile_from_options(internal_options):
    profile = {
        "brands": [],
        "technology_values": [],
        "skin_concern_values": [],
        "runtime_values": [],
        "intensity_values": [],
        "price_values": [],
    }

    if not isinstance(internal_options, list):
        return profile

    brands_seen = set()
    for option in internal_options:
        if not isinstance(option, dict):
            continue

        model_name = _safe_text(option.get("model_name") or option.get("name"))
        if model_name:
            maybe_brand = model_name.split(" ")[0].strip()
            if maybe_brand and maybe_brand not in brands_seen:
                brands_seen.add(maybe_brand)
                profile["brands"].append(maybe_brand)

        for source_key, target_key in [
            ("technology", "technology_values"),
            ("tech_type", "technology_values"),
            ("energy_class", "technology_values"),
            ("energy", "technology_values"),
            ("skin_concern", "skin_concern_values"),
            ("concern", "skin_concern_values"),
            ("niche", "skin_concern_values"),
            ("niche_height", "skin_concern_values"),
            ("runtime", "runtime_values"),
            ("battery_life", "runtime_values"),
            ("capacity", "runtime_values"),
            ("volume", "runtime_values"),
            ("intensity", "intensity_values"),
            ("mode", "intensity_values"),
            ("noise", "intensity_values"),
            ("noise_level", "intensity_values"),
            ("price", "price_values"),
            ("base_price", "price_values"),
        ]:
            value = _safe_text(option.get(source_key))
            if value and value not in profile[target_key]:
                profile[target_key].append(value)

    return profile


def _is_add_to_cart_intent(user_text):
    text = str(user_text or "").lower()
    if not text:
        return False

    add_tokens = [
        "add to cart",
        "add this to cart",
        "put in cart",
        "add it to cart",
        "add to basket",
        "put this in basket",
        "buy this",
    ]
    return any(token in text for token in add_tokens)


def _extract_cart_item_name_from_result(result_payload):
    if not isinstance(result_payload, dict):
        return None

    inventory_check = result_payload.get("inventory_check") or {}
    if isinstance(inventory_check, dict):
        internal_options = inventory_check.get("internal_options") or []
        if isinstance(internal_options, list):
            for option in internal_options:
                if not isinstance(option, dict):
                    continue
                model_name = _safe_text(option.get("model_name") or option.get("name") or option.get("model_number"))
                if model_name:
                    return model_name

    specialist_responses = result_payload.get("specialist_responses") or []
    if isinstance(specialist_responses, list):
        for specialist in specialist_responses:
            if not isinstance(specialist, dict):
                continue
            raw_payload = specialist.get("raw_response") or specialist.get("response")
            if not raw_payload:
                continue
            parsed = None
            if isinstance(raw_payload, dict):
                parsed = raw_payload
            else:
                try:
                    parsed = json.loads(str(raw_payload))
                except Exception:
                    parsed = None
            if not isinstance(parsed, dict):
                continue

            recommended = parsed.get("recommended_models")
            if isinstance(recommended, list) and recommended:
                first_model = recommended[0] if isinstance(recommended[0], dict) else {}
                model_name = _safe_text(
                    first_model.get("model_name")
                    or first_model.get("model_number")
                    or parsed.get("product_model")
                )
                if model_name:
                    return model_name

            model_name = _safe_text(parsed.get("product_model") or parsed.get("model_name") or parsed.get("model_number"))
            if model_name:
                return model_name

    state_payload = result_payload.get("state") or {}
    if isinstance(state_payload, dict):
        model_name = _safe_text(
            state_payload.get("product_model")
            or state_payload.get("selected_product")
            or state_payload.get("selected_model")
            or state_payload.get("agreed_model")
        )
        if model_name:
            return model_name

    return None


def _add_item_to_cart(item_name):
    name = _safe_text(item_name)
    if not name:
        return False

    if "cart_items" not in st.session_state:
        st.session_state.cart_items = []

    for entry in st.session_state.cart_items:
        if _safe_text(entry.get("name")).lower() == name.lower():
            entry["quantity"] = int(entry.get("quantity", 1)) + 1
            return True

    st.session_state.cart_items.append({"name": name, "quantity": 1})
    return True

# Helper function to get icon (assets only)
def get_agent_icon(agent_name):
    """Get base64 encoded image for agent icon from assets only."""
    icon_mapping = {
        'retail_agent': 'Ceconomy.png',
        'assistant': 'Ceconomy.png',
        'product_specialist': 'Beiersdorf.png',
        'finance_specialist': 'DZBank.png',
    }
    icon_file = icon_mapping.get(str(agent_name or "").lower())
    if not icon_file:
        return ""
    return _get_asset_icon_tag(icon_file, str(agent_name or "agent"))


def get_agent_label_with_icon(agent_name, icon_key):
    icon_tag = get_agent_icon(icon_key)
    if icon_tag:
        return f"{icon_tag} {html.escape(agent_name)}"
    return html.escape(agent_name)

# Webpage configurations
page_icon_path = os.path.join(os.path.dirname(__file__), "assets", "Ceconomy.png")
st.set_page_config(page_title="Agentic AI System Interface", page_icon=page_icon_path if os.path.exists(page_icon_path) else None)

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

.title-subheading {
    display: block;
    font-size: 1.1rem;
    font-weight: 400;
    opacity: 0.9;
    margin-top: 4px;
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

.finance-message,
.finance-message {
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

.sidebar-agent-icon {
    width: 16px;
    height: 16px;
    object-fit: contain;
    vertical-align: text-bottom;
    margin-right: 4px;
}

/* Sidebar agent cards */
.agent-status-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 8px;
}

.agent-status-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    transition: all 0.2s ease;
}

.agent-status-card .agent-name {
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.2px;
}

.agent-status-card .chat-icon-img {
    width: 30px;
    height: 30px;
    margin-right: 0;
}

.agent-status-card.active {
    background: rgba(33, 150, 243, 0.18);
    border-color: rgba(33, 150, 243, 0.55);
    box-shadow: 0 0 0 1px rgba(33, 150, 243, 0.35) inset;
}

.agent-status-card.active .agent-name {
    color: #FFFFFF;
}

.agent-status-card.inactive {
    background: rgba(158, 158, 158, 0.12);
    border-color: rgba(158, 158, 158, 0.26);
}

.agent-status-card.inactive .agent-name {
    color: #9E9E9E;
}

.agent-status-card.inactive .chat-icon-img {
    filter: grayscale(100%);
    opacity: 0.5;
}

.cart-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.cart-row {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 8px 10px;
}

.cart-row .cart-name {
    font-size: 0.95rem;
    font-weight: 600;
    color: #FFFFFF;
}

.cart-row .cart-qty {
    font-size: 0.8rem;
    color: #BDBDBD;
}
</style>
"""

# Apply the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Display title with icon
icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'Ceconomy.png')
if os.path.exists(icon_path):
    # Read and encode the image for display
    with open(icon_path, 'rb') as f:
        img_bytes = f.read()
    img_base64 = base64.b64encode(img_bytes).decode()
    icon_html = f'<div class="title-icon"><img src="data:image/png;base64,{img_base64}" alt="Assistant"></div>'
else:
    icon_html = '<div class="title-icon"></div>'

st.markdown(f'''
<div class="title-with-icon">
    {icon_html}
    <h1>SkinTech<span class="title-subheading">Your personal BeautyTech Shopping Assistant </span></h1>
</div>
''', unsafe_allow_html=True)

st.write("Hi Beautiful! Ask me anything, and I'll coordinate with specialized teams when needed.")

# Initialize all agents
@st.cache_resource
def initialize_all_agents():
    """Initialize customer-facing retail_agent and specialized agents"""
    agents = {}
    clients = {}
    errors = {}

    def run_with_timeout(func, timeout_seconds, *args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                raise TimeoutError(f"Timed out after {timeout_seconds}s while running {func.__name__}")
    
    try:
        # Initialize Customer-facing retail_agent
        try:
            customer_agent, customer_client, project_client = run_with_timeout(
                initialize_customer_facing_agent,
                25,
            )
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
            orchestrator_agent, orchestrator_client = run_with_timeout(
                initialize_orchestrator_agent,
                20,
                clients.get('project'),
            )
            agents['orchestrator'] = orchestrator_agent
            clients['orchestrator'] = orchestrator_client
            if orchestrator_agent is None:
                errors['orchestrator'] = "Agent not found or inaccessible. Verify AGENT_ORCHESTRATOR and Azure permissions."
        except Exception as e:
            agents['orchestrator'] = None
            errors['orchestrator'] = str(e)
        
        # Initialize Product Agent (specialist)
        try:
            mfg_agent, mfg_client = run_with_timeout(
                initialize_product_agent,
                20,
            )
            agents['product'] = mfg_agent
            clients['product'] = mfg_client
            if mfg_agent is None:
                errors['product'] = "Agent not found or inaccessible. Verify AGENT_PRODUCT and Azure permissions."
        except Exception as e:
            agents['product'] = None
            errors['product'] = str(e)
        
        # Initialize Finance Agent (specialist)
        try:
            finance_agent, finance_client = run_with_timeout(
                initialize_finance_agent,
                20,
            )
            agents['finance'] = finance_agent
            clients['finance'] = finance_client
            if finance_agent is None:
                errors['finance'] = "Agent not found or inaccessible. Verify AGENT_FINANCE and Azure permissions."
        except Exception as e:
            agents['finance'] = None
            errors['finance'] = str(e)
            
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

    # Avoid blocking initial page render. Initialize only when explicitly requested.
    should_initialize = force_initialize

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
    4. Finance - Offering protection plans
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
    
    # Phase 4: Finance keywords
    if any(kw in conversation_text for kw in ['finance', 'financing', 'warranty', 'protection plan', 'coverage']):
        return 4
    
    # Phase 3: Product agreement keywords
    if any(kw in conversation_text for kw in ['confirm', 'agreed', 'accept', 'this model', 'go with']):
        return 3
    
    # Phase 2: Inventory/product search keywords
    if any(kw in conversation_text for kw in ['product', 'beauty', 'beauty tech', 'skincare device', 'looking for', 'need', 'stock', 'available']):
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
        'finance_agent_calls': 0
    }

if "cart_items" not in st.session_state:
    st.session_state.cart_items = []

# Display initialization status in sidebar
with st.sidebar:
    # Phase Tracker - Compact view
    st.subheader("Progress")
    
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
        (4, "Finance"),
        (5, "Quotation")
    ]
    
    # Compact phase display
    phase_status = []
    for num, title in phases:
        if num < current_phase:
            phase_status.append(f"✅ {title}")
        elif num == current_phase:
            if num == 5:
                phase_status.append(f"✅ **{title}**")
            else:
                phase_status.append(f"🔵 **{title}**")
        else:
            phase_status.append(f"⚪ {title}")
    
    st.markdown("<br>".join(phase_status), unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Agent Status - Compact
    st.subheader("Agents")

    missing_env_vars = get_missing_required_env_vars()
    if missing_env_vars:
        st.error("Missing App Settings: " + ", ".join(missing_env_vars))

    if not agents_initialized:
        st.info("Agents will initialize on first request.")
    elif 'main' not in init_errors:
        # Exactly one agent is shown as active based on the current phase.
        if current_phase == 2:
            active_agent_key = 'product'
        elif current_phase == 4:
            active_agent_key = 'finance'
        else:
            active_agent_key = 'customer'

        agent_cards = []
        # Orchestrator remains internal and is not shown in user-facing UI.
        agent_rows = [
            ('customer', 'SkinTech', 'assistant'),
            ('product', 'GlowBi', 'product_specialist'),
            ('finance', 'DZBankFinancing', 'finance_specialist'),
        ]

        for key, label, icon_key in agent_rows:
            if not agents.get(key):
                continue
            icon_html = get_agent_icon(icon_key)
            state_class = "active" if key == active_agent_key else "inactive"
            agent_cards.append(
                f'<div class="agent-status-card {state_class}">{icon_html}<span class="agent-name">{html.escape(label)}</span></div>'
            )

        if agent_cards:
            st.markdown(
                '<div class="agent-status-list">' + ''.join(agent_cards) + '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning("No agents configured")
    else:
        st.error("Initialization failed")

    st.markdown("---")
    st.subheader("Cart")
    if st.session_state.cart_items:
        cart_rows = []
        for item in st.session_state.cart_items:
            name = html.escape(_safe_text(item.get("name") or "Item"))
            qty = int(item.get("quantity", 1))
            cart_rows.append(
                f'<div class="cart-row"><div class="cart-name">{name}</div><div class="cart-qty">Quantity: {qty}</div></div>'
            )
        st.markdown('<div class="cart-list">' + ''.join(cart_rows) + '</div>', unsafe_allow_html=True)
        if st.button("Clear Cart", use_container_width=True):
            st.session_state.cart_items = []
            st.rerun()
    else:
        st.caption("Your cart is empty")

def generate_quotation():
    """Generate a product quotation after all agents collaborate to finalize the offer"""
    global agents, clients, init_errors, agents_initialized

    missing_env_vars = get_missing_required_env_vars()
    if missing_env_vars:
        return None, "Missing required App Settings: " + ", ".join(missing_env_vars)

    if not agents_initialized:
        agents, clients, init_errors, agents_initialized = get_agent_runtime(force_initialize=True)

    if len(st.session_state.messages) <= 1:
        return None, "No conversation to generate quotation from. Start chatting first!"
    
    # Build conversation context
    conversation_text = ""
    for msg in st.session_state.messages:
        sender = msg.get("sender", "Unknown")
        content = msg.get("content", "")
        conversation_text += f"{sender}: {content}\n\n"
    
    # Create prompt for customer-facing retail_agent to generate quotation after collaboration
    quotation_prompt = f"""Based on the collaboration between the assistant, product specialist, and finance specialist in the conversation below, create a formal product quotation for the customer.

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
            quotation_text = _sanitize_proposal_text(response.output_text)
            return quotation_text, None
        else:
            return None, "Customer-facing agent is not available to generate quotation."
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
    
    add_thinking_step("Assistant is analyzing your query...")
    
    # Check iteration limits
    if st.session_state.iteration_counts['customer_clarifications'] >= 15:
        add_thinking_step("Maximum assistant conversation iterations reached (15/15)")
        add_thinking_step("Please reset chat to start a new conversation.")
        return {
            'thinking': "\n\n".join(thinking_steps),
            'main_response': "I have reached the maximum of 15 conversation iterations for this session. Please click 'Reset Chat' to continue with a new request.",
            'inventory_check': None,
            'specialist_responses': []
        }
    
    try:
        global agents, clients, init_errors, agents_initialized

        missing_env_vars = get_missing_required_env_vars()
        if missing_env_vars:
            add_thinking_step("Missing required App Settings")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': "Configuration incomplete. Missing App Settings: " + ", ".join(missing_env_vars),
                'inventory_check': None,
                'specialist_responses': []
            }

        if not agents_initialized:
            add_thinking_step("Initializing agents...")
            agents, clients, init_errors, agents_initialized = get_agent_runtime(force_initialize=True)

        if agents.get('customer'):
            add_thinking_step("Assistant is collecting your requirements...")

            customer_packet = collect_customer_input_packet(
                user_input,
                agents['customer'],
                clients['customer'],
                st.session_state.messages,
                st.session_state.iteration_counts,
            )

            add_thinking_step("Orchestrator is coordinating specialist requests...")

            orchestrator_result = orchestrate_customer_packet(
                customer_packet,
                agents.get('orchestrator'),
                clients.get('orchestrator'),
                (agents.get('product'), clients.get('product')),
                (agents.get('finance'), clients.get('finance')),
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
                            'icon': '',
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
                add_thinking_step("Checked internal inventory")
            
            if result.get('specialist_responses'):
                specialists = [s['agent'] for s in result['specialist_responses']]
                add_thinking_step(f"Consulted with: {', '.join(specialists)}")
            
            add_thinking_step("Response ready!")
            
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': result['main_response'],
                'inventory_check': result.get('inventory_check'),
                'specialist_responses': result['specialist_responses']
            }
        else:
            add_thinking_step("Assistant not fully configured, using demo mode")
            return {
                'thinking': "\n\n".join(thinking_steps),
                'main_response': f"Assistant (Demo): Thank you for your query about '{user_input}'. I can help you with information, specifications, and coordinate with product and finance specialists as needed.",
                'inventory_check': None,
                'specialist_responses': []
            }
    except Exception as e:
        add_thinking_step(f"Error: {str(e)}")
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
        "sender": "SkinTech",
        "content": "Hello! I'm SkinTech. I can help you with information, specifications, features, and more. I can also coordinate with product and finance specialists when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": get_agent_icon('retail_agent')
    }]

# Reset chat history button
if st.sidebar.button("Reset Chat"):
    st.session_state.messages = [{
        "role": "agent",
        "sender": "SkinTech",
        "content": "Hello! I'm SkinTech. I can help you with information, specifications, features, and more. I can also coordinate with product and finance specialists when needed. How can I assist you today?",
        "timestamp": datetime.now().strftime("%I:%M %p"),
        "icon": get_agent_icon('retail_agent')
    }]
    # Reset all tracking flags
    st.session_state.iteration_counts = {
        'customer_clarifications': 0,
        'product_agent_calls': 0,
        'finance_agent_calls': 0
    }
    st.session_state.retail_state = None
    st.session_state.current_phase = 1
    st.session_state.cart_items = []
    st.rerun()

# Show quotation section only in final phase (Phase 5)
if st.session_state.current_phase >= 5:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Final Proposal")
    if st.sidebar.button("Generate Proposal", type="primary", use_container_width=True):
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
                        st.success("Ready")
                        st.download_button(
                            label="Download PDF",
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
    icon = msg.get("icon", "")
    if "<img" not in str(icon):
        icon = ""
    timestamp = msg.get("timestamp", "")
    content = msg.get("content", "")
    
    # Determine CSS class based on sender
    if msg["role"] == "user":
        css_class = "user-message"
    elif "Assistant" in sender or "SkinTech" in sender:
        css_class = "retail-message"
        icon = icon or get_agent_icon("assistant")
    elif "Product Specialist" in sender or "GlowBi" in sender:
        css_class = "product-message"
        icon = get_agent_icon("product_specialist")
    elif "Finance Specialist" in sender or "DZBankFinancing" in sender:
        css_class = "finance-message"
        icon = get_agent_icon("finance_specialist")
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
        with st.expander("Agent Coordination Process", expanded=False):
            st.markdown(msg["thinking"])
    
    # Show internal inventory check results when available
    if msg.get("inventory_check") and msg["inventory_check"].get("checked"):
        inventory = msg["inventory_check"]
        internal_options = inventory.get("internal_options", []) if isinstance(inventory, dict) else []
        if not isinstance(internal_options, list):
            internal_options = []

        inventory_details_text = str(inventory.get("details", "Checked our internal database for available products."))
        profile_from_options = _build_inventory_profile_from_options(internal_options)

        options_lines = []
        for option in internal_options[:4]:
            if not isinstance(option, dict):
                continue
            model_name = option.get("model_name") or option.get("model_number") or option.get("name") or "Internal model"
            price = option.get("price") or option.get("base_price")
            availability = option.get("availability")
            dimensions = option.get("dimensions") or option.get("dimension") or option.get("size")
            skin_concern = option.get("skin_concern") or option.get("concern") or option.get("niche") or option.get("niche_height")
            runtime = option.get("runtime") or option.get("battery_life") or option.get("capacity") or option.get("volume")
            technology = option.get("technology") or option.get("tech_type") or option.get("energy_class") or option.get("energy")
            intensity = option.get("intensity") or option.get("mode") or option.get("noise") or option.get("noise_level")
            option_line = f"• {model_name}"
            detail_parts = []
            if dimensions:
                detail_parts.append(f"Size: {dimensions}")
            if skin_concern:
                detail_parts.append(f"Skin concern: {skin_concern}")
            if runtime:
                detail_parts.append(f"Runtime: {runtime}")
            if technology:
                detail_parts.append(f"Technology: {technology}")
            if intensity:
                detail_parts.append(f"Intensity: {intensity}")
            if price:
                detail_parts.append(f"Price: {price}")
            if availability:
                detail_parts.append(f"Stock: {availability}")
            if detail_parts:
                option_line += " — " + " | ".join([str(part) for part in detail_parts])
            options_lines.append(option_line)

        no_match_reason = str(inventory.get("no_match_reason", "")).strip()
        internal_match_found = inventory.get("internal_match_found") if isinstance(inventory, dict) else None

        profile_lines = []
        match_status = "Confirmed internal matches" if internal_match_found is True else (
            "No internal match found" if internal_match_found is False else "Internal match status pending"
        )
        profile_lines.append(f"• Match status: {match_status}")
        if internal_options:
            profile_lines.append(f"• Structured internal options: {len(internal_options)}")
        if profile_from_options.get("price_values"):
            profile_lines.append(
                f"• Price points: {', '.join(profile_from_options['price_values'][:4])}"
            )
        if profile_from_options.get("technology_values"):
            profile_lines.append(
                f"• Technology types: {', '.join(profile_from_options['technology_values'][:4])}"
            )
        if profile_from_options.get("skin_concern_values"):
            profile_lines.append(
                f"• Skin concerns: {', '.join(profile_from_options['skin_concern_values'][:3])}"
            )
        if profile_from_options.get("runtime_values"):
            profile_lines.append(
                f"• Runtime values: {', '.join(profile_from_options['runtime_values'][:3])}"
            )
        if profile_from_options.get("intensity_values"):
            profile_lines.append(
                f"• Intensity levels: {', '.join(profile_from_options['intensity_values'][:3])}"
            )
        if profile_from_options.get("brands"):
            profile_lines.append(
                f"• Candidate brands: {', '.join(profile_from_options['brands'][:5])}"
            )

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
                <span>{get_agent_icon('product_specialist')} <strong>Internal Inventory Check</strong></span>
                <span class="specialist-badge" style="background-color: #FFE0B2; color: #E65100;">Internal Inventory</span>
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
            specialist_icon = specialist.get("icon", "")
            if "<img" not in str(specialist_icon):
                specialist_icon = ""
            specialist_css = specialist.get("css_class", "chat-message")
            specialist_content = str(specialist.get("response", "")).strip()

            if "system" in str(specialist_sender).lower():
                specialist_sender = "System"
                specialist_css = "system-message"
                specialist_icon = ""
            elif "product specialist" in str(specialist_sender).lower():
                specialist_sender = "GlowBi"
                specialist_icon = get_agent_icon("product_specialist")
            elif "finance specialist" in str(specialist_sender).lower():
                specialist_sender = "DZBankFinancing"
                specialist_icon = get_agent_icon("finance_specialist")

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
    
    # Get assistant response
    with st.status("Assistant is working on your request...", expanded=True) as status:
        thinking_container = st.empty()
        
        # Handle the customer query
        result = handle_customer_query(prompt, thinking_container)
        
        status.update(label="Response ready", state="complete", expanded=False)
    
    # Add assistant response to message history
    response_time = datetime.now().strftime("%I:%M %p")
    agent_message = {
        "role": "agent",
        "sender": "SkinTech",
        "content": result['main_response'],
        "timestamp": response_time,
        "icon": get_agent_icon('retail_agent'),
        "thinking": result['thinking'],
        "inventory_check": result.get('inventory_check'),
        "specialist_responses": result.get('specialist_responses', [])
    }
    st.session_state.messages.append(agent_message)

    # Update cart when user explicitly asks to add an item.
    if _is_add_to_cart_intent(prompt):
        item_name = _extract_cart_item_name_from_result(result)
        if not item_name:
            product_details = extract_product_details(st.session_state.messages)
            item_name = _safe_text(product_details.get("product_model"))
        _add_item_to_cart(item_name)
    
    st.rerun()
