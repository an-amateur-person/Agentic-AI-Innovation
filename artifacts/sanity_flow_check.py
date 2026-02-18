from agents.retail_orchestrator_agent import orchestrate_customer_packet

# Scenario 1: Product routing requested, but no failed internal agreement yet
packet1 = {
    "routing_context": {
        "state": {
            "product_status": "searching",
            "insurance_status": "not_offered",
            "overall_status": "inventory_check",
            "routing": "product_agent",
            "inventory_checked": False,
            "iteration_count": 1,
        },
        "routing_hint": "product_agent",
    },
    "conversation": {"latest_user_input": "Need a built-in fridge in Munich around 1000 EUR"},
    "intake": {
        "customer_visible_draft": "Proceeding with product search.",
        "extracted_requirements": {
            "budget": "1000 EUR",
            "region": "Germany",
            "usage": "family of 3",
            "features": ["built-in"],
            "constraints": ["standard niche"],
        },
    },
}
res1 = orchestrate_customer_packet(packet1, None, None, (None, None), (None, None), [], {"product_agent_calls": 0, "insurance_agent_calls": 0})

# Scenario 2: Customer rejects internal options, then product routing should proceed
history2 = [{"role": "user", "content": "none of these internal options work, show more options"}]
packet2 = {
    "routing_context": {
        "state": {
            "product_status": "searching",
            "insurance_status": "not_offered",
            "overall_status": "inventory_check",
            "routing": "product_agent",
            "inventory_checked": True,
            "iteration_count": 2,
        },
        "routing_hint": "product_agent",
    },
    "conversation": {"latest_user_input": "show more options"},
    "intake": {
        "customer_visible_draft": "Customer asked for more options.",
        "extracted_requirements": {
            "budget": "1000 EUR",
            "region": "Germany",
            "usage": "family of 3",
            "features": ["built-in"],
            "constraints": ["standard niche"],
        },
    },
}
res2 = orchestrate_customer_packet(packet2, None, None, (None, None), (None, None), history2, {"product_agent_calls": 0, "insurance_agent_calls": 0})

# Scenario 3: Intake only (no specialist route)
packet3 = {
    "routing_context": {
        "state": {
            "product_status": "collecting",
            "insurance_status": "not_offered",
            "overall_status": "intake",
            "routing": "none",
            "inventory_checked": False,
            "iteration_count": 1,
        },
        "routing_hint": "none",
    },
    "conversation": {"latest_user_input": "looking for fridge"},
    "intake": {
        "customer_visible_draft": "Need more details before search.",
        "extracted_requirements": {
            "budget": None,
            "region": None,
            "usage": None,
            "features": [],
            "constraints": [],
        },
    },
}
res3 = orchestrate_customer_packet(packet3, None, None, (None, None), (None, None), [], {"product_agent_calls": 0, "insurance_agent_calls": 0})

print("SCENARIO_1")
print({
    "routing": res1.get("routing"),
    "inventory_checked": bool((res1.get("inventory_check") or {}).get("checked")),
    "specialists": [s.get("agent") for s in res1.get("specialist_responses", [])],
})

print("SCENARIO_2")
print({
    "routing": res2.get("routing"),
    "inventory_checked": bool((res2.get("inventory_check") or {}).get("checked")),
    "specialists": [s.get("agent") for s in res2.get("specialist_responses", [])],
})

print("SCENARIO_3")
print({
    "routing": res3.get("routing"),
    "inventory_checked": bool((res3.get("inventory_check") or {}).get("checked")),
    "specialists": [s.get("agent") for s in res3.get("specialist_responses", [])],
})
