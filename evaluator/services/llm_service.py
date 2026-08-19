import json
import os
import re
import uuid
import logging

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from evaluator.config import (
    LLM_MODEL,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_TEMPERATURE,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_ENABLED,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_MIN_WAIT,
    LLM_RETRY_MAX_WAIT,
)

logger = logging.getLogger(__name__)


def _get_llm():
    """Create a ChatOllama instance from config."""
    return ChatOllama(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
    )


def _get_langchain_config() -> dict:
    """
    Build a per-call LangChain config with a fresh Langfuse trace.
    """
    config = {
        "configurable": {"thread_id": f"user---{uuid.uuid4()}"},
        "metadata": {"language": "english"},
    }

    if LANGFUSE_ENABLED:
        # Set env vars so langfuse client picks them up
        os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST
        os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
        os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY

        try:
            from langfuse.langchain import CallbackHandler
            config["callbacks"] = [CallbackHandler()]
        except ImportError:
            logger.warning("Langfuse not installed, tracing disabled.")

    return config


@retry(
    stop=stop_after_attempt(LLM_RETRY_ATTEMPTS),
    wait=wait_exponential(
        multiplier=1, min=LLM_RETRY_MIN_WAIT, max=LLM_RETRY_MAX_WAIT
    ),
    retry=retry_if_exception_type(
        (ValueError, AttributeError, json.JSONDecodeError)
    ),
    reraise=True,
)
def get_llm_json_response(prompt_text: str) -> dict:
    """
    Invoke the LLM with the given prompt and parse the response as JSON.

    Retries up to LLM_RETRY_ATTEMPTS times on parse failures.
    """
    llm = _get_llm()
    config = _get_langchain_config()

    try:
        response = llm.invoke(
            [HumanMessage(content=prompt_text)], config=config
        )
    except Exception as e:
        logger.error("LLM invocation failed: %s: %s", type(e).__name__, e)
        raise

    content = response.content.strip()
    logger.debug("LLM raw response: %s", content[:300])

    # Extract JSON object from response
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    return json.loads(content)
