# Agent Orchestrator
# Triages requests between different specialized agents

import re

class AgentOrchestrator:
    """Orchestrates requests between analysis, product, manufacturing, and finance agents"""
    
    def __init__(self):
        self.thinking_steps = []
    
    def triage_request(self, user_input):
        """
        Analyze user input and determine which agent should handle it
        Returns: (agent_name, reasoning)
        """
        self.thinking_steps = []
        user_input_lower = user_input.lower()
        
        # Step 1: Initial analysis
        self.thinking_steps.append("🔍 Analyzing user query...")
        
        # Keywords for each agent domain
        product_keywords = [
            'product', 'feature', 'design', 'specification', 'quality',
            'development', 'release', 'roadmap', 'innovation', 'prototype'
        ]
        
        manufacturing_keywords = [
            'manufacturing', 'production', 'assembly', 'inventory', 'supply',
            'operations', 'factory', 'capacity', 'process', 'equipment', 'workflow'
        ]
        
        finance_keywords = [
            'cost', 'price', 'budget', 'finance', 'revenue', 'profit',
            'expense', 'investment', 'roi', 'financial', 'accounting', 'payment'
        ]
        
        # Count keyword matches
        product_score = sum(1 for kw in product_keywords if kw in user_input_lower)
        manufacturing_score = sum(1 for kw in manufacturing_keywords if kw in user_input_lower)
        finance_score = sum(1 for kw in finance_keywords if kw in user_input_lower)
        
        # Step 2: Keyword matching
        self.thinking_steps.append(
            f"📊 Domain scores - Product: {product_score}, "
            f"Manufacturing: {manufacturing_score}, Finance: {finance_score}"
        )
        
        # Step 3: Decision
        max_score = max(product_score, manufacturing_score, finance_score)
        
        if max_score == 0:
            self.thinking_steps.append("❓ No specific domain detected, using general analysis")
            return "analysis", "Query requires general analysis"
        
        if product_score == max_score:
            self.thinking_steps.append("✅ Routing to Product Agent - Product-related query detected")
            return "product", f"Product keywords found: {product_score} matches"
        elif manufacturing_score == max_score:
            self.thinking_steps.append("✅ Routing to Manufacturing Agent - Operations query detected")
            return "manufacturing", f"Manufacturing keywords found: {manufacturing_score} matches"
        else:
            self.thinking_steps.append("✅ Routing to Finance Agent - Financial query detected")
            return "finance", f"Finance keywords found: {finance_score} matches"
    
    def get_thinking_process(self):
        """Return the thinking steps as a formatted string"""
        return "\n\n".join(self.thinking_steps)
