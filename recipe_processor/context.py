from dataclasses import dataclass, field
from typing import Any, Optional
from database import MacroNutrients

@dataclass
class RecipeContext:
    """
    Holds the state of a recipe as it passes through the Chain of Responsibility pipeline.
    """
    recipe_id: str
    name: str
    url: str
    description: str
    manual_tags: Optional[list[str]] = None
    
    # State populated by handlers
    ingredients: list[dict[str, Any]] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    macros: MacroNutrients = field(default_factory=MacroNutrients)
    tags: list[str] = field(default_factory=list)
    transcript: str = ""
    
    # Control flow flags
    is_skipped: bool = False
    status: Optional[bool] = None  # True if added, False if skipped, None if saved to not-added
