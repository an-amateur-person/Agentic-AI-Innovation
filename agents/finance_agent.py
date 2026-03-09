"""Finance Agent.

Handles finance and budget-related queries.
"""

import json
import os

from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

from .utilities import create_azure_credential


load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=False)


def initialize_finance_agent():
	"""Initialize the finance specialist agent."""
	endpoint = os.getenv("AZURE_AIPROJECT_ENDPOINT")
	tenant_id = os.getenv("AZURE_TENANT_ID")

	if not endpoint:
		raise ValueError("Missing required environment variable: AZURE_AIPROJECT_ENDPOINT")

	credential = create_azure_credential(tenant_id)
	project_client = AIProjectClient(endpoint=endpoint, credential=credential)

	agent_name = os.getenv("AGENT_FINANCE", "finance-agent")
	try:
		agent = project_client.agents.get(agent_name=agent_name)
	except Exception:
		agent = None

	openai_client = project_client.get_openai_client()
	return agent, openai_client


def get_finance_response(user_input, agent, openai_client):
	"""Get response from finance specialist agent."""
	payload = user_input
	if isinstance(user_input, (dict, list)):
		payload = json.dumps(user_input, ensure_ascii=False)

	if not agent:
		return f"Finance Specialist: Analyzing finance query - '{payload}'"

	try:
		response = openai_client.responses.create(
			input=[{"role": "user", "content": payload}],
			extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
		)
		return response.output_text
	except Exception as exc:
		return f"Finance Specialist Error: {str(exc)}"


__all__ = ["initialize_finance_agent", "get_finance_response"]
