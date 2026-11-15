"""External local service & REST integration connectors."""

from src.integrations.fancytanky import FancyTankyConnector
from src.integrations.hermes import HermesBridge, HermesIntentMessage, HermesToolCall
from src.integrations.paperless import DocumentHit, PaperlessConnector
from src.integrations.rest_learner import RESTSkillLearner, SkillExecutionResult
from src.integrations.search import KnowledgeSearchConnector, SearchHit

__all__ = [
    "DocumentHit",
    "FancyTankyConnector",
    "HermesBridge",
    "HermesIntentMessage",
    "HermesToolCall",
    "KnowledgeSearchConnector",
    "PaperlessConnector",
    "RESTSkillLearner",
    "SearchHit",
    "SkillExecutionResult",
]

