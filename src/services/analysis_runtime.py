"""One runtime factory for automatic and manually requested job analysis."""

from src.config import get_settings
from src.infrastructure.llm_client import create_structured_model_client
from src.services.jd_analysis_service import JDAnalysisService
from src.services.product_jd_execution import ProductJDExecutionParser
from src.services.semantic_evidence_matcher import SemanticEvidenceMatcher


def create_product_parser(client, settings):
    return ProductJDExecutionParser(
        client,
        mode=settings.product_parse_mode,
        prompt_version=(
            settings.product_prompt_version
            if settings.product_parse_mode == "two_stage"
            else settings.product_single_call_prompt_version
        ),
        parser_version=settings.product_parser_version,
        validation_retries=settings.parser_validation_retries,
    )


def create_analysis_service(session, *, settings=None, client_factory=None):
    settings = settings or get_settings()
    client_factory = client_factory or create_structured_model_client
    parser = create_product_parser(client_factory(settings), settings)
    matcher = None
    if settings.evidence_matching_mode == "semantic":
        matching_settings = settings.model_copy(
            update={
                "llm_max_retries": 0,
                "llm_timeout_seconds": min(
                    settings.llm_timeout_seconds,
                    settings.evidence_matching_timeout_seconds,
                ),
            }
        )
        matcher = SemanticEvidenceMatcher(
            client_factory(matching_settings),
            timeout_seconds=settings.evidence_matching_timeout_seconds,
        )
    return JDAnalysisService(session, parser=parser, semantic_matcher=matcher)
