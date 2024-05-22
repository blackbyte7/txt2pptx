from langchain.agents import ZeroShotAgent
from langchain.llms import OpenAI


def create_agent(tools):
    llm = OpenAI(api_key="YOUR_API_KEY")
    agent = ZeroShotAgent(llm=llm, tools=tools)
    return agent
