from langchain_openai import OpenAI
from langchain_anthropic import Anthropic
from langchain.agents import ZeroShotAgent, AgentExecutor
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain
from typing import Any, Dict

from app.tools import create_bullet_points_tool, create_pptx_code_tool, create_quality_check_tool


class PresentationAgent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools
        self.memory = ConversationBufferMemory(memory_key="chat_history")

        prefix = """You are an expert presentation creation assistant. Your goal is to create professional, 
        engaging PowerPoint presentations. You have access to the following tools:"""

        suffix = """Follow these steps for each request:
        1. Analyze the input content and requirements
        2. Plan the presentation structure
        3. Create detailed bullet points and design specifications
        4. Generate and validate the presentation code
        5. Review and optimize the final output

        Previous conversation history:
        {chat_history}

        Current task: {input}
        {agent_scratchpad}"""

        prompt = ZeroShotAgent.create_prompt(
            tools=tools,
            prefix=prefix,
            suffix=suffix,
            input_variables=["input", "chat_history", "agent_scratchpad"]
        )

        self.chain = LLMChain(llm=llm, prompt=prompt)
        self.agent = ZeroShotAgent(llm_chain=self.chain, tools=tools)
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=self.agent,
            tools=tools,
            memory=self.memory,
            verbose=True,
            max_iterations=5
        )

    def run(self, user_input: str, style: str) -> Dict:
        """Execute the presentation creation process with planning."""
        # First, create a plan
        planning_prompt = f"""
        Create a detailed plan for converting this content into a presentation:
        Content: {user_input}
        Style: {style}

        Return the plan in JSON format with specific steps and requirements.
        """

        plan = self.llm.predict(planning_prompt)

        # Execute the plan
        result = self.agent_executor.run(
            input=f"""
            Following this plan: {plan}
            Create a presentation with this content: {user_input}
            Using this style: {style}
            """
        )

        return result


def create_agent(llm_provider: str, api_key: str, rag_system: Any) -> PresentationAgent:
    """Creates a presentation agent with all specialized tools."""

    if llm_provider == "OpenAI":
        llm = OpenAI(api_key=api_key)
    elif llm_provider == "Anthropic":
        llm = Anthropic(api_key=api_key)
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_provider}")

    tools = [
        create_bullet_points_tool(llm),
        create_pptx_code_tool(llm, rag_system),
        create_quality_check_tool(llm)
    ]

    return PresentationAgent(llm=llm, tools=tools)
