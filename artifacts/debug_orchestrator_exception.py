import traceback

from agents.retail_agent import initialize_customer_facing_agent, collect_customer_input_packet
from agents.retail_orchestrator_agent import initialize_orchestrator_agent, orchestrate_customer_packet
from agents.product_agent import initialize_product_agent
from agents.insurance_agent import initialize_insurance_agent


def main():
    user_input = "looking for a fridge in munich, family kitchen - 3 people, around 1000, classic built-in fridge-freezer, standard size, no brand preferences, flexible with timeline, standard niche"

    customer_agent, customer_client, project_client = initialize_customer_facing_agent()
    orchestrator_agent, orchestrator_client = initialize_orchestrator_agent(project_client)
    product_agent = initialize_product_agent()
    insurance_agent = initialize_insurance_agent()

    history = []
    counts = {
        "customer_clarifications": 0,
        "product_agent_calls": 0,
        "insurance_agent_calls": 0,
    }

    packet = collect_customer_input_packet(
        user_input,
        customer_agent,
        customer_client,
        history,
        counts,
    )

    print("PACKET_READY")
    try:
        result = orchestrate_customer_packet(
            packet,
            orchestrator_agent,
            orchestrator_client,
            product_agent,
            insurance_agent,
            history,
            counts,
        )
        print("RESULT_TYPE", type(result).__name__)
        if isinstance(result, dict):
            print("RESULT_KEYS", sorted(result.keys()))
            print("ROUTING", result.get("routing"))
            print("INVENTORY_CHECK", result.get("inventory_check"))
            print("SPECIALISTS", [s.get("agent") for s in result.get("specialist_responses", []) if isinstance(s, dict)])
        else:
            print("RAW_RESULT", result)
    except Exception:
        print("ORCHESTRATOR_EXCEPTION")
        traceback.print_exc()


if __name__ == "__main__":
    main()
