from abc import ABC, abstractmethod
from typing import Optional
from .context import RecipeContext

class BaseHandler(ABC):
    """
    Abstract base class for all handlers in the Chain of Responsibility pipeline.
    """
    def __init__(self):
        self._next_handler: Optional[BaseHandler] = None

    def set_next(self, handler: 'BaseHandler') -> 'BaseHandler':
        self._next_handler = handler
        return handler

    @abstractmethod
    def handle(self, context: RecipeContext) -> None:
        pass

    def next(self, context: RecipeContext) -> None:
        """
        Passes the context to the next handler in the chain, if one exists.
        """
        if self._next_handler:
            self._next_handler.handle(context)
