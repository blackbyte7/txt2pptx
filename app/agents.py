from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from typing import Dict, Any, List, Tuple

from app.tools import create_bullet_points_tool, create_pptx_code_tool, create_quality_check_tool


class PresentationAgent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools

        # Create the prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert presentation creation assistant. Your goal is to create professional,
            engaging PowerPoint presentations.

            Follow these steps for each request:
            1. Analyze the input content and requirements
            2. Plan the presentation structure
            3. Create detailed bullet points and design specifications
            4. Generate and validate the presentation code
            5. Review and optimize the final output"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        # Create the agent using LangGraph's create_react_agent
        self.agent = create_react_agent(
            llm,
            tools,
            self.prompt
        )

    def run(self, user_input: str, style: str) -> Dict:
        """Execute the presentation creation process with planning."""
        # Planning stage using LCEL
        planning_prompt = ChatPromptTemplate.from_template("""
        Create a detailed plan for converting this content into a presentation:
        Content: {user_input}
        Style: {style}

        Return the plan in JSON format with specific steps and requirements.
        """)

        planning_chain = (
            RunnablePassthrough.assign(
                plan=lambda x: self.llm.invoke(
                    planning_prompt.format(
                        user_input=x['user_input'],
                        style=x['style']
                    )
                )
            )
        )

        # Combine planning and agent execution
        full_chain = (
                planning_chain
                | RunnablePassthrough.assign(
            output=lambda x: self.agent.invoke({
                "input": f"""
                    Following this plan: {x['plan']}
                    Create a presentation with this content: {x['user_input']}
                    Using this style: {x['style']}
                    """,
                "chat_history": []
            })['output']
        )
        )

        return full_chain.invoke({
            "user_input": user_input,
            "style": style
        })


def create_agent(llm_provider: str, api_key: str, rag_system: Any) -> PresentationAgent:
    """Creates a presentation agent with all specialized tools."""
    if llm_provider == "OpenAI":
        llm = ChatOpenAI(api_key=api_key, model="gpt-3.5-turbo-0125")
    elif llm_provider == "Anthropic":
        llm = ChatAnthropic(api_key=api_key, model_name="claude-3-opus-20240229")
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_provider}")

    tools = [
        create_bullet_points_tool(llm_provider, api_key),
        create_pptx_code_tool(llm_provider, api_key, rag_system),
        create_quality_check_tool(llm_provider, api_key)
    ]

    return PresentationAgent(llm=llm, tools=tools)

