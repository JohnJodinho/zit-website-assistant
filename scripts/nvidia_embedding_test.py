import os

import dotenv
from openai import OpenAI

dotenv.load_dotenv()

client = OpenAI(
    api_key=os.getenv("NVIDIA_API_KEY"),
    base_url="https://integrate.api.nvidia.com/v1",
)

response = client.embeddings.create(
    input="This is a test of the NVIDIA embedding model.",
    model="nvidia/nemotron-3.5-embed-1b",
    encoding_format="float",
    extra_body={
        "modality": ["text"],
        "input_type": "query",
        "truncate": "END",
        "dimensions": 768,
    },
)

print(len(response.data[0].embedding))
