"""
Data models for the Recipe Ingestion & Database Engine.

Defines the canonical schema as Python dataclasses with serialization
methods that produce the exact JSON structure specified in the requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MacroNutrients:
    """Nutritional macro breakdown for a single recipe."""

    protein: float = 0.0
    carbs: float = 0.0
    fats: float = 0.0
    calories: int = 0
    serving: Optional[str] = None
    food_id: Optional[str] = None
    food_name: Optional[str] = None

    def calculate_calories_atwater(self) -> int:
        """
        Apply the standard Atwater estimation formula:
            Calories = (Protein * 4) + (Carbs * 4) + (Fats * 9)

        Updates self.calories in-place and returns the value.
        """
        self.calories = int((self.protein * 4) + (self.carbs * 4) + (self.fats * 9))
        return self.calories

    def to_dict(self) -> dict:
        d = {
            "protein": round(self.protein, 2),
            "carbs": round(self.carbs, 2),
            "fats": round(self.fats, 2),
            "calories": self.calories,
            "serving": self.serving,
        }
        if self.food_id:
            d["food_id"] = self.food_id
        if self.food_name:
            d["food_name"] = self.food_name
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MacroNutrients:
        return cls(
            protein=float(data.get("protein", 0)),
            carbs=float(data.get("carbs", 0)),
            fats=float(data.get("fats", 0)),
            calories=int(data.get("calories", 0)),
            serving=data.get("serving"),
            food_id=data.get("food_id"),
            food_name=data.get("food_name"),
        )


@dataclass
class Recipe:
    """
    Canonical recipe record matching the required JSON schema.

    Serializes to:
    {
        "name": "...",
        "url": "...",
        "description": "...",
        "macros": { "protein": ..., "carbs": ..., "fats": ..., "calories": ... },
        "ingredients": [...],
        "instructions": [...],
        "tags": [...],
        "added_on": "YYYY-MM-DD HH:MM:SS",
        "transcript": "...",
        "last_processed": "YYYY-MM-DD HH:MM:SS"
    }
    """

    name: str
    url: str
    description: str
    macros: MacroNutrients = field(default_factory=MacroNutrients)
    ingredients: list[dict[str, str]] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    added_on: str = ""
    transcript: str = ""
    last_processed: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.name:
            self.name = self.name[:200]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.added_on:
            self.added_on = now_str
        if not self.last_processed:
            self.last_processed = now_str
        if not self.metadata:
            self.metadata = {
                "transcript": self.transcript,
                "description": self.description,
            }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "macros": self.macros.to_dict(),
            "ingredients": self.ingredients,
            "instructions": self.instructions,
            "tags": self.tags,
            "added_on": self.added_on,
            "transcript": self.transcript,
            "last_processed": self.last_processed,
            "metadata": self.metadata if self.metadata else {
                "transcript": self.transcript,
                "description": self.description,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        meta = data.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not meta:
            meta = {
                "transcript": data.get("transcript", ""),
                "description": data.get("description", ""),
            }
        return cls(
            name=data.get("name", ""),
            url=data.get("url", ""),
            description=data.get("description", ""),
            macros=MacroNutrients.from_dict(data.get("macros", {})),
            ingredients=data.get("ingredients", []),
            instructions=data.get("instructions", []),
            tags=data.get("tags", []),
            added_on=data.get("added_on", ""),
            transcript=data.get("transcript", ""),
            last_processed=data.get("last_processed", ""),
            metadata=meta,
        )
