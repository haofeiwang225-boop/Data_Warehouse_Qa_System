from pathlib import Path


def load_prompt(name:str):
    prompt_path = Path(__file__).parent[2]/'Prompts/'+name+'.prompt'
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()