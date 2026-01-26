import streamlit as st
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.projects import AIProjectClient
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv("analysis_agent.env")

# Webpage configurations
st.set_page_config(page_title="Agentic AI Interface", page_icon=":bot:")
st.title("Agentic AI Interface")
st.write("Welcome to the Agentic AI interface. Configure your agent and interact with it below.")

# Define custom CSS for styling
custom_css = """
<style>
/*body {
    background-image: url('https://wallpaper.dog/large/10991978.jpg');
    background-size: cover;
    background-repeat: no-repeat;
    opacity: 0.85;
}*/

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

/* Bot icon for chat messages */
.stChatMessage [data-testid="chatAvatarIcon-assistant"]::before {
    content: "🤖";
    font-size: 24px;
}
</style>
"""

# Apply the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Add floating bot icon
st.markdown('<div class="bot-icon">🤖</div>', unsafe_allow_html=True)

# Initialize Azure AI agent
@st.cache_resource
def initialize_agent():
    # Load endpoint from environment
    myEndpoint = os.getenv("AZURE_EXISTING_AIPROJECT_ENDPOINT")
    if not myEndpoint:
        myEndpoint = "https://agentic-innovation-day-resource.services.ai.azure.com/api/projects/agentic-innovation-day"
    
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    # Use InteractiveBrowserCredential with specific tenant
    # This will open a browser window for authentication to the correct tenant
    credential = InteractiveBrowserCredential(
        tenant_id=tenant_id if tenant_id else "92b47701-5969-4434-887e-ff0df53842ab",
        additionally_allowed_tenants=["*"]
    )
    
    project_client = AIProjectClient(
        endpoint=myEndpoint,
        credential=credential,
    )
    myAgent = "analysis-agent"
    agent = project_client.agents.get(agent_name=myAgent)
    openai_client = project_client.get_openai_client()
    return agent, openai_client

try:
    agent, openai_client = initialize_agent()
    agent_initialized = True
except Exception as e:
    agent_initialized = False
    st.error(f"Failed to initialize agent: {str(e)}")
    st.info("Falling back to placeholder responses.")

def get_agent_response(user_input):
    """Get response from Azure AI agent"""
    if not agent_initialized:
        return f"Agent not initialized. Your message: '{user_input}'"
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": user_input}],
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
        return response.output_text
    except Exception as e:
        return f"Error getting response: {str(e)}"

# Initialize session state for chat messages
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "How can I help you?"}]

# Reset chat history button
if st.sidebar.button("Reset chat history"):
    st.session_state.messages = [{"role": "assistant", "content": "How can I help you?"}]
    st.rerun()

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Receive user input and generate response
if prompt := st.chat_input(placeholder="Ask me anything..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    
    # Generate response from Azure AI agent
    with st.spinner("Thinking..."):
        response = get_agent_response(prompt)
    
    # Add assistant response
    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.write(response)
    
    st.rerun()