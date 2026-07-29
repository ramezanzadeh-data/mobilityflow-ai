import ollama

MODEL = "llama3.1"

def ask_ai(prompt: str) -> str:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return response["message"]["content"]