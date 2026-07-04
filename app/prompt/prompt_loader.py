from pathlib import Path


def load_prompt(name:str):
    prompt_path = Path(__file__).parents[2] / 'prompts' / f'{name}.prompt'
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()
