from pydantic import BaseModel
from typing import List, Dict

# Pydantic models
class SystemPrompts(BaseModel):
    detect: str
    abstract: str = None


class MessageRequest(BaseModel):
    message: str
    system_prompts: SystemPrompts = None
    model : str = None
    temperature: float = 0.0
    top_p : float = 0.5


class WordListRequest(BaseModel):
    words: Dict[str, List[int]] 
