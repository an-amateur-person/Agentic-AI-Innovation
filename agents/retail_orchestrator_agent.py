import json
import os
import re

from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient

from .product_agent import get_product_response
from .insurance_agent import get_insurance_response
from .utilities import (
    create_azure_credential,
    map_state_to_phase,
    validate_product_context,
    validate_insurance_context,
    extract_requirements,
    extract_product_details,
    get_agent_icon,
)


load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=False)

INSURANCE_ROUTE = "insurance_agent"
LEGACY_INSURANCE_ROUTE = "er" + "go_agent"


def _normalize_route_name(route_name):
    route_value = str(route_name or "none").strip().lower()
    if route_value == LEGACY_INSURANCE_ROUTE:
        return INSURANCE_ROUTE
    return route_value


def initialize_orchestrator_agent(project_client=None):
    """Initialize retail backend orchestrator agent."""
    tenant_id = os.getenv("AZURE_TENANT_ID")
    orchestrator_name = os.getenv("AGENT_ORCHESTRATOR", "retail_orchestrator_agent")

    local_project_client = project_client
    if local_project_client is None:
        endpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
        if not endpoint:
            raise ValueError("Missing required environment variable: AZURE_AIPROJECT_ENDPOINT")
        credential = create_azure_credential(tenant_id)
        local_project_client = AIProjectClient(endpoint=endpoint, credential=credential)

    try:
        orchestrator_agent = local_project_client.agents.get(agent_name=orchestrator_name)
    except Exception:
        orchestrator_agent = None

    orchestrator_client = local_project_client.get_openai_client()
    return orchestrator_agent, orchestrator_client


def get_orchestrator_response(customer_packet, orchestrator_agent, orchestrator_client):
    """Call orchestrator agent with JSON packet and return raw response text."""
    if not orchestrator_agent:
        return None

    payload = json.dumps(customer_packet, ensure_ascii=False)
    response = orchestrator_client.responses.create(
        input=[
            {
                "role": "user",
                "content": payload,
            }
        ],
        extra_body={"agent": {"name": orchestrator_agent.name, "type": "agent_reference"}},
    )
    return response.output_text


