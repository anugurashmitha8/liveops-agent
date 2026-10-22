import os
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])

def generator(prompt, system_prompt=None):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    res = client.chat.completions.create(
        model=os.environ["MODEL"], messages=messages, temperature=0.2)
    return res.choices[0].message.content

if __name__ == "__main__":
    print(generator("Say hello in 5 words."))