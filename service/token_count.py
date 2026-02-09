import tiktoken

def count_tokens(text: str, model: str = "gpt-4-0125-preview") -> int:
    """
    Count the number of tokens in a string for a specific model.
    
    Args:
        text: The text to count tokens for
        model: The model to use for counting (defaults to GPT-4 Turbo)
    
    Returns:
        int: Number of tokens
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except KeyError:
        print(f"Warning: model {model} not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))