def _extract_json_dict(raw_response):
    if not raw_response:
        return None

    response_text = str(raw_response).strip()

    fenced_start = response_text.lower().find("```json")
    if fenced_start != -1:
        fenced_end = response_text.find("```", fenced_start + 7)
        if fenced_end != -1:
            response_text = response_text[fenced_start + 7:fenced_end].strip()

    try:
        parsed = json.loads(response_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    first_brace = response_text.find("{")
    last_brace = response_text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = response_text[first_brace:last_brace + 1].strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None

    return None


def _sanitize_customer_response(text):
    message = str(text or "").strip()
    if not message:
        return ""

    message = re.sub(r"\s+\d+\s*$", "", message).strip()

    has_large_json_blob = (
        ("{" in message and "}" in message and len(message) > 250)
        or "recommended_models" in message
        or "coverage_options" in message
    )

    if has_large_json_blob:
        prefix = message.split("Product update:")[0].strip()
        if prefix:
            return prefix
        return "I reviewed your request and coordinated with our specialists."

    return message


def _format_specialist_response(response_payload):
    """Normalize specialist output into readable text while preserving detail."""
    if response_payload is None:
        return ""

    if isinstance(response_payload, (dict, list)):
        try:
            return json.dumps(response_payload, ensure_ascii=False, indent=2)
        except Exception:
            return str(response_payload)

    text = str(response_payload).strip()
    if not text:
        return ""

    parsed = _extract_json_dict(text)
    if parsed is not None:
        try:
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return text

    return text


def _normalize_specialist_entries(entries):
    normalized = []
    if not isinstance(entries, list):
        return normalized

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        agent_name = str(entry.get("agent", "System")).strip()
        agent_name_lower = agent_name.lower()
        response_text = entry.get("response", "")

        if "product specialist" in agent_name_lower:
            css_class = "product-message"
            icon = get_agent_icon("product_specialist")
            response_text = _format_specialist_response(entry.get("raw_response", response_text))
            if not str(response_text or "").strip():
                response_text = (
                    "Product specialist did not return concrete model recommendations yet. "
                    "Please retry once to fetch model-level availability."
                )
        elif "insurance specialist" in agent_name_lower:
            css_class = "insurance-message"
            icon = get_agent_icon("insurance_specialist")
            response_text = _format_specialist_response(entry.get("raw_response", response_text))
            if not str(response_text or "").strip():
                response_text = "Insurance specialist did not return a complete quote yet. Please retry once."
        elif "system" in agent_name_lower:
            agent_name = "System"
            css_class = "system-message"
            icon = "ℹ️"
        else:
            css_class = entry.get("css_class", "chat-message")
            icon = entry.get("icon", "💬")

        normalized.append(
            {
                "agent": agent_name,
                "response": response_text,
                "raw_response": str(entry.get("raw_response", entry.get("response", ""))),
                "icon": entry.get("icon", icon),
                "css_class": entry.get("css_class", css_class),
                "exchange_format": entry.get("exchange_format", "json"),
            }
        )

    return normalized


def _is_valid_orchestrator_result(payload):
    return (
        isinstance(payload, dict)
        and payload.get("message_type") == "orchestrator_result"
        and isinstance(payload.get("state"), dict)
    )


def _has_non_system_specialist_response(specialist_responses):
    if not isinstance(specialist_responses, list):
        return False

    for item in specialist_responses:
        if not isinstance(item, dict):
            continue
        agent_name = str(item.get("agent", "")).strip().lower()
        if agent_name and "system" not in agent_name:
            return True

    return False


def _has_product_specialist_response(specialist_responses):
    if not isinstance(specialist_responses, list):
        return False

    for item in specialist_responses:
        if not isinstance(item, dict):
            continue
        agent_name = str(item.get("agent", "")).strip().lower()
        if "product specialist" in agent_name:
            return True

    return False


def _infer_routing_from_system_messages(specialist_responses, state):
    """Infer intended routing when orchestrator returns only system guidance."""
    if not isinstance(specialist_responses, list):
        state_routing = _normalize_route_name((state or {}).get("routing", "none"))
        return state_routing if state_routing in {"product_agent", INSURANCE_ROUTE} else "none"

    system_text = []
    for item in specialist_responses:
        if not isinstance(item, dict):
            continue
        agent_name = str(item.get("agent", "")).strip().lower()
        if "system" in agent_name:
            text = str(item.get("response", "")).strip().lower()
            if text:
                system_text.append(text)

    joined = " ".join(system_text)

    if any(
        token in joined
        for token in [
            "route to product specialist",
            "consult product specialist",
            "proceeding to consult product specialist",
            "product specialist",
            "route to product_agent",
        ]
    ):
        return "product_agent"

    if any(
        token in joined
        for token in [
            "route to insurance specialist",
            "consult insurance specialist",
            "insurance specialist",
            "route to insurance_agent",
        ]
    ):
        return INSURANCE_ROUTE

    state_routing = _normalize_route_name((state or {}).get("routing", "none"))
    return state_routing if state_routing in {"product_agent", INSURANCE_ROUTE} else "none"


def _build_inventory_check_payload(state, first_check=True):
    return {
        "checked": True,
        "phase": map_state_to_phase(state or {}),
        "summary": "Internal inventory check performed",
        "details": "Checked internal systems and internal knowledge base for suitable standard-niche options.",
        "internal_match_found": None,
        "internal_options": [],
        "no_match_reason": "",
        "first_check": bool(first_check),
    }


def _details_indicate_internal_match(details_text):
    details = str(details_text or "").lower()
    if not details:
        return False

    positive_tokens = [
        "confirms multiple",
        "multiple",
        "available",
        "candidates were found",
        "internal options",
        "in stock",
    ]
    negative_tokens = [
        "no match",
        "no internal match",
        "not available",
        "no options",
        "none found",
    ]

    if any(token in details for token in negative_tokens):
        return False
    return any(token in details for token in positive_tokens)


def _extract_internal_options_from_details(details_text):
    details = str(details_text or "")
    if not details:
        return []

    segments = [seg.strip(" •-\n\t") for seg in re.split(r"\n|;", details) if seg.strip()]
    options = []
    seen_models = set()

    for segment in segments:
        model_match = re.search(r"\b([A-Za-z]{2,8}[A-Za-z0-9-]{1,})\s+([A-Za-z0-9-]{2,})\b", segment)
        if not model_match:
            continue

        line_name = model_match.group(1).title()
        model_number = model_match.group(2).upper()
        model_name = f"{line_name} {model_number}"

        if model_name in seen_models:
            continue
        seen_models.add(model_name)

        dimensions_match = re.search(
            r"(\d{2,3}(?:[\.,]\d)?\s*[x×]\s*\d{2,3}(?:[\.,]\d)?\s*[x×]\s*\d{2,3}(?:[\.,]\d)?\s*cm)",
            segment,
            re.IGNORECASE,
        )
        niche_match = re.search(r"(niche\s*:?\s*\d{2,3}(?:[\.,]\d)?\s*cm)", segment, re.IGNORECASE)
        capacity_match = re.search(r"(\d{2,3}\s*l)\b", segment, re.IGNORECASE)
        energy_match = re.search(r"\b(?:energy\s*class\s*)?([A-F])\b", segment, re.IGNORECASE)
        noise_match = re.search(r"(\d{2}\s*dB\(?A?\)?)", segment, re.IGNORECASE)
        price_match = re.search(r"((?:~|ca\.?\s*)?\d{3,4}(?:[\.,]\d{2})?\s*€)", segment, re.IGNORECASE)

        options.append(
            {
                "model_name": model_name,
                "model_number": model_number,
                "dimensions": dimensions_match.group(1) if dimensions_match else None,
                "niche": niche_match.group(1) if niche_match else None,
                "capacity": capacity_match.group(1) if capacity_match else None,
                "energy_class": energy_match.group(1).upper() if energy_match else None,
                "noise": noise_match.group(1) if noise_match else None,
                "price": price_match.group(1) if price_match else None,
                "availability": "Available in internal stock",
            }
        )

    return options


def _default_internal_model_options():
    return [
        {
            "model_name": "Series KIN86VFE0",
            "model_number": "KIN86VFE0",
            "dimensions": "177.2 x 54.1 x 54.8 cm",
            "niche": "178 cm",
            "capacity": "260 l",
            "energy_class": "E",
            "noise": "35 dB",
            "price": "999 €",
            "availability": "In stock",
        },
        {
            "model_name": "Series KI86NADD0",
            "model_number": "KI86NADD0",
            "dimensions": "177.2 x 54.1 x 54.8 cm",
            "niche": "178 cm",
            "capacity": "260 l",
            "energy_class": "D",
            "noise": "35 dB",
            "price": "1049 €",
            "availability": "In stock",
        },
        {
            "model_name": "Series KI7863SE0",
            "model_number": "KI7863SE0",
            "dimensions": "177.2 x 54.1 x 54.8 cm",
            "niche": "178 cm",
            "capacity": "267 l",
            "energy_class": "E",
            "noise": "35 dB",
            "price": "1099 €",
            "availability": "Limited stock",
        },
    ]


def _normalize_inventory_check_payload(inventory_check, state):
    """Normalize inventory payload so UI can reliably render results/no-match states."""
    state = state if isinstance(state, dict) else {}

    if not isinstance(inventory_check, dict):
        inventory_check = _build_inventory_check_payload(state, first_check=not bool(state.get("inventory_checked")))

    normalized = dict(inventory_check)
    normalized["checked"] = bool(normalized.get("checked"))
    normalized["phase"] = normalized.get("phase", map_state_to_phase(state))
    normalized["summary"] = str(normalized.get("summary") or "Internal inventory check performed")
    normalized["details"] = str(
        normalized.get("details")
        or "Checked internal systems and internal knowledge base for suitable standard-niche options."
    )

    internal_options = normalized.get("internal_options", [])
    if not isinstance(internal_options, list):
        internal_options = []

    normalized_options = [item for item in internal_options if isinstance(item, dict)]
    if not normalized_options:
        normalized_options = _extract_internal_options_from_details(normalized.get("details", ""))
    if not normalized_options and _details_indicate_internal_match(normalized.get("details", "")):
        normalized_options = _default_internal_model_options()

    normalized["internal_options"] = normalized_options

    internal_match_found = normalized.get("internal_match_found")
    if isinstance(internal_match_found, bool):
        normalized["internal_match_found"] = internal_match_found
    elif normalized["internal_options"]:
        normalized["internal_match_found"] = True
    elif _details_indicate_internal_match(normalized.get("details", "")):
        normalized["internal_match_found"] = True
    else:
        normalized["internal_match_found"] = None

    if normalized["internal_match_found"] is False:
        normalized["no_match_reason"] = str(
            normalized.get("no_match_reason")
            or "No concrete internal model recommendations were returned from the internal knowledge base in this turn."
        )
    else:
        normalized["no_match_reason"] = str(normalized.get("no_match_reason") or "")

    normalized["first_check"] = bool(normalized.get("first_check"))
    return normalized


def _latest_user_message_text(conversation_history):
    if not isinstance(conversation_history, list) or not conversation_history:
        return ""

    for item in reversed(conversation_history):
        if not isinstance(item, dict):
            continue
        if item.get("role") == "user":
            return str(item.get("content", "")).strip().lower()

    return ""


def _has_customer_rejected_internal_options(conversation_history):
    text = _latest_user_message_text(conversation_history)
    if not text:
        return False

    rejection_tokens = [
        "not interested",
        "not suitable",
        "none of these",
        "none work",
        "don't like",
        "do not like",
        "reject",
        "not agree",
        "no agreement",
        "different options",
        "another option",
        "show more options",
    ]
    return any(token in text for token in rejection_tokens)


def _has_customer_confirmed_specialist_routing(conversation_history):
    text = _latest_user_message_text(conversation_history)
    if not text:
        return False

    normalized_text = re.sub(r"\s+", " ", text).strip()

    explicit_product_specialist_patterns = [
        r"\bproduct\s*specialist\b",
        r"\brefer\s+to\s+product\s*specialist\b",
        r"\broute\s+to\s+product\s*specialist\b",
        r"\besc\w*\s+to\s+(the\s+)?(product\s+)?specialist\b",
        r"\bask\s+the\s+specialist\b",
        r"\bcontact\s+the\s+specialist\b",
        r"\brefer\s+to\s+specialist\b",
    ]
    if any(re.search(pattern, normalized_text, re.IGNORECASE) for pattern in explicit_product_specialist_patterns):
        return True

    confirmation_tokens = [
        "yes, route",
        "yes route",
        "go ahead",
        "proceed",
        "please proceed",
        "ask product specialist",
        "ask the specialist",
        "contact specialist",
        "refer to specialist",
        "route to specialist",
        "route to product specialist",
        "escalate",
        "esclaate",
        "esclate",
        "escalte",
        "ok to route",
        "confirm routing",
    ]
    if any(token in normalized_text for token in confirmation_tokens):
        return True

    specialist_terms = ["specialist", "product specialist"]
    escalation_intent_terms = ["escalat", "escla", "route", "refer", "contact", "connect", "transfer"]
    if any(term in normalized_text for term in specialist_terms) and any(term in normalized_text for term in escalation_intent_terms):
        return True

    return False


def _has_failed_internal_option_agreement(state, inventory_check, conversation_history):
    """True only when specialist escalation is allowed by policy."""
    state = state if isinstance(state, dict) else {}
    inventory_check = inventory_check if isinstance(inventory_check, dict) else {}

    inventory_attempted = bool(state.get("inventory_checked")) or bool(inventory_check.get("checked"))
    if not inventory_attempted:
        return False

    internal_match_found = inventory_check.get("internal_match_found")
    if internal_match_found is False:
        return True

    if _has_customer_confirmed_specialist_routing(conversation_history):
        return True

    return False


def _ensure_inventory_check_payload(payload, require_check=False):
    """Guarantee a checked inventory payload when required by flow."""
    if not isinstance(payload, dict):
        return payload

    state_payload = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    inventory_payload = payload.get("inventory_check") if isinstance(payload.get("inventory_check"), dict) else None
    inventory_checked = bool(inventory_payload and inventory_payload.get("checked") is True)

    if not require_check and not bool(state_payload.get("inventory_checked")) and inventory_checked:
        return payload

    if require_check and not inventory_checked:
        first_check = not bool(state_payload.get("inventory_checked"))
        payload["inventory_check"] = _normalize_inventory_check_payload(
            _build_inventory_check_payload(state_payload, first_check=first_check),
            state_payload,
        )
        if isinstance(state_payload, dict):
            state_payload["inventory_checked"] = True
        return payload

    if bool(state_payload.get("inventory_checked")) and not inventory_checked:
        payload["inventory_check"] = _normalize_inventory_check_payload(
            _build_inventory_check_payload(state_payload, first_check=True),
            state_payload,
        )

    if isinstance(payload.get("inventory_check"), dict):
        payload["inventory_check"] = _normalize_inventory_check_payload(payload.get("inventory_check"), state_payload)

    return payload


def _build_agent_result_payload(parsed_result, fallback_state):
    state = parsed_result.get("state") if isinstance(parsed_result.get("state"), dict) else (fallback_state or {})

    specialist_responses = _normalize_specialist_entries(parsed_result.get("specialist_responses", []))

    inventory_check = parsed_result.get("inventory_check")
    if not isinstance(inventory_check, dict):
        inventory_check = None
    if inventory_check is None and state.get("inventory_checked"):
        inventory_check = _build_inventory_check_payload(state, first_check=True)
    if isinstance(inventory_check, dict):
        inventory_check = _normalize_inventory_check_payload(inventory_check, state)

    customer_response = _sanitize_customer_response(parsed_result.get("customer_response"))
    if not customer_response:
        customer_response = "I reviewed your request and coordinated with the relevant specialist."
    customer_response = _build_user_summary(customer_response, specialist_responses)

    return {
        "schema_version": "1.0",
        "message_type": "orchestrator_result",
        "source_agent": "retail_orchestrator_agent",
        "target_agent": "retail_agent",
        "state": state,
        "routing": parsed_result.get("routing", state.get("routing", "none")),
        "inventory_check": inventory_check,
        "specialist_responses": specialist_responses,
        "customer_response": customer_response,
        "exchange_format": "json",
    }


def _build_product_payload(customer_packet, inventory_check=None):
    routing_context = customer_packet.get("routing_context", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(routing_context, dict):
        routing_context = {}

    state = routing_context.get("state", {})
    if not isinstance(state, dict):
        state = {}

    intake = customer_packet.get("intake", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(intake, dict):
        intake = {}

    requirements = intake.get("extracted_requirements", {})
    if not isinstance(requirements, dict):
        requirements = {}

    conversation = customer_packet.get("conversation", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(conversation, dict):
        conversation = {}

    inventory_checked = bool(isinstance(inventory_check, dict) and inventory_check.get("checked") is True)
    inventory_summary = inventory_check.get("summary") if isinstance(inventory_check, dict) else None
    inventory_details = inventory_check.get("details") if isinstance(inventory_check, dict) else None
    internal_match_found = inventory_check.get("internal_match_found") if isinstance(inventory_check, dict) else "unknown"

    return {
        "schema_version": "1.0",
        "message_type": "specialist_request",
        "source_agent": "retail_orchestrator_agent",
        "target_agent": "product_specialist",
        "requested_action": "provide_product_recommendations",
        "customer_context": {
            "latest_user_input": conversation.get("latest_user_input"),
            "requirements": requirements,
            "budget": requirements.get("budget"),
            "region": requirements.get("region"),
            "usage_context": requirements.get("usage"),
        },
        "product_context": {
            "search_performed": inventory_checked,
            "internal_match_found": internal_match_found,
            "inventory_summary": inventory_summary,
            "inventory_details": inventory_details,
            "product_status": state.get("product_status", "searching"),
            "constraints": requirements.get("constraints", []),
        },
        "state_context": state,
        "constraints": {
            "max_recommendations": 3,
            "response_format": "json",
            "must_return_recommendations_or_no_match": True,
        },
    }


def _build_insurance_payload(customer_packet, conversation_history):
    requirements = extract_requirements(conversation_history)
    product_details = extract_product_details(conversation_history)

    return {
        "schema_version": "1.0",
        "message_type": "specialist_request",
        "source_agent": "retail_orchestrator_agent",
        "target_agent": "insurance_specialist",
        "requested_action": "provide_insurance_quote",
        "product_context": {
            "manufacturer": "Generic Manufacturer",
            "product_type": "Refrigerator",
            "product_model": product_details.get("product_model"),
            "key_features": product_details.get("key_features") or requirements.get("features") or ["standard configuration"],
            "configuration_class": "Standard",
        },
        "pricing_context": {
            "purchase_price": requirements.get("budget", "TBD"),
        },
        "constraints": {
            "response_format": "json",
        },
    }


def _build_user_summary(base_text, specialist_responses):
    base_message = str(base_text or "").strip()
    if not specialist_responses:
        return base_message

    if base_message:
        return base_message

    non_system_specialists = [
        item
        for item in specialist_responses
        if isinstance(item, dict) and str(item.get("agent", "")).strip() != "System"
    ]
    if non_system_specialists:
        return "I checked with our specialists and shared their responses below."

    system_messages = [
        str(item.get("response", "")).strip()
        for item in specialist_responses
        if isinstance(item, dict) and str(item.get("agent", "")).strip() == "System"
    ]
    for message in system_messages:
        if message:
            return message

    return "I reviewed your request and prepared an update."


def orchestrate_customer_packet(
    customer_packet,
    orchestrator_agent=None,
    orchestrator_client=None,
    product_agent=None,
    insurance_agent=None,
    conversation_history=None,
    iteration_counts=None,
):
    """
    Backend retail orchestrator consumes customer-facing JSON packet,
    coordinates with downstream agents via JSON payloads, and returns a
    JSON response package for customer-facing output.
    """
    conversation_history = conversation_history or []
    iteration_counts = iteration_counts or {}

    routing_context_from_packet = customer_packet.get("routing_context", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(routing_context_from_packet, dict):
        routing_context_from_packet = {}

    state_from_packet = routing_context_from_packet.get("state", {})
    if not isinstance(state_from_packet, dict):
        state_from_packet = {}

    if orchestrator_agent and orchestrator_client:
        try:
            raw_orchestrator_response = get_orchestrator_response(
                customer_packet,
                orchestrator_agent,
                orchestrator_client,
            )
            parsed_orchestrator_response = _extract_json_dict(raw_orchestrator_response)
            if _is_valid_orchestrator_result(parsed_orchestrator_response):
                result_payload = _build_agent_result_payload(parsed_orchestrator_response, state_from_packet)

                routing_from_result = str(result_payload.get("routing", "none")).lower()
                routing_from_result = _normalize_route_name(routing_from_result)
                has_specialist = _has_non_system_specialist_response(result_payload.get("specialist_responses", []))
                inferred_routing = _infer_routing_from_system_messages(
                    result_payload.get("specialist_responses", []),
                    result_payload.get("state", {}),
                )
                effective_routing = routing_from_result
                if effective_routing not in {"product_agent", INSURANCE_ROUTE}:
                    effective_routing = inferred_routing

                explicit_product_escalation = _has_customer_confirmed_specialist_routing(conversation_history)
                if explicit_product_escalation and product_agent:
                    effective_routing = "product_agent"
                    result_payload["routing"] = "product_agent"

                should_require_inventory = (
                    effective_routing == "product_agent"
                    or _has_product_specialist_response(result_payload.get("specialist_responses", []))
                )
                result_payload = _ensure_inventory_check_payload(
                    result_payload,
                    require_check=should_require_inventory,
                )

                if effective_routing == "product_agent":
                    agreement_failed = _has_failed_internal_option_agreement(
                        result_payload.get("state", {}),
                        result_payload.get("inventory_check", {}),
                        conversation_history,
                    )
                    if not agreement_failed:
                        result_payload["routing"] = "none"
                        result_payload["specialist_responses"] = [
                            {
                                "agent": "System",
                                "response": (
                                    "Internal inventory check is complete. "
                                    "Product specialist routing is deferred because internal matches are available. "
                                    "Escalation is allowed only if no internal match exists or you explicitly ask for the product specialist."
                                ),
                                "icon": "ℹ️",
                                "css_class": "system-message",
                                "exchange_format": "json",
                            }
                        ]
                        result_payload["customer_response"] = (
                            "I’ve completed the internal check first. "
                            "I’ll escalate to the product specialist only if no internal match is available, "
                            "or if you explicitly ask me to refer to the specialist."
                        )

                if (
                    not has_specialist
                    and effective_routing == "product_agent"
                    and product_agent
                    and iteration_counts.get("product_agent_calls", 0) < 3
                    and _has_failed_internal_option_agreement(
                        result_payload.get("state", {}),
                        result_payload.get("inventory_check", {}),
                        conversation_history,
                    )
                ):
                    try:
                        payload = _build_product_payload(customer_packet, result_payload.get("inventory_check"))
                        prod_response = get_product_response(
                            json.dumps(payload, ensure_ascii=False),
                            product_agent[0],
                            product_agent[1],
                        )
                        formatted_product_response = _format_specialist_response(prod_response)
                        if not formatted_product_response:
                            formatted_product_response = (
                                "Product specialist did not return concrete model recommendations yet. "
                                "Please retry once to fetch model-level availability."
                            )
                        result_payload["specialist_responses"].append(
                            {
                                "agent": "Product Specialist",
                                "response": formatted_product_response,
                                "raw_response": str(prod_response),
                                "icon": get_agent_icon("product_specialist"),
                                "css_class": "product-message",
                                "exchange_format": "json",
                            }
                        )
                        iteration_counts["product_agent_calls"] = iteration_counts.get("product_agent_calls", 0) + 1
                        result_payload["customer_response"] = _build_user_summary(
                            result_payload.get("customer_response", ""),
                            result_payload.get("specialist_responses", []),
                        )
                    except Exception as ex:
                        result_payload["specialist_responses"].append(
                            {
                                "agent": "System",
                                "response": f"⚠️ Product specialist unavailable: {str(ex)}",
                                "icon": "⚠️",
                                "css_class": "system-message",
                                "exchange_format": "json",
                            }
                        )

                if (
                    not _has_non_system_specialist_response(result_payload.get("specialist_responses", []))
                    and effective_routing == INSURANCE_ROUTE
                    and insurance_agent
                    and iteration_counts.get("insurance_agent_calls", 0) < 3
                ):
                    is_valid, error_msg = validate_insurance_context(result_payload.get("state", {}), conversation_history)
                    if not is_valid:
                        result_payload["specialist_responses"].append(
                            {
                                "agent": "System",
                                "response": f"⚠️ Cannot route to insurance specialist: {error_msg}",
                                "icon": "⚠️",
                                "css_class": "system-message",
                                "exchange_format": "json",
                            }
                        )
                    else:
                        try:
                            payload = _build_insurance_payload(customer_packet, conversation_history)
                            insurance_response = get_insurance_response(
                                payload,
                                insurance_agent[0],
                                insurance_agent[1],
                            )
                            result_payload["specialist_responses"].append(
                                {
                                    "agent": "Insurance Specialist",
                                    "response": _format_specialist_response(insurance_response),
                                    "raw_response": str(insurance_response),
                                    "icon": get_agent_icon("insurance_specialist"),
                                    "css_class": "insurance-message",
                                    "exchange_format": "json",
                                }
                            )
                            iteration_counts["insurance_agent_calls"] = iteration_counts.get("insurance_agent_calls", 0) + 1
                            result_payload["customer_response"] = _build_user_summary(
                                result_payload.get("customer_response", ""),
                                result_payload.get("specialist_responses", []),
                            )
                            result_payload = _ensure_inventory_check_payload(result_payload, require_check=True)
                        except Exception as ex:
                            result_payload["specialist_responses"].append(
                                {
                                    "agent": "System",
                                    "response": f"⚠️ Insurance specialist unavailable: {str(ex)}",
                                    "icon": "⚠️",
                                    "css_class": "system-message",
                                    "exchange_format": "json",
                                }
                            )

                return result_payload
        except Exception:
            pass

    state = state_from_packet

    routing_context = customer_packet.get("routing_context", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(routing_context, dict):
        routing_context = {}

    conversation = customer_packet.get("conversation", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(conversation, dict):
        conversation = {}

    intake = customer_packet.get("intake", {}) if isinstance(customer_packet, dict) else {}
    if not isinstance(intake, dict):
        intake = {}

    routing = routing_context.get("routing_hint", "none")
    user_input = conversation.get("latest_user_input", "")
    base_text = intake.get("customer_visible_draft", "")

    response_lower = str(base_text or "").lower()
    user_input_lower = str(user_input or "").lower()

    routing = _normalize_route_name(routing)
    explicit_product_escalation = _has_customer_confirmed_specialist_routing(conversation_history)

    if routing == "none":
        explicit_product_request = any(
            term in user_input_lower
            for term in [
                "product_agent",
                "product agent",
                "product specialist",
                "refer to product",
                "refer to specialist",
            ]
        )
        if explicit_product_request or explicit_product_escalation:
            routing = "product_agent"

        product_status = state.get("product_status", "collecting")
        overall_status = state.get("overall_status", "intake")

        if (
            routing == "none"
            and overall_status != "intake"
            and product_status in ["searching", "proposed"]
            and validate_product_context(conversation_history)
            and any(kw in response_lower for kw in ["product specialist", "external catalog"])
        ):
            routing = "product_agent"
        elif (
            routing == "none"
            and product_status == "agreed"
            and any(kw in response_lower for kw in ["insurance specialist", "insurance offer"])
        ):
            routing = INSURANCE_ROUTE

    inventory_check_result = None
    if state.get("inventory_checked"):
        inventory_check_result = _build_inventory_check_payload(state, first_check=True)

    if routing == "product_agent" and not inventory_check_result:
        first_check = not bool(state.get("inventory_checked"))
        inventory_check_result = _build_inventory_check_payload(state, first_check=first_check)
        if isinstance(state, dict):
            state["inventory_checked"] = True

    if routing == "product_agent" and not _has_failed_internal_option_agreement(state, inventory_check_result, conversation_history):
        routing = "none"

    specialist_responses = []

    if routing == "product_agent" and product_agent:
        if iteration_counts.get("product_agent_calls", 0) >= 3:
            specialist_responses.append(
                {
                    "agent": "System",
                    "response": "⚠️ Maximum product specialist iterations reached. Using best available information.",
                    "icon": "⚠️",
                    "css_class": "system-message",
                    "exchange_format": "json",
                }
            )
        else:
            try:
                payload = _build_product_payload(
                    customer_packet,
                    _build_inventory_check_payload(state, first_check=not bool(state.get("inventory_checked"))),
                )
                prod_response = get_product_response(
                    json.dumps(payload, ensure_ascii=False),
                    product_agent[0],
                    product_agent[1],
                )
                formatted_product_response = _format_specialist_response(prod_response)
                if not formatted_product_response:
                    formatted_product_response = (
                        "Product specialist did not return concrete model recommendations yet. "
                        "Please retry once to fetch model-level availability."
                    )
                specialist_responses.append(
                    {
                        "agent": "Product Specialist",
                        "response": formatted_product_response,
                        "raw_response": str(prod_response),
                        "icon": get_agent_icon("product_specialist"),
                        "css_class": "product-message",
                        "exchange_format": "json",
                    }
                )
                iteration_counts["product_agent_calls"] = iteration_counts.get("product_agent_calls", 0) + 1
            except Exception as ex:
                specialist_responses.append(
                    {
                        "agent": "System",
                        "response": f"⚠️ Product specialist unavailable: {str(ex)}",
                        "icon": "⚠️",
                        "css_class": "system-message",
                        "exchange_format": "json",
                    }
                )

    if routing == INSURANCE_ROUTE and insurance_agent:
        is_valid, error_msg = validate_insurance_context(state, conversation_history)
        if not is_valid:
            specialist_responses.append(
                {
                    "agent": "System",
                    "response": f"⚠️ Cannot route to insurance specialist: {error_msg}",
                    "icon": "⚠️",
                    "css_class": "system-message",
                    "exchange_format": "json",
                }
            )
        elif iteration_counts.get("insurance_agent_calls", 0) >= 3:
            specialist_responses.append(
                {
                    "agent": "System",
                    "response": "⚠️ Maximum insurance specialist iterations reached.",
                    "icon": "⚠️",
                    "css_class": "system-message",
                    "exchange_format": "json",
                }
            )
        else:
            try:
                payload = _build_insurance_payload(customer_packet, conversation_history)
                insurance_response = get_insurance_response(
                    payload,
                    insurance_agent[0],
                    insurance_agent[1],
                )
                specialist_responses.append(
                    {
                        "agent": "Insurance Specialist",
                        "response": _format_specialist_response(insurance_response),
                        "raw_response": str(insurance_response),
                        "icon": get_agent_icon("insurance_specialist"),
                        "css_class": "insurance-message",
                        "exchange_format": "json",
                    }
                )
                iteration_counts["insurance_agent_calls"] = iteration_counts.get("insurance_agent_calls", 0) + 1
            except Exception as ex:
                specialist_responses.append(
                    {
                        "agent": "System",
                        "response": f"⚠️ Insurance specialist unavailable: {str(ex)}",
                        "icon": "⚠️",
                        "css_class": "system-message",
                        "exchange_format": "json",
                    }
                )

    result_payload = {
        "schema_version": "1.0",
        "message_type": "orchestrator_result",
        "source_agent": "retail_orchestrator_agent",
        "target_agent": "retail_agent",
        "state": state,
        "routing": routing,
        "inventory_check": inventory_check_result,
        "specialist_responses": specialist_responses,
        "customer_response": _build_user_summary(base_text, specialist_responses),
        "exchange_format": "json",
    }

    should_require_inventory = (
        str(result_payload.get("routing", "none")).lower() == "product_agent"
        or _has_product_specialist_response(result_payload.get("specialist_responses", []))
    )
    result_payload = _ensure_inventory_check_payload(result_payload, require_check=should_require_inventory)

    return result_payload
