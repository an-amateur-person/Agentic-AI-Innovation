# Agentic AI Innovation - Multi-Agent System

An intelligent Streamlit application that uses Azure AI agents with AI-powered orchestration to handle different types of queries.

## 🤖 Agent Architecture

### Analysis Agent (AI-Powered Orchestrator)
- **Role**: Intelligent triage and general analysis
- **Function**: 
  - Receives user input and uses AI to understand context and intent
  - Routes requests to appropriate specialist agents based on semantic understanding
  - Handles general queries directly
  - Provides detailed reasoning for routing decisions
- **Display**: Shows complete thinking process in the UI
- **Advantages**: 
  - Smarter than keyword matching
  - Understands nuanced and complex queries
  - Adapts to context

### Specialized Agents

1. **Product Agent** 🔧
   - Handles product-related queries
   - Topics: product features, design, specifications, quality, development, releases, roadmap

2. **Manufacturing Agent** 🏭
   - Handles manufacturing and operations queries
   - Topics: production, assembly, inventory, supply chain, factory processes, capacity

3. **Finance Agent** 💰
   - Handles financial and budget queries
   - Topics: costs, pricing, budget, revenue, profit, expenses, investments, ROI

## 🚀 Features

- ✅ **AI-Powered Routing** - Analysis agent uses LLM for intelligent query triage
- ✅ **Semantic Understanding** - Goes beyond keywords to understand intent
- ✅ **Thinking Process Visualization** - See how the AI makes routing decisions
- ✅ **Floating bot icon** with animation
- ✅ **Chat history** with reset functionality
- ✅ **Azure AI integration** with browser-based authentication
- ✅ **Agent status monitoring** in sidebar
- ✅ **Graceful fallbacks** - Works even if specialist agents aren't configured

## 📦 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/an-amateur-person/Agentic-AI-Innovation.git
   cd Agentic-AI-Innovation
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   ```

3. **Activate virtual environment**
   
   Windows PowerShell:
   ```bash
   Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
   .\.venv\Scripts\Activate.ps1
   ```
   
   Or directly run without activation:
   ```bash
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your Azure credentials:
   - `AZURE_TENANT_ID` - Your Azure tenant ID
   - `AZURE_SUBSCRIPTION_ID` - Your Azure subscription ID
   - `AZURE_AIPROJECT_ENDPOINT` - Your Azure AI project endpoint
   - `AZURE_LOCATION` - Azure region (e.g., swedencentral)
   - Agent names (default values provided)

## 🏃 Running the Application

```bash
.\.venv\Scripts\streamlit.exe run agentic_ai.py
```

Or if virtual environment is activated:
```bash
streamlit run agentic_ai.py
```

The app will open at `http://localhost:8501`

## 🔐 Authentication

The application uses `InteractiveBrowserCredential` for Azure authentication:
1. When you run the app, a browser window will open
2. Sign in with your Microsoft account that has access to the Azure AI resources
3. Grant necessary permissions
4. The app will authenticate and connect to your Azure AI agents

## 📁 Project Structure

```
Agentic-AI-Innovation/
├── agentic_ai.py                 # Main Streamlit application
├── requirements.txt              # Python dependencies
├── .env                          # Environment configuration (not in git)
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore rules
├── agents/
│   ├── analysis_agent.py         # Original Azure AI setup code
│   ├── product_agent.py          # Product specialist
│   ├── manufacturing_agent.py    # Manufacturing specialist
│   └── finance_agent.py          # Finance specialist
└── .venv/                        # Virtual environment
```

**Note:** 
- `.env` contains your actual credentials and is excluded from git
- `analysis_agent.env` is deprecated - use `.env` instead
- All hardcoded values have been removed - everything uses environment variables

## 💡 Usage Examples

**Product Query:**
```
"What are the features of our new product line?"
```
→ Routes to Product Agent

**Manufacturing Query:**
```
"What is our current production capacity?"
```
→ Routes to Manufacturing Agent

**Finance Query:**
```
"What's our budget for Q2?"
```
→ Routes to Finance Agent

**General Query:**
```
"Give me an overview of company operations"
```
→ Handled by Analysis Agent

## 🛠️ Customization

### Adding New Agents

1. Create a new agent file in `agents/` directory
2. Implement `initialize_*_agent()` and `get_*_response()` functions
3. Update the Analysis Agent's system prompt in Azure to recognize new agent types
4. Add initialization in `agentic_ai.py`

### Configuring Analysis Agent for Triage

In Azure AI Studio, configure the Analysis Agent with this system prompt:

```
You are an intelligent triage agent for a multi-agent system. Analyze user queries and determine which specialist should handle them:

- PRODUCT: product features, design, specifications, quality, development, releases
- MANUFACTURING: production, operations, inventory, supply chain, factory processes
- FINANCE: costs, pricing, budget, revenue, expenses, investments, financial planning
- GENERAL: queries that don't fit above or need general analysis

Respond in JSON format with agent type, reasoning, and confidence level.
```

## 📊 Agent Status

The sidebar displays real-time status of all agents:
- ✅ Green: Agent initialized successfully
- ⚠️ Yellow: Agent not configured (uses placeholder)
- ❌ Red: Initialization error

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License

MIT License - feel free to use and modify

## 🆘 Troubleshooting

**Streamlit command not found:**
```bash
.\.venv\Scripts\streamlit.exe run agentic_ai.py
```

**PowerShell execution policy error:**
```bash
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
```

**Authentication errors:**
- Ensure you're logged in with the correct tenant
- Check `AZURE_TENANT_ID` in `.env`
- Verify you have access to the Azure AI resources
- Make sure `.env` file exists and is properly configured

**Missing environment variables:**
- Copy `.env.example` to `.env`
- Fill in all required values
- Never commit `.env` to git (it's in .gitignore)

---

Built with ❤️ using Streamlit and Azure AI
