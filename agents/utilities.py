import os
import json
import base64
import re

from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential


def create_azure_credential(tenant_id=None):
    """Create Azure credential with cloud-first strategy and local fallback."""
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        credential.get_token("https://management.azure.com/.default")
        return credential
    except Exception:
        browser_kwargs = {"additionally_allowed_tenants": ["*"]}
        if tenant_id:
            browser_kwargs["tenant_id"] = tenant_id
        return InteractiveBrowserCredential(**browser_kwargs)


def parse_retail_state(response):
    """
    Parse structured state metadata from retail_agent response.

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
        "product_status": "collecting",
        "insurance_status": "not_offered",
        "overall_status": "intake",
        "routing": "none",
        "inventory_checked": False,
        "iteration_count": 0,
    }

    if not response or "---" not in response:
        return default_state

    try:
        parts = [part.strip() for part in response.split("---") if part.strip()]
        if not parts:
            return default_state

        metadata = ""
        for part in reversed(parts):
            part_lower = part.lower()
            if "state:" in part_lower or "routing:" in part_lower:
                metadata = part
                break

        if not metadata:
            return default_state

        state_match = re.search(
            r"STATE:\s*product_status=([\w-]+)\s*\|\s*insurance_status=([\w-]+)\s*\|\s*overall_status=([\w-]+)",
            metadata,
            re.IGNORECASE,
        )
        if state_match:
            default_state["product_status"] = state_match.group(1).lower()
            default_state["insurance_status"] = state_match.group(2).lower()
            default_state["overall_status"] = state_match.group(3).lower()

        routing_match = re.search(r"ROUTING:\s*([\w-]+)", metadata, re.IGNORECASE)
        if routing_match:
            default_state["routing"] = routing_match.group(1).lower()

        inventory_match = re.search(r"INVENTORY_CHECKED:\s*(true|false)", metadata, re.IGNORECASE)
        if inventory_match:
            default_state["inventory_checked"] = inventory_match.group(1).lower() == "true"

        iteration_match = re.search(r"ITERATION_COUNT:\s*(\d+)", metadata)
        if iteration_match:
            default_state["iteration_count"] = int(iteration_match.group(1))

    except Exception:
        pass

    return default_state


def strip_retail_metadata(response):
    """Remove structured metadata block from retail_agent response before UI display."""
    if not response:
        return response

    cleaned = str(response)

    metadata_block_pattern = re.compile(
        r"\n?\s*---\s*\n\s*STATE:\s*.*?\n\s*ROUTING:\s*.*?\n\s*INVENTORY_CHECKED:\s*.*?\n\s*ITERATION_COUNT:\s*.*?(?:\n\s*---\s*)?",
        re.IGNORECASE | re.DOTALL,
    )
    cleaned = metadata_block_pattern.sub("\n", cleaned)

    cleaned = re.sub(r"(?im)^\s*STATE\s*:.*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*ROUTING\s*:.*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*INVENTORY_CHECKED\s*:.*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*ITERATION_COUNT\s*:.*$", "", cleaned)

    cleaned = re.sub(r"(?m)^\s*---\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned if cleaned else str(response).strip()


def extract_requirements(conversation_history):
    """Extract key requirements from conversation history."""
    requirements = {
        "budget": None,
        "region": None,
        "usage": None,
        "features": [],
        "constraints": [],
    }

    if not conversation_history:
        return requirements

    text = " ".join([msg.get("content", "") for msg in conversation_history[-5:]])
    text_lower = text.lower()

    budget_patterns = [
        r"(\d+(?:[.,]\d+)*)\s*(eur|euro|€|dollar|\$)",
        r"(eur|euro|€|dollar|\$)\s*(\d+(?:[.,]\d+)*)",
    ]
    for pattern in budget_patterns:
        budget_match = re.search(pattern, text_lower)
        if budget_match:
            requirements["budget"] = budget_match.group(0)
            break

    regions = ["germany", "france", "austria", "switzerland", "europe"]
    for region in regions:
        if region in text_lower:
            requirements["region"] = region.title()
            break

    features = ["ice maker", "water dispenser", "french door", "energy efficient", "smart"]
    requirements["features"] = [feature for feature in features if feature in text_lower]

    return requirements


def map_state_to_phase(state):
    """Map retail_agent overall_status to UI phase number (1-5)."""
    overall_status = state.get("overall_status", "intake")

    phase_map = {
        "intake": 1,
        "inventory_check": 2,
        "product_negotiation": 3,
        "insurance_phase": 4,
        "ready_to_checkout": 5,
        "stopped": 5,
    }

    return phase_map.get(overall_status, 1)


def extract_product_details(conversation_history):
    """Extract selected product details from conversation history."""
    product_details = {
        "product_model": None,
        "key_features": [],
    }

    if not conversation_history:
        return product_details

    recent_messages = conversation_history[-12:]
    text_parts = []

    for msg in recent_messages:
        content = msg.get("content", "")
        if content:
            text_parts.append(content)

        for specialist in msg.get("specialist_responses", []) or []:
            specialist_response = specialist.get("response", "")
            if specialist_response:
                text_parts.append(specialist_response)

    text = " ".join(text_parts)
    text_lower = text.lower()

    model_patterns = [
        r"\bmodel\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9\-_/]{1,30})\b",
        r"\b([A-Z]{1,5}-\d{2,6}[A-Z0-9-]*)\b",
        r"\b([A-Z]{2,5}\d{2,6}[A-Z0-9-]*)\b",
    ]

    for pattern in model_patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate.lower() not in {"from", "with", "this", "that", "model"}:
                product_details["product_model"] = candidate
                break

    feature_keywords = [
        "ice maker",
        "water dispenser",
        "french door",
        "energy efficient",
        "energy-efficient",
        "no frost",
        "a+++",
        "nofrost",
        "biofresh",
        "smart",
    ]

    extracted_features = [feature for feature in feature_keywords if feature in text_lower]

    json_candidates = []
    fenced_json_matches = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    json_candidates.extend(fenced_json_matches)

    if not json_candidates:
        loose_json_matches = re.findall(r"(\{[\s\S]*\})", text)
        if loose_json_matches:
            json_candidates.append(loose_json_matches[-1])

    for candidate in json_candidates:
        try:
            parsed = json.loads(candidate)

            if not product_details["product_model"]:
                product_details["product_model"] = parsed.get("product_model") or product_details["product_model"]

            parsed_features = parsed.get("key_features")
            if isinstance(parsed_features, list):
                extracted_features.extend([str(item).strip().lower() for item in parsed_features if item])

            recommended = parsed.get("recommended_models")
            if isinstance(recommended, list) and recommended:
                first_model = recommended[0] if isinstance(recommended[0], dict) else {}

                if not product_details["product_model"]:
                    product_details["product_model"] = (
                        first_model.get("model_number")
                        or first_model.get("model_name")
                        or product_details["product_model"]
                    )

                model_features = first_model.get("features")
                if isinstance(model_features, list):
                    extracted_features.extend([str(item).strip().lower() for item in model_features if item])

            break
        except Exception:
            continue

    if not extracted_features:
        extracted_features.extend(extract_requirements(conversation_history).get("features", []))

    normalized = []
    seen = set()
    for feature in extracted_features:
        value = str(feature).strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    product_details["key_features"] = normalized
    return product_details


def validate_insurance_context(state, conversation_history):
    """Validate that required fields are present before routing to insurance."""
    if state.get("product_status") != "agreed":
        return False, "Product not yet agreed - cannot offer insurance"

    requirements = extract_requirements(conversation_history)
    if not requirements.get("budget"):
        return False, "Product price not confirmed - cannot calculate premium"

    product_details = extract_product_details(conversation_history)
    if not product_details.get("product_model"):
        return False, "Product model not confirmed - please confirm selected model before insurance"

    return True, None


def validate_product_context(conversation_history):
    """Validate minimum requirement coverage before routing to FridgeBuddy."""
    requirements = extract_requirements(conversation_history)
    has_budget = requirements.get("budget") is not None
    has_region = requirements.get("region") is not None
    has_features = len(requirements.get("features", [])) > 0
    return has_budget or has_region or has_features


def get_agent_icon(agent_name):
    """Get the custom icon for an agent (PNG or fallback to emoji)."""
    icon_mapping = {
        "retail_agent": ("buybuddy.png", "🛒"),
        "buybuddy": ("buybuddy.png", "🛒"),
        "fridgebuddy": ("fridgebuddy.png", "📦"),
        "insurancebuddy": ("insurancebuddy.png", "🛡️"),
        "customer": (None, "👤"),
    }

    icon_file, emoji_fallback = icon_mapping.get(agent_name.lower(), (None, "💬"))
    if not icon_file:
        return emoji_fallback

    icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", icon_file)
    if os.path.exists(icon_path):
        try:
            with open(icon_path, "rb") as icon_file_handle:
                image_data = base64.b64encode(icon_file_handle.read()).decode("utf-8")
            return f'<img src="data:image/png;base64,{image_data}" class="chat-icon-img"/>'
        except Exception:
            return emoji_fallback

    return emoji_fallback
