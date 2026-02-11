# Agentic AI Innovation - Product Agent System

An intelligent Streamlit application where customers interact directly with a Product Agent that coordinates with specialized teams (Manufacturing and Finance) when needed.

## 🤖 Agent Architecture

### Product Agent (Primary Interface) 🤖
- **Role**: Main customer-facing agent
- **Function**: 
  - Directly handles all customer interactions
  - Analyzes customer queries to understand their needs
  - Coordinates with specialist agents when expertise is needed
  - Provides comprehensive responses combining product knowledge with specialist input
  - Maintains conversation context and history
- **Display**: Shows coordination process and specialist consultations
- **Advantages**: 
  - Single point of contact for customers
  - Seamless specialist coordination
  - Context-aware responses
  - Efficient query handling

### Specialist Agents (Support Teams)

1. **Manufacturing Agent** 🏭
   - Consulted for: production, assembly, inventory, supply chain, factory processes, capacity
   - Provides specialist input when manufacturing topics are mentioned

2. **Finance Agent** 💰
   - Consulted for: costs, pricing, budget, revenue, profit, expenses, investments, ROI
   - Provides specialist input when financial topics are mentioned

## 🚀 Features

- ✅ **Direct Customer Interaction** - Customers chat directly with Product Agent
- ✅ **Smart Coordination** - Product Agent automatically consults specialists when needed
- ✅ **Context-Aware** - Maintains conversation history for better responses
- ✅ **Transparent Process** - See when and why specialists are consulted
- ✅ **Proposal Generation** - Create PDF proposals from conversations
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
   - `AGENT_PRODUCT` - Product Agent name (primary)
   - `AGENT_MANUFACTURING` - Manufacturing Agent name (specialist)
   - `AGENT_FINANCE` - Finance Agent name (specialist)

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
├── agentic_ai.py                 # Main Streamlit application with Product Agent interface
├── requirements.txt              # Python dependencies
├── .env                          # Environment configuration (not in git)
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore rules
├── agents/
│   ├── product_agent.py          # Product Agent (primary customer interface)
│   ├── manufacturing_agent.py    # Manufacturing specialist (support)
│   ├── finance_agent.py          # Finance specialist (support)
│   └── orchestrator.py           # DEPRECATED - no longer used
└── .venv/                        # Virtual environment
```

**Note:** 
- `.env` contains your actual credentials and is excluded from git
- `orchestrator.py` is deprecated - Product Agent now handles coordination
- All hardcoded values have been removed - everything uses environment variables

## 💡 Usage Examples

**Product Inquiry:**
```
"Tell me about the features of your latest product"
```
→ Product Agent responds directly

**Manufacturing Question:**
```
"What's the production timeline and capacity for bulk orders?"
```
→ Product Agent consults Manufacturing specialist and provides comprehensive answer

**Financial Inquiry:**
```
"What's the pricing for enterprise licensing?"
```
→ Product Agent consults Finance specialist and provides detailed pricing

**Combined Query:**
```
"Can you produce 10,000 units and what would the cost be?"
```
→ Product Agent consults both Manufacturing and Finance specialists

## 🛠️ How It Works

### Query Flow

1. **Customer asks a question** → Product Agent receives it
2. **Analysis** → Product Agent analyzes if specialist input is needed
3. **Coordination** → Consults Manufacturing/Finance agents if relevant topics detected
4. **Response** → Product Agent synthesizes all information into comprehensive answer

### Specialist Detection

Product Agent automatically detects when to consult specialists based on keywords:
- **Manufacturing**: production, inventory, supply, operations, capacity, assembly
- **Finance**: cost, price, budget, revenue, expense, investment, ROI

## 📊 Agent Status

The sidebar displays real-time status of all agents:
- ✅ Green: Agent initialized successfully (Product Agent is required)
- ⚠️ Yellow: Specialist not configured (system still works, limited capabilities)
- ❌ Red: Initialization error

**Agent Roles:**
- **Product Agent (Primary)** - Must be configured for system to work
- **Manufacturing & Finance (Specialists)** - Optional, consulted when needed

## 🎯 Key Changes from Previous Version

- ❌ **Removed**: Analysis Agent / Orchestrator - no longer needed
- ✅ **Simplified**: Direct customer → Product Agent interaction
- ✅ **Enhanced**: Product Agent now coordinates with specialists automatically
- ✅ **Improved**: Single conversation thread, better context retention
- ✅ **Streamlined**: Reduced complexity, faster responses

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

**Product Agent not responding:**
- Verify `AGENT_PRODUCT` is correctly set in `.env`
- Check that the agent exists in your Azure AI project
- Specialist agents are optional - system works without them but with reduced capabilities

---

Built with ❤️ using Streamlit and Azure AI
