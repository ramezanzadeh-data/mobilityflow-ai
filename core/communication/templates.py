import ollama

def generate_email(step, name, canton):

    prompt = f"""
You are an administrative assistant in Switzerland.

Write a formal email for the following task:

Task: {step}
Employee name: {name}
Canton: {canton}

Rules:
- formal tone
- concise
- Swiss administrative style
"""

    response = ollama.chat(
        model="llama3.1",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response["message"]["content"]