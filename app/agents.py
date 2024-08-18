from langchain.agents import ZeroShotAgent
from langchain_openai import OpenAI


def create_agent(tools):
    try:
        llm = OpenAI(api_key="YOUR_API_KEY")
        agent = ZeroShotAgent(llm=llm, tools=tools)
        return agent
    except Exception as e:
        print(f"Error creating agent: {str(e)}")
        raise
