from langchain.agents import ZeroShotAgent
from langchain_openai import OpenAI
from langchain_anthropic import Anthropic


def create_agent(tools, llm_provider, api_key):
    try:
        if llm_provider == "OpenAI":
            llm = OpenAI(api_key=api_key)
        elif llm_provider == "Anthropic":
            llm = Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        agent = ZeroShotAgent(llm=llm, tools=tools)
        return agent
    except Exception as e:
        print(f"Error creating agent: {str(e)}")
        raise
