# from google import genai
# from dotenv import load_dotenv
# import os

# load_dotenv("details.env")

# client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# response = client.models.generate_content(
#     model="gemini-2.5-flash",
#     contents="Say hello in one sentence!"
# )

# print(response.text)
# from dotenv import load_dotenv
# import os

# load_dotenv("details.env")
# print("API Key:", os.getenv("GEMINI_API_KEY"))
from google import genai
from dotenv import load_dotenv
import os

load_dotenv("details.env")

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello in one word"
)
print(response.text